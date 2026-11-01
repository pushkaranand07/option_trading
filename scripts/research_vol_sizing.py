"""Report-only: constant, GARCH and HAR sizing of a fixed always-long basket (docs/vol_sizing_test_v1.json). No edge claim.

    python scripts/research_vol_sizing.py

Development rows only, from reports/models/dev. Refuses a changed spec. Logs one trial per sizer, once. Writes docs/vol_sizing_report_v1.md.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.research import models as m  # noqa: E402

SPEC_FILE = ROOT / "docs" / "vol_sizing_test_v1.json"
SPEC_SHA256 = "d1512bbf062be9ffbf753d1d391d8021a17505f16a9cc2f9d015531be241fce4"
DEV = ROOT / "reports" / "models" / "dev"
ANNUAL = np.sqrt(252)
TARGET, CAP = 0.30, 2.0
FOLD_NAMES = {0: "2013-14", 1: "2015-16", 2: "2017-18", 3: "2019-20", 4: "2021-22"}
SIZERS = ("constant", "garch", "har")


def read_spec(path: Path | None = None) -> dict:
    spec = json.loads((path or SPEC_FILE).read_text(encoding="utf-8"))
    if hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() != SPEC_SHA256:
        raise ValueError("vol_sizing_test_v1.json changed after it was frozen")
    return spec


def weight(vol: np.ndarray) -> np.ndarray:
    """min(cap, target / annual vol); no forecast, no weight."""
    v = np.where(vol > 0, vol, np.nan)
    return np.minimum(CAP, TARGET / v)


def har_forecast(x: pd.DataFrame, sessions: list) -> np.ndarray:
    """Annualised HAR forecast for test-fold rows, each fold fitted only on rows ending before it."""
    out = np.full(len(x), np.nan)
    ok = x[["rv_5", "rv_20", "rv_60"]].gt(0).all(axis=1).to_numpy()
    logs = np.log(x[["rv_5", "rv_20", "rv_60"]].where(x[["rv_5", "rv_20", "rv_60"]] > 0).to_numpy(dtype=float))
    for f in m.DEV_FOLDS:
        fit = m.fit_mask(x["entry_pos"].to_numpy(), x["exit_pos"].to_numpy(), f, 1, sessions) & ok & (x["t3_vol"].to_numpy() > 0)
        te = (x["fold"].to_numpy() == f) & ok
        if fit.sum() < 1000 or not te.any():
            continue
        coef = np.linalg.lstsq(np.column_stack([np.ones(fit.sum()), logs[fit]]), np.log(x["t3_vol"].to_numpy()[fit]), rcond=None)[0]
        out[te] = np.exp(np.column_stack([np.ones(te.sum()), logs[te]]) @ coef) * ANNUAL
    return out


def stats(daily: pd.Series) -> dict:
    curve = daily.cumsum()
    return {"vol": float(daily.std() * ANNUAL * 100), "drawdown": float((curve - curve.cummax()).min() * 100), "mean": float(daily.mean() * 100), "days": len(daily)}


def build_daily(x: pd.DataFrame, w: pd.Series, net: bool) -> pd.Series:
    r = x["gross"] - (x["cost"] if net else 0.0)
    return (r * w).groupby(x["signal"]).mean()


def main() -> int:
    read_spec()
    sessions = [date.fromisoformat(s) for s in json.loads((DEV / "sessions.json").read_text(encoding="utf-8"))]
    rows = pd.read_parquet(DEV / "rows_h1.parquet")
    rows = rows[rows["in_U1"] & (rows["kind"] == "stock")]
    panel = pd.read_parquet(DEV / "panel.parquet", columns=["panel_row", "rv_5", "rv_20", "rv_60", "garch_h1"])
    all_rows = rows.merge(panel, on="panel_row", how="left").reset_index(drop=True)
    all_rows["har"] = har_forecast(all_rows, sessions)
    x = all_rows[(all_rows["fold"] >= 0)].copy()
    x["w_constant"], x["w_garch"], x["w_har"] = 1.0, weight(x["garch_h1"].to_numpy(dtype=float)), weight(x["har"].to_numpy(dtype=float))
    x = x.dropna(subset=["w_garch", "w_har"]).reset_index(drop=True)
    base = stats(build_daily(x, x["w_constant"], False))
    L = ["# Volatility sizing: constant, GARCH, HAR", "", "> **Status:** Run 2026-11-01 from frozen [vol_sizing_test_v1.json](vol_sizing_test_v1.json). **Report-only, with no edge claim.**", "> **Scope:** development test folds 2013-2022, U1 stocks, always long, h = 1. All three sizers on identical rows.", "",
         "**Lower risk is not an edge. Cost model unverified.** Research and decision support only, not investment advice.", "", f"Rows: {len(x):,}; dates: {x['signal'].nunique():,}; rows dropped for a missing forecast: {int((all_rows['fold'] >= 0).sum() - len(x)):,}.", "",
         "## All folds", "", "| Sizer | Volatility % | Max drawdown % | Mean a day % gross | Mean a day % net | Mean weight | Mean daily weight change | Drawdown % at the constant sizer's volatility (hindsight scaling) |", "|---|---|---|---|---|---|---|---|"]
    res = {}
    for s in SIZERS:
        w = x[f"w_{s}"]
        g_, n_ = build_daily(x, w, False), build_daily(x, w, True)
        a, b = stats(g_), stats(n_)
        scale = base["vol"] / a["vol"] if a["vol"] else float("nan")
        change = float(x.sort_values(["symbol", "signal"]).groupby("symbol")[f"w_{s}"].diff().abs().mean())
        res[s] = a | {"net_mean": b["mean"], "mean_weight": float(w.mean()), "weight_change": change, "scaled_drawdown": stats(g_ * scale)["drawdown"]}
        L.append(f"| {s} | {a['vol']:.2f} | {a['drawdown']:.1f} | {a['mean']:+.4f} | {b['mean']:+.4f} | {w.mean():.3f} | {change:.3f} | {res[s]['scaled_drawdown']:.1f} |")
    L += ["", "## By fold", "", "| Fold | Sizer | Volatility % | Max drawdown % | Mean a day % gross |", "|---|---|---|---|---|"]
    for f, name in FOLD_NAMES.items():
        part = x[x["fold"] == f]
        for s in SIZERS:
            st = stats(build_daily(part, part[f"w_{s}"], False))
            L.append(f"| {name} | {s} | {st['vol']:.2f} | {st['drawdown']:.1f} | {st['mean']:+.4f} |")
    L.append("")
    (ROOT / "docs" / "vol_sizing_report_v1.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
    seen = {t.idea for t in trial_log.load()}
    for s in SIZERS:
        idea = f"vol_sizing_v1_{s}"
        if idea not in seen:
            trial_log.record(trial_log.Trial(idea=idea, params={"sha256": SPEC_SHA256}, universe="U1", data_start="2013-01-01", data_end=str(date(2022, 12, 31)), n_trials=1, n_oos_trades=len(x), notes="report-only sizing test; no edge claim; cost model unverified"))
    print(json.dumps(res, indent=0)[:900], trial_log.trial_count())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Report-only: best baseline and every model cell at 1x, 1.5x, 2x and 3x slippage, on development (docs/cost_parameters_v1.md).

    python scripts/research_cost_sensitivity.py

Charges stay at 1x; only slippage moves, so the columns are not the gate's 1.5x on everything. Trades and directions are those of the
frozen refit: settings come from reports/models/development.json and nothing is refit or re-chosen. Nothing after 2022 is loaded. It decides
nothing and changes no verdict. Writes docs/cost_sensitivity_v1.md.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_models as rm  # noqa: E402

from tradingagents.research import gate as g, gate2 as g2, models as m  # noqa: E402

MULTIPLES = (1.0, 1.5, 2.0, 3.0)
NAMES = {"a_elastic_logistic": "a logistic", "a_elastic_linear": "a linear", "b_lightgbm": "b LightGBM", "d_temporal_cnn": "d CNN", "e_ensemble": "e ensemble", "f_rank": "f rank"}


def scenario_costs(kinds: pd.Series, multiple: float) -> np.ndarray:
    """Charges at 1x plus slippage at ``multiple``."""
    slip = np.where(kinds == "index", 2 * g.SLIPPAGE_BPS["index"], 2 * g.SLIPPAGE_BPS["stock"]) / 1e4
    return g._costs(kinds, 1.0) - slip + multiple * slip


def baselines(h: int, rows: pd.DataFrame, costs: dict[float, np.ndarray]) -> dict[float, tuple[str, float]]:
    """The best baseline's highest net % across 20 schedules, per slippage multiple. Rows carry their cost per multiple."""
    folder = rm.paths(rm.DEV_END)[0]
    sessions = [date.fromisoformat(s) for s in json.loads((folder / "sessions.json").read_text(encoding="utf-8"))]
    pos = {pd.Timestamp(d): i for i, d in enumerate(sessions)}
    x = rows.assign(**{f"c{k}": v for k, v in costs.items()})
    x = x[(x["fold"] >= 0) & x["in_U1"]]
    panel = pd.read_parquet(folder / "panel.parquet", columns=["panel_row", "ret_1", "ret_5", f"garch_h{rm.GARCH_NEAR[h]}"])
    x = x.merge(panel, on="panel_row", how="left")
    v = x[f"garch_h{rm.GARCH_NEAR[h]}"].to_numpy()
    plans = {"always_long": (np.ones(len(x)), np.ones(len(x))), "always_short": (-np.ones(len(x)), np.ones(len(x))), "prev_day": (np.sign(x["ret_1"].fillna(0).to_numpy()), np.ones(len(x))),
             "momentum_5d": (np.sign(x["ret_5"].fillna(0).to_numpy()), np.ones(len(x))), "garch_risk_scaled": (np.where(v > 0, 1.0, 0.0), np.minimum(2.0, 0.30 / np.where(v > 0, v, np.nan)))}
    best = dict.fromkeys(MULTIPLES, ("", -np.inf))
    for name, (d, w) in plans.items():
        t = x.assign(_d=d, _w=w)
        t = t[t["_d"] != 0]
        for s in range(20):
            y = g.one_open_trade(g2.schedule_rows(t, s, pos))
            for k in MULTIPLES:
                val = float(((y["_d"] * y["gross"] - y[f"c{k}"]) * y["_w"]).mean() * 100) if len(y) else float("nan")
                if val > best[k][1]:
                    best[k] = (name, val)
    return best


def main() -> int:
    spec = m.read_spec()
    done = json.loads((rm.OUT / "development.json").read_text(encoding="utf-8"))
    settings = {(c["spec"], c["h"]): c.get("setting") for c in done["cells"]}
    rep_rows, base_rows = [], []
    for h in g.HORIZONS:
        rows = pd.read_parquet(rm.paths(rm.DEV_END)[0] / f"rows_h{h}.parquet")
        costs = {k: scenario_costs(rows["kind"], k) for k in MULTIPLES}
        best = baselines(h, rows, costs)
        base_rows.append(f"| {h} | " + " | ".join(f"{best[k][1]:+.3f} ({best[k][0]})" for k in MULTIPLES) + " |")
        rows = rows.assign(**{f"c{k}": v for k, v in costs.items()})
        for name in NAMES:
            setting = settings.get((name, h))
            preds = rm.predictions(name, h, m.DEV_FOLDS, None, rows, spec)
            if setting is None or not preds:
                rep_rows.append(f"| {NAMES[name]} | {h} | no setting | | | | |")
                continue
            pool, score = rm.pooled(preds, rows)
            u1 = rm.universe_trades(name, pool, score, setting, "in_U1")
            vals = [float((u1["_d"] * u1["gross"] - u1[f"c{k}"]).mean() * 100) for k in MULTIPLES]
            rep_rows.append(f"| {NAMES[name]} | {h} | {len(u1):,} | " + " | ".join(f"{v:+.3f}" for v in vals) + " |")
        print(h, flush=True)
    text = ["# Cost sensitivity: slippage at 1x to 3x", "", "> **Status:** Measured 2026-11-01. Report-only: it decides nothing and changes no verdict.", "> **Scope:** development test folds 2013-2022, U1, after the GARCH fix. Trades and settings are the refit's; nothing was refit or re-chosen.", "",
            "**Cost model unverified.** Charges stay at 1x and only slippage moves, so 1.5x here is not the gate's 1.5x on everything. Slippage itself is an ASSUMPTION: 2 bps per fill on index futures, 5 bps on stocks. Net % per trade. Research and decision support only, not investment advice.", "",
            "## Best baseline, highest of 20 schedules", "", "| h | 1x | 1.5x | 2x | 3x |", "|---|---|---|---|---|", *base_rows, "", "## Model cells", "", "| Spec | h | Trades | 1x | 1.5x | 2x | 3x |", "|---|---|---|---|---|---|---|", *rep_rows, ""]
    (ROOT / "docs" / "cost_sensitivity_v1.md").write_text("\n".join(text), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

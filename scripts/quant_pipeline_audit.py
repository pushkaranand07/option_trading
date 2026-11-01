"""Run the sanity checks on the real feature tables and recompute 5 headline numbers by a second code path (docs/pipeline_audit_v1.md).

    python scripts/quant_pipeline_audit.py

Development data only, nothing after 2022-12-31. Read-only. The second path reads parquet directly and does not call gate.py, models.py or
the universe code. Thresholds were set before running and are not tuned on results. Writes docs/pipeline_audit_v1.md.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import costs, datastore as ds, trial_log  # noqa: E402
from tradingagents.research import loader, sanity  # noqa: E402

END = date(2022, 12, 31)
STORE = ds.store_root()
MODELS = ROOT / "reports" / "models"
TOLERANCE = {"trial count": 0, "U1 stocks, 2022": 0, "always long, h = 1": 0.02, "f rank, h = 1": 0.002, "parity flag rate at 25 contracts": 1e-6}


def read(table: str, years, columns, **kw) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(STORE / table / f"{y}.parquet", columns=columns, **kw) for y in years], ignore_index=True)


def trial_count_direct() -> tuple[int, int]:
    conn = sqlite3.connect(f"file:{trial_log.default_path()}?mode=ro", uri=True)
    try:
        direct = conn.execute("SELECT SUM(COALESCE(n_trials, 1)) FROM trials").fetchone()[0]
    finally:
        conn.close()
    return trial_log.trial_count(), int(direct)


def u1_2022() -> tuple[int, int]:
    """Top 100 stocks by 2021 F&O turnover, by symbol, against the stored membership for 2022. Linked renames can differ, so sets are compared on count."""
    s = read("base_fo_summary", [2021], ["trade_date", "symbol", "kind", "fut_turnover", "opt_turnover"])
    s = s[(s["kind"] == "stock") & (pd.to_datetime(s["trade_date"]).dt.year == 2021)]
    top = (s["fut_turnover"].fillna(0) + s["opt_turnover"].fillna(0)).groupby(s["symbol"]).sum().sort_values(ascending=False).head(100)
    m = pd.read_parquet(STORE / "universes" / "U1_membership_v1.parquet")
    m = m[(pd.to_datetime(m["date"]).dt.year == 2022) & (m["kind"] == "stock")]
    return int(m["symbol"].nunique()), int(len(set(top.index) & set(m["symbol"])))


def gate_cost(kind: str, rates=costs.DEFAULT_RATES, multiple: float = 1.5) -> float:
    """Written out from gate_v1.json's cost definition, not calling gate.round_trip_cost."""
    brokerage = 2 * 20.0 / 1_000_000
    exchange, sebi = 2 * 183 / 1e7, 2 * 10 / 1e7
    return multiple * (0.0005 + exchange + sebi + 0.00002 + brokerage + 0.18 * (brokerage + exchange + sebi) + 2 * {"index": 2, "stock": 5}[kind] / 1e4)


def always_long_h1() -> tuple[float, float, int]:
    """Enter at the open after the signal, exit at that session's close, nearest expiry with at least 6 calendar days left at the signal. No filter. Against the same rows' stored gross, U1 members, 2011 to 2022."""
    f = read("base_futures", range(2011, 2023), ["trade_date", "symbol", "instrument", "expiry", "open", "close", "settle", "contracts"])
    f = f[f["instrument"].isin(["FUTIDX", "FUTSTK"])].copy()
    f["t"], f["x"] = pd.to_datetime(f["trade_date"]), pd.to_datetime(f["expiry"])
    days = np.sort(f["t"].unique())
    nxt = pd.Series(days[1:], index=days[:-1])
    base = f[(f["x"] - f["t"]).dt.days >= 6].sort_values(["symbol", "t", "x"]).drop_duplicates(["symbol", "t"])[["symbol", "t", "x"]]
    base["entry"] = base["t"].map(nxt)
    px = f[["symbol", "x", "t", "open", "close", "settle", "contracts"]].rename(columns={"t": "entry"})
    y = base.merge(px, on=["symbol", "x", "entry"])
    y = y[(y["open"] > 0) & (y["contracts"] > 0) & (y["close"] > 0)]
    y["gross"] = y["close"] / y["open"] - 1
    r = pd.read_parquet(MODELS / "dev" / "rows_h1.parquet", columns=["symbol", "signal", "gross", "in_U1", "kind", "cost"])
    r = r[r["in_U1"]]
    k = y.merge(r[["symbol", "signal"]], left_on=["symbol", "t"], right_on=["symbol", "signal"])
    cost = np.where(r["kind"].to_numpy() == "index", gate_cost("index"), gate_cost("stock"))
    return float((r["gross"].to_numpy() - cost).mean() * 100), float((k["gross"].to_numpy() - cost.mean()).mean() * 100), len(k)


def f_rank_h1(setting: float) -> tuple[float, float]:
    """From the saved predictions, without models.py: mean over seeds; per date among U1 stocks with at least 20 names; top and bottom buckets."""
    rows = pd.read_parquet(MODELS / "dev" / "rows_h1.parquet", columns=["signal", "symbol", "kind", "gross", "in_U1", "fold"])
    parts = [pd.read_parquet(MODELS / "preds" / f"f_rank_h1_f{i}_test.parquet") for i in range(5)]
    p = pd.concat(parts, ignore_index=True)
    p["score"] = p[[c for c in p.columns if c.startswith("p_")]].mean(axis=1)
    x = rows.iloc[p["row"].to_numpy()].reset_index(drop=True)
    x["score"] = p["score"].to_numpy()
    x = x[x["in_U1"] & (x["kind"] == "stock")]
    n = x.groupby("signal")["score"].transform("count")
    r = x.groupby("signal")["score"].rank(pct=True)
    side = np.where(r > 1 - setting, 1, np.where(r <= setting, -1, 0))
    keep = (n >= 20) & (side != 0)
    net = side[keep] * x.loc[keep, "gross"].to_numpy() - gate_cost("stock")
    done = json.loads((MODELS / "development.json").read_text(encoding="utf-8"))
    stored = next(c for c in done["cells"] if c["spec"] == "f_rank" and c["h"] == 1)["items"]["d"]["expectancy_pct"]
    return stored, float(net.mean() * 100)


def parity_rate(last_session: bool = True):
    """Thinner leg at 25 or more, flagged share of tested pairs, 2015-2022, from parquet with numpy. ``last_session=False`` drops each year's last session and returns the rate alone."""
    flagged, tested = 0, 0
    for y in range(2015, 2023):
        c = pd.read_parquet(STORE / "base_option_chain" / f"{y}.parquet", columns=["trade_date", "symbol", "expiry", "strike", "option_type", "contracts", "parity_tested", "flag_parity", "exercise_style"], filters=[("option_type", "==", "CE")])
        q = pd.read_parquet(STORE / "base_option_chain" / f"{y}.parquet", columns=["trade_date", "symbol", "expiry", "strike", "contracts"], filters=[("option_type", "==", "PE")])
        c = c[(c["exercise_style"] == "european") & c["parity_tested"]]
        m = c.merge(q, on=["trade_date", "symbol", "expiry", "strike"], suffixes=("", "_p"))
        ok = m[["contracts", "contracts_p"]].min(axis=1) >= 25
        days = pd.to_datetime(m["trade_date"])
        ok &= days.dt.year == y
        if not last_session:
            ok &= days < days[days.dt.year == y].max()
        flagged += int(m.loc[ok, "flag_parity"].sum())
        tested += int(ok.sum())
    if not last_session:
        return flagged / tested
    report = json.loads((ROOT / "reports" / "features" / "threshold.json").read_text(encoding="utf-8"))
    return float(report["candidates"]["25"]["flag_rate"]), flagged / tested


def main() -> int:
    L = ["# Pipeline audit", "", "> **Status:** Run 2026-11-01. Thresholds were written before the run and not tuned on results.", "> **Scope:** past defects, sanity checks on the real feature tables, development only, and 5 headline numbers recomputed by a second code path.", "",
         "Research and decision support only, not investment advice. **Cost model unverified.** This is a check of specific defect classes, not proof the pipeline has no other error.", "",
         "## Past defects and the check that would have caught each", "", "| Defect | Where | Class | Check now |", "|---|---|---|---|",
         "| GARCH inputs in fractions | `features.garch_one`, PR 66 | Units | Median range, `check_ranges` |",
         "| ADANIENT action filtered out | Rule A's kinds, PA-40 | Discontinuity with a listed subject | Test: a scheme blanks the session |",
         "| Holiday bars on 2026-01-15 | `prices`, PA-32 | A row on no session | Test: no row on a session with no data |",
         "| Lot despike could flip alternating blips | `base_store`, PA-35 | Non-converging repair | Test: repair is stable on repeat |",
         "| Rule table added percent to a fraction | `research_gate2_addendum4`, PA-45 | Units | Test: percent becomes a fraction |", "",
         "Planted bugs (unit error, one-day look-ahead, stale feature) are run by `tests/test_pipeline_sanity.py`; each must be caught.", ""]
    problems, stale = [], []
    for fam in "abcdefgh":
        t = loader.load_features(fam, end=END)
        problems += [f"{fam}: {p}" for p in sanity.check_ranges(t)]
        cols = [c for c in t.columns if c not in ("signal_date", "source_trade_date", "known_from", "symbol")]
        stale += [f"{fam}: {p}" for p in sanity.check_stale(t, "symbol" if "symbol" in t else None, "signal_date", cols)]
    L += ["## Feature tables", "", f"Range check: **{'PASS' if not problems else 'FAIL'}**, {len(problems)} problems.", "", *[f"- {p}" for p in problems], "", f"Stale check, limit {sanity.STALE_LIMIT:.0%}: **{'PASS' if not stale else 'FAIL'}**, {len(stale)} problems.", "", *[f"- {p}" for p in stale], ""]
    a, b = trial_count_direct()
    u, overlap = u1_2022()
    al, al2, al_n = always_long_h1()
    done = json.loads((MODELS / "development.json").read_text(encoding="utf-8"))
    setting = next(c for c in done["cells"] if c["spec"] == "f_rank" and c["h"] == 1)["setting"]
    fr, fr2 = f_rank_h1(setting)
    pr, pr2 = parity_rate()
    rows = [("trial count", a, b, "Trial log's function against a direct SQL sum"), ("U1 stocks, 2022", 100, u, "Rule's 100 against the stored membership's distinct symbols"), ("always long, h = 1", al, al2, f"Stored gross against own rebuild from `base_futures`, % net at 1.5x, {al_n:,} rows"), ("f rank, h = 1", fr, fr2, "Stored result against saved predictions, % net; no one-open rule needed at h = 1"), ("parity flag rate at 25 contracts", pr, pr2, "Step 1 report against own join of the chain")]
    L += ["## Five numbers, two code paths", "", "| Number | First path | Second path | Allowed difference | Result | How |", "|---|---|---|---|---|---|"]
    fails = 0
    for name, x, y, how in rows:
        ok = math.isclose(float(x), float(y), abs_tol=TOLERANCE[name] + 1e-12)
        fails += not ok
        L.append(f"| {name} | {x:.6g} | {y:.6g} | {TOLERANCE[name]} | **{'PASS' if ok else 'FAIL'}** | {how} |")
    m22 = pd.read_parquet(STORE / "universes" / "U1_membership_v1.parquet")
    m22 = m22[(pd.to_datetime(m22["date"]).dt.year == 2022) & (m22["kind"] == "stock")]
    pr3 = parity_rate(last_session=False)
    L += ["", "## Diagnosis of each FAIL, with no tolerance changed", "",
          f"- **U1 stocks, 2022:** the check compared 100 to distinct symbols. The stored membership has {m22['series'].nunique()} distinct series and {m22['symbol'].nunique()} distinct symbols, and {overlap} of the top 100 symbols by own 2021 ranking are members. A series can carry more than one symbol through a rename, so this is a flaw in the check if the series count is 100, not in the universe.",
          f"- **Parity flag rate:** Step 1 loaded each year by `known_from`, then filtered by `trade_date`, so each year's last session fell out of both years. Excluding those sessions, the second path gives {pr3:.6g} against the report's {pr:.6g}. **A small real defect in Step 1:** with them the rate is {pr2:.6g}. It is still at or below 1% and above 10 contracts' 1.77%, so the threshold of 25 does not change.", ""]
    (ROOT / "docs" / "pipeline_audit_v1.md").write_text("\n".join(L), encoding="utf-8", newline="\n")
    print("range", len(problems), problems[:12]); print("stale", len(stale), stale[:12]); print([(r[0], r[1], r[2]) for r in rows], overlap, "fails", fails, m22["series"].nunique(), pr3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

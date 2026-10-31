"""Gate v2 addendum 2 measurements: family coverage per fold, and the pass rates without Tier 2 (docs/PA_43). No model.

    python scripts/research_gate2_addendum2.py --part folds
    python scripts/research_gate2_addendum2.py --part power

Folds: for each family and walk-forward fold, the signal dates with data and the share of U1 stock rows filled. Power: Tier 1 as
gate v2 defines it (a, c, d, e, f, g), without item c, and items a, d, e, f alone, on fresh seeds, development trades, rule A.
Writes reports/gate/addendum2_*.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_gate2_addendum as a1  # noqa: E402
import research_gate2_harness as h2  # noqa: E402

from tradingagents.research import gate as g, gate2 as g2, loader, universes as uv  # noqa: E402

OUT = ROOT / "reports" / "gate"
GROUPS = {"participant": ("d", "fii_fut_idx_net"), "delivery": ("e", "deliv_pct"), "options_atm": ("c", "atm_iv_front"), "options_skew": ("c", "skew_5"),
          "india_vix": ("f", "vix"), "garch": ("a", "garch_h5"), "price": ("a", "ret_1"), "oi": ("b", "oi_chg_1")}
MIN_DATES, DATES_SHARE, ROWS_SHARE = 100, 0.80, 0.50
NULL_RUNS, PLANTED_RUNS = 5000, 300
VARIANTS = {"tier1_v2": "acdefg", "without_c": "adefg", "a_d_e_f_only": "adef"}


def run_folds() -> dict:
    summ = g.load("base_fo_summary")
    u1, _ = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    m = u1[u1["kind"] == "stock"]
    rows = pd.DataFrame({"signal_date": pd.to_datetime(m["date"]), "symbol": m["symbol"].to_numpy()})
    tables: dict = {}
    rep: dict = {"definitions": {"item_g_minimum": f"at least {MIN_DATES} signal dates with data", "stricter": f"at least {DATES_SHARE:.0%} of the fold's dates and {ROWS_SHARE:.0%} of U1 stock rows filled"}, "folds": {}}
    all_dates = pd.DatetimeIndex(sorted(rows["signal_date"].unique()))
    for a, b in g.FOLDS:
        days = all_dates[(all_dates.year >= a) & (all_dates.year <= b)]
        cell = {"dates": len(days)}
        base = rows[rows["signal_date"].isin(days)]
        for name, (fam, col) in GROUPS.items():
            t = tables.setdefault(fam, loader.load_features(fam).assign(signal_date=lambda x: pd.to_datetime(x["signal_date"])))
            if "symbol" in t:
                x = base.merge(t[["signal_date", "symbol", col]], on=["signal_date", "symbol"], how="left")
            else:
                x = base.merge(t[["signal_date", col]], on="signal_date", how="left")
            by_date = x.groupby("signal_date")[col].count()
            enough = int((by_date >= 20).sum())
            filled = float(x[col].notna().mean())
            cell[name] = {"dates_with_20_values": enough, "rows_filled": filled, "item_g_minimum": enough >= MIN_DATES,
                          "stricter": enough >= DATES_SHARE * len(days) and filled >= ROWS_SHARE}
        rep["folds"][f"{a}-{b}"] = cell
    fam_names = ["participant", "delivery", "options_atm", "options_skew"]
    combos = {**{f: [f] for f in fam_names}, "participant_delivery": ["participant", "delivery"], "participant_delivery_options_atm": ["participant", "delivery", "options_atm"], "all_four": fam_names}
    rep["folds_left"] = {}
    for k, names in combos.items():
        for test in ("item_g_minimum", "stricter"):
            keep = [f for f, c in rep["folds"].items() if all(c[n][test] for n in names)]
            rep["folds_left"].setdefault(k, {})[test] = {"folds": keep, "development_only": [f for f in keep if f != "2023-2024"]}
    (OUT / "addendum2_folds.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return rep


def variants(rows: list[dict]) -> dict:
    out = {k: a1.rate([all(r[i] for i in items) for r in rows]) for k, items in VARIANTS.items()}
    return out | {"mean_win": float(np.nanmean([r["win"] for r in rows]))}


def run_power(workers: int) -> dict:
    spec = g2.read_spec()
    data = h2.load_rule("A")
    garch = h2.garch_cached(data, workers)
    payload = {"x": {h: spec["gate"]["g"]["x_h_percent"][str(h)] / 100 for h in g.HORIZONS},
               "block": {h: spec["gate"]["d"]["block_dates_by_h"][str(h)] for h in g.HORIZONS}}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            payload[f"{uni}_{h}"] = h2.pack(h2.trades_for(data, h, uni), data["returns"], garch, h)
    rep: dict = {"label": "development trades, rule A; cost model unverified", "null": {}, "planted": {}}
    t0 = time.monotonic()
    with ProcessPoolExecutor(workers, initializer=h2._init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            for mi, mode in enumerate(("null", "null_zero")):
                for n in h2.TARGETS:
                    jobs = [(h, None, n, 800_000_000 + 10_000_000 * h + 1_000_000 * mi + 100_000 * (n // 50) + i * 5, mode) for i in range(NULL_RUNS)]
                    rep["null"].setdefault(f"h{h}", {})[f"{mode}_{n}"] = variants(list(pool.map(h2.one_run, jobs, chunksize=20)))
            print(f"null h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for hit in h2.HITS:
                for n in h2.TARGETS:
                    jobs = [(h, hit, n, 1_000_000_000 + 1_000_000 * h + int(hit * 100) * 10_000 + n + i * 7, "planted") for i in range(PLANTED_RUNS)]
                    rep["planted"].setdefault(f"h{h}", {})[f"hit{hit:.2f}_n{n}"] = variants(list(pool.map(h2.one_run, jobs, chunksize=10)))
            print(f"planted h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
    (OUT / "addendum2_power.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["folds", "power"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.part == "folds":
        run_folds()
    else:
        run_power(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

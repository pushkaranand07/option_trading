"""Gate v2 addendum measurements: item d and both tiers at 5,000 runs, and the time-shift control at no-overlap shifts.

    python scripts/research_gate2_addendum.py

Development trades only, rule A, fresh seeds. The gate files are not changed. Writes reports/gate/addendum_stats.json.
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
from scipy.stats import beta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_gate2_harness as h2  # noqa: E402

from tradingagents.research import gate as g, gate2 as g2  # noqa: E402

RUNS, SHIFT_RUNS = 5000, 1000


def interval(k: int, n: int) -> list[float]:
    """Exact two-sided 95% (Clopper-Pearson)."""
    lo = 0.0 if k == 0 else float(beta.ppf(0.025, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(0.975, k + 1, n - k))
    return [lo, hi]


def rate(flags: list[bool]) -> dict:
    k = int(np.sum(flags))
    return {"runs": len(flags), "passes": k, "rate": k / len(flags), "ci95": interval(k, len(flags))}


def shifts_for(h: int) -> dict[str, int]:
    return {"h": h, "2h": 2 * h, "20_dates": 20}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    spec = g2.read_spec()
    data = h2.load_rule("A")
    garch = h2.garch_cached(data, args.workers)
    payload = {"x": {h: spec["gate"]["g"]["x_h_percent"][str(h)] / 100 for h in g.HORIZONS},
               "block": {h: spec["gate"]["d"]["block_dates_by_h"][str(h)] for h in g.HORIZONS}}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            payload[f"{uni}_{h}"] = h2.pack(h2.trades_for(data, h, uni), data["returns"], garch, h)
    rep: dict = {"label": "development trades, rule A; cost model unverified", "gate_sha256": g2.GATE_SHA256, "item_d": {}, "tiers": {}, "time_shift": {}}
    t0 = time.monotonic()
    with ProcessPoolExecutor(args.workers, initializer=h2._init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            for ki, kind in enumerate(h2.NULLS):
                for n in h2.TARGETS:
                    jobs = [(h, payload["block"][h], kind, n, 200_000_000 + 10_000_000 * h + 1_000_000 * ki + 100_000 * (n // 50) + i) for i in range(RUNS)]
                    rep["item_d"].setdefault(f"h{h}", {})[f"{kind}_{n}"] = rate(list(pool.map(h2.cal_run, jobs, chunksize=100)))
            print(f"item d h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for mi, mode in enumerate(("null", "null_zero")):
                for n in h2.TARGETS:
                    jobs = [(h, None, n, 400_000_000 + 10_000_000 * h + 1_000_000 * mi + 100_000 * (n // 50) + i * 5, mode) for i in range(RUNS)]
                    rows = list(pool.map(h2.one_run, jobs, chunksize=20))
                    rep["tiers"].setdefault(f"h{h}", {})[f"{mode}_{n}"] = {"tier1": rate([r["tier1"] for r in rows]), "tier2": rate([r["tier2"] for r in rows]),
                                                                           "item_d": rate([r["d"] for r in rows])}
            print(f"tiers h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for name, s in shifts_for(h).items():
                for n in h2.TARGETS:
                    jobs = [(h, 0.90, n, 600_000_000 + 10_000_000 * h + 100_000 * s + 10_000 * (n // 50) + i * 5, f"shift_dates_{s}") for i in range(SHIFT_RUNS)]
                    rows = list(pool.map(h2.one_run, jobs, chunksize=20))
                    rep["time_shift"].setdefault(f"h{h}", {})[f"{name}_n{n}"] = {"shift_dates": s, "tier1": rate([r["tier1"] for r in rows]), "tier2": rate([r["tier2"] for r in rows]),
                                                                                 "mean_win": float(np.nanmean([r["win"] for r in rows]))}
            print(f"shift h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
    (ROOT / "reports" / "gate" / "addendum_stats.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

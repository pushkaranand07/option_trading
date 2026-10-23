"""Evaluate a signal on the real store with the Phase 2 harness.

    python scripts/quant_evaluate.py --signal ma_trend --position-value 25000 100000 500000
    python scripts/quant_evaluate.py --signal random --position-value 100000 --random-runs 200

Position value (Rs per position) is required: you decide it, and several values
can be given to see how much trade size changes the result. Every run is
written to the trial log. Signals are listed in SIGNALS; ideas from Phase 5 are
added there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics.evaluate import evaluate, moving_average_trend, panel  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402


def random_signal(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Harness self-check: must never pass. Holds random long/flat/short blocks of 10 sessions."""
    rng = np.random.default_rng(params["seed"])
    blocks = -(-len(data) // 10)
    draws = rng.choice([-1.0, 0.0, 1.0], size=(blocks, data["close"].shape[1]))
    return pd.DataFrame(np.repeat(draws, 10, axis=0)[: len(data)], index=data.index,
                        columns=data["close"].columns)


SIGNALS = {
    "random": (random_signal, [{"seed": s} for s in range(10)]),
    "ma_trend": (moving_average_trend, [{"fast": f, "slow": s} for f in (20, 50, 100) for s in (150, 200, 250)]),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--signal", choices=sorted(SIGNALS), required=True)
    parser.add_argument("--position-value", type=float, nargs="+", required=True, help="Rs per position")
    parser.add_argument("--segment", default="delivery", choices=["delivery", "futures"])
    parser.add_argument("--random-runs", type=int, default=1000)
    args = parser.parse_args()

    data = panel(load_prices(STOCKS))
    signal, grid = SIGNALS[args.signal]
    for value in args.position_value:
        result = evaluate(args.signal, signal, grid, data, position_value=value, segment=args.segment,
                          random_runs=args.random_runs, universe_note="29 F&O stocks since 2018")
        print(result.summary(), "\n")
    print(SURVIVORSHIP_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())

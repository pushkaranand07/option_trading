"""Phase 6, second model: which stocks will beat the rest of the universe?

    python scripts/quant_relative.py --position-value 100000
    python scripts/quant_relative.py --position-value 100000 --k 5 --horizon 10

Features: price/volume/structure and the NSE store features (OI, PCR, delivery,
implied vol), each ranked across the 29 stocks per day; plus market context
(NIFTY, India VIX, regime, FII/Client positioning) unranked. Every 10 sessions,
buy the top-k by predicted probability; judged on the return in excess of
holding all 29 equally, after delivery costs and a NIFTY-futures hedge.
The deflated Sharpe counts every relative-strength run in the trial log.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.analytics.evaluate import panel  # noqa: E402
from tradingagents.analytics.ml import (
    features as mf,  # noqa: E402
    relative as mr,  # noqa: E402
)
from tradingagents.analytics.ml.inputs import market_context, store_features  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402

IDEA = "relative_strength"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--position-value", type=float, required=True, help="Rs per stock position")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--random-runs", type=int, default=300)
    args = parser.parse_args()

    data = panel(load_prices(STOCKS))
    ctx, regimes = market_context()
    extra, positioning = store_features(data["close"])
    ctx.update(positioning)
    leaks = mf.leak_check(data, samples=6, context=ctx, extra=extra)
    print(f"Feature leak check: {leaks} mismatching sessions", flush=True)
    feats = mf.build(data, context=ctx, extra=extra)
    labels = mr.relative_labels(data["open"], horizon=args.horizon)
    n_trials = trial_log.trial_count(IDEA) + 1
    print(f"Features {feats.shape}; labels {len(labels):,}; trial #{n_trials} of this idea", flush=True)

    result = mr.run(data, feats, labels, context=list(ctx), position_value=args.position_value, k=args.k,
                    horizon=args.horizon, random_runs=args.random_runs, leak_mismatches=leaks,
                    regimes=regimes, n_trials=n_trials)
    print(result.summary())
    print(f"\n{SURVIVORSHIP_NOTE}")
    e = result.excess
    trial_log.record(trial_log.Trial(
        idea=IDEA, params={"k": args.k, "horizon": args.horizon, "position_value": args.position_value},
        universe="29 F&O stocks since 2018", data_start=str(e.index[0].date()), data_end=str(e.index[-1].date()),
        n_trials=1, n_oos_trades=result.picks, oos_sharpe=result.excess_sharpe, dsr=result.deflated_sharpe,
        verdict=result.verdict, gate_verdict=result.gates.verdict,
        notes=f"same-day AUC {result.daily_auc:.3f}; long Sharpe {result.long_sharpe:.2f} vs "
              f"universe {result.bench_sharpe:.2f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

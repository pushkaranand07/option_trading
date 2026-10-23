"""Phase 6: walk-forward LightGBM on the 29-stock universe.

    python scripts/quant_ml.py --position-value 100000
    python scripts/quant_ml.py --position-value 100000 --horizon 10 --k 1.0
    python scripts/quant_ml.py --position-value 100000 --with-store   # + OI, PCR, delivery, FII, IV

Features: price/volume/structure per stock, plus NIFTY 20-day return, India
VIX and regime probabilities as context. ``--with-store`` adds futures OI,
put/call ratios, delivery %, FII/Client futures positioning and each stock's
implied vol from the NSE store (scripts/quant_build_store.py first). Long-only, delivery costs, entry at the
open, exit per the triple-barrier rule. Every run goes to the trial log.
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
    labels as ml,  # noqa: E402
    pipeline as mp,  # noqa: E402
)
from tradingagents.analytics.ml.inputs import market_context, store_features  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--position-value", type=float, required=True, help="Rs per position")
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--k", type=float, default=1.0)
    parser.add_argument("--random-runs", type=int, default=300)
    parser.add_argument("--with-store", action="store_true", help="add NSE derivatives / flow features")
    args = parser.parse_args()

    data = panel(load_prices(STOCKS))
    ctx, regimes = market_context()
    extra = {}
    if args.with_store:
        extra, positioning = store_features(data["close"])
        ctx.update(positioning)
        print(f"Store features: {sorted(extra)} + {sorted(k for k in ctx if 'share' in k)}", flush=True)
    print(f"Panel: {len(data)} sessions x {data['close'].shape[1]} stocks; context: {sorted(ctx)}", flush=True)
    leaks = mf.leak_check(data, samples=6, context=ctx, extra=extra)
    print(f"Feature leak check: {leaks} mismatching sessions", flush=True)
    feats = mf.build(data, context=ctx, extra=extra)
    labels = ml.triple_barrier(data["open"], data["close"], ml.causal_daily_vol(data["close"]),
                               k=args.k, horizon=args.horizon)
    print(f"Features {feats.shape}, labels {len(labels):,} (exits: "
          f"{labels['exit_reason'].value_counts().to_dict()})", flush=True)

    result = mp.run(data, feats, labels, position_value=args.position_value, embargo=args.horizon + 5,
                    random_runs=args.random_runs, leak_mismatches=leaks, regimes=regimes)
    print(result.summary())
    print(f"\n{SURVIVORSHIP_NOTE}")
    r = result.oos_net.mean(axis=1)
    trial_log.record(trial_log.Trial(
        idea=f"lgbm_h{args.horizon}_k{args.k}{'_store' if args.with_store else ''}", params={"thresholds": list(mp.THRESHOLDS),
                                                         "position_value": args.position_value},
        universe="29 F&O stocks since 2018", data_start=str(r.index[0].date()), data_end=str(r.index[-1].date()),
        n_trials=len(mp.THRESHOLDS), n_oos_trades=result.stats.n, oos_sharpe=result.oos_sharpe,
        dsr=result.deflated_sharpe, verdict=result.verdict, gate_verdict=result.gates.verdict,
        notes=f"AUC {result.auc:.3f}, Brier {result.brier:.4f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

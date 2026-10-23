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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import (
    datastore as ds,  # noqa: E402
    trial_log,  # noqa: E402
)
from tradingagents.analytics.datastore import store_root  # noqa: E402
from tradingagents.analytics.evaluate import panel  # noqa: E402
from tradingagents.analytics.implied_vol import atm_iv_table  # noqa: E402
from tradingagents.analytics.ml import (
    derived as md,  # noqa: E402
    features as mf,  # noqa: E402
    labels as ml,  # noqa: E402
    pipeline as mp,  # noqa: E402
)
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402


def context() -> tuple[dict[str, pd.Series], pd.Series | None]:
    """Market context dated by the close it is known after, and the regime known at each session's start."""
    p = load_prices(["NIFTY", "INDIAVIX"])
    p = p.assign(trade_date=pd.to_datetime(p["trade_date"])).pivot(index="trade_date", columns="symbol",
                                                                     values="close")
    ctx = {"nifty_ret20": np.log(p["NIFTY"]).diff(20), "vix": np.log(p["INDIAVIX"])}
    regimes = None
    f = store_root() / "regime" / "regime.parquet"
    if f.exists():
        r = pd.read_parquet(f).assign(trade_date=lambda d: pd.to_datetime(d["trade_date"])).set_index("trade_date")
        for col in ("p_calm", "p_choppy", "p_stress"):
            ctx[col] = r[col]
        regimes = r["regime"].shift(1).dropna()
    return ctx, regimes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--position-value", type=float, required=True, help="Rs per position")
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--k", type=float, default=1.0)
    parser.add_argument("--random-runs", type=int, default=300)
    parser.add_argument("--with-store", action="store_true", help="add NSE derivatives / flow features")
    args = parser.parse_args()

    data = panel(load_prices(STOCKS))
    ctx, regimes = context()
    extra = {}
    if args.with_store:
        extra.update(md.from_fo_summary(ds.load("fo_summary", symbols=STOCKS)))
        extra.update(md.from_delivery(ds.load("delivery", symbols=STOCKS)))
        extra.update(md.from_iv(atm_iv_table(ds.load("option_chain", symbols=STOCKS)), data["close"]))
        ctx.update(md.from_participant(ds.load("participant")))
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

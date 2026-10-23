"""Phase 6, approach A, step 1: can the model tell which stocks will make a big move?

    python scripts/quant_move_size.py

Label: |10-session open-to-open move| > 1 x the stock's expected move (trailing
60-session vol x sqrt(10)). Features: price/volume plus the NSE store features,
ranked across stocks per day, and market context. Scored by same-day AUC, and
against a simple benchmark: ranking stocks by their GARCH 10-session forecast
relative to trailing vol. Step 2 (a premium-selling strategy on the stocks
predicted quietest) is built only if this clearly beats both 0.5 and GARCH.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.analytics.datastore import store_root  # noqa: E402
from tradingagents.analytics.evaluate import panel  # noqa: E402
from tradingagents.analytics.ml import features as mf, move_size as ms  # noqa: E402
from tradingagents.analytics.ml.inputs import market_context, store_features  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402

IDEA = "move_size_h10_k1"


def garch_benchmark(closes: pd.DataFrame) -> pd.DataFrame:
    """GARCH 10-session forecast / trailing 60-session vol, as known before each session opens."""
    trailing = np.log(closes).diff().rolling(ms.VOL_WINDOW, min_periods=30).std().shift(1) * np.sqrt(252)
    cols = {}
    for s in closes.columns:
        f = store_root() / "vol_forecasts" / f"{s}.parquet"
        if f.exists():
            g = pd.read_parquet(f)["garch_h10"]
            g.index = pd.to_datetime(g.index)
            cols[s] = g.shift(1).reindex(closes.index)      # forecast after t-1's close, used on t
    return pd.DataFrame(cols) / trailing


def main() -> int:
    data = panel(load_prices(STOCKS))
    ctx, _ = market_context()
    extra, positioning = store_features(data["close"])
    ctx.update(positioning)
    leaks = mf.leak_check(data, samples=6, context=ctx, extra=extra)
    print(f"Feature leak check: {leaks} mismatching sessions", flush=True)
    feats = mf.build(data, context=ctx, extra=extra)
    labels = ms.move_labels(data["open"], data["close"], horizon=10, k_sigma=1.0)
    print(f"Features {feats.shape}; labels {len(labels):,}, base rate {labels['label'].mean():.1%}", flush=True)

    result = ms.run(feats, labels, context=list(ctx), benchmark=garch_benchmark(data["close"]))
    print(result.summary())
    print(f"\n{SURVIVORSHIP_NOTE}")
    p = result.predictions
    trial_log.record(trial_log.Trial(
        idea=IDEA, params={"horizon": 10, "k_sigma": 1.0}, universe="29 F&O stocks since 2018",
        data_start=str(p["date"].min().date()), data_end=str(p["date"].max().date()), n_trials=1,
        n_oos_trades=len(p), verdict="predictive_check", gate_verdict=None,
        notes=f"same-day AUC {result.daily_auc:.3f}; GARCH benchmark {result.garch_daily_auc}; leaks {leaks}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

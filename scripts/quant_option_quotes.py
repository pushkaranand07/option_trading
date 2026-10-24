"""Save tonight's NSE option bid/ask snapshot and report real spreads vs the slippage model.

    python scripts/quant_option_quotes.py              # capture + report
    python scripts/quant_option_quotes.py --report     # report only

Part of the 19:30 daily refresh (last step). See ``tradingagents/analytics/quotes.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import quotes  # noqa: E402
from tradingagents.analytics.universe import SYMBOLS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="skip the capture")
    args = parser.parse_args()
    if not args.report:
        counts = quotes.capture(SYMBOLS)
        print(f"Option quotes: {counts['saved']} chains saved, {counts['already']} already had, "
              f"{counts['failed']} failed", flush=True)
    q = quotes.load()
    if q.empty:
        print("No quotes captured yet.")
        return 0
    v = quotes.versus_model(q)
    days = sorted(v["trade_date"].unique())
    print(f"\n{len(days)} snapshot day(s), {days[0]} -> {days[-1]}; strikes within 10% of the underlying")
    last = v[v["trade_date"] == days[-1]].sort_values("real_vs_model")
    print(f"Latest ({days[-1]}): real half-spread / model slippage, median across symbols "
          f"{last['real_vs_model'].median():.2f}")
    print("Most expensive to trade:")
    print(last.tail(5)[["symbol", "real_vs_model", "half_spread"]].round(2).to_string(index=False))
    if len(days) > 1:
        print("\nBy symbol over all days (median):")
        print(v.groupby("symbol")["real_vs_model"].median().sort_values().round(2).to_string())
    # Exit 1 only if nothing at all could be read tonight: the job's status then shows it.
    return 0 if args.report or counts["saved"] + counts["already"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

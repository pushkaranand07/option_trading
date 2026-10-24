"""What works in your own trades: a Dhan tradebook broken down by holding period, instrument and more.

    python scripts/trade_journal.py reports/journal/tradebook.xlsx
    python scripts/trade_journal.py reports/journal/tradebook.csv --horizon intraday
    python scripts/trade_journal.py reports/journal/*.csv --horizon week

--horizon: all (default), intraday, week (overnight up to 7 days), month (8-31 days), long (over a month).
Every section is shown for the chosen holding period; "all" also shows the comparison between periods.

Keep the tradebook under reports/journal/ (gitignored: it is your personal data). The round trips are
written to reports/journal/round_trips.csv. Add a "Reason" (or "Tag") column to your own export with a
word per trade (e.g. PCR, breakout, news, VWAP) and the report shows which reasons make money.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import journal as jr  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHOICES = {"all": "all", "intraday": jr.HORIZONS[0], "week": jr.HORIZONS[1], "month": jr.HORIZONS[2],
           "long": jr.HORIZONS[3]}


def show(title: str, table: pd.DataFrame) -> None:
    if table.empty:
        return
    t = table.copy()
    for c in ("avg_win", "avg_loss", "net_per_trade", "total_net", "charges"):
        t[c] = t[c].map(lambda v: f"{'−' if v < 0 else ''}₹{abs(v):,.0f}")
    t["win_rate"] = t["win_rate"].map(lambda v: f"{v:.0%}")
    t["charges_share_of_gross_profit"] = t["charges_share_of_gross_profit"].map(
        lambda v: "–" if pd.isna(v) else f"{v:.0%}")
    t["profit_factor"] = t["profit_factor"].map(lambda v: "∞" if v == float("inf") else f"{v:.2f}")
    t["trades"] = t["trades"].astype(int)
    t = t.rename(columns={"charges_share_of_gross_profit": "charges/gross profit", "net_per_trade": "net/trade"})
    t.index.name = None
    print(f"\n{title}\n{t.to_string()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--horizon", choices=list(CHOICES), default="all")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    trades = pd.concat([jr.read_tradebook(f) for f in args.files], ignore_index=True)
    trades = trades.sort_values("datetime", kind="stable").reset_index(drop=True)
    trips, still_open = jr.round_trips(trades)
    print(f"{len(trades)} trades from {trades['datetime'].min():%d-%b-%Y} to {trades['datetime'].max():%d-%b-%Y} "
          f"-> {len(trips)} round trips; {len(still_open)} positions still open (not counted)")
    charges_note = "from the file" if "charges" in trades and trades["charges"].notna().any() else \
        "estimated (Dhan ₹20/order + statutory, costs.py)"
    print(f"Charges: {charges_note}")

    if args.horizon == "all":
        show("By holding period", jr.summarize(trips, "horizon"))
    chosen = jr.filter_horizon(trips, CHOICES[args.horizon])
    label = "all holding periods" if args.horizon == "all" else CHOICES[args.horizon]
    if not chosen:
        print(f"\nNo round trips held {label}.")
        return 0
    show(f"Overall ({label})", jr.summarize(chosen))
    show(f"By style ({label})", jr.summarize(chosen, "style"))
    show(f"By instrument type ({label})", jr.summarize(chosen, "kind"))
    by_under = jr.summarize(chosen, "underlying")
    show(f"By underlying, best and worst 5 ({label})",
         pd.concat([by_under.head(5), by_under.tail(5)]).drop_duplicates() if len(by_under) > 10 else by_under)
    for t in chosen:
        t.entry_hour = f"{t.open_time.hour:02d}:00" if t.open_time.hour or t.open_time.minute else "no time"
        t.weekday = t.open_time.strftime("%a")
    show(f"By hour of entry ({label})", jr.summarize(chosen, "entry_hour").sort_index())
    show(f"By day of week ({label})", jr.summarize(chosen, "weekday"))
    if any(t.reason for t in chosen):
        for t in chosen:
            t.tag = t.reason or "(no tag)"
        show(f"By your reason / tag ({label})", jr.summarize(chosen, "tag"))

    out = ROOT / "reports" / "journal"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{**vars(t), "gross": t.gross, "net": t.net, "horizon": t.horizon, "style": t.style}
                  for t in trips]).to_csv(out / "round_trips.csv", index=False)
    print(f"\nRound trips written to {out / 'round_trips.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Paper trading

> **Status:** Current. One strategy tracked, as observation only.
> **Scope:** the forward paper-trading ledger (proof plan Stage 3).
> **Last verified against the code:** 2026-10-24

Research only, not investment advice. No orders are placed; nothing here is a trade instruction.

---

## 1. What it does for you

It answers the one question a backtest cannot: does a frozen strategy keep working on data that did not exist when its
rules were written? Every evening the strategy's frozen simulation is re-run on all data to date, and the trades it
enters from its paper start date are recorded in a ledger and tracked to exit, at NSE closing prices with full costs.

It also guards itself: a recorded trade that later changes or disappears is an **integrity event**, and the report
applies the proof plan's kill rules (below the backtest's 5th-percentile path, 8 losses in a row, a loss beyond the
defined max risk).

## 2. Current strategy

| Strategy | Start | Status |
|---|---|---|
| `vrp_condor_pooled` — VRP iron condor on NIFTY + BANKNIFTY, 4 staggered books ([spec](../strategies/vrp_condor_pooled.md)) | 2026-10-26 | **Observation only**: rejected after the backward holdout (2015–21: −5.6% of risk per trade, beats random 60%). Tracked at your choice; never reported as passing, not eligible for live trading |

The strategy fires about 17 times a year, so evidence builds slowly.

## 3. How to use it

It updates in the daily refresh. To update or read it by hand:

```powershell
.venv\Scripts\python.exe scripts\quant_paper.py            # update the ledger and print the report
.venv\Scripts\python.exe scripts\quant_paper.py --report   # report only
```

The report shows closed and open trades, mean return on max risk, wins, a one-sided p-value, the longest losing streak,
trades needed (at least 30), and the status line.

## 4. Files

`tradingagents/analytics/paper.py`, `tradingagents/analytics/paper_strategies.py`, `scripts/quant_paper.py`.

## 5. Settings

None to change. A strategy's entry is frozen: changing it means a new strategy with a new name and start date.

## 6. Outputs

`~/.tradingagents/cache/quant/paper_ledger.sqlite` (tables `trades` and `events`), outside git.

## 7. Known issues

- The backtest band (+11.1% mean, 20.2% spread per trade) comes from the period the settings were chosen on, so it is
  optimistic.
- Fills are end-of-day closes plus modelled slippage, not your real Dhan fills.
- The Stage 3 targets (≥ 3 months, ≥ 50 paper trades, slippage ≤ 1.5× model) apply only to a candidate that has passed
  its backtest; none has yet.

How it is built: [../architecture/15-daily-refresh-and-paper-trading.md](../architecture/15-daily-refresh-and-paper-trading.md).

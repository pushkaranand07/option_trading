# PA-20 — Trade journal: what works in the user's own Dhan trades

| | |
|---|---|
| **Status** | Done (merged) — waiting for the user's tradebook export |
| **Scope** | `tradingagents/analytics/journal.py`, `scripts/trade_journal.py`, `tests/test_trade_journal.py`, `pyproject.toml` (`openpyxl` in `[quant]`) |
| **Related** | [features/trade-journal](features/trade-journal.md), [guides/exporting-your-dhan-tradebook](guides/exporting-your-dhan-tradebook.md) |
| **Pull request** | #26 (branch `quant/trade-journal`) |
| **Date** | 2026-10-24 |

## 1. Problem

Phase 5 of the plan needs the user's own trading idea as exact rules. The user's answers (user): trades NIFTY /
BANKNIFTY options, stock options, futures and shares; buys and sells options depending on the market; holding "depends"
(intraday to weeks); enters on OI / PCR / option chain, chart patterns, news and indicators together. That is a
discretionary method — it cannot be backtested as stated, and inventing rules for it would test a guess. Under 30 trades
in the last 6–12 months (user).

## 2. Decision

Measure the user's real trades first (real decisions, fills and costs), with a view for **every holding period**, as
the user asked: intraday, up to a week, 1–4 weeks, longer. A "Reason" / "Tag" column added by the user shows which
signals pay. Personal data stays in `reports/journal/` (gitignored).

## 3. What was built

| Piece | Does |
|---|---|
| `read_tradebook(path)` | CSV or Excel; finds the header row under title lines; loose column names (symbol, buy/sell, quantity, price, date and time, optional charges and reason); split date + time columns; newest-first files put in time order |
| `classify(symbol)` | option / future / equity, underlying, index or stock |
| `round_trips(trades)` | FIFO per contract, partial fills; positions still open listed separately |
| `RoundTrip` | gross, charges, net; `horizon`; `style` (option buying / selling, futures long / short, shares) |
| `summarize(trips, by)` | trades, win rate, average win / loss, net per trade, total, charges ÷ gross profit, profit factor |
| `scripts/trade_journal.py` | `--horizon all|intraday|week|month|long`; sections by holding period, style, instrument, underlying, entry hour, weekday, reason; writes `reports/journal/round_trips.csv` |

Charges come from the file when it has a charges column, otherwise the Dhan + statutory model (same-day shares as
intraday, otherwise delivery).

## 4. Tests

Header after title lines; newest-first file reordered; FIFO with partial fills; holding periods and styles; charges from
the file vs estimated (intraday cheaper than delivery); symbol classification; summary arithmetic; missing columns named
in the error.

**Bug caught by the tests:** "RELIANCE" ends in "CE" and was classified as a call option (so would any stock ending in
CE or PE). An option symbol always has a strike before CE/PE; the rule now requires a digit there.

## 5. Verification

End-to-end run on a synthetic 120-round-trip tradebook (deleted afterwards so it cannot be mistaken for real results);
unit suite 1,364 passed; ruff clean.

## 6. Risks and open items

- Real Dhan export column names are not yet seen; the script lists the columns it found if it cannot match one.
- With under 30 trades, results are a first look, not evidence. A journal with a reason per trade going forward is the
  path to Phase 5 rules.

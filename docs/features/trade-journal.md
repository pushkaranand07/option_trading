# Trade journal

> **Status:** Current. Built; your tradebook has not been analysed yet.
> **Scope:** analysing your own Dhan tradebook.
> **Last verified against the code:** 2026-10-24

Research only, not investment advice.

---

## 1. What it does for you

Shows what actually makes or loses money in **your own** trades. It reads a Dhan tradebook export (CSV or Excel), pairs
buys and sells into round trips first-in-first-out per contract, and breaks the results down by:

- holding period: intraday, up to 1 week, 1–4 weeks, over a month;
- style: option buying / selling, futures long / short, shares long / short;
- instrument type (option, future, equity) and underlying (best and worst 5 when there are more than 10);
- hour of entry and day of week;
- your own reason or tag, if the file has a column for it.

Each table shows trades, win rate, average win and loss, net per trade, total, charges, charges as a share of gross
profit, and profit factor. With fewer than 30 trades it is a first look, not a firm conclusion.

## 2. How to use it

1. Export your tradebook from Dhan (last 6–12 months).
2. Put it in `reports\journal\` (gitignored: it is personal data).
3. Optional: add a column named `Reason` or `Tag` with a word per trade (e.g. PCR, breakout, news, VWAP).
4. Run:

```powershell
.venv\Scripts\python.exe scripts\trade_journal.py reports\journal\tradebook.xlsx
.venv\Scripts\python.exe scripts\trade_journal.py reports\journal\tradebook.csv --horizon intraday
```

`--horizon`: `all` (default; also compares holding periods), `intraday`, `week` (overnight up to 7 days), `month`
(8–31 days), `long` (over a month). Several files can be given at once.

## 3. Files

`tradingagents/analytics/journal.py`, `scripts/trade_journal.py`. Excel reading needs `openpyxl` (in the `quant` extra).

## 4. Settings

Column names are matched loosely (e.g. "Trade Date", "Buy/Sell", "Qty", "Trade Price"), and the header row is found
within the first 30 rows. Charges come from the file when it has a charges column; otherwise they are estimated with
the Dhan + statutory model in `costs.py` (equity charged as intraday when opened and closed the same day, delivery
otherwise).

## 5. Outputs

Tables printed to the console, and `reports/journal/round_trips.csv` (gitignored). Positions still open at the end of
the file are reported but not counted.

## 6. Known issues

- Never commit a tradebook or its output; the repository is public.
- Estimated charges are a model, not your contract note (the cost model has not yet been checked against a real Dhan
  contract note).
- Symbols are classified from their text (index names, `FUT`, a strike before `CE` / `PE`); unusual symbol formats may
  be misread.

Next step in the plan (Phase 5): turn one setup from the journal into exact rules and test it like any other candidate.

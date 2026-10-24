# Exporting your Dhan tradebook for the trade journal

> **Status:** Current.
> **Scope:** getting your trade history into the [trade journal](../features/trade-journal.md). Your data stays on
> your computer.
> **Last verified against the code:** 2026-10-24

---

## 1. Export

1. In Dhan (web), open the **Reports** section and download your **tradebook** (or the P&L / trade report) for the last
   6–12 months, as **Excel** or **CSV**. The exact menu names in Dhan are not recorded here; any report with one row per
   executed trade works.
2. Save it in the project's `reports\journal\` folder, e.g. `reports\journal\tradebook.xlsx`.
   `reports/` is excluded from git, so the file never goes to GitHub.

## 2. Optional: add your reasons

Add a column named **Reason** (or Tag, Setup, Remarks) with one word per trade: `PCR`, `breakout`, `news`, `VWAP`, … The
report then shows which reasons make money.

## 3. Run

```powershell
.venv\Scripts\python.exe scripts\trade_journal.py reports\journal\tradebook.xlsx
.venv\Scripts\python.exe scripts\trade_journal.py reports\journal\tradebook.xlsx --horizon intraday
```

`--horizon`: `all` (default), `intraday`, `week` (up to 7 days), `month` (8–31 days), `long` (over a month).

## 4. If it cannot read the file

The script names the columns it needs (symbol, buy/sell, quantity, price, date) and lists the columns it found. Send
that message (not the file) and the column matching can be extended.

## 5. How much history is enough

Under 30 trades gives a first look, not evidence. Keep adding a reason per trade; after 30–50 trades the per-reason
results start to mean something.

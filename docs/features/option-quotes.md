# Option quotes (measured trading costs)

> **Status:** Current. Snapshots from 2026-10-23.
> **Scope:** the nightly NSE option bid/ask snapshot and the spread-vs-model report.
> **Last verified against the code:** 2026-10-24

Research only, not investment advice.

---

## 1. What it does for you

Every backtest here assumes a slippage of 1 tick + 1% of premium per option leg per fill. This feature checks that
assumption against reality: each evening it saves NSE's closing bid and ask for every strike of the first 3 expiries of
all 31 symbols, and reports the real half-spread (half the gap between bid and ask, roughly what one fill costs) against
the model.

For your Dhan trading it shows which underlyings are too expensive for multi-leg option trades.

First snapshot (tracker, 2026-10-24): real half-spreads **0.85× the model** on ATM / wing strikes (ATM 1.1% of premium,
wings 1.6%); worst SUNPHARMA 4.8×, JSWSTEEL 4.1×, DIVISLAB 3.1×.

## 2. How to use it

It runs as the last step of the daily refresh. By hand (after the close):

```powershell
.venv\Scripts\python.exe scripts\quant_option_quotes.py            # capture tonight's snapshot, then report
.venv\Scripts\python.exe scripts\quant_option_quotes.py --report   # report on saved snapshots only
```

The report gives the number of snapshot days, the latest median ratio (real half-spread ÷ model slippage) across
symbols, the 5 most expensive symbols, and with more than one day a per-symbol median over all days. Only strikes
within 10% of the underlying are counted.

## 3. Files

`tradingagents/analytics/quotes.py`, `scripts/quant_option_quotes.py`.

## 4. Settings

None. 3 expiries per symbol; the band is 10% of the underlying; the model is `costs.DEFAULT_SLIPPAGE`.

## 5. Outputs

Raw JSON, exactly as NSE served it, at `~/.tradingagents/cache/quant/raw/option_quotes/<date>/<symbol>_<expiry>.json`
(outside git; raw NSE data is never committed).

## 6. Known issues

- The snapshot is the closing book only; intraday spreads, and spreads for your order size, can be wider.
- A holiday or weekend run saves nothing new (the date comes from NSE's timestamp), by design.
- The step fails only if no chain at all could be saved; individual symbol failures are counted and logged.
- Your real Dhan fills (screen price vs fill) are still needed to compare with these spreads (tracker, "Waiting on you").

How it is built: [../architecture/11-nse-data-store.md](../architecture/11-nse-data-store.md), section 6.

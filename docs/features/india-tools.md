# India tools for the analysts

> **Status:** Current.
> **Scope:** the four `get_india_*` tools in `tradingagents/agents/tools.py` and their renderers in
> `tradingagents/dataflows/vendors/nse/tool_text.py` — inputs, outputs and what each answer means.
> Architecture: [../architecture/07-india-market-layer.md](../architecture/07-india-market-layer.md).
> **Last verified against the code:** 2026-10-24

---

## 1. Summary

| Tool | Analyst | Answers |
|---|---|---|
| `get_india_fii_dii_flows` | News Analyst | FII/FPI and DII buying and selling in the cash market, ₹ crore, with publication status |
| `get_india_fo_contract_info` | Market Analyst | Lot size in force on the date (with confidence) and upcoming option expiries with weekdays |
| `get_india_delivery_data` | Market Analyst | Per-session traded quantity, delivered quantity and delivery % for a stock |
| `get_india_index_data_health` | Market Analyst | Whether an index's vendor volume can be trusted, a turnover proxy, and missing sessions |

Common behaviour:

- **The instrument is not an argument.** Each tool reads the run's instrument (`company_of_interest`) from graph
  state. The model only supplies dates (and a look-back).
- **No data from after the run's date.** Dates the model passes are clamped to the run's `trade_date`.
- **Never raises.** Outages and missing files come back as text that says "missing", "unavailable" or "do not
  estimate".
- **Non-Indian instruments** get one line, e.g.
  `NSE F&O contract data applies to NSE-listed instruments only; AAPL is not one. Not applicable.`
  Indian means: ticker ends in `.NS` or `.BO`, or is one of `^NSEI, ^NSEBANK, ^INDIAVIX, ^CNXIT, ^CNXFIN, ^NSMIDCP,
  ^BSESN`.
- **Provenance** is printed on each answer (source URL or "local ... history", fetch time, and `STALE` with its age
  when NSE was unreachable and a cached answer was served).

The examples below show the **shape** of each output, taken from the format strings in the code. Figures shown as
`<...>` are placeholders, not real data.

## 2. `get_india_fii_dii_flows(curr_date)`

**Input:** `curr_date` — `yyyy-mm-dd`.

**What happens:** finds the latest NSE session on or before the date; answers from the local history
(`~/.tradingagents/cache/nse/fii_dii_history.csv`) if that past session was captured; otherwise fetches NSE's latest
published day, saves it to the history, and classifies it.

**Output shape:**

```text
## FII/DII cash-market flows (requested 24-Oct-2026)
Status: pending — fii_dii for 24-Oct-2026 is not published yet (NSE publishes it in the evening, normally by ~20:00 IST). Latest available is for <date>; do not read it as today's figure.
Figures below are for <date> (₹ crore, provisional):
| Category | Buy | Sell | Net |
|---|---:|---:|---:|
| FII/FPI | <buy> | <sell> | <+/-net> |
| DII | <buy> | <sell> | <+/-net> |
(source: https://www.nseindia.com/api/fiidiiTradeReact; fetched <YYYY-MM-DD HH:MM> UTC)
```

**Status values:** `fresh` (figures are for the requested session), `pending` (not out yet, normal before the
evening), `late` (should be out and is not, or a past date never captured — treat as missing), `no_session` (the date
was a weekend or holiday; the message names the latest session). With no figures at all the table is replaced by
`No FII/DII figures are available. Do not estimate them.`

**Limit:** NSE serves only the latest day, so history exists only for days on which a run fetched it.

## 3. `get_india_fo_contract_info(curr_date)`

**Input:** `curr_date` — `yyyy-mm-dd`.

**What happens:** loads the latest F&O bhavcopy on or before the date (up to 7 days back), records every symbol's lot
in `~/.tradingagents/cache/nse/lot_size_history.json`, and reads the instrument's lot and expiries. For a date within
a day of today it also asks NSE's live contract-info API.

**Output shape:**

```text
## NSE F&O contract facts for NIFTY as of 24-Oct-2026
Lot size: <lot> (observed, from bhavcopy <date>)
Option expiries (from traded contracts; weekdays shift around holidays): <dd-Mon-yyyy (Tue)>, <dd-Mon-yyyy (Mon)>, ...
Live expiries (NSE contract info): ...
(source: https://nsearchives.nseindia.com/content/fo/...; fetched ...)
```

- Lot confidence is `observed`, or `extrapolated` (up to 31 days after the last observation, with a "re-check" note).
  When it cannot be settled the line reads `Lot size unknown: ...` with the reason (e.g. the lot changed between two
  observations and the date falls in the gap).
- `^NSEI` → `NIFTY`, `^NSEBANK` → `BANKNIFTY`, `RELIANCE.NS` → `RELIANCE`.
- A stock with no F&O contracts: `<SYMBOL> has no F&O contracts in the <date> bhavcopy (not in F&O).`
- Bhavcopy unreachable: `F&O bhavcopy unavailable (...); lot size and expiries unknown — do not assume them.`

Use this for any sizing or expiry reasoning instead of remembered values.

## 4. `get_india_delivery_data(curr_date, look_back_days=10)`

**Input:** `curr_date` — last date of the window; `look_back_days` — sessions to include, clamped to 1–20.

**Applies to:** NSE stocks only. Indices (tickers starting with `^`) get "not applicable".

**Output shape:**

```text
## Delivery data for RELIANCE (NSE sec_bhavdata_full)
| Date | Close | Traded qty | Delivered qty | Delivery % |
|---|---:|---:|---:|---:|
| <date> | <close> | <qty> | <qty> | <pct>% |
...
Not yet published / unavailable: <dates>
High delivery % on a rise suggests buying for holding; low delivery % suggests intraday/speculative activity.
```

Delivery % is the share of traded quantity that was actually delivered (held overnight) rather than squared off the
same day. With no rows: `No delivery data found for <SYMBOL> in the <n> sessions to <date>.`

## 5. `get_india_index_data_health(start_date, end_date)`

**Input:** `start_date`, `end_date` — `yyyy-mm-dd`; the window is clamped to the run's date.

**Applies to:** `^NSEI, ^NSEBANK, ^INDIAVIX, ^CNXIT, ^CNXFIN, ^NSMIDCP, ^CRSLDX`. The ₹ turnover proxy is built only for
NIFTY 50 and NIFTY BANK; other indices get the volume and gap checks only.

**Output shape:**

```text
## Data health for ^NSEI 01-Oct-2026..24-Oct-2026
Vendor volume for this index is UNRELIABLE and was removed: <n>% of bars have zero volume; latest bar has zero/missing volume.
Use `volume_proxy_turnover_cr` (₹ crore traded across point-in-time constituents) for volume analysis; it is a proxy, label it as such.
Vendor series is MISSING NSE sessions: <dates>. Do not treat the gap as a price move.

Recent sessions (proxy = ₹ crore traded across constituents):
<table of Close, volume_proxy_turnover_cr, proxy_coverage>
```

When everything is consistent: `Vendor volume looks consistent and no NSE sessions are missing.` A survivorship note
is added when the constituent membership is not proven for part of the window.

Call this before any volume-based claim about an Indian index.

## 6. Related context the analysts also get

- `get_quant_signal_report` (Market Analyst) — regime and volatility for NIFTY, BANKNIFTY and the quant layer's F&O
  stocks: [../architecture/16-quant-context-in-agents.md](../architecture/16-quant-context-in-agents.md).
- Every complete report ends with the SEBI disclaimer and an advice-language review
  ([../architecture/09-cli-webapp-and-reports.md](../architecture/09-cli-webapp-and-reports.md)).

## 7. Checking the tools by hand

`scripts/india_live_check.py` exercises the NSE client, calendar, flows, contracts, constituents, index volume, the
options engine, swings, walk-forward validation and the compliance review against live data. It needs the network.
The unit tests (`tests/test_nse_*.py`, `tests/test_india_*.py`) run offline.

## 8. Known issues

- FII/DII history starts empty and grows one day per run.
- The index change log ships empty, so constituent-based answers before the first stored snapshot are marked not
  survivorship-safe until someone enters past reconstitutions.
- Special trading sessions (e.g. Muhurat) are not loaded into the calendar automatically.
- If NSE's holiday list cannot be fetched, the calendar falls back to weekends only, so a holiday can appear as a
  missing session.

This is research and decision support, not investment advice.

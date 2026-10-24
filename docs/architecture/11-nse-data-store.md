# NSE data store

> **Status:** Current.
> **Scope:** `tradingagents/analytics/backfill.py`, `datastore.py`, `prices.py`, `quotes.py`, `universe.py`;
> `scripts/quant_backfill.py`, `scripts/quant_build_store.py`.
> **Last verified against the code:** 2026-10-24

---

## 1. Why a point-in-time store

A backtest that uses a number before it was published looks better than live trading can be. NSE publishes its daily
files after the close, so a value about session *d* can only drive a decision from session *d+1*. Every stored row
therefore carries two dates:

- `trade_date` — the session the row describes;
- `known_from` — the first session on which a trader could have used it (the next trading session).

`datastore.as_of(df, t)` keeps only rows with `known_from <= t`. Nothing in the store calls the network; it is built
from raw files already on disk.

All data lives outside git, under `<data_cache_dir>/quant/` (by default `~/.tradingagents/cache/quant/`, overridable
with the `TRADINGAGENTS_CACHE_DIR` environment variable). See
[../development/data-and-secrets.md](../development/data-and-secrets.md).

## 2. Universe — `universe.py`

| Item | Value |
|---|---|
| Indices | `NIFTY`, `BANKNIFTY` (plus `INDIAVIX` as a price series) |
| Stocks | 29, grouped by sector: banks/finance 9 (HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, BAJFINANCE, FEDERALBNK, CANBK, PNB), IT 5 (INFY, TCS, HCLTECH, TECHM, WIPRO), energy/conglomerate 2 (RELIANCE, ADANIENT), telecom 1 (BHARTIARTL), metals 3 (TATASTEEL, HINDALCO, JSWSTEEL), auto 2 (M&M, MARUTI), pharma 2 (SUNPHARMA, DIVISLAB), FMCG 2 (ITC, NESTLEIND), infra/capital goods 2 (LT, BHEL), aviation 1 (INDIGO) |
| History start | `HISTORY_START = 2018-01-01` |
| How chosen (2026-10-23) | Top ~40 by F&O futures turnover in the week to 2026-10-22, kept only if also in F&O on 2018-01-02 and 2022-01-03 |

**Survivorship.** The list is today's survivors: stocks that fell out of F&O or collapsed are not in it, so
historical results lean optimistic. Every report built on it must carry `SURVIVORSHIP_NOTE`, and the agents' quant
report does ([16](16-quant-context-in-agents.md)).

## 3. Raw download — `backfill.py`

| Kind | File (per day) | NSE URL pattern |
|---|---|---|
| `fo` | F&O bhavcopy (UDiFF format from 2024-07-08, legacy before; both URLs are tried) | from `derivatives.udiff_url` / `legacy_url` |
| `participant` | Participant-wise open interest (FII / DII / Pro / Client) | `/content/nsccl/fao_participant_oi_DDMMYYYY.csv` |
| `mto` | Security-wise delivery position | `/archives/equities/mto/MTO_DDMMYYYY.DAT` |
| `indices` | Official open/high/low/close of every NSE index, incl. India VIX | `/content/indices/ind_close_all_DDMMYYYY.csv` |

- Files are kept exactly as NSE served them, under `raw/<kind>/<year>/`, written atomically.
- **Manifest.** `raw/manifest.csv` records each (day, kind) as `ok` or `missing` with URL, bytes and fetch time. Later
  lines win, so a retried `missing` that became `ok` replaces the old line. Re-running skips what is done.
- **Retry.** `--retry-missing` re-checks days marked missing. The daily job uses it for the last 10 days, because a
  run before NSE publishes would otherwise mark today missing for good.
- **Stopping cleanly.** If NSE becomes unreachable the run stops (`stopped_early`) instead of marking days missing,
  so the next run resumes.
- **Throttle.** `scripts/quant_backfill.py --interval` (default 1.5 seconds between requests) so NSE does not block
  the IP.
- **Weekend probing.** NSE sometimes trades on a weekend (Budget days 2025-02-01 and 2026-02-01, Diwali Muhurat
  sessions, special live sessions). Every calendar day is visited; on a weekend only the `WEEKEND_PROBE` file
  (`"indices"`) is requested first, and the other kinds only if it was published. A normal weekend costs one request.
  This fix probed every weekend since 2015 (1,232 weekend days) and recovered 11 real sessions (tracker, 2026-10-24).

The tracker records the full download as 9,200/9,200 files (2018 → today), plus 2015–2017 F&O and index files for
the backward holdout.

## 4. Parquet store — `datastore.py`

Layout: `<data_cache_dir>/quant/store/<dataset>/<year>.parquet`.

| Dataset | Content |
|---|---|
| `fo_summary` | One row per (day, symbol): near-month future close/settle, underlying price, futures OI and change, option OI, PCR by OI and by volume, turnover, lot size |
| `option_chain` | Option contracts within `CHAIN_MAX_DAYS = 70` days to expiry and `CHAIN_MAX_MONEYNESS = 0.25` of the underlying |
| `participant` | FII / DII / Pro / Client open interest by contract type |
| `delivery` | Traded and deliverable quantity, delivery % (EQ series, universe only) |
| `index_close` | NSE's official OHLC for NIFTY, BANKNIFTY and India VIX |

Other files written beside them by the scripts: `prices/prices.parquet`, `iv/iv30.parquet`,
`vol_forecasts/<symbol>.parquet` (+ `comparison.csv`), `regime/regime.parquet`, `chronos/<symbol>.parquet`,
`events/<idea>_trades.csv`, `quality_report.csv`.

Key behaviour:

- **`known_from` = next session.** `next_sessions` maps each F&O trading day to the following one; the last day maps
  to the next weekday. `build_year` stamps every dataset with it.
- **Parsers** accept both F&O formats, participant files with or without an "as on <date>" title (short or full month
  name; a title that disagrees with the file date raises), and the MTO record layout.
- **Atomic writes.** `write_parquet` writes to a temporary file beside the target and swaps it in with `os.replace`.
  A reader sees the old file or the new one, never half of one. A failure raises, because a silently skipped write
  would leave stale data that looks current.
- **Lot sizes.** The UDiFF format states the lot; the legacy format does not. For those files
  `lots_from_open_interest` takes the greatest common divisor of open interest and its change on the nearest-expiry
  contracts (OI is in whole lots), then the multiple of it nearest a turnover-based estimate. `despike_lots` /
  `clean_lot_sizes` then remove blips shorter than 5 sessions with the same lot on both sides. The tracker records
  lot sizes for 2018–mid-2024 as exact from open interest (they had been estimated ±3% before).
- **Partial rebuilds.** `build_year(year, datasets=...)` parses only the datasets named, e.g. `index_close` after
  downloading index files.
- **Reading.** `load(dataset, start, end, symbols)` filters symbols while reading, because the option chain is about
  15 million rows across all symbols.

## 5. Prices — `prices.py`

- Daily OHLCV from Yahoo Finance through the data layer. Yahoo's `close` is split-adjusted; `adj_close` is also
  dividend-adjusted and is what return calculations use. **Neither is the traded price:** option strikes are always
  compared with NSE's own prices (`underlying_price` / `fut_close` in `fo_summary`).
- **NSE index bars replace Yahoo.** `merge_nse_indices` replaces Yahoo's NIFTY / BANKNIFTY / India VIX bars with NSE's
  official values wherever NSE has the day (`source = "nse"`).
- **Stock gap filling.** `fill_stock_gaps` fills sessions Yahoo lacks from NSE's equity bhavcopy: NSE's prices for the
  missing day are scaled by `yahoo_close(prev) / nse_close(prev)`, so the bar is on Yahoo's adjusted basis
  (`source = "nse_fill"`). Runs of missing days are filled in order.
- **Last complete session at 16:00.** `last_complete_session_date` returns today from 16:00 local time (NSE closes at
  15:30 IST), otherwise yesterday, so an unfinished live bar is never stored as a finished day.
- `save_prices` stamps `known_from` from NSE's trading calendar.
- `quality_report` lists, per symbol, sessions still missing and one-day moves above 20% with no split recorded. The
  tracker records 0 missing sessions in any dataset and every stock jump above 20% verified as a real event.

## 6. Option quotes — `quotes.py`

End-of-day bhavcopies have closes but no bid/ask, so every backtest **assumes** slippage. NSE's option-chain API shows
the best bid and offer per strike; after the close it holds the closing book.

- `capture(symbols, expiries=3)` saves the chain of the first 3 expiries per symbol as raw JSON under
  `raw/option_quotes/<snapshot date>/<symbol>_<expiry>.json`. The snapshot date comes from NSE's own timestamp, so a
  holiday or weekend run (NSE still serves the last session's book) writes nothing new. One symbol failing does not
  lose the others.
- `parse` gives one row per (strike, type) with both a bid and an ask, plus mid and half-spread.
- `versus_model` compares the median real half-spread with the modelled slippage (1 tick + 1% of premium) for strikes
  within 10% of the underlying.

First snapshot (2026-10-23, tracker): real half-spreads 0.85× the model on ATM / wing strikes (ATM 1.1% of premium,
wings 1.6%); worst SUNPHARMA 4.8×, JSWSTEEL 4.1×, DIVISLAB 3.1×. Use and outputs:
[../features/option-quotes.md](../features/option-quotes.md).

## 7. Building it

```powershell
.venv\Scripts\python.exe scripts\quant_backfill.py                  # 2018-01-01 to yesterday, all kinds (slow by design)
.venv\Scripts\python.exe scripts\quant_build_store.py               # every year, plus prices and IV
.venv\Scripts\python.exe scripts\quant_build_store.py --years 2026  # rebuild one year (what the daily job does)
```

`quant_build_store.py` prints a data-quality summary (missing participant / MTO / index files per F&O day, symbols
below 98% coverage, price bars by source) and writes the full issue list to `<store>/quality_report.csv`. With
`--years`, the 30-day IV table is recomputed only for those years.

Related: [10 — overview](10-quant-layer-overview.md), [13 — volatility and regime models](13-volatility-and-regime-models.md).

# 07 — India market layer (NSE)

> **Status:** Current.
> **Scope:** `tradingagents/dataflows/vendors/nse/` (client, calendar, derivatives, indices, flows, index_volume,
> tool_text), the four `get_india_*` agent tools in `tradingagents/agents/tools.py`, and the report compliance hook
> `tradingagents/compliance.py`. The quant layer's NSE data store is separate: [11-nse-data-store.md](11-nse-data-store.md).
> **Last verified against the code:** 2026-10-24

---

## 1. Why this layer exists

The upstream framework was built for US markets. Running it on NSE instruments with Yahoo data alone gave wrong or
misleading answers. The live checks of 2026-10-22, recorded in section 13 of
[INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md](../plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md), found:

| What was observed | Why it matters |
|---|---|
| `nseindia.com/` homepage answers **403** to non-browser clients; `/option-chain` answers 200 with cookies | The usual "hit the homepage for cookies" recipe fails |
| `/api/option-chain-indices` answers **404** (moved to `/api/option-chain-v3`) | NSE endpoints move without notice |
| Yahoo `^NSEI` volume read 391,600 → 285,800 → **0**, while RELIANCE alone traded about 15M shares | Index volume from Yahoo is not traded volume; volume patterns on it are noise |
| Yahoo `^NSEI` had **no 2026-10-21 bar** although NSE traded | Vendor gaps can look like price moves |
| NIFTY lot **50** (Jan-2024, derived) → **65** (Oct-2026); BANKNIFTY 15 → 30 | Any constant lot size is wrong for some period |
| NIFTY expiries are Tuesdays, but **2026-11-09 and 2026-11-23 are Mondays**; BANKNIFTY is monthly only | Expiry days must come from data |

Plus the publication problem: FII/DII figures, bhavcopies and delivery data come out in the evening, so a question
asked at 15:45 IST would otherwise read yesterday's numbers as today's.

The design rule throughout: **report what is known, say when something is missing or late, never estimate.**

## 2. Module map

| Module | Problem (build plan ID) | Main names |
|---|---|---|
| `nse/client.py` | P-01 NSE blocking | `NSEClient`, `default_client()`, `Fetched`, `NSEDataNotPublishedError` |
| `nse/calendar.py` | P-03 sessions and holidays, P-04 publication lag | `NSECalendar`, `SessionState`, `classify_availability`, `Availability`, `EXPECTED_BY`, `now_ist` |
| `nse/derivatives.py` | P-08 lot sizes and expiries | `fo_bhavcopy`, `latest_bhavcopy`, `LotSizeHistory`, `expiries_from_bhavcopy`, `live_contract_info`, `delivery_data`, `equity_bhavcopy`, `fno_symbol` |
| `nse/indices.py` | P-09 survivorship bias | `fetch_constituents`, `ConstituentStore`, `Membership`, `survivorship_warning` |
| `nse/flows.py` | P-04 FII/DII publication and history | `get_fii_dii`, `FlowsReport`, `record_history`, `load_history` |
| `nse/index_volume.py` | P-02 index volume and gaps | `assess_volume`, `constituent_turnover_proxy`, `sanitize_index_ohlcv` |
| `nse/tool_text.py` | Agent-facing text | `is_indian_instrument`, `fii_dii_text`, `fo_contract_text`, `delivery_text`, `index_health_text` |

All failures surface as the shared `VendorError` types from `dataflows/errors.py`
(see [06-data-vendors.md](06-data-vendors.md)), so the rest of the system treats NSE like any other vendor.

## 3. The NSE client (`client.py`)

One process-wide `NSEClient` (`default_client()`) so every tool shares one session, throttle and circuit breaker.

| Behaviour | Setting |
|---|---|
| Browser headers (`BROWSER_HEADERS`) on every request | Chrome User-Agent, `Referer: https://www.nseindia.com/` |
| Cookie bootstrap from pages that are not blocked | `BOOTSTRAP_PAGES = ("/option-chain", "/market-data/live-equity-market", "/")` — homepage last |
| Throttle | `MIN_INTERVAL_SECONDS = 0.35` between requests |
| Retries | `MAX_ATTEMPTS = 4`; backoff `1 s × 2^attempt`, capped at 30 s, with jitter; `Retry-After` honoured |
| Session loss | 401/403, or HTTP 200 with an HTML body where JSON was expected → clear cookies, re-bootstrap, retry |
| Throttling / server faults | 429, 500, 502, 503, 504 → back off and retry |
| 404 | `NSEDataNotPublishedError` (a `NoMarketDataError`): "not published or moved", not an outage |
| Circuit breaker | After `BREAKER_THRESHOLD = 5` failed requests, `VendorUnavailableError` for `BREAKER_COOLDOWN_SECONDS = 120` |
| Disk cache | `<data_cache_dir>/nse/`, keyed by a hash of URL + params |
| Stale on outage | If NSE cannot be reached and a cached answer exists, it is served with `stale=True`; `Fetched.provenance()` prints its age |

Two entry points: `get_json(path, params, ttl=300)` for `/api` endpoints, and `get_archive(url, ttl=None)` for files
on `nsearchives.nseindia.com`, which never change once published and are cached forever by default.

## 4. Calendar and publication status (`calendar.py`)

### 4.1 Sessions

`NSECalendar.from_nse()` reads NSE's `/api/holiday-master?type=trading` (capital-market segment `CM`, cached for a
day). If NSE is unreachable it falls back to **weekends only** and logs a warning. A weekday that is not a holiday
is a session.

- `is_trading_day`, `previous_session`, `latest_session`, `sessions_between`.
- `missing_sessions(have, start, end)` — sessions a vendor series lacks (catches the missing `^NSEI` bar).
- `unexpected_bars(have)` — bars dated on non-sessions.
- `session_state(now)` → `no_session`, `pre_market` (before 09:00 IST), `pre_open` (09:00–09:15),
  `open` (09:15–15:30), `post_close`.

**Special sessions** (a weekend Muhurat or Budget-day session) are trading days. `from_nse()` adds two kinds
([PA-27](../PA_19-weekend-nse-sessions.md)):

- `KNOWN_SPECIAL_SESSIONS` — the 11 weekend sessions since 2015, each verified by downloading its NSE files
  (NSE's holiday list covers only the current year, so past sessions come from this list);
- holidays NSE marks with `*` (e.g. "Diwali Laxmi Pujan*"), which have a Muhurat session — kept in `muhurat_days`.

On a Muhurat day `session_state` never reports `open` during regular hours (the one-hour Muhurat window is announced
separately and not modelled): `pre_market` before 15:30, `post_close` after, so that day's files are expected.

### 4.2 Publication status

`classify_availability(dataset, requested, published, now, calendar)` compares the date **inside** the data with
the date asked for:

| Status | Meaning |
|---|---|
| `fresh` | The data is for the requested session |
| `pending` | Not out yet, and not expected yet — the message says "do not read it as today's figure" |
| `late` | Should be out by now and is not — "treat today's value as missing" |
| `no_session` | The requested date was not a session; the message names the latest session |

The expected-by times (`EXPECTED_BY`, IST, on the session's own day) are conservative approximations:
`fii_dii` 20:00; `cm_bhavcopy`, `delivery`, `fo_bhavcopy` 19:00. The clock only separates `pending` from `late`; it
never makes old data `fresh`.

## 5. F&O contracts and delivery data (`derivatives.py`)

- **Bhavcopy in one schema.** `fo_bhavcopy(day)` loads NSE's F&O bhavcopy in either format — UDiFF (from
  `UDIFF_SINCE = 2024-07-08`, carries the lot size `NewBrdLotQty`) or the legacy `foDDMONYYYYbhav.csv` (no lot
  column) — into `UNIFIED_COLUMNS` (`trade_date, instrument, symbol, expiry, strike, option_type, open, high, low,
  close, settle, underlying_price, open_interest, oi_change, contracts, turnover, lot_size, format`).
  `latest_bhavcopy(on_or_before)` walks back up to 7 days past holidays and unpublished days.
- **Lot sizes as dated runs.** `LotSizeHistory` (saved to `<data_cache_dir>/nse/lot_size_history.json`) records
  `(first_seen, last_seen, lot, source)` per symbol. UDiFF lots are `bhavcopy`; legacy lots are `derived` from
  turnover ÷ (contracts × close) over the day's futures. `lot_size(symbol, day)` answers with a confidence:
  `observed` inside a run; `extrapolated` up to `EXTRAPOLATE_DAYS = 31` after the last observation (with a "re-check"
  note); otherwise it raises `NoMarketDataError` — including when the date falls between two runs with different
  lots ("the change date is uncertain").
- **Expiries from data.** `expiries_from_bhavcopy` (options that actually traded) and `live_contract_info` (NSE
  `/api/option-chain-contract-info`). `describe_expiries` prints the weekday so a holiday-shifted expiry is visible.
- **Delivery data.** `delivery_data(day)` reads `sec_bhavdata_full_DDMMYYYY.csv` (EQ series): traded quantity,
  delivered quantity, delivery %.
- **Equity bhavcopy.** `equity_bhavcopy(day)` gives unadjusted EQ-series OHLC and volume (full bhavcopy, or the
  legacy CM bhavcopy).
- **Symbols.** `fno_symbol` maps Yahoo-style tickers to NSE F&O symbols (`^NSEI` → `NIFTY`, `^NSEBANK` →
  `BANKNIFTY`, `RELIANCE.NS` → `RELIANCE`).

## 6. Index membership (`indices.py`)

Backtesting "Nifty 50 stocks" with today's list tests only the winners. NSE publishes the current list as CSV
(`CONSTITUENT_FILES` for NIFTY 50, NIFTY BANK, NIFTY NEXT 50, NIFTY 100, NIFTY 500) but no machine-readable history.

`ConstituentStore` (files `index_snapshots.json` and `index_changes.json` under `<data_cache_dir>/nse/`):

- `refresh(index, today)` stores today's list as a dated snapshot; snapshots accumulate.
- `add_change(index, day, added, removed)` records an announced reconstitution; `set_complete_since(index, day)`
  declares the change log complete from that date.
- `members_as_of(index, day)` returns a `Membership` with `method` (`snapshot`, `reconstructed`,
  `nearest_snapshot`) and **`survivorship_safe`**. A date before the declared complete log is answered but flagged
  `survivorship_safe=False`; `survivorship_warning` turns that into a report line.

The change log ships empty: nothing is invented. Filling it from NSE press releases is a manual task (section 10).

## 7. FII/DII flows (`flows.py`)

NSE's `/api/fiidiiTradeReact` returns only the latest published day; there is no free history endpoint.
`get_fii_dii(requested)`:

1. Looks up the latest session on or before the requested date.
2. If that past session is already in the local history (`<data_cache_dir>/nse/fii_dii_history.csv`), answers from
   it with no network call.
3. Otherwise fetches the API (cached 600 s), appends the day to the history once, and classifies the result with
   `classify_availability`.
4. A past date never captured is reported `late` / missing — never estimated.

`FlowsReport.to_text()` prints a table of FII/FPI and DII buy, sell and net (₹ crore, provisional) with its status
and source.

## 8. Index volume and gaps (`index_volume.py`)

- `assess_volume(volume, constituent_volume)` marks a volume column unreliable when more than `MAX_ZERO_SHARE = 5%`
  of bars are zero, the latest bar is zero or missing, or the median index volume is below
  `MIN_RATIO_TO_CONSTITUENTS = 5%` of the constituents' summed volume.
- `constituent_turnover_proxy(index, start, end)` sums ₹ traded value (close × volume, from Yahoo) over the members
  **as of each date** (from `ConstituentStore`), with per-date coverage and the `survivorship_safe` flag.
- `sanitize_index_ohlcv(df, index, calendar, proxy)` blanks unreliable volume, adds `volume_proxy_turnover_cr` and
  `proxy_coverage`, sets `volume_source` (`vendor`, `unavailable` or `constituent_turnover_proxy`), and lists
  missing sessions and unexpected bars.

## 9. Agent tools and "not applicable"

The four tools are in `tradingagents/agents/tools.py`. Each reads the instrument from graph state
(`company_of_interest`) and clamps its date with `as_of` / `as_of_window`, so it never serves data after the run's
date. Each calls a function in `nse/tool_text.py`, which **never raises**: an outage or missing file becomes an
explicit "missing — do not estimate" line.

| Tool | Offered to | `tool_text` function | Applies to |
|---|---|---|---|
| `get_india_fii_dii_flows(curr_date)` | News Analyst | `fii_dii_text` | any Indian instrument |
| `get_india_fo_contract_info(curr_date)` | Market Analyst | `fo_contract_text` | any Indian instrument (says so when the symbol has no F&O contracts) |
| `get_india_delivery_data(curr_date, look_back_days=10)` | Market Analyst | `delivery_text` | Indian stocks only, not indices; `look_back_days` clamped to 1–20 |
| `get_india_index_data_health(start_date, end_date)` | Market Analyst | `index_health_text` | NSE index tickers in `INDEX_TICKERS` |

How "Indian" is decided (`tool_text.is_indian_instrument`): the ticker ends in `.NS` or `.BO`, or is one of
`^NSEI, ^NSEBANK, ^INDIAVIX, ^CNXIT, ^CNXFIN, ^NSMIDCP, ^BSESN`. The index health check uses its own list
(`index_volume.INDEX_TICKERS = ^NSEI, ^NSEBANK, ^INDIAVIX, ^CNXIT, ^CNXFIN, ^NSMIDCP, ^CRSLDX`), and builds the
constituent proxy only for NIFTY 50 and NIFTY BANK.

For anything else the tool returns one line, for example:

```text
FII/DII flow data applies to NSE-listed instruments only; AAPL is not one. Not applicable.
```

So offering the tools to every run costs one line of context on a US ticker, not a wrong answer. Examples of the
outputs are in [../features/india-tools.md](../features/india-tools.md).

Two other India-relevant pieces reach the agents:

- `get_quant_signal_report` (Market Analyst) — regime and volatility context for the quant layer's universe; see
  [16-quant-context-in-agents.md](16-quant-context-in-agents.md).
- `benchmark_map` in `default_config.py` maps `.NS` → `^NSEI` and `.BO` → `^BSESN` for the reflection layer's alpha.

## 10. Other safeguards from the build plan

| Problem | Module | What it does |
|---|---|---|
| P-17 look-ahead in swing detection | `tradingagents/analytics/swings.py` | Swings carry `confirmed_at`; `find_lookahead()` is a replay check |
| P-18 overfitting | `tradingagents/analytics/validation.py` | Walk-forward with embargo, PSR, Deflated Sharpe, minimum-trades verdict |
| P-25 SEBI | `tradingagents/compliance.py` | `DISCLAIMER` on every complete report (Markdown and HTML); `review(text)` flags red-flag phrases such as "guaranteed returns" or "sure-shot" (negations ignored); the text itself is never rewritten |
| P-15 options engine | `option_backtester/` + `tradingagents/integrations/optopsy/` | See [08-option-backtester.md](08-option-backtester.md) |

`scripts/india_live_check.py` runs each fix against live NSE / Yahoo data and prints what happened (network
required; options `--skip-optopsy`, `--skip-walkforward`).

## 11. What still needs a human

From section 13 of the build plan:

- **Index change log.** NSE publishes reconstitutions only as press-release PDFs. Until past changes are entered and
  `set_complete_since()` is called, dates before the first snapshot are flagged `survivorship_safe=False`.
- **FII/DII history** builds up one day per run. Older dates are reported as missing.
- **Publication times** in `EXPECTED_BY` are approximations; status is always decided by the date in the data.
- **Special sessions** are not loaded automatically (section 4.1).

## 12. Tests

| Area | Test file |
|---|---|
| Client | `tests/test_nse_client.py` |
| Calendar and flows | `tests/test_nse_calendar_flows.py` |
| Contracts, lot sizes, constituents | `tests/test_nse_contracts_universe.py` |
| Index volume | `tests/test_india_index_volume.py` |
| Swings and validation | `tests/test_india_analytics.py` |
| Options bridge and compliance | `tests/test_optopsy_bridge_compliance.py` |

All run offline; the suite blocks network access (see
[../development/testing-and-lint.md](../development/testing-and-lint.md)).

This layer is research and decision support, not investment advice.

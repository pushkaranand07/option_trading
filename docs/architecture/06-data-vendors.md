# 06 — Data vendors

> **Status:** Current.
> **Scope:** `tradingagents/dataflows/` — vendor routing, fallbacks and errors, each data vendor, caching, and the
> point-in-time rules that keep data on or before the analysis date. The NSE vendor has its own document:
> [07-india-market-layer.md](07-india-market-layer.md).
> **Last verified against the code:** 2026-10-24

---

## 1. What this layer does

The analysts never call a data source directly. They call LangChain tools in `tradingagents/agents/tools.py`
(see [03-agents-and-tools.md](03-agents-and-tools.md)). Each tool:

1. takes the run's `trade_date` from graph state and clamps any date the model asks for to it
   (`as_of`, `as_of_window` in `tradingagents/dataflows/date_window.py`);
2. calls `route_to_vendor(method, ...)` in `tradingagents/dataflows/router.py`, which picks the vendor(s) from the
   configuration and tries them in order;
3. gets back text that the model can quote — either data, or an explicit sentinel such as `NO_DATA_AVAILABLE` /
   `DATA_UNAVAILABLE` that tells the model not to invent values.

| File | Role |
|---|---|
| `dataflows/router.py` | Categories, the method → vendor table, the fallback chain and the sentinels |
| `dataflows/errors.py` | The error types vendors raise (`VendorError` and its three subclasses) |
| `dataflows/config.py` | The process-wide config and the per-run config (`run_config`, a `ContextVar`) |
| `dataflows/date_window.py` | Point-in-time rules (section 6) |
| `dataflows/symbols.py` | `normalize_symbol` (broker symbol → Yahoo symbol) and `safe_ticker_component` (path safety) |
| `dataflows/files.py` | `replace_file` (atomic cache writes) and `locked` (one writer at a time, Windows and POSIX) |
| `dataflows/net.py` | `get_scrubbed` (HTTP GET that keeps API keys out of error text) and `vendor_reachable` |
| `dataflows/vendors/` | One module or package per vendor (section 4) |

## 2. Categories and the default vendors

`TOOLS_CATEGORIES` in `router.py` groups the routed methods. The defaults come from `data_vendors` in
`tradingagents/default_config.py`.

| Category | Methods | Default vendor chain | Vendors that implement it |
|---|---|---|---|
| `core_stock_apis` | `get_stock_data` | `yfinance` | `alpha_vantage`, `yfinance` |
| `technical_indicators` | `get_indicators` | `yfinance` | `alpha_vantage`, `yfinance` |
| `fundamental_data` | `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement` | `sec_edgar,yfinance` | statements: `alpha_vantage`, `sec_edgar`, `yfinance`; `get_fundamentals`: `alpha_vantage`, `yfinance` |
| `news_data` | `get_news`, `get_global_news`, `get_insider_transactions` | `yfinance` | `alpha_vantage`, `yfinance` |
| `macro_data` | `get_macro_indicators` | `fred` | `fred` |
| `prediction_markets` | `get_prediction_markets` | `polymarket` | `polymarket` |

Not routed (called directly, outside `route_to_vendor`):

- **StockTwits and Reddit** — fetched by the Sentiment Analyst itself (`agents/analysts/sentiment_analyst.py`).
- **The verified market snapshot** — `get_verified_market_snapshot` calls
  `vendors/yahoo/snapshot.py:build_verified_market_snapshot` directly.
- **NSE India tools** — `get_india_*` call `vendors/nse/tool_text.py` (see [07](07-india-market-layer.md)).

## 3. Routing, fallbacks and errors

### 3.1 Choosing the vendor chain

`get_vendor(category, method)` reads `tool_vendors[method]` first (a per-tool override), then
`data_vendors[category]`. The value is a comma-separated list and **is the whole chain**: the router does not fall
back to vendors the user did not list. Only the value `"default"` means "every vendor that implements the method",
in the order of `VENDOR_METHODS`. A listed vendor that does not implement the method is skipped; if none do,
`route_to_vendor` raises `ValueError`.

Example: `data_vendors={"core_stock_apis": "yfinance,alpha_vantage"}` tries Yahoo, then Alpha Vantage.

The config read is the per-run one when a graph run is in progress (`config.run_config`), so two graphs in one
process can use different vendors. `set_config` merges dict-valued keys one level deep.

### 3.2 The error types

From `dataflows/errors.py`. The number of types equals the number of different router reactions.

| Error | Meaning | Router reaction |
|---|---|---|
| `NoMarketDataError(symbol, canonical, detail)` | The vendor answered but has no usable rows (empty **or** stale) | Remember it, try the next vendor |
| `VendorUnavailableError` | Throttled or failed request; says nothing about the instrument | Log a warning, try the next vendor |
| `VendorNotConfiguredError` (also a `ValueError`) | Selected but its API key / config is missing | Log, keep as first error, try the next vendor |
| any other exception | An unexpected failure | Log a warning (never silent), keep it, try the next vendor |

Vendor-named subclasses exist: `AlphaVantageRateLimitError` (unavailable), `AlphaVantageNotConfiguredError` and
`FredNotConfiguredError` (not configured), `NSEDataNotPublishedError` (no data).

### 3.3 What comes back when no vendor served the call

`route_to_vendor` decides in this order after the chain is exhausted:

1. Any vendor was **unavailable** → returns the `DATA_UNAVAILABLE: no configured vendor could serve ...` text
   (`vendor_unavailable`). A throttled vendor never said whether it has the symbol, so another vendor's "no data"
   cannot speak for the whole chain.
2. A vendor **failed** with an untyped error and another reported no data → also `DATA_UNAVAILABLE`.
3. Every vendor that answered said **no data** → returns `NO_DATA_AVAILABLE: No usable market data for '<symbol>'`
   with the canonical symbol and the vendor's detail (e.g. "latest row is ... stale") (`no_data_available`).
4. Only real errors → for the optional categories (`OPTIONAL_CATEGORIES = {"macro_data", "prediction_markets"}`)
   a `DATA_UNAVAILABLE: optional ... Proceed without it` sentinel; for core categories the first error is
   **raised**, so a broken primary vendor is loud.

## 4. The vendors

### 4.1 Yahoo Finance (`vendors/yahoo/`, key: none)

| Module | What it serves |
|---|---|
| `common.py` | `yf_retry` — retries `YFRateLimitError` with exponential backoff (3 retries, base 2 s); any other failure becomes `VendorUnavailableError`; Yahoo saying "no such data" returns `None`. `raise_for_empty` checks `vendor_reachable(YAHOO_HOST)` to tell an outage from an empty answer |
| `ohlcv.py` | `load_ohlcv(symbol, as_of_date, fill_gaps=True)` — the cached 5-year daily download used by prices, indicators and the snapshot (section 5). Refuses data more than `MAX_OHLCV_STALE_DAYS = 10` days older than the request |
| `market.py` | `get_YFin_data_online` (OHLCV for a window), `get_stock_stats_indicators_window` (indicators via `stockstats`), plus helpers `get_closes`, `get_daily_history` |
| `fundamentals.py` | `get_fundamentals` (`Ticker.info`), the three statements, insider transactions — all subject to the point-in-time withholding rules (section 6) |
| `news.py` | `get_news_yfinance`, `get_global_news_yfinance` (searches the `global_news_queries` in the config) |
| `snapshot.py` | `build_verified_market_snapshot` — a deterministic snapshot (latest bar on or before the date, common indicators, recent closes) that the Market Analyst must treat as ground truth for exact numbers |

All Yahoo entry points pass the ticker through `normalize_symbol` (e.g. `XAUUSD` → `GC=F`, `600519.SH` →
`600519.SS`, `700.HK` → `0700.HK`). Indian tickers use Yahoo's own suffixes (`RELIANCE.NS`, `^NSEI`) unchanged.

### 4.2 Alpha Vantage (`vendors/alpha_vantage/`, key: `ALPHA_VANTAGE_API_KEY`)

Stock, indicator, fundamentals, news, global news and insider transactions. `common._make_api_request` sends the key
through `get_scrubbed` so it never appears in exceptions, and classifies the JSON notices: rate-limit wording →
`AlphaVantageRateLimitError`; invalid / missing key → `AlphaVantageNotConfiguredError`; `"Error Message"` →
`VendorUnavailableError`. A missing key raises `AlphaVantageNotConfiguredError`.

### 4.3 SEC EDGAR (`vendors/sec_edgar.py`, key: none)

The three statements **as filed**: EDGAR dates every fact by its filing, so a run dated `as_of_date` sees what was on
file by then, restatements at the vintage that was current. US filers only; a ticker absent from EDGAR's ticker map
falls through to the next vendor (`yfinance` by default). SEC requires a User-Agent with a contact address:
`SEC_EDGAR_USER_AGENT` (optional; the default carries a placeholder address). Ticker map and company facts are
cached for 24 hours under `<data_cache_dir>/sec_edgar/`. Every request failure is `VendorUnavailableError`.

### 4.4 FRED (`vendors/fred.py`, key: `FRED_API_KEY`)

`get_macro_data(indicator, as_of_date, look_back_days=None)` for `get_macro_indicators`. Accepts a friendly alias from
`MACRO_SERIES` (e.g. `cpi`, `10y_treasury`, `unemployment`, `ecb_deposit_rate`) or any raw FRED series ID. The
**data vintage is pinned** to `as_of_date` (FRED's real-time bounds, clamped to FRED's own date in US Central time),
so a past run sees values as published then, not later revisions. Default look-back 365 days. A missing key raises
`FredNotConfiguredError`; because `macro_data` is optional, the run continues with a sentinel.

### 4.5 Polymarket (`vendors/polymarket.py`, key: none)

`get_prediction_markets(topic, limit, as_of_date)` — implied probabilities of open markets from the public Gamma API.
Polymarket has no history, so a run dated before today gets a "withheld" notice instead of live odds.

### 4.6 StockTwits and Reddit (`vendors/stocktwits.py`, `vendors/reddit.py`, key: none)

Called by the Sentiment Analyst. StockTwits reads the public symbol stream (crypto mapped to `<BASE>.X`); Reddit reads
the public RSS search feed (the JSON search endpoint is blocked for anonymous clients), backing off once on 429 and
honouring `Retry-After`. Both trim items to the analysis window and both report a failed fetch as `<... unavailable>`,
never as "no posts", because those are different claims. When `TYPESAFE_API_KEY` is set, posts are screened by
`tradingagents/agents/post_screen.py` before the analyst sees them.

### 4.7 NSE India (`vendors/nse/`, key: none)

Session-safe NSE client, calendar, F&O bhavcopies, delivery data, FII/DII flows, index constituents and index-volume
repair. See [07-india-market-layer.md](07-india-market-layer.md).

## 5. Caching and the cache directory

All caches live under `data_cache_dir`, which defaults to `~/.tradingagents/cache` and is overridden by
`TRADINGAGENTS_CACHE_DIR` (`default_config.py`). Results go to `results_dir` (`~/.tradingagents/logs`,
`TRADINGAGENTS_RESULTS_DIR`).

| Cache | Location under `data_cache_dir` | Lifetime |
|---|---|---|
| Yahoo daily OHLCV | `<SYMBOL>-YFin-data.csv` (one file per symbol, 5 years to today) | Served only on the day it was written; for a request about today, refetched after `OHLCV_CACHE_TTL_SECONDS = 900` because Yahoo's in-session bar is partial |
| SEC EDGAR | `sec_edgar/company_tickers.json`, `sec_edgar/CIK<cik>.json` | 24 hours |
| NSE answers | `nse/<hash>.json` / `.bin` + `.meta.json` | Per call: JSON default 300 s; archive files forever (see [07](07-india-market-layer.md)) |
| NSE derived stores | `nse/lot_size_history.json`, `nse/fii_dii_history.csv`, `nse/index_snapshots.json`, `nse/index_changes.json` | Grow over time |
| Quant data store | `quant/store/` | See [11-nse-data-store.md](11-nse-data-store.md) |
| Checkpoints | `checkpoints/` | See [05-memory-reflection-and-checkpoints.md](05-memory-reflection-and-checkpoints.md) |

Rules shared by the caches:

- **Writes are atomic.** `files.replace_file` writes a uniquely named temp file beside the target and moves it into
  place, so a reader sees the old file or the new one. On Windows, if another process holds the file open, the old
  file is kept and the write is skipped with a warning.
- **Empty results are never cached.** An empty or column-less Yahoo cache file is treated as a miss.
- **Tickers in file names are validated** by `safe_ticker_component`, so a value such as `../../x` (from user input
  or a prompt-injected tool call) cannot escape the cache directory.

## 6. Point-in-time rules

The goal: a run dated `D` sees only what was knowable on `D`. The rules live in `dataflows/date_window.py` and in
each vendor.

| Rule | Where | Effect |
|---|---|---|
| Clamp dates | `as_of`, `as_of_window` | Any date the model passes later than the run's `trade_date` is replaced by it; a window wholly after it is moved back, keeping its length. An unreadable start date is returned to the model as an error |
| Filter rows | `yahoo/ohlcv.load_ohlcv` | Rows after `as_of_date` are dropped from the cached 5-year download |
| Trim dated items | `in_window` | News, StockTwits and Reddit items outside `[start, end + 1 day)` (UTC) are removed; undated items are kept only when the window reaches the present |
| Report unobserved windows | `coverage_gap` | A feed that only serves recent items says "unavailable for this window", not "none found" |
| Withhold live snapshots | `withhold_live_profile` | `Ticker.info` and Alpha Vantage `OVERVIEW` have no history, so a past run gets a notice instead |
| Withhold undated statements | `withhold_undated_statements` | Yahoo / Alpha Vantage statements carry no filing date; a past run is told so. SEC EDGAR serves as filed |
| Withhold undisclosed trades | `withhold_undisclosed_trades` | Insider trades dated by trade, not filing, are withheld for past runs |
| Pin vintages | `fred.get_macro_data` | Values as published on the date |
| Withhold live odds | `polymarket.get_prediction_markets` | No odds for past dates |
| Publication lag (NSE) | `nse/calendar.classify_availability` | `fresh / pending / late / no_session` — see [07](07-india-market-layer.md) |

"Historical" means `trade_date` before today's local date (`is_historical`).

## 7. Known limitations

- Yahoo is the default for prices, indicators and news. Its index volume for NSE indices is unreliable; use
  `get_india_index_data_health` (see [07](07-india-market-layer.md)).
- Yahoo news, StockTwits and Reddit serve only recent items, so historical runs mostly get "unavailable for this
  window" for social and ticker news.
- Fundamentals for Indian companies come from Yahoo only (SEC EDGAR covers US filers), and for past dates Yahoo
  statements are withheld — so a historical run on an NSE stock has no statements.
- Alpha Vantage is not in `.env.example`; set `ALPHA_VANTAGE_API_KEY` yourself if you route to it.

Related: [01-system-overview.md](01-system-overview.md), [03-agents-and-tools.md](03-agents-and-tools.md),
[04-llm-providers-and-configuration.md](04-llm-providers-and-configuration.md).

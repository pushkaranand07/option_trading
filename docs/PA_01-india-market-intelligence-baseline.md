# PA-01 — Baseline import and India market intelligence (NSE data, analytics, options engine)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | Whole repository (initial import); `tradingagents/dataflows/vendors/nse/`, `tradingagents/analytics/{swings,validation}.py`, `tradingagents/compliance.py`, `option_backtester/`, `tradingagents/integrations/optopsy/`, `tradingagents/agents/{tools.py,analysts/}`, `scripts/india_live_check.py`, plan docs |
| **Related** | [PA-02](PA_02-webapp.md) · [PA-03](PA_03-quant-foundation-nse-data-store.md) · [PA-06](PA_06-windows-test-portability.md) · [PA-07](PA_07-option-backtester-exit-fixes.md) · [architecture/01-system-overview.md](architecture/01-system-overview.md) · [architecture/06-data-vendors.md](architecture/06-data-vendors.md) · [architecture/07-india-market-layer.md](architecture/07-india-market-layer.md) · [architecture/08-option-backtester.md](architecture/08-option-backtester.md) · [plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md](plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md) |
| **Pull request** | Direct commits: `0628ada` "Initial commit"; `9b71aeb` "Add India market intelligence…" (reached GitHub `main` as the first commit of PR #2, branch `quant/phase-0-1-foundation`) |
| **Date** | 2026-10-22 (initial commit and plan section 13); `9b71aeb` committed 2026-10-23 |

---

## 1. Problem

The project started from the open-source TradingAgents multi-agent LLM framework, which is built around US data
sources. To analyse Indian markets it needed NSE data (option chains, F&O bhavcopies, FII/DII flows, delivery,
index constituents), a way to backtest options on that data, protection against look-ahead and overfitting, and the
SEBI-style disclaimers an Indian research tool needs.

## 2. Root cause / findings

**Initial import (`0628ada`).** TradingAgents version `0.7.0` (per `tradingagents/__init__.py` and `CHANGELOG.md`):
212 files, 30,437 lines — `cli/`, `tradingagents/` (agents, dataflows, graph, LLM clients, memory, reporting),
87 test files, Docker files, GitHub workflows. No India-specific code.

**Live data findings (22-Oct-2026), from plan section 13:**

| Observation | Consequence |
|---|---|
| `nseindia.com/` homepage → 403; `/option-chain` page → 200 with cookies | Cookie bootstrap uses pages that are not blocked, homepage last |
| `/api/option-chain-indices` → 404 (moved to `/api/option-chain-v3`) | 404 treated as "moved / not published", not an outage; archive files preferred |
| Yahoo `^NSEI` volume 391,600 → 285,800 → 0, while RELIANCE alone traded ~15M shares | Index volume judged unreliable and replaced with a ₹-turnover proxy |
| Yahoo `^NSEI` had no 21-Oct-2026 bar although NSE traded | Calendar gap check reports missing sessions |
| NIFTY lot 50 (Jan-2024, derived) → 65 (Oct-2026); BANKNIFTY 15 → 30 | Dated lot-size history from bhavcopies, never constants |
| NIFTY expiries on Tuesdays, but 09-Nov and 23-Nov are Mondays; BANKNIFTY monthly only | Expiries read from traded contracts / live contract info |
| optopsy env: Python 3.13.2, pandas 3.0.1, pandas-ta-classic 0.3.59; TradingAgents env: Python 3.13.5, pandas 3.0.6, no pandas-ta-classic | Engine moved into the repo with its dependencies at optopsy's tested versions; the bridge converts pandas 3 `datetime64[s]` dates |
| optopsy `short_put_spread` with defaults returned nothing (both legs 0.30Δ, same strike) | Always pass distinct leg deltas |
| `^NSEI` SMA-trend walk-forward: in-sample Sharpe 1.17 → out-of-sample 0.50, Deflated Sharpe 0.40, 26 trades | Verdict `insufficient_evidence` — the validator catches overfitting |

## 3. Decisions

- **Options engine moved in, not linked.** Only what TradingAgents runs was copied from optopsy into
  `option_backtester/`: core (pricing, evaluation, rules, filters, exits, metrics, simulator, plugins), 40 strategies,
  ~100 signals, and its `LICENSE`. Left out: optopsy's chat UI, EODHD downloader and parquet cache, tests, docs.
  Recorded in plan section 11 as "Decided".
- **Licence kept separate.** optopsy is AGPL-3.0-or-later, TradingAgents Apache-2.0; `option_backtester/LICENSE` is
  kept and the plan says to get legal advice before distributing.
- **`option_backtester` keeps upstream style:** excluded from ruff in `pyproject.toml`.
- **Data defaults (plan section 11):** NSE F&O bhavcopy for historical options (free, end-of-day), yfinance + NSE
  filings for fundamentals, local vector index. Who chose these defaults: not recorded.
- Engine default leg deltas left as upstream wrote them; callers pass distinct deltas.

## 4. What was built / changed

Nine priority problems from the plan's catalogue (P-01, P-02, P-03/04, P-08, P-09, P-15, P-17, P-18, P-25):

| Problem | Module(s) |
|---|---|
| P-01 NSE blocking | `tradingagents/dataflows/vendors/nse/client.py` — browser headers, cookie bootstrap, throttle, backoff + jitter + Retry-After, re-bootstrap on 401/403/HTML, circuit breaker, disk cache, stale-on-outage |
| P-02 index volume | `.../nse/index_volume.py` — reliability check, point-in-time constituent turnover proxy, calendar gap check |
| P-03/P-04 calendar and evening publication | `.../nse/calendar.py` (holiday master, IST session state, `fresh/pending/late/no_session`), `.../nse/flows.py` (FII/DII, locally accumulated history) |
| P-08 lot size and expiries | `.../nse/derivatives.py` — UDiFF and legacy bhavcopy to one schema, `LotSizeHistory`, expiries from data, delivery data |
| P-09 survivorship bias | `.../nse/indices.py` — dated constituent snapshots, change-log reconstruction, `survivorship_safe` flag |
| P-15 Python/pandas conflict | `option_backtester/` + `tradingagents/integrations/optopsy/{bridge,adapter}.py` — `doctor()`, NSE bhavcopy → engine chain with Black-Scholes deltas |
| P-17 look-ahead | `tradingagents/analytics/swings.py` — swings carry `confirmed_at`; `find_lookahead()` replay check |
| P-18 overfitting | `tradingagents/analytics/validation.py` — walk-forward with embargo, PSR, Deflated Sharpe, min-trades verdict |
| P-25 SEBI | `tradingagents/compliance.py`, hooked into `reporting.py` and `report_html.py` — disclaimer on every complete report, red-flag phrases flagged |

Agent wiring: `get_india_fii_dii_flows` (news analyst); `get_india_index_data_health`, `get_india_delivery_data`,
`get_india_fo_contract_info` (market analyst). Non-Indian instruments get "not applicable".

Also added: `scripts/india_live_check.py` (live check against NSE/Yahoo), the build plan and the quant signal layer
plan (then at `docs/` root, now [plans/](plans/)), README section, and `pandas-ta-classic`, `empyrical-reloaded`,
`pydantic` dependencies for the engine. `9b71aeb` total: 69 files, 15,184 lines added.

## 5. Tests

65 new offline tests (no network): `tests/test_nse_client.py`, `test_india_index_volume.py`,
`test_nse_calendar_flows.py`, `test_nse_contracts_universe.py`, `test_india_analytics.py`,
`test_optopsy_bridge_compliance.py`. Among them: the look-ahead replay check catches a centred-window pivot
(13 repaints on real `^NSEI`).

## 6. Results

- Existing suite still passed: 1418 passed, with 5 pre-existing failures in ChatGPT-auth, CLI-update and
  yfinance-cache tests, unrelated to this work (fixed in [PA-06](PA_06-windows-test-portability.md)).
- The SMA-trend example came out `insufficient_evidence` (see section 2).

## 7. Verification

Each fix was run against live NSE/Yahoo data with `python scripts/india_live_check.py` on 2026-10-22 (plan section 13).

## 8. Risks and open items

- **Index change log** (`~/.tradingagents/cache/nse/index_changes.json`) must be filled by hand from NSE press
  releases; until then dates before the first snapshot are flagged `survivorship_safe=False`.
- **FII/DII history** builds up one day per run; older dates are reported missing, not estimated.
- **Publication times** in `calendar.EXPECTED_BY` are approximations; status is decided by the date inside the data.
- **Options backtests** on NSE data use the end-of-day close as both bid and ask — treat P&L as optimistic (later
  measured: [PA-23](PA_23-option-quotes-measured-spreads.md)).
- Engine bugs found later: [PA-07](PA_07-option-backtester-exit-fixes.md).
- AGPL obligations apply if the combined code is distributed or offered over a network.
- Research and decision support only; not investment advice.

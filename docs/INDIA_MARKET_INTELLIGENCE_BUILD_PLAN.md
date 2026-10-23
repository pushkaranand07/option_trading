# India Market Intelligence for TradingAgents — Build Plan & Real-World Problem Guide

> **Status:** Design / build plan. The nine priority real-world problems (P-01, P-02, P-03/04, P-08, P-09, P-15, P-17, P-18, P-25) are **implemented and verified on live data** — see [section 13](#13-implemented-fixes-2026-10-22).
> **Workspace:** `C:\coding\stock market\TradingAgents\`. The optopsy options engine has been moved into this repo as `option_backtester/` (AGPL-3.0); the separate `optopsy/` folder is no longer needed.
> **Date:** 2026-10-22
> **Disclaimer:** This system is for research and decision support only. It is not financial advice. Past performance of any investor, strategy or backtest does not guarantee future results.

---

## Table of contents

1. [What we are building and why](#1-what-we-are-building-and-why)
2. [Step 0 findings: what actually exists today](#2-step-0-findings-what-actually-exists-today)
3. [Gap analysis](#3-gap-analysis)
4. [Target architecture](#4-target-architecture)
5. [Core design principles](#5-core-design-principles)
6. [Phase-by-phase build process](#6-phase-by-phase-build-process)
   - [Phase A — Data tools (India + global)](#phase-a--data-tools-india--global)
   - [Phase B — Pattern & indicator engine](#phase-b--pattern--indicator-engine)
   - [Phase C — optopsy strategy ingestion & registry](#phase-c--optopsy-strategy-ingestion--registry)
   - [Phase D — Legendary investors library](#phase-d--legendary-investors-library)
   - [Phase E — New agents, prompts and graph wiring](#phase-e--new-agents-prompts-and-graph-wiring)
   - [Phase F — Reporting ("why did it move")](#phase-f--reporting-why-did-it-move)
   - [Phase G — Backtesting, regime ranking & post-mortem](#phase-g--backtesting-regime-ranking--post-mortem)
7. [Real-world problem catalogue (problem → impact → solution)](#7-real-world-problem-catalogue)
8. [Configuration reference](#8-configuration-reference)
9. [Testing & validation strategy](#9-testing--validation-strategy)
10. [Delivery checklist per phase](#10-delivery-checklist-per-phase)
11. [Open decisions](#11-open-decisions)
12. [Risk disclaimer](#12-risk-disclaimer)
13. [Implemented fixes (2026-10-22)](#13-implemented-fixes-2026-10-22)

---

## 1. What we are building and why

**Problem.** TradingAgents can produce a buy/hold/sell rating for a ticker, but it:

- has no knowledge of a strategy library, so it can't say "strategy X triggered because A, B and C are true";
- has no rulebook from well-known investors, so it can't say "this passes Graham and fails Minervini";
- is built for US markets (Alpha Vantage, SEC EDGAR, FRED, Reddit, StockTwits), so it lacks Indian market drivers: FII/DII flows, delivery %, India VIX, NSE option chains, GIFT Nifty, RBI policy and index-heavyweight contribution;
- describes *what* the price did, not *why* it moved, and doesn't separate causation from correlation.

**Outcome.** We want a question like *"Why did Nifty 50 fall 1.2% today, and what should I do?"* to produce an evidence-based report with these parts:

1. ranked causes, each backed by numbers;
2. which strategies triggered, with the reason for each;
3. which legendary-investor frameworks pass or fail;
4. a bull and bear debate;
5. a trade plan with an invalidation level;
6. a data source and timestamp for every number.

**Non-goals.** The system does not place orders automatically. It does not claim to copy any investor's real trades, and it does not issue investment advice.

---

## 2. Step 0 findings: what actually exists today

### 2.1 Naming correction

The brief refers to `otopsy/`, but the folder on disk is **`optopsy/`**. This document uses `optopsy`.

### 2.2 `optopsy/` is a library, not a strategy notebook

The brief expects a folder of strategy write-ups (md/pdf/txt/notebooks) to parse. **That's not what's there.** `optopsy/` is a Python package (`option-backtester`, Python 3.12–3.13) for **backtesting options strategies**:

| Asset | Location | What it is |
|---|---|---|
| **Options strategies** | `option_backtester/strategies/*.py` | 40 public strategy functions (the README advertises 38): singles, straddles/strangles, vertical spreads, butterflies, condors, iron condor/butterfly, calendars, diagonals, covered call, protective put, collar, cash-secured put, ratio back/front spreads |
| **Entry signals** | `option_backtester/signals/*.py` | 105 public signal functions: momentum (RSI, MACD, Stoch, CCI, ROC, TSI…), overlap (SMA/EMA/DEMA/TEMA/HMA/KAMA crosses), trend (ADX, Aroon, Supertrend, PSAR, CHOP), volatility (ATR, BB, Keltner, Donchian, NATR), volume (MFI, OBV, CMF, A/D), price (gaps, N-day highs/lows, drawdown, consecutive days), IV rank, calendar, plus `and_signals`/`or_signals`/`sustained`/`custom_signal` combinators |
| **Exits** | `exits.py` | Stop-loss, take-profit and max-hold-days early exits |
| **Metrics** | `metrics.py` | Sharpe, Sortino, max drawdown, VaR, CVaR, win rate, profit factor, Calmar, Omega, tail ratio |
| **Simulator** | `simulator.py` | Chronological trade simulation with capital tracking (`SimulationResult`, `PortfolioResult`) |
| **Data** | `data/providers/` | EODHD provider (US-centric), Parquet cache, yfinance helpers |
| **Docs** | `docs/strategies/*.md`, `docs/entry-signals.md` | Prose documentation for every strategy and signal |
| **Sample data** | `samples/data/sample_spx_data.csv` | SPX options sample only. **There is no Indian data.** |
| **Status report** | `docs/@PROJECT_CURRENT_INFO.MD` | Self-assessment that lists mid-price fills, simplified exit matching and no liquidity/assignment modelling as known limits |

**What this means for Part A:**

- "Ingestion" means **introspecting code plus docs**, not parsing PDFs. Most rules are already executable, so coverage will be high on paper.
- optopsy strategies are **options structures** (what to trade), and signals are **entry filters** (when to trade). A tradeable "strategy" in our registry is therefore *structure + entry signal(s) + exit rules + DTE/delta parameters*. We'll ship a curated set of named combinations, for example "RSI<30 + long put spread, 30–45 DTE".
- Backtesting optopsy strategies on Nifty/Bank Nifty needs **historical Indian option chains**. No free source has bid/ask history. See [Problem P-07](#7-real-world-problem-catalogue).
- The 105 signals double as a **ready-made pattern library** for equities and indices. The Strategy Analyst can evaluate them on spot OHLCV with no options data at all.

### 2.3 `TradingAgents/` today

A LangGraph multi-agent framework (Python ≥3.11, pandas ≥3.0.6, langgraph, yfinance, stockstats).

**Agents** (`tradingagents/agents/`):

| Layer | Agents |
|---|---|
| Analysts | Market (technical), Social/Sentiment, News, Fundamentals — registered in `graph/analyst_execution.py::ANALYST_NODE_SPECS` |
| Research | Bull Researcher ⇄ Bear Researcher debate → Research Manager |
| Execution | Trader |
| Risk | Aggressive ⇄ Neutral ⇄ Conservative debators → Portfolio Manager (final 5-tier rating) |
| Memory | Memory Log step: settles past decisions against realized and alpha returns, and writes lessons via `memory/reflection.py` |

**Data flow:** analysts run in parallel. Each runs a tool loop capped by `max_tool_rounds` and writes into `AgentState` (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`). The bull/bear debate and the Research Manager produce `investment_plan`. The Trader writes `trader_investment_plan`. The risk debate and Portfolio Manager write `final_trade_decision` and `final_rating`.

**Data layer** (`tradingagents/dataflows/`): `router.py` maps tool categories to vendors. Vendors are `yahoo`, `alpha_vantage`, `fred`, `sec_edgar`, `polymarket`, `reddit` and `stocktwits`. `net.py` handles HTTP, and `errors.py` defines `NoMarketDataError`, `VendorNotConfiguredError` and `VendorUnavailableError`. `date_window.py` serves data "as of" the trade date, and there are tests for look-ahead (`test_fundamentals_lookahead.py`, `test_date_boundaries.py`).

**Tools** (`agents/tools.py`): `get_stock_data`, `get_indicators`, `get_verified_market_snapshot`, `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`, `get_news`, `get_global_news`, `get_insider_transactions`, `get_macro_indicators`, `get_prediction_markets`.

**Backtest** (`tradingagents/backtest.py`): runs the graph over a (ticker × date) grid and scores **decision quality** from the memory log. Its docstring explicitly says *"It is not a portfolio simulator, and must not grow one."* We respect that: strategy backtesting goes in a **separate module**.

**Config:** `default_config.py` holds a dict plus a `TRADINGAGENTS_*` env-override table. Secrets live in `.env`. There are 89 test files.

**India support:** none. No NSE vendor, no `.NS` handling, no INR or IST awareness beyond what yfinance gives for free.

---

## 3. Gap analysis

| Capability required | Exists? | Gap / action |
|---|---|---|
| OHLCV for `^NSEI`, `^NSEBANK`, `*.NS` | 🟡 via yfinance | Index volume is missing or zero, and NSE holidays and IST session times aren't handled. Add an India-aware OHLCV adapter |
| FII/DII, delivery %, India VIX, option chain, bulk/block deals | ❌ | New `nse` vendor with session/cookie handling, a cache and fallbacks |
| Indian fundamentals (ROE, ROCE, promoter holding, pledge) | 🟡 yfinance partial | ROCE and promoter data are missing. Compute from statements, plus a pluggable fundamentals vendor |
| Global/macro: crude, gold, USD/INR, DXY, US indices, US yields, GIFT Nifty | 🟡 FRED (US macro) | New `global_cues` tool (yfinance tickers + FRED); GIFT Nifty is best-effort |
| Indian news (ET, Moneycontrol, Mint, Reuters) + sentiment score | 🟡 yfinance/AV news | RSS vendor, dedupe, IST market-hours alignment, sentiment scoring |
| Indicator/pattern engine (candles, chart patterns, structure, pivots, VWAP) | 🟡 stockstats indicators only | Deterministic `patterns/` engine; reuse optopsy signals where possible |
| Strategy registry + vector search | ❌ | `strategies/registry` (YAML/JSON) + local embedding index |
| Executable rule evaluation (TRIGGERED / PARTIAL / NOT) | ❌ (optopsy has boolean signals) | Wrapper that returns per-condition evidence |
| Legend scorecards + Legend Consensus | ❌ | `legends/` library: YAML scorecards + a deterministic scorer |
| Options/Derivatives analyst | ❌ | New analyst: OI, PCR, max pain, buildup, IV |
| Macro/Global analyst | 🟡 macro tool exists, no dedicated India analyst | New analyst |
| Strategy Analyst, Legends Analyst | ❌ | New analysts |
| Strategy-conflict handling by horizon | ❌ | Conflict matrix in state, passed to the researchers and the Trader |
| Index move attribution (heavyweights) | ❌ | `attribution.py` (weight × return contribution) |
| 10-section evidence report with sources/timestamps | 🟡 `reporting.py`, `report_html.py` | New report template + **evidence ledger** + number validator |
| Strategy backtesting on Indian data, regime ranking | ❌ (`backtest.py` is decision-quality only) | New `strategy_backtest/` module using optopsy metrics |
| Post-mortem per agent/strategy | 🟡 memory log settles final rating only | Extend settlement to per-agent and per-strategy predictions |
| Logging of every decision and tool call | 🟡 | Structured JSONL run log |

---

## 4. Target architecture

```
                         ┌───────────────────────── config (YAML + .env) ─────────────────────────┐
                         │ symbols · timeframes · vendors · LLMs · enabled strategies/legends    │
                         └───────────────────────────────────────────────────────────────────────┘
 DATA LAYER (tradingagents/dataflows/vendors/)
 ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐
 │ yahoo    │ │ nse      │ │fundamentals│ │ global    │ │ news_rss │ │ fred     │  ← each behind the router,
 │ (OHLCV)  │ │ FII/DII, │ │ (pluggable)│ │ crude,gold│ │ ET, MC,  │ │ (yields) │    cached, retried,
 │          │ │ chain,VIX│ │            │ │ INR,DXY.. │ │ Mint..   │ │          │    with fallbacks
 └────┬─────┘ └────┬─────┘ └─────┬──────┘ └─────┬─────┘ └────┬─────┘ └────┬─────┘
      └────────────┴─────────────┴──────┬───────┴────────────┴────────────┘
                                         ▼
                        ┌────────────────────────────────┐
                        │ EVIDENCE LEDGER (per run)      │  every fetched number gets an id,
                        │ id · value · source · as_of    │  source, timestamp; reports may
                        └───────────────┬────────────────┘  only cite ledger ids
                                        ▼
 DETERMINISTIC ENGINES (no LLM)
 ┌───────────────────┐ ┌────────────────────┐ ┌───────────────────┐ ┌────────────────┐ ┌──────────────┐
 │ indicators &      │ │ strategy evaluator │ │ legend scorer     │ │ index          │ │ regime       │
 │ patterns engine   │ │ (optopsy registry) │ │ (YAML scorecards) │ │ attribution    │ │ classifier   │
 └─────────┬─────────┘ └─────────┬──────────┘ └─────────┬─────────┘ └───────┬────────┘ └──────┬───────┘
           └─────────────────────┴───────────┬──────────┴───────────────────┴─────────────────┘
                                             ▼
 AGENT LAYER (LangGraph — extends existing graph)
   Technical · Fundamental · Macro/Global · News&Sentiment · Options/Derivatives · Strategy · Legends   (parallel)
                                             ▼
                         Conflict Matrix (by horizon)  ──►  Bull ⇄ Bear  ──►  Research Manager
                                             ▼
                                Trader  ──►  Risk debate  ──►  Portfolio Manager
                                             ▼
                     Report builder (10 sections) + Number validator + Disclaimer
                                             ▼
                     Memory/Post-mortem (per agent, per strategy, per legend)
 OFFLINE
   strategy_backtest/ (walk-forward, regime-tagged)  ──►  regime-fit weights consumed by Strategy Analyst
```

**The key idea:** *code computes, LLMs explain.* Deterministic Python produces every number and every TRIGGERED/PASS verdict. LLM agents interpret, weigh, debate and write. That's the main defence against hallucinated numbers.

---

## 5. Core design principles

1. **Evidence ledger, not free text.** Every tool returns `{"evidence_id", "value", "unit", "source", "as_of", "fetched_at"}`. Agents cite `[E12]`. A post-processor rejects numbers in the final report that don't match a ledger entry (within rounding).
2. **Missing data is a first-class value.** Tools return `status="missing"` with a reason. Agents must say "FII/DII data not yet published for 2026-10-22" rather than estimate.
3. **Point-in-time correctness.** Everything is served "as of" `trade_date`, reusing `date_window.py`. Fundamentals are keyed by *announcement date*, not period end.
4. **Every source is swappable.** Each vendor implements a small interface and registers in `router.py`. Fallback chains are configured, not hardcoded.
5. **Market-agnostic core, India adapters.** Calendars, sessions, lot sizes, tickers and index weights are injected per market (`markets/india.yaml`). The US remains the default for existing users.
6. **The options engine lives in this repo.** optopsy's engine was moved in as `option_backtester/` (engine only: no chat UI, no EODHD downloader). Use it through `tradingagents.integrations.optopsy`; keep it close to upstream so fixes can be exchanged.
7. **Horizon tagging.** Every strategy, signal and legend carries a horizon (intraday, swing ≤4w, positional 1–6m, long-term >6m). Conflicts are resolved *per horizon*, not by majority vote.
8. **Small context, structured state.** Agents get compact tables (≈1 line per strategy), not raw DataFrames, which keeps cost and context size under control.
9. **Follow house style.** Mirror the existing patterns: `AnalystNodeSpec` registration, `@tool` functions in `agents/tools.py`, vendor packages under `dataflows/vendors/`, env overrides in `_ENV_OVERRIDES`, and tests in `tests/test_*.py`.

---

## 6. Phase-by-phase build process

Each phase follows the same loop:
**design → implement → unit tests → run on a Nifty 50 example → show real output → review → next phase.**
Nothing moves forward until the phase's acceptance criteria pass.

### Phase A — Data tools (India + global)

**Goal:** reliable, cached, point-in-time data for every input the agents need.

**New modules**

```
tradingagents/dataflows/
  markets/
    india.py            # NSE calendar, session 09:15–15:30 IST, holidays, lot sizes (dated), ticker map
    india.yaml          # holiday list, index constituents+weights snapshots, lot-size history
  vendors/
    nse/
      session.py        # cookie bootstrap, headers, throttle, retry/backoff
      flows.py          # FII/DII cash (+ F&O participant OI when available)
      derivatives.py    # option chain (live), F&O bhavcopy (historical EOD), India VIX
      equity.py         # delivery % (sec_bhavdata_full), bulk/block deals, corporate actions
    global_cues.py      # crude (BZ=F, CL=F), gold (GC=F), USD/INR (INR=X), DXY (DX-Y.NYB),
                        # ^GSPC, ^IXIC, ES=F/NQ=F/YM=F, ^N225, ^HSI, US 10Y (^TNX / FRED DGS10)
    news_rss.py         # ET, Moneycontrol, Mint, Reuters India RSS + optional NewsAPI
    fundamentals_in.py  # pluggable: yfinance + statement-derived ROCE + NSE shareholding (promoter/pledge)
  cache.py              # TTL by data type; on-disk parquet/json under data_cache_dir
  evidence.py           # EvidenceLedger
```

**New tools** (in `agents/tools.py`): `get_index_snapshot`, `get_fii_dii_flows`, `get_delivery_data`, `get_option_chain_summary`, `get_india_vix`, `get_global_cues`, `get_bulk_block_deals`, `get_india_news`, `get_shareholding`.

**Steps**

1. Define the `Vendor` protocol and the evidence record shape. Add `nse`, `global_cues` and `news_rss` to `TOOLS_CATEGORIES` in `router.py`.
2. Build the NSE session handler first. Everything NSE depends on it (see P-01).
3. Implement each fetcher with a **TTL cache**: intraday quotes 60 s; option chain 3 min; EOD data until the next session; fundamentals 24 h; news 10 min.
4. Implement fallback chains, for example India VIX: NSE API → yfinance `^INDIAVIX` → `missing`.
5. Add the market calendar: `is_trading_day`, `previous_session`, and a session state (`pre_open`, `open`, `closed`, `post_close_data_pending`).
6. Add the keys to `.env.example` (`NEWSAPI_KEY`, optional `FUNDAMENTALS_API_KEY`, etc.). Never hardcode them.

**Acceptance**

- `get_index_snapshot("^NSEI", "2026-10-21")` returns close, % change, high/low, previous close, source and timestamp.
- Unit tests use recorded fixtures (no network in CI). One opt-in `@pytest.mark.live` smoke test per vendor.
- When NSE is unreachable, the tool returns a typed `VendorUnavailableError` → fallback → or `missing`. It never crashes the graph.

**Real-world problems handled here:** P-01 through P-06 and P-12 through P-14.

---

### Phase B — Pattern & indicator engine

**Goal:** deterministic detection of everything listed under "Technical and price-action patterns", each returning evidence.

```
tradingagents/analytics/
  indicators.py     # EMA/SMA 20/50/200, RSI, MACD, BB, ATR, ADX, Supertrend, OBV, VWAP (intraday only)
  candles.py        # engulfing, doji, hammer/hanging man, shooting star, morning/evening star
  chart_patterns.py # double top/bottom, H&S / inverse H&S, flags, triangles, cup & handle, VCP, Darvas box
  structure.py      # swing points (ZigZag/fractal), HH/HL/LH/LL, BOS/CHoCH, S/R clustering, pivots (classic/CPR)
  volume.py         # spikes (vol / 20d avg), dry-ups, price-volume divergence, breakout-on-volume, delivery% context
  options.py        # PCR (OI & volume), max pain, OI change buildup classifier, ATM IV, IV percentile
  regime.py         # trending / ranging / high-vol classifier (ADX + ATR% + India VIX percentile)
  optopsy_bridge.py # wraps optopsy signals so they run on our OHLCV and return per-date booleans + values
```

**Output contract** (every detector returns this):

```python
@dataclass
class PatternHit:
    name: str               # "bullish_engulfing"
    detected: bool
    confidence: float       # 0–1, rule-based (e.g., body ratio, volume confirmation)
    as_of: date
    evidence: dict          # {"prev_body": -42.1, "body": 88.3, "vol_ratio": 1.8}
    horizon: str            # "swing"
    definition: str         # human-readable rule used — transparency for agents
```

**Steps**

1. Reuse optopsy signal logic through `optopsy_bridge.py` (it's pandas-ta-classic based) rather than re-implementing 105 indicators. Fall back to `stockstats` (already a TradingAgents dependency) when there's a version conflict (P-15).
2. Write the chart-pattern detectors on top of a single swing-point function so all patterns share one definition of "pivot". Document tolerances, for example "double top: two peaks within 1.5% and ≥10 bars apart".
3. Option analytics: long buildup = price ↑ & OI ↑; short buildup = price ↓ & OI ↑; short covering = price ↑ & OI ↓; long unwinding = price ↓ & OI ↓.
4. Regime classifier: `trending` if ADX(14) > 25; `high_vol` if the ATR% or India VIX percentile over 1y is > 80; otherwise `ranging`. Thresholds live in config.

**Acceptance:** each detector has a synthetic-series unit test (a constructed hammer or head-and-shoulders must be detected, and noise must not be). We run on Nifty 50 for the last 250 sessions and print the hits table.

---

### Phase C — optopsy strategy ingestion & registry

**Goal:** a registry of everything optopsy knows, executable where possible, searchable by question.

**Schema** (`strategies/schema.py`, pydantic):

```yaml
id: optopsy.iron_condor.rsi_neutral
name: Iron Condor on range-bound RSI
source: option_backtester/strategies/iron_strategies.py::iron_condor
category: options/neutral          # trend | momentum | mean_reversion | breakout | options/* | volume | price_action
market: any (validated: NIFTY, BANKNIFTY)
timeframe: daily
horizon: swing
entry:
  - {id: c1, rule: "RSI(14) between 40 and 60", code: "rsi_between(14,40,60)"}
  - {id: c2, rule: "ADX(14) < 20", code: "adx_below(14,20)"}
  - {id: c3, rule: "IV rank > 50", code: "iv_rank_above(50)"}
structure: {legs: 4, short_delta: 0.16, long_delta: 0.05, dte: [30, 45]}
exit: {take_profit: 0.5, stop_loss: 2.0, max_hold_days: 21}
position_sizing: "max loss ≤ 1% equity; lots = floor(risk / (width*lot_size - credit))"
inputs: [ohlcv, option_chain, iv_history]
works_when: [ranging regime, elevated IV]
fails_when: [trend breakouts, event days (RBI/budget/results), IV expansion]
coding_status: full            # full | partial | text_only
ambiguities:
  - "optopsy fills at mid; Indian EOD bhavcopy has no bid/ask → close price used (approximation)"
```

**Three kinds of entries**

| Kind | Count (approx.) | How |
|---|---|---|
| **Structures** (from `strategies/`) | 40 | Auto-extracted by introspection: function name, signature, docstring and the matching `docs/strategies/*.md` section |
| **Signals** (from `signals/`) | 105 | Auto-extracted; become reusable conditions (`code:` references) |
| **Curated playbooks** (structure + signals + exits) | ~20–30 to start | Hand-written YAML that references the above (for example "bearish breakdown → long put spread") |

**Ingestion pipeline** (`scripts/ingest_optopsy.py`)

1. `importlib` loads `option_backtester` and walks `strategies` and `signals` with `inspect`.
2. Parse docstrings and the matching markdown docs for descriptions, parameters and defaults.
3. Classify the category with rules (module name → category) and use the LLM only to *suggest* `works_when`/`fails_when` text. Mark suggested text `source: llm_suggested`, and require human review before `reviewed: true`.
4. Validate against the schema. Anything with an unclear rule goes into `ambiguities`, never filled in silently.
5. Write `strategies/registry/optopsy/*.yaml` plus a `coverage_report.md`.
6. Build the vector index from name + description + works/fails text + category. Use local embeddings (sentence-transformers, or the configured LLM provider's embedding API) stored in a small on-disk index (FAISS or a plain numpy file). It rebuilds whenever the registry hash changes.

**Evaluator** (`strategies/evaluator.py`)

```python
@dataclass
class StrategyVerdict:
    strategy_id: str
    status: Literal["TRIGGERED", "PARTIAL", "NOT_TRIGGERED", "NOT_APPLICABLE", "DATA_MISSING"]
    met: list[ConditionResult]      # each with value, threshold, evidence_id
    unmet: list[ConditionResult]
    score: float                    # met / total (weighted)
    regime_fit: float | None        # from Phase G backtests
    horizon: str
```

- `PARTIAL` means ≥ 50% of conditions are met but not all (the threshold is configurable).
- `NOT_APPLICABLE` covers cases like an options structure on a stock without F&O, or a cash-secured put when shorting isn't allowed.
- `DATA_MISSING` means a required input is unavailable. It's reported separately and never counted as "not triggered".

**Coverage report** (generated, example shape):

```
optopsy coverage — 2026-10-22
  structures found ............ 40   fully coded 40 | partial 0 | text-only 0
  signals found ............... 105  fully coded 105
  curated playbooks ........... 24   fully coded 19 | partial 4 | text-only 1
  needs Indian option history . 40 structures (backtest-limited, see P-07)
  open ambiguities ............ 11  (listed in ambiguities.md)
```

**Acceptance:** the coverage report is generated, and every registry file passes schema validation. `evaluate_all("^NSEI", date)` returns a verdict for every enabled strategy in under 5 s with warm caches. A vector search for "what works in a sideways high-IV market" returns the iron condor/butterfly family first.

---

### Phase D — Legendary investors library

**Goal:** transparent, rule-based scorecards that agents evaluate deterministically, plus philosophy notes that can be retrieved by search.

**Module layout:** one YAML per legend in `legends/library/` plus `legends/scorer.py`.

```yaml
id: graham
name: Benjamin Graham
style: deep_value
horizon: long_term
applies_to: [stock]                 # not indices
philosophy: |
  Buy assets below conservative intrinsic value with a margin of safety. Demand earnings
  stability, low leverage and a long dividend record. Treat Mr. Market's moods as opportunity.
criteria:
  - {id: pe,   metric: pe_ttm,           op: "<=", value: 15,  weight: 0.20}
  - {id: pb,   metric: pb,               op: "<=", value: 1.5, weight: 0.15}
  - {id: pexpb,metric: pe_x_pb,          op: "<=", value: 22.5,weight: 0.15}
  - {id: gn,   metric: price_vs_graham_number, op: "<=", value: 1.0, weight: 0.20}
  - {id: cr,   metric: current_ratio,    op: ">=", value: 2.0, weight: 0.10}
  - {id: stab, metric: years_positive_eps_of_10, op: ">=", value: 10, weight: 0.10}
  - {id: div,  metric: years_dividend_paid, op: ">=", value: 10, weight: 0.10, proxy: true,
     proxy_note: "Original rule is 20 years; reduced for Indian data availability"}
pass_threshold: 0.70
buy: "Score ≥ 0.70 and price ≤ Graham Number"
hold: "While price < intrinsic value estimate"
sell: "Price ≥ Graham Number × 1.5, or 2 consecutive years of losses"
sizing: "Diversify across ≥ 10 positions; no single position > 10%"
best_regimes: [bear markets, post-crash, value rotation]
weaknesses: [misses compounders, value traps in structurally declining sectors]
disclaimer: "Rule-based approximation of publicly documented principles. Not Graham's actual portfolio."
```

**Legends to encode** (all from the brief), grouped by how measurable they are:

| Group | Legends | Mostly measurable? | Typical proxies (labelled `proxy: true`) |
|---|---|---|---|
| Value | Graham, Buffett/Munger, Lynch, Greenblatt, Fisher, Templeton, Marks | Graham/Greenblatt/Lynch: yes. Buffett/Fisher: partly | Moat ≈ 10y ROCE > 15% with low variance + gross-margin stability; management quality ≈ promoter pledge 0%, related-party flags, capital-allocation ROIC; "max pessimism" ≈ price ≥ 40% below 52w high + India VIX percentile > 80; Marks cycle ≈ market-wide P/E percentile + credit spreads |
| Growth/momentum | O'Neil, Minervini, Darvas, Weinstein, Livermore, Turtles, Seykota/PTJ/Williams | Yes, almost fully | CAN SLIM "N" (new product) → news-based, so text-only; "M" = Nifty above 50/200 DMA |
| Macro/systematic | Soros, Druckenmiller, Dalio, Simons, Schwager/Steinhardt | Mostly qualitative | Reflexivity ≈ price-flow feedback (FII flows and price trend in the same direction for N weeks); liquidity ≈ RBI stance + system liquidity + US 10Y trend; Dalio ≈ regime quadrant (growth/inflation up/down); Simons ≈ "only signals with backtested edge" (uses Phase G stats) |
| India | Jhunjhunwala, R. Damani, Kedia (SMILE), Ramesh Damani, Porinju, Dolly Khanna | Partly | SMILE: Small = mcap < ₹5,000 cr; Medium experience = company age 10–25y; Large aspiration ≈ revenue CAGR > 20%; XL potential ≈ sector TAM tag (manual list). **Mandatory liquidity/governance guard**: ADV, free float, promoter pledge, auditor changes |

**Legend Consensus**

```
consensus = Σ(pass_i × w_i) / Σ(w_i)   over legends applicable to the instrument & data available
```

- Report it as **"7 of 16 applicable frameworks pass (weighted 0.46)"** and break it down by horizon (long-term value vs. swing momentum). A single blended number hides real conflicts.
- Legends with `DATA_MISSING` criteria above 30% weight are reported as *not evaluable*, not as failing.
- For indices, only frameworks that make sense for an index are used: Weinstein stage, Turtles, the 200-DMA rules, Marks/Templeton cycle proxies, Dalio regime and Druckenmiller liquidity. Stock-picking scorecards are `NOT_APPLICABLE`.

**Acceptance:** every legend YAML validates. Every subjective criterion is marked `proxy: true` with a note. We run the scorecards on RELIANCE.NS, HDFCBANK.NS and ^NSEI and show the pass/fail table with the evidence for each criterion.

---

### Phase E — New agents, prompts and graph wiring

**Agent map** (reuse first):

| Agent | Status | Inputs | Output in state |
|---|---|---|---|
| Technical Analyst | **Extend** `market_analyst.py` | Phase B engine, regime | `market_report` (+ pattern table) |
| Fundamental Analyst | **Extend** `fundamentals_analyst.py` | `fundamentals_in`, shareholding | `fundamentals_report` |
| News & Sentiment Analyst | **Extend** `news_analyst.py` + `sentiment_analyst.py` | `news_rss`, sentiment scorer | `news_report`, `sentiment_report` |
| Macro/Global Analyst | **New** | global cues, FII/DII, RBI/Fed calendar, FRED | `macro_report` |
| Options/Derivatives Analyst | **New** | option chain, PCR, max pain, buildup, VIX | `derivatives_report` |
| Strategy Analyst | **New** | registry evaluator + vector retrieval + regime fit | `strategy_report`, `strategy_verdicts` |
| Legends Analyst | **New** | legend scorer | `legends_report`, `legend_consensus` |
| Conflict step | **New** (deterministic node) | all verdicts | `conflict_matrix` |
| Bull/Bear, Research Manager | **Extend prompts** | all of the above + conflict matrix | unchanged keys |
| Trader | **Extend prompt + schema** | plan + ATR/levels | structured trade plan |
| Risk debate + Portfolio Manager | **Extend** | trade plan, sizing rules | unchanged keys |

**Wiring:** add new `AnalystNodeSpec` entries in `graph/analyst_execution.py` (`"macro"`, `"derivatives"`, `"strategy"`, `"legends"`) and new keys in `AgentState`. Add a conflict node between the analysts and the Bull Researcher. They become selectable from the CLI exactly like existing analysts.

**Conflict matrix** (deterministic, then explained by the LLM):

```
horizon      | bullish signals              | bearish signals              | net
-------------|------------------------------|------------------------------|-----
intraday     | short covering (OI↓, px↑)    | —                            | +
swing        | —                            | Minervini fail, below 50DMA  | −
long_term    | Graham pass, Lynch PEG 0.8   | —                            | +
```

The Trader must state which horizon the trade plan is for and why the other horizons don't override it.

**Prompt rules** (added to every analyst):

- "Only cite numbers that appear in tool outputs, with their evidence id `[E#]`."
- "If a required input has `status=missing`, say so explicitly. Do not estimate."
- "Distinguish *coincided with* from *caused*. Give a causal claim only when there is a mechanism (for example a heavyweight's contribution in index points) and a timing match."

**Trader output schema** (pydantic, in `agents/schemas.py`): `stance`, `confidence` (0–100), `horizon`, `entry` (price/zone), `stop_loss`, `targets[]`, `risk_reward`, `position_size` (as % of equity and lots/shares), `invalidation[]` and `rationale`.

**Logging:** one JSONL per run (`results_dir/runs/<run_id>.jsonl`) with every tool call (args, latency, cache hit, vendor, status) and every agent's output and token usage.

**Acceptance:** an end-to-end run on `^NSEI` completes with all analysts. A test with a mocked LLM verifies state wiring (same pattern as `test_graph_end_to_end.py`).

---

### Phase F — Reporting ("why did it move")

**Report template** (Markdown + HTML through the existing `report_html.py`):

| # | Section | Built from |
|---|---|---|
| 1 | Summary: direction, % move, key levels | `get_index_snapshot`, structure.py |
| 2 | Cause attribution, ranked with numbers | `attribution.py` + flows + global cues + news |
| 3 | Technical view | Technical Analyst |
| 4 | Fundamental & macro view | Fundamental + Macro analysts |
| 5 | News & sentiment (headlines listed with time & source) | News analyst |
| 6 | optopsy strategy signals | Strategy Analyst verdict table |
| 7 | Legendary investor view + Legend Consensus by horizon | Legends Analyst |
| 8 | Bull vs. bear, final stance + confidence | Research Manager / PM |
| 9 | Trade plan + invalidation | Trader schema |
| 10 | Sources & timestamps | Evidence ledger dump |
| — | Risk disclaimer | Always appended |

**Cause attribution method**

1. **Index contribution:** `points_i = weight_i(prev close, free-float) × return_i × index_prev_close`. The top 5 positive and negative contributors are listed, and the residual is shown. Weights come from the latest available constituent snapshot, and the report states its date (P-10).
2. **Flow and cross-asset context:** FII/DII net (₹ cr), USD/INR change, Brent change, previous US close / US futures, Asian indices, GIFT Nifty move vs. the previous Nifty close.
3. **Event check:** whether there was an RBI/Fed/budget/CPI/GDP release or a heavyweight's results in the window.
4. **Ranking:** a score = |contribution or z-score of the move| × timing match × mechanism strength. Each cause is labelled **"direct mechanism"** (for example HDFC Bank −3% = −68 pts), **"plausible driver"** (crude +4% on an import-dependent market) or **"correlated / unconfirmed"**.

**Number validator:** before printing, a regex extracts every number from the narrative and matches it to ledger values with a ±0.5% tolerance (or exact match for prices). Anything unmatched gets flagged inline as `⚠ unverified`, and the run log records a warning.

**Acceptance:** generate the report for "Why did Nifty 50 move on <last session>?". Zero unverified numbers, every section present, and the disclaimer present.

---

### Phase G — Backtesting, regime ranking & post-mortem

**New module** `tradingagents/strategy_backtest/`, kept separate from `backtest.py` to respect its "decision quality only" scope.

**What gets backtested**

| Item | Data | Engine |
|---|---|---|
| Spot/equity rules (signals, patterns, Turtles, Weinstein, Darvas, Minervini trend template, 200-DMA rules) | Daily OHLCV for ^NSEI, ^NSEBANK, a sample of NSE stocks | Vectorised event backtester (next-bar-open fills, costs, slippage) |
| Options structures | NSE F&O bhavcopy history (EOD, close prices, OI) | optopsy engine via adapter, with Indian lot sizes and expiries |
| Fundamental legends (Graham, Greenblatt, Lynch…) | Point-in-time fundamentals (only if available) | Periodic rebalance backtest; otherwise **flagged as not backtested** |

**Bias controls**

- **Look-ahead:** signals are computed on bar *t* and filled at the open of *t+1*. Fundamentals use the announcement date. Indicators are recomputed causally with no centred windows, and swing points are confirmed only after N bars (P-17).
- **Survivorship:** the universe is drawn from historical index constituent lists as of each date, never today's Nifty 50 (P-09).
- **Costs:** STT, exchange charges, stamp duty, GST, SEBI fees, brokerage and slippage go in a configurable cost model, because Indian F&O costs are significant.
- **Overfitting:** walk-forward (train 3y → test 1y, rolling). Report in-sample vs. out-of-sample separately. With hundreds of strategy × parameter combinations, also report a multiple-testing-adjusted measure (deflated Sharpe or a simple Bonferroni-style haircut) (P-18).

**Metrics:** win rate, profit factor, Sharpe, Sortino, max drawdown, CAGR and exposure %. We reuse `option_backtester.metrics` so the formulas are identical across both projects.

**Regime ranking:** tag each bar with the Phase B regime, then aggregate per (strategy, regime). Store the results in `strategy_backtest/results/regime_fit.parquet`. The Strategy Analyst weights each verdict by the current regime's out-of-sample profit factor and Sharpe, and shows the weight.

**Post-mortem loop** (extends `memory/settlement.py`):

1. At decision time, store each agent's directional call, each strategy verdict and the legend consensus alongside the final rating.
2. At settlement (N trading days later, configurable per horizon), compute the realized return and the alpha vs. benchmark (`^NSEI` for Indian instruments).
3. Score each component: hit or miss, and magnitude error.
4. `reflection.py` writes a 2–4 sentence lesson per run, and a leaderboard tracks rolling accuracy per agent, strategy and legend by regime.
5. Lessons feed back as `past_context`, the mechanism that already exists.

**Acceptance:** the backtest report prints for at least ^NSEI, ^NSEBANK and 10 sample stocks, with in-sample and out-of-sample columns, costs on, and a bias checklist ticked. A post-mortem entry appears after a settled run.

---

## 7. Real-world problem catalogue

Each problem lists its **impact** and the **solution built into the plan**.

### Data acquisition

| ID | Problem | Impact | Solution |
|---|---|---|---|
| **P-01** | **NSE blocks automated requests.** Endpoints need a browser-like session: cookies from a homepage hit, specific headers. They return 401/403 or empty bodies when throttled and change without notice. | FII/DII, option chain, VIX and delivery data silently fail | A dedicated `nse/session.py`: bootstrap cookies, rotate the session on 401, throttle to ≤ 3 req/s, exponential backoff with jitter, and a circuit breaker. Prefer **archive files** (bhavcopy CSVs, `fiidiiTradeReact`, daily reports) over live JSON for anything EOD. `nsepython` is an optional backend behind the same interface. Respect NSE's terms of use and never hammer the endpoints. |
| **P-02** | **yfinance index quirks.** `^NSEI`/`^NSEBANK` volume is often 0 or missing. Intraday history is limited to recent windows. Data is sometimes delayed or has gaps. | Volume patterns on indices are meaningless | For index volume, use the **sum of constituent volumes** or Nifty futures volume (from the bhavcopy) as a proxy, labelled as a proxy. Validate every OHLCV frame (no NaN rows, no zero prices, monotonic dates) before use. |
| **P-03** | **Timezones and sessions.** NSE trades 09:15–15:30 IST. US data lands overnight IST. Muhurat trading sessions and special sessions exist, and holidays change yearly. | Wrong "today" and wrong previous close; US cues misaligned | All timestamps are stored in UTC and rendered in IST. Use a market calendar from `india.yaml` (updated yearly from the NSE circular). "Global cues for date D" means US/European closes *before* 09:15 IST on D. |
| **P-04** | **Data publication lag.** FII/DII provisional data is published in the evening after market close. Delivery data and the bhavcopy come after close. Shareholding is quarterly. | Running "why did Nifty fall today" at 15:45 finds no flow data | Session state `post_close_data_pending` → the report says *"FII/DII for today not yet published; using yesterday's [E#]"*. Optionally schedule a re-run in the evening. |
| **P-05** | **Corporate actions.** Indian companies issue frequent bonuses and splits, and adjusted vs. unadjusted prices differ by vendor. | Fake crashes or gaps; broken patterns and 52-week highs | Use adjusted series for indicators and raw prices for levels quoted to the user. Cross-check large overnight gaps against the NSE corporate-actions feed before calling them "gaps". |
| **P-06** | **Indian fundamentals are thin in free sources.** yfinance `.info` lacks ROCE and promoter holding/pledge, and has gaps for small caps. Popular screener sites have no official API, and their terms restrict scraping. | Legend scorecards can't be evaluated | `fundamentals_in.py` is pluggable. (a) Compute ROE/ROCE/debt ratios from the statements yfinance provides. (b) Get promoter holding/pledge from NSE shareholding-pattern filings. (c) Optional paid-API adapter. Every criterion without data → `DATA_MISSING`, and the legend is marked "not evaluable" if missing weight is above 30%. |
| **P-07** | **No free historical Indian option chains with bid/ask.** The NSE live option chain is current-only. | optopsy backtests (which expect bid/ask/delta per quote) can't run on Indian data directly | Use the **NSE F&O bhavcopy** archive (daily close, settle price, OI, contracts) → adapter maps it to optopsy's column format with bid=ask=close and **slippage set to a spread model**. Compute delta/IV with Black-Scholes (risk-free = 91-day T-bill; div yield from config). Every options backtest is labelled *"EOD close-price approximation; no intraday or bid/ask realism"*. A paid tick/quote vendor can be plugged in later. |
| **P-08** | **Changing contract specs.** NSE lot sizes are revised periodically, weekly-expiry availability was cut back by SEBI rules, and the expiry weekday has changed over time. | Wrong P&L and sizing; backtests on expiries that didn't exist | A **dated** table in `india.yaml`: `lot_size[symbol][effective_from]` and an expiry calendar derived from actual bhavcopy expiries (the source of truth), never a hardcoded weekday. |
| **P-09** | **Survivorship bias.** Today's Nifty 50 contains the winners. | Inflated backtest returns | Historical constituent snapshots (NSE index rebalancing announcements, semi-annual) stored in `india.yaml`. The universe at date *t* = members at *t*. Where history is unavailable, the report flags "survivorship-biased sample". |
| **P-10** | **Index weights for attribution.** Exact daily free-float weights aren't published freely. NSE publishes monthly factsheets. | Attribution points are approximate | Use the last factsheet weights drifted by price since that date (standard approximation). Show "weights as of <date>, price-drifted". Report the residual (index move − sum of contributions) so the error is visible. |
| **P-11** | **GIFT Nifty data.** There's no reliable free API, and the old SGX Nifty tickers are gone. | Pre-open global cue missing | Best-effort vendor + fallback to US futures and Asian indices. When unavailable, say so. Never estimate it. |
| **P-12** | **News quality.** RSS feeds duplicate the same story across outlets, some are paywalled (headline only), and timestamps can be in different zones. | Sentiment double-counting; news after 15:30 wrongly "explaining" today's move | Deduplicate by normalized title + URL similarity. Use headlines + summaries only. Normalize to IST. News stamped after the close is assigned to the **next** session. Each headline is kept as evidence with source and time. |
| **P-13** | **Sentiment scoring reliability.** LLM scores drift between runs, and general-purpose models misread finance jargon ("cut" can be bullish for rates). | Noisy sentiment | Ensemble: a finance-tuned classifier (for example FinBERT, optional dependency) + an LLM with a fixed rubric (−1..+1 scale, per headline, with entity tags). Report the mean, dispersion and count. Low count → low weight. |
| **P-14** | **Rate limits and outages across many vendors.** | Slow or failed runs | Per-vendor token bucket, TTL cache, parallel fetch with a timeout, and `stale-while-revalidate` (serve the cached value marked `stale=True` with its age when the vendor is down). |

### Integration & engineering

| ID | Problem | Impact | Solution |
|---|---|---|---|
| **P-15** | **Dependency mismatch.** optopsy requires Python 3.12–3.13 and pandas-ta-classic. TradingAgents pins `pandas>=3.0.6`, and pandas-ta-classic compatibility with pandas 3 must be verified. | Import failures or subtle numeric differences | **Resolved:** the engine was moved into TradingAgents and runs in its environment (pandas 3.0.6), with its dependencies pinned to the versions optopsy was tested with (pandas-ta-classic 0.3.59, empyrical-reloaded 0.5.12). |
| **P-16** | **optopsy must stay read-only.** | Can't patch upstream bugs | Wrap, don't edit. Fixes go in the adapter layer and are documented in `ambiguities.md`. Upstream issues get recorded for the owner. |
| **P-17** | **Look-ahead in pattern detection.** Swing highs/lows and ZigZag "repaint" because they need future bars to confirm. | Backtests look great, live results don't | Swing points are confirmed only after `k` bars, and the evaluator uses the confirmation date, not the pivot date. A dedicated test feeds data bar by bar and asserts that results don't change after the fact. |
| **P-18** | **Overfitting through many combinations** (≈40 structures × 105 signals × parameters × legends). | Something will always "work" by chance | Walk-forward only, an out-of-sample table first, a minimum trade count (for example ≥ 30) before a regime-fit weight is trusted, and a multiple-testing haircut. Low-sample strategies are shown with "insufficient evidence". |
| **P-19** | **Context window and cost.** Passing 150+ strategy evaluations and 20+ legend scorecards to every agent is expensive. | Slow and costly runs; diluted reasoning | Agents receive a **compact table** (id, status, score, 1-line reason). Only triggered or partial items are expanded. Full detail stays in the ledger and report. The quick-think model handles analysts and the deep-think model handles managers, which matches the existing tier config. |
| **P-20** | **LLM hallucinating numbers or causes.** | Wrong, confident reports | The evidence ledger, the number validator, the causal-label taxonomy (direct / plausible / correlated), and a prompt rule that numbers come only from tools. Missing data is rendered explicitly. |
| **P-21** | **Strategy conflicts.** Value says buy, momentum says sell. | Confusing or averaged-out stance | The conflict matrix by horizon. The Trader picks a horizon and must justify why the others don't override it. Conflicts are always shown in section 7/8 of the report. |
| **P-22** | **Index vs. stock applicability.** Graham on Nifty is meaningless, and options strategies on non-F&O stocks are impossible. | Garbage verdicts | `applies_to` and `requires` fields → `NOT_APPLICABLE` status, excluded from consensus denominators. |
| **P-23** | **Reproducibility.** Live data changes and LLMs aren't deterministic. | Can't audit a past report | Each run persists its evidence ledger snapshot + config hash + model ids. A "replay" mode re-renders the report from a saved ledger. |
| **P-24** | **Secrets.** | Leaked API keys | `.env` only (already the pattern); `.env.example` updated; keys never logged (the run log redacts any header or param named `*key*`/`*token*`). |

### Domain & compliance

| ID | Problem | Impact | Solution |
|---|---|---|---|
| **P-25** | **Regulatory context.** In India, giving investment advice or research for consideration falls under SEBI regulations (RA/IA). | Legal risk if outputs are distributed as advice | Every report carries the disclaimer. The output is framed as research and decision support. No auto-execution. If reports are ever shared publicly or commercially, get proper legal review first. |
| **P-26** | **Misrepresenting legends.** | Reputational and ethical risk | Each module says "rule-based approximation of publicly documented principles"; proxies are labelled; no claims about their actual holdings or trades. |
| **P-27** | **Small/micro-cap liquidity and governance** (relevant to Kedia, Porinju and Dolly Khanna style picks). | Untradeable or manipulated names pass the scorecards | Hard guards: minimum average daily traded value, free float, promoter pledge threshold, surveillance-list check (ASM/GSM lists where obtainable). Failing a guard caps the score and prints a warning. |
| **P-28** | **Regime shifts.** A strategy's edge disappears. | Stale weights | Regime-fit weights are recomputed on a schedule with a rolling window. The post-mortem leaderboard alerts when live hit rate falls well below backtest. |

---

## 8. Configuration reference

`config/india.yaml` (loaded on top of `default_config.py`; keys can be overridden by `TRADINGAGENTS_*` env vars):

```yaml
market: india
benchmark_ticker: "^NSEI"
symbols:
  indices: ["^NSEI", "^NSEBANK"]
  watchlist: ["RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS"]
timeframes: {primary: "1d", secondary: "1wk"}
vendors:
  ohlcv:        [yahoo]
  flows:        [nse]
  derivatives:  [nse]                  # live chain + bhavcopy history
  fundamentals: [fundamentals_in, yahoo]
  news:         [news_rss, yahoo]
  global:       [global_cues, fred]
cache_ttl_seconds: {quote: 60, option_chain: 180, eod: session, fundamentals: 86400, news: 600}
analysts: [market, fundamentals, news, social, macro, derivatives, strategy, legends]
strategies:
  registries: [optopsy, curated]
  enabled: all                         # or list of ids
  partial_threshold: 0.5
legends:
  enabled: all
  consensus_min_evaluable_weight: 0.7
regime: {adx_trend: 25, vol_percentile_high: 80, lookback_days: 252}
risk:
  max_risk_per_trade_pct: 1.0
  atr_stop_multiple: 2.0
  min_reward_risk: 1.5
backtest:
  walk_forward: {train_years: 3, test_years: 1}
  costs: india_default                 # STT, stamp, exchange, GST, SEBI, brokerage
  min_trades_for_weight: 30
llm:
  quick_think_llm: <configured>
  deep_think_llm:  <configured>
report: {formats: [md, html], include_ledger: true, disclaimer: true}
```

`.env` additions: `NEWSAPI_KEY=`, `FUNDAMENTALS_API_KEY=` (optional), `TRADINGAGENTS_MARKET=india`.

---

## 9. Testing & validation strategy

| Layer | Test type | Example |
|---|---|---|
| Vendors | Fixture-based unit tests (recorded responses), error-path tests | NSE 401 → session refresh → success; NSE down → fallback → `missing` |
| Calendar | Table tests | Holiday on a Monday → previous session is Friday |
| Indicators | Golden-value tests vs. a reference (stockstats / hand calc) | RSI(14) on a fixed series equals the known value |
| Patterns | Synthetic constructions + negative cases | A constructed inverse H&S is detected; random walk false-positive rate under threshold |
| Look-ahead | Incremental replay test | Results for bar *t* identical when computed with data to *t* and to *t+50* |
| Registry | Schema validation of every YAML; ingestion idempotency | Re-running ingest produces no diff |
| Evaluator | Condition-level tests | Known setup → exact met/unmet lists |
| Legends | Scorecard tests with fake fundamentals | Graham Number computed as √(22.5 × EPS × BVPS) |
| Graph | Mocked-LLM end-to-end (existing pattern) | All new state keys populated; conflict node runs |
| Report | Number-validator tests | Fabricated number in narrative → flagged |
| Backtest | Known-answer tests | Buy-and-hold strategy CAGR equals index CAGR minus costs |
| Live smoke | `pytest -m live` (opt-in, not in CI) | Real Nifty 50 run end to end |

The existing 89 test files must keep passing. US behaviour is unchanged when `market` isn't `india`.

---

## 10. Delivery checklist per phase

For every phase:

- [ ] Code follows existing structure and style (ruff clean)
- [ ] Types + docstrings on public functions
- [ ] Unit tests added and passing; existing suite green
- [ ] Config keys documented; `.env.example` updated if needed
- [ ] Logging of tool calls / decisions in place
- [ ] **Real run on a Nifty 50 example with output shown**
- [ ] Known limitations and proxies written down
- [ ] README section updated (setup, usage, example)

Phase demo outputs to show:

| Phase | Demo |
|---|---|
| A | Table: ^NSEI snapshot, FII/DII, VIX, top 5 global cues, 5 latest headlines — all with source + timestamp |
| B | Pattern hits and regime label for ^NSEI over the last 250 sessions |
| C | Coverage report + `evaluate_all("^NSEI")` verdict table |
| D | Legend scorecards for RELIANCE.NS / HDFCBANK.NS + index-applicable legends for ^NSEI |
| E | Full graph run, each analyst's report |
| F | The 10-section "why did Nifty move" report with zero unverified numbers |
| G | Backtest table (IS vs OOS, by regime) + one post-mortem entry |

---

## 11. Open decisions

Sensible defaults are listed. Change any of them before the phase that needs it.

1. **Strategy source:** optopsy contains options structures and signals, not prose strategies. *Default:* ingest the code and docs as described, plus a curated playbook set. If you have separate strategy notes (PDFs or notebooks) elsewhere, point to them and the same schema applies.
2. **Historical options data:** *Default:* NSE F&O bhavcopy (free, EOD, close-price approximation). Alternative: a paid tick/quote vendor.
3. **Fundamentals source:** *Default:* yfinance statements + NSE shareholding filings. Alternative: a paid India fundamentals API.
4. **Vector index:** *Default:* local embeddings in an on-disk index (no external service).
5. **optopsy integration mode:** *Decided:* engine moved into this repo as `option_backtester/` (AGPL-3.0, see section 13).

---

## 12. Risk disclaimer

This software and every report it generates are for **research and educational decision support only** and are **not investment advice**. Markets involve risk of loss, including loss of capital. Backtested and historical results, including any rule-based approximation of a well-known investor's approach, do **not** guarantee future performance, and they may contain modelling errors, data errors or biases. Approximations and proxies are labelled as such. Before acting on any output, verify the data independently and consult a SEBI-registered investment adviser where appropriate.

---

## 13. Implemented fixes (2026-10-22)

Each fix below was built, unit-tested offline (65 new tests, no network), and run against live NSE/Yahoo data with `python scripts/india_live_check.py`. The existing suite still passes (1418 passed; the same 5 pre-existing failures in ChatGPT-auth, CLI-update and yfinance-cache tests are unrelated).

### What the live data showed (and the code now handles)

| Observation (22-Oct-2026) | Consequence |
|---|---|
| `nseindia.com/` homepage → **403**; `/option-chain` page → 200 with cookies | Cookie bootstrap uses pages that are not blocked, homepage last |
| `/api/option-chain-indices` → **404** (moved to `/api/option-chain-v3`) | 404 is "moved / not published", not an outage; archive files preferred |
| Yahoo `^NSEI` volume 391,600 → 285,800 → **0**; RELIANCE alone traded ~15M shares | Index volume judged unreliable (0.1% of constituents' volume) and replaced with a ₹-turnover proxy |
| Yahoo `^NSEI` has **no 21-Oct-2026 bar** although NSE traded (20-Oct was Dussehra) | Calendar gap check reports missing sessions |
| NIFTY lot **50** (Jan-2024, derived) → **65** (Oct-2026); BANKNIFTY 15 → 30 | Dated lot-size history from bhavcopies, never constants |
| NIFTY expiries: Tuesdays, but **09-Nov and 23-Nov are Mondays**; BANKNIFTY monthly only | Expiries read from traded contracts / live contract-info |
| optopsy venv: Python 3.13.2, pandas 3.0.1, pandas-ta-classic 0.3.59; TradingAgents env: Python 3.13.5, pandas 3.0.6, **no pandas-ta-classic** | Engine moved into TradingAgents with its two dependencies at optopsy's tested versions. Under pandas 3, dates become `datetime64[s]`, which the engine rejects; the bridge converts them |
| optopsy `short_put_spread` with defaults → **empty**: both legs default to 0.30Δ and collapse onto one strike | Always pass distinct leg deltas (engine default left as upstream wrote it) |
| ^NSEI SMA-trend walk-forward: IS Sharpe 1.17 → OOS 0.50, DSR 0.40, 26 trades | Verdict `insufficient_evidence` — exactly the overfitting the validator exists to catch |

### Where each fix lives

| Problem | Module(s) | Tests |
|---|---|---|
| P-01 NSE blocking | `tradingagents/dataflows/vendors/nse/client.py` — browser headers, cookie bootstrap, throttle, backoff + jitter + Retry-After, re-bootstrap on 401/403/HTML, circuit breaker, disk cache, stale-on-outage | `tests/test_nse_client.py` |
| P-02 index volume | `.../nse/index_volume.py` — reliability assessment, point-in-time constituent turnover proxy, calendar gap check | `tests/test_india_index_volume.py` |
| P-03/P-04 calendar & evening publication | `.../nse/calendar.py` (NSE holiday master, IST session state, `fresh/pending/late/no_session`), `.../nse/flows.py` (FII/DII + locally accumulated history) | `tests/test_nse_calendar_flows.py` |
| P-08 lot size & expiries | `.../nse/derivatives.py` — UDiFF + legacy bhavcopy → one schema, `LotSizeHistory` (dated runs, explicit uncertainty), expiries from data, delivery data | `tests/test_nse_contracts_universe.py` |
| P-09 survivorship bias | `.../nse/indices.py` — dated constituent snapshots, change-log reconstruction, `survivorship_safe` flag on every answer | `tests/test_nse_contracts_universe.py` |
| P-15 Python/pandas conflict | `option_backtester/` (engine, moved in) + `tradingagents/integrations/optopsy/{bridge,adapter}.py` — `doctor()`, NSE bhavcopy → engine chain with BS deltas | `tests/test_optopsy_bridge_compliance.py` |
| P-17 look-ahead | `tradingagents/analytics/swings.py` — swings carry `confirmed_at`; `find_lookahead()` replay check (catches a centred-window pivot: 13 repaints on real ^NSEI) | `tests/test_india_analytics.py` |
| P-18 overfitting | `tradingagents/analytics/validation.py` — walk-forward with embargo, PSR, Deflated Sharpe, min-trades verdict | `tests/test_india_analytics.py` |
| P-25 SEBI | `tradingagents/compliance.py`, hooked into `reporting.py` and `report_html.py` — disclaimer on every complete report, red-flag phrases flagged (negations ignored) | `tests/test_optopsy_bridge_compliance.py` |

Agent wiring: `get_india_fii_dii_flows` (News Analyst); `get_india_index_data_health`, `get_india_delivery_data`, `get_india_fo_contract_info` (Market Analyst). Non-Indian instruments get "not applicable".

### What still needs a human

- **Index change log** (`~/.tradingagents/cache/nse/index_changes.json`): NSE publishes reconstitutions only as press-release PDFs. Until past changes are entered and `set_complete_since()` is called, any date before the first snapshot is flagged `survivorship_safe=False`. Snapshots taken from now on accumulate automatically.
- **FII/DII history** builds up one day per run; NSE has no free history endpoint. Older dates are reported as missing, not estimated.
- **Publication times** in `calendar.EXPECTED_BY` are conservative approximations; status is always decided by the date inside the data.
- **Options backtests** on NSE data use EOD close as bid and ask; treat their P&L as optimistic and use optopsy's slippage settings.

### Options engine moved in from optopsy

Only what TradingAgents runs was brought over: `option_backtester/` with its core (pricing, evaluation, rules, filters, exits, metrics, simulator, plugins), `strategies/` (40) and `signals/` (~100), plus its `LICENSE`. Left out: optopsy's chat UI (chainlit/litellm/postgres), its EODHD downloader and parquet cache (`load_cached_options`/`load_cached_stocks` now say so), and its tests, docs and samples. The `optopsy/` folder can be deleted.

**License:** optopsy is AGPL-3.0-or-later; TradingAgents is Apache-2.0. Using the combined code privately is fine. Distributing it, or letting others use it over a network, brings the AGPL's source-sharing obligations for the combined work. Unless the optopsy copyright holder relicenses the engine, keep `option_backtester/LICENSE` and get proper legal advice before distributing.

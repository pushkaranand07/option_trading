# TradingAgents (India) — documentation

> **Status:** Current. Restructured on 2026-10-24 ([the docs restructure](development/documentation-standards.md)).
> **Scope:** everything under `docs/`.
> **Last verified against the code:** 2026-10-24

A multi-agent LLM research system for Indian markets (a fork of the open-source TradingAgents framework), extended
with NSE data, an options backtester, and a **quant signal layer** that tests trading ideas honestly — walk-forward,
real costs, pre-registered rules — before anything is trusted. It produces research and signals only; the user trades
manually on Dhan. **Research and decision support, not investment advice.**

---

## 1. Start here

| If you want to… | Read |
|---|---|
| Understand the project in five minutes | [Executive summary](architecture/18-executive-summary.md) |
| See where the work stands today | [Progress tracker](PROGRESS_TRACKER.md) |
| Run an analysis on a stock or index | [Running an analysis](guides/running-an-analysis.md) |
| Use the system's numbers in your own trading | [Using the quant outputs on Dhan](guides/using-the-quant-outputs-on-dhan.md) |
| Analyse your own trades | [Exporting your Dhan tradebook](guides/exporting-your-dhan-tradebook.md) |
| Set up the code on a new machine | [Local setup](development/local-setup.md) |
| Understand the system | [System overview](architecture/01-system-overview.md) → [Quant layer overview](architecture/10-quant-layer-overview.md) |
| Know what data exists, its holes and its corrections | [Data catalog](data_catalog.md) |
| See what changed and why | The PA change records (§3) |

---

## 2. Folders

| Folder | What is in it |
|---|---|
| [`architecture/`](architecture/) | How the system is built: agents, LLMs, data, India layer, backtester, UI, quant layer |
| [`features/`](features/) | One document per live feature: what it does, how to use it, files, settings, known issues |
| [`development/`](development/) | Working on the code: setup, tests, git workflow, the scheduled job, data and secrets, documentation standards |
| [`guides/`](guides/) | Step-by-step guides for the user |
| [`plans/`](plans/) | The plans the work follows: [quant signal layer](plans/QUANT_SIGNAL_LAYER_PLAN.md), [proof plan](plans/PROOF_PLAN.md), [India market intelligence](plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md) |
| [`strategies/`](strategies/) | Frozen strategy specifications (written and pushed before testing) with their results |
| [`data/`](data/) | Small public reference data the code reads ([researched market events 2021–26](data/market_events_2021_2026.json)) |
| [`archive/`](archive/) | History only; never a statement of current behaviour |
| Root `PA_*.md` | Change records, one per change, in the PA format ([standards](development/documentation-standards.md)) |
| [`PROGRESS_TRACKER.md`](PROGRESS_TRACKER.md) | Live progress bars, verdicts and next steps (rewritten by `scripts/update_progress.py`) |

---

## 3. Change records (PA)

| # | Change | Status |
|---|---|---|
| [PA-01](PA_01-india-market-intelligence-baseline.md) | Baseline import and India market intelligence (NSE data, analytics, options engine) | Done |
| [PA-02](PA_02-webapp.md) | "Pulse Trader" web app | Done |
| [PA-03](PA_03-quant-foundation-nse-data-store.md) | Quant foundation: plan, gates, trial log, universe, NSE downloader, point-in-time store, costs | Done |
| [PA-04](PA_04-evaluation-harness-and-baselines.md) | Walk-forward evaluation harness and baselines; MA trend rejected | Done |
| [PA-05](PA_05-garch-volatility-and-vrp-condor.md) | GARCH volatility (validated), implied vol, VRP iron condor (rejected: too few trades) | Done |
| [PA-06](PA_06-regime-detection-hmm.md) | Market regimes (HMM, validated as a risk input), data repairs, progress tracker | Done |
| [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) | Quant report tool for the agents, LightGBM (no edge), sizing, bug sweep | Done |
| [PA-08](PA_08-relative-strength-model.md) | Relative-strength model (rejected), data completion, remaining bug fixes | Done |
| [PA-09](PA_09-ship-expected-move-and-daily-refresh.md) | Expected move in the agents' report; scheduled daily refresh | Done |
| [PA-10](PA_10-retest-pooled-condor-and-relative-buffer.md) | Re-tests: pooled 4-book VRP condor (close), relative strength with buffer (rejected) | Done |
| [PA-11](PA_11-proof-plan-move-size-and-paper-trading.md) | Proof plan; move size (GARCH 0.573 beats LightGBM); quiet-stock condor rejected; paper-trading ledger | Done |
| [PA-12](PA_12-stage2-stress-tests.md) | Stage 2 stress tests for the VRP condor: pass, weak spot found | Done |
| [PA-13](PA_13-backward-holdout-2015.md) | Backward holdout 2015–21 rejects the VRP condor; paper trading as observation only | Done |
| [PA-14](PA_14-market-map-2021-26.md) | Market Map 2021–26: law changes and events measured against NSE data | Done |
| [PA-15](PA_15-weekend-nse-sessions.md) | Weekend NSE special sessions recovered (11) | Done |
| [PA-16](PA_16-chronos-pretrained-model.md) | Chronos-Bolt pretrained model vs GARCH: not kept | Done |
| [PA-17](PA_17-results-day-iron-butterfly.md) | Results-day iron butterfly (IV crush): rejected — edge real, costs larger | Done |
| [PA-18](PA_18-results-fly-overpriced-retest.md) | Results fly: cost diagnosis; overpriced-only re-test rejected | Done |
| [PA-19](PA_19-option-quotes-measured-spreads.md) | Option trading costs measured from NSE bid/ask every evening | Done |
| [PA-20](PA_20-trade-journal.md) | Trade journal for the user's own Dhan trades | Done; waiting for the export |
| [PA-21](PA_21-phase9-replay-and-report-wording.md) | Phase 9 replay (10 analyses): 0 invented quant numbers, 0 validation claims; clearer verdict wording; check v2 | Done |
| [PA-22](PA_22-morning-plan.md) | Morning plan at 8:30 AM: session, AI view, levels; live call with per-lot figures (the risk-limit card was later removed) | Done |
| [PA-23](PA_23-ai-strategist-and-nse-option-chain.md) | Plan tab: AI options strategist (defined risk, priced at bid / ask) and NSE option chain | Done |
| [PA-24](PA_24-trade-ticket-and-premium-levels.md) | AI trade shown like a Dhan order: premium target / stop per leg, tap a leg for its ticket (premium chart, depth), marked on chart and chain | Done |
| [PA-25](PA_25-trade-record.md) | Trade Record tab: take the AI's trade as a dummy 1-lot trade, live monitoring with target / stop flags, P&L history | Done |
| [PA-26](PA_26-evidence-score-and-ai-track-record.md) | Pulse evidence score (0-100) for every AI suggestion, debit-spread check fixed, one retry, AI track record by score | Done |
| [PA-27](PA_27-pulse-trade-ranking.md) | Pulse trade ranking: concrete trades (strike, entry, target, stop per leg) best first, iron butterfly accepted | Done |
| [PA-28](PA_28-backend-latency.md) | Backend latency: one fetch per key, refresh-ahead, stale-feed blockers, p50/p95/p99 at `/api/latency` (p99 1.3 s → 0.14 s) | Done |
| [PA-29](PA_29-plan-chart-tools.md) | Plan chart: decluttered and larger, layer toggles, automatic day levels / swings / crossovers, drawing tools, O/H/L/C readout | Done |
| [PA-31](PA_31-research-splits-and-locked-loader.md) | Data foundation step 1: frozen splits (2025+ locked and labelled contaminated, clean forward holdout), locked research loader, point-in-time audit, NSE archive holes | Done |
| [PA-32](PA_32-prices-holiday-bars.md) | Prices: bars only on NSE sessions; 29 Yahoo bars on the 2026-01-15 holiday removed, 32 `known_from` corrected; data catalog started | Done |
| [PA-33](PA_33-fo-universe-count.md) | Data foundation step 2, count only: 19 index + 473 stock symbols since 2010, 274 left F&O; option rows and disk for 5 filter options; nothing ingested | Done |
| [PA-34](PA_34-base-2015-2017.md) | Data foundation batch a: stored base 2015–2017, every F&O underlying (14.5M chain rows, 136 MB), quality checks PASS, pre-2018 lots UNVERIFIED and masked | Done |
| [PA-35](PA_35-base-2018-2026.md) | Data foundation batch b: stored base 2018–2026 (65.7M chain rows, 919 MB), reconciled with the live store (identical after a lot-despiking fix), corporate actions and parity breakdown | Done |
| [PA-36](PA_36-base-2010-2014.md) | Data foundation batch c: stored base 2010–2014 (15.5M chain rows, 126 MB), F&O calendar from NSE circulars, American options marked, research loader base-only | Done |
| [PA-37](PA_37-symbol-map-and-universes.md) | Data foundation batch d: NSE symbol map (41 of 57 renames mapped), point-in-time universes U1 (indices + top 100 stocks by prior-year turnover) and U2, sealed 2026 ranking | Done |
| [PA-38](PA_38-intraday-free-source-probe.md) | Dataset B (intraday): free-source probe; parked, no usable source; nothing ingested | Done |

**Renumbered on 2026-10-26.** Sixteen small records were folded into the ones they belong to and the rest numbered 01–27. Pull requests and commits before that date use the old numbers:

| Old | Now | Old | Now |
|---|---|---|---|
| 01 | PA-01 |  23 | PA-19 |
| 02 | PA-02 |  24 | PA-20 |
| 03 | PA-03 |  25 | PA-21 |
| 04 | PA-04 |  26 | removed (git history) |
| 05 | PA-05 |  27 | in PA-15 |
| 06 | removed (git history) |  28 | in PA-05 |
| 07 | in PA-05 |  29 | removed (git history) |
| 08 | PA-06 |  30 | in PA-02 |
| 09 | PA-07 |  31 | removed (git history) |
| 10 | PA-08 |  32 | in PA-02 |
| 11 | PA-09 |  33 | PA-22 |
| 12 | removed (git history) |  34 | PA-23 |
| 13 | in PA-09 |  35 | in PA-22 |
| 14 | PA-10 |  36 | PA-24 |
| 15 | PA-11 |  37 | in PA-02 |
| 16 | PA-12 |  38 | PA-25 |
| 17 | PA-13 |  39 | PA-26 |
| 18 | PA-14 |  40 | PA-27 |
| 19 | PA-15 |  41 | in PA-24 |
| 20 | PA-16 |  42 | in PA-02 |
| 21 | PA-17 |  43 | in PA-02 |
| 22 | PA-18 |

---

## 4. Architecture

| # | Document | Covers |
|---|---|---|
| 01 | [System overview](architecture/01-system-overview.md) | Every component and how they fit together |
| 02 | [Agent pipeline](architecture/02-agent-pipeline.md) | The LangGraph graph, node order, debate rounds, state, `propagate()` |
| 03 | [Agents and tools](architecture/03-agents-and-tools.md) | Each agent role, what it reads and writes, its tools |
| 04 | [LLM providers and configuration](architecture/04-llm-providers-and-configuration.md) | Provider factory, quick / deep tiers, config keys, `TRADINGAGENTS_*` overrides |
| 05 | [Memory, reflection and checkpoints](architecture/05-memory-reflection-and-checkpoints.md) | Decision memory log, settlement, reflection, resumable runs |
| 06 | [Data vendors](architecture/06-data-vendors.md) | Vendor routing, fallbacks, caching, point-in-time data |
| 07 | [India market layer](architecture/07-india-market-layer.md) | NSE client, calendar, derivatives, flows, India tools and safeguards |
| 08 | [Option backtester](architecture/08-option-backtester.md) | The optopsy fork and the NSE adapter |
| 09 | [CLI, webapp and reports](architecture/09-cli-webapp-and-reports.md) | Command line, web app, Markdown / HTML reports |
| 10 | [Quant layer overview](architecture/10-quant-layer-overview.md) | Purpose, module and script map, what is in use vs rejected |
| 11 | [NSE data store](architecture/11-nse-data-store.md) | Downloader, point-in-time Parquet store, prices, quotes, universe |
| 12 | [Evaluation and validation](architecture/12-evaluation-and-validation.md) | Walk-forward, gates, deflated Sharpe, trial log, stress, holdout |
| 13 | [Volatility and regime models](architecture/13-volatility-and-regime-models.md) | GARCH family, implied vol, HMM regimes, Chronos, LightGBM |
| 14 | [Option strategy simulators and costs](architecture/14-option-strategy-simulators-and-costs.md) | Cost model, condor, VRP, event fly, sizing |
| 15 | [Daily refresh and paper trading](architecture/15-daily-refresh-and-paper-trading.md) | The 19:30 job, paper ledger, kill rules |
| 16 | [Quant context in the agents](architecture/16-quant-context-in-agents.md) | The quant report, prompt rules, replay check |
| 17 | [Market Map](architecture/17-market-map.md) | Series, events, impact windows, network |
| 18 | [Executive summary](architecture/18-executive-summary.md) | The project in five minutes |

---

## 5. Features

| Feature | Document |
|---|---|
| Multi-agent analysis of a stock or index | [analysis-pipeline](features/analysis-pipeline.md) |
| Web app | [webapp](features/webapp.md) |
| India tools for the analysts | [india-tools](features/india-tools.md) |
| Option backtester | [option-backtester](features/option-backtester.md) |
| Quant context in every report (regime, volatility, expected move) | [quant-report](features/quant-report.md) |
| Daily refresh at 19:30 | [daily-refresh](features/daily-refresh.md) |
| Forward paper trading | [paper-trading](features/paper-trading.md) |
| Market Map 2021–26 | [market-map](features/market-map.md) |
| Measured option spreads | [option-quotes](features/option-quotes.md) |
| Trade journal | [trade-journal](features/trade-journal.md) |

---

## 6. Development

[Local setup](development/local-setup.md) · [Testing and lint](development/testing-and-lint.md) ·
[Git workflow](development/git-workflow.md) · [Scheduled job operations](development/scheduled-job-operations.md) ·
[Data and secrets](development/data-and-secrets.md) · [Documentation standards](development/documentation-standards.md)

Check every link in the docs: `python scripts/check_doc_links.py`.

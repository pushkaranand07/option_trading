# PA-03 — Quant layer foundation: plan, gates, trial log, universe, NSE downloader, point-in-time store, costs

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/{gates,trial_log,universe,backfill,datastore,prices,costs}.py`, `scripts/quant_backfill.py`, `scripts/quant_build_store.py`, `tests/test_quant_{gates,backfill,datastore,costs}.py`, `pyproject.toml`; plan `docs/QUANT_SIGNAL_LAYER_PLAN.md` (now [plans/QUANT_SIGNAL_LAYER_PLAN.md](plans/QUANT_SIGNAL_LAYER_PLAN.md)) |
| **Related** | [PA-01](PA_01-india-market-intelligence-baseline.md) · [PA-04](PA_04-evaluation-harness-and-baselines.md) · [PA-06](PA_06-regime-detection-hmm.md) (data repairs) · [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) (lot sizes) · [PA-08](PA_08-relative-strength-model.md) (data complete) · [PA-15](PA_15-weekend-nse-sessions.md) · [PA-19](PA_19-option-quotes-measured-spreads.md) · [architecture/10-quant-layer-overview.md](architecture/10-quant-layer-overview.md) · [architecture/11-nse-data-store.md](architecture/11-nse-data-store.md) · [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md) · [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) |
| **Pull request** | #2 (branch `quant/phase-0-1-foundation`); commit `d52ed0c` (the PR also carried `9b71aeb`, see [PA-01](PA_01-india-market-intelligence-baseline.md)) |
| **Date** | 2026-10-23 |

---

## 1. Problem

The LLM agents argue from text; nothing in the repo could say whether a trading idea actually had a measured edge.
The quant signal layer plan (written 2026-10-23) sets out a slow, gated path: numbers forecast, LLMs reason. Before
any model could be tested, it needed (Phases 0–1 of the plan):

- success rules fixed **before** seeing results, so a bad backtest cannot move the goalposts;
- a record of every backtest run, so the number of ideas tried can be corrected for;
- years of NSE history where every value carries the date it became **known**, not just the date it describes;
- realistic Indian trading costs.

## 2. Root cause / findings

- Free, end-of-day NSE archive files exist per trading day: F&O bhavcopy (UDiFF format from 2024-07-08, legacy
  before), participant-wise open interest (FII / DII / Pro / Client) and security-wise delivery (MTO).
- NSE publishes these after the close, so a value for session D is first usable on the next session.
- F&O STT was raised on 2026-04-01 (NSE circular NSE/FATAX/73524, Finance Act 2026); NSE transaction charges
  changed 2026-03-01 (NSE/FA/73061). Sources are listed in `costs.py`.
- Universe check: of the top ~40 stocks by F&O futures turnover (week to 22-Oct-2026), several were not in F&O for
  the whole history — BSE, ETERNAL, JIOFIN, LTM, DIXON, PERSISTENT, LAURUSLABS, INDHOTEL, INDUSTOWER, ADANIENSOL
  listed after 2018; YESBANK and ADANIPOWER left F&O in between; IDEA excluded (penny stock, repeated dilution).

## 3. Decisions

- **Universe:** 29 stocks plus NIFTY and BANKNIFTY, history from 2018-01-01 (`universe.py`). Stocks in F&O on both
  2018-01-02 and 2022-01-03, grouped into 10 sectors. Because this is today's survivors, every report built on it
  carries `SURVIVORSHIP_NOTE` ("results lean optimistic").
- **Holding horizon:** 5–20 sessions; monthly options (tracker, Phase 0).
- **Eight gates** (`gates.py`, thresholds from plan Phase 0): ≥ 100 out-of-sample trades, Deflated Sharpe ≥ 0.95,
  OOS/IS Sharpe ≥ 0.5, positive after costs in ≥ 70% of folds, |max drawdown| ≤ 2× average yearly return, positive in
  ≥ 2 regimes (or the losers switched off), neighbour-parameter Sharpe ≥ 0.5× the chosen one, plus the look-ahead check.
  **Missing evidence is `not_evaluated`, never a pass**; a strategy is `approved` only when every gate was checked
  and passed.
- **Trial log:** SQLite, one row per backtest run, so the Deflated Sharpe uses an honest trial count.
- **Point-in-time rule:** every store row has `trade_date` and `known_from` = next trading session; `as_of()` filters
  on `known_from <= t`.
- **Costs at 2026 rates applied to all history, on purpose:** older trades were cheaper, so a strategy that only pays
  at old rates is rejected rather than flattered.
- **Brokerage default ₹20 per executed order** (the highest of the brokers checked, Dhan included); slippage 0.05% of
  price per equity/futures fill, and 1 tick (₹0.05) + 1% of premium per option fill.
- **Raw files kept exactly as NSE served them**; published archives never change, so nothing is re-downloaded.
- Whether the user approved the universe and horizon: not recorded. The switch to Dhan as the default broker
  (the user's broker) came in [PA-04](PA_04-evaluation-harness-and-baselines.md).

## 4. What was built / changed

| File | What it does |
|---|---|
| `tradingagents/analytics/gates.py` | The eight gates; `evidence_from_walk_forward`, `check_gates` |
| `tradingagents/analytics/trial_log.py` | SQLite log of every run, trial counts |
| `tradingagents/analytics/universe.py` | 29 stocks by sector, indices, Yahoo tickers, survivorship note |
| `tradingagents/analytics/backfill.py` + `scripts/quant_backfill.py` | Resumable, throttled download of F&O bhavcopy, participant OI and MTO delivery from 2018; manifest CSV marks each (day, kind) `ok` or `missing`; stops cleanly when NSE goes down |
| `tradingagents/analytics/datastore.py` + `scripts/quant_build_store.py` | Parsers and Parquet store `<cache>/quant/store/<dataset>/<year>.parquet`: `fo_summary`, `option_chain` (near-dated, near-the-money universe contracts), `participant`, `delivery` |
| `tradingagents/analytics/prices.py` | Yahoo OHLCV with an NSE-calendar quality report |
| `tradingagents/analytics/costs.py` | NSE round-trip charges (STT, exchange incl. IPFT, SEBI fee, stamp duty, 18% GST, brokerage, DP charge) plus slippage |

14 files, 1,578 lines added.

## 5. Tests

- `test_quant_gates.py`: all gates met → approved; missing evidence never passes; each gate rejects its own failure;
  regime rule; drawdown arithmetic; trial log keeps every run.
- `test_quant_backfill.py`: formats tried in NSE's publication order; holidays marked, weekends skipped; resume
  without refetching; clean stop on outage; universe has 29 unique stocks each with a sector and ticker.
- `test_quant_datastore.py`: participant and MTO parsing; nearest future and total OI; rows usable only from the next
  session; price normalisation and quality check.
- `test_quant_costs.py`: a NIFTY option round trip matches a hand calculation; futures STT sell-side only at the 2026
  rate; delivery STT both sides plus DP charge; exercised option pays STT on intrinsic; slippage on top of charges.

## 6. Results

At the first tracker snapshot (2026-10-23 13:22) the NSE download was 31% done (2,160 of 6,897 files). No model results
belong to this change.

## 7. Verification

Code and tests only at merge. The full download, store build and data-quality report were completed later on the
same day ([PA-08](PA_08-relative-strength-model.md): 0 missing sessions in any dataset).

## 8. Risks and open items

- **Cost model vs a real Dhan contract note within ₹1** — the Phase 1 exit check — still open; needs the user's
  contract note.
- Survivorship: the universe leans optimistic by construction.
- Participant-OI parsing and lot sizes needed fixes ([PA-06](PA_06-regime-detection-hmm.md),
  [PA-07](PA_07-agent-quant-tool-and-lightgbm.md)); weekend special sessions were missed until
  [PA-15](PA_15-weekend-nse-sessions.md); slippage was later measured, not assumed ([PA-19](PA_19-option-quotes-measured-spreads.md)).
- The plan placed the store under `data_cache/quant/`; the code uses the TradingAgents cache dir
  (`~/.tradingagents/cache/quant/`).
- Research and decision support only; not investment advice.

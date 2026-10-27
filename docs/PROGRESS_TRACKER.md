# Quant Signal Layer — Progress Tracker

> Plan: [QUANT_SIGNAL_LAYER_PLAN.md](plans/QUANT_SIGNAL_LAYER_PLAN.md).
> Bars are recalculated from the checkboxes below (and the live NSE download log) by
> `python scripts/update_progress.py`. Tick a box (`[x]`), run the script, and every bar updates.
>
> **Picking this up? Read [Start here](#start-here) first.** All documentation: [docs/README.md](README.md) (index,
> architecture, features, guides, and one PA change record per change).
> **How a candidate becomes tradable: [PROOF_PLAN.md](plans/PROOF_PLAN.md)** (evidence ladder, kill rules, risk limits).
>
> The bars count only work that is live or still planned. Items that no longer apply (dropped models, steps that
> need a strategy that has passed its tests) are listed as **on hold** without a checkbox, with what would bring them back.

<!-- progress:overall -->
**Overall:** `██████████████████████░░░` 89% (96/108 tasks)
<!-- /progress:overall -->

<!-- progress:download -->
**NSE history download:** `█████████████████████████` 100% (9,204/9,204 files)
<!-- /progress:download -->

_Last updated: 2026-10-27 13:09_

| Work | Status | In GitHub `main`? |
|---|---|---|
| Phases 0–4, 6, 7, 10 tooling, bug fixes, Market Map, weekend sessions, option quotes, trade journal | done | merged (PRs #1–#26) |
| `quant/phase-9-replay` — quant-report wording fix + replay check | replay done: **passed on reading every flag** | merged (PR #27); results: `quant/phase-9-result` |
| `docs/pa-restructure` — docs index, folders, PA_01–PA_26 change records, architecture 01–18 | done | merged (PR #28) |

---

## Phase 0 — Ground rules and success gates
<!-- progress:phase -->
`█████████████████████████` 100% (5/5)
<!-- /progress:phase -->
- [x] Universe chosen from real NSE turnover (29 stocks + NIFTY, BANKNIFTY)
- [x] Holding horizon fixed (5–20 sessions; monthly options)
- [x] Eight success gates in code (`gates.py`)
- [x] Trial log of every backtest run (`trial_log.py`)
- [x] Tests for gates and trial log

## Phase 1 — Point-in-time data foundation
<!-- progress:phase -->
`██████████████████████░░░` 90% (9/10)
<!-- /progress:phase -->
- [x] Resumable, throttled NSE downloader (F&O bhavcopy, participant OI, MTO delivery, index closes)
- [x] Parsers + Parquet store with `known_from` on every row
- [x] Yahoo prices through the data layer, stopping at the last complete session
- [x] Cost model at 2026 rates with sources (Dhan + statutory)
- [x] Parser fixes: untitled / full-month participant files, lot sizes per day
- [x] Full download 2018 → today (plus 2015–17 F&O and index files for holdouts); every weekday and the 11 weekend
  special sessions present; the "missing" days are market holidays
- [x] Store built for every year: participant and delivery on every F&O day, 31/31 symbols ≥98%, IV on every
  symbol-day with a chain; lot sizes exact (from open interest)
- [x] Data-quality report: 0 missing sessions in any dataset; NSE index bars replace Yahoo; stock gaps filled from
  NSE; every stock jump >20% verified as a real event
- [x] **Slippage measured, not assumed** (2026-10-24): NSE's closing bid/ask captured every evening (`quotes.py`,
  last step of the 19:30 job; 31 symbols × 3 expiries). First snapshot: real half-spreads **0.85× the model** on
  ATM / wing strikes (ATM 1.1% of premium, wings 1.6%); worst SUNPHARMA 4.8×, JSWSTEEL 4.1×, DIVISLAB 3.1×
- [ ] Cost model matched to a real Dhan contract note within ₹1 (**needs your contract note**)

## Phase 2 — Evaluation harness and baselines
<!-- progress:phase -->
`█████████████████████████` 100% (5/5)
<!-- /progress:phase -->
- [x] Walk-forward harness with costs, trade ledger, per-year breakdown
- [x] Same-session and future-data leak check
- [x] Baselines: buy-and-hold, 50/200 MA, same trades at random dates
- [x] Exit gate: random signal rejected (synthetic and real), planted edge found
- [x] First real results recorded (MA trend rejected)

## Phase 3 — Volatility engine (GARCH) and VRP condor
<!-- progress:phase -->
`█████████████████████████` 100% (8/8)
<!-- /progress:phase -->
- [x] GARCH / GJR / EGARCH forecasts, expanding window, weekly refit, causal (tested)
- [x] Exit check 1: GARCH beats historical vol out of sample (31/31 symbols) → **in use** (expected move, risk)
- [x] ATM and 30-day IV from option closes (tracks India VIX)
- [x] End-of-day iron condor simulator (your rules: monthly, 50% TP, 2× SL)
- [x] VRP signal + walk-forward with "enter always" and "random days" baselines
- [x] VRP condor on NIFTY and BANKNIFTY (2021-04 → 2026-05 out of sample, costs + slippage)
- [x] Exit check 2: rejected on both (15–19 trades in 5 years; the 100-trade gate cannot be met by a monthly condor)
- [x] Re-test fixing the cause: 4 staggered books, both indices pooled → 84 trades, +12.7% of risk/trade, beats random
  100% — but **rejected by the backward holdout** (2015–21: −5.6%/trade, beats random 60%; see Phase 10)

## Phase 4 — Regime detection (HMM)
<!-- progress:phase -->
`█████████████████████████` 100% (7/7)
<!-- /progress:phase -->
- [x] Features: returns, realised vol, India VIX, breadth
- [x] 3-state Gaussian HMM, filtered probabilities only (no look-ahead; tested against hmmlearn's smoothed output)
- [x] Stable labels (p > 0.7 for 2 days)
- [x] Regime gate wired into Phase 2/3 evaluations
- [x] First real run: calm 68% / choppy 30% / stress 2.4% of days (2021–2026)
- [x] Re-run on NSE's VIX: calm 64% / choppy 34% / stress 1.4%
- [x] Exit gate **passed as a risk input** → **in use**: next-21-day vol calm 11.5% vs choppy 15.1% (p=0.026);
  returns by regime not significant (p=0.14) → not a direction signal

## Phase 5 — Your own idea as exact rules
<!-- progress:phase -->
`█████░░░░░░░░░░░░░░░░░░░░` 20% (1/5)
<!-- /progress:phase -->
Your style (2026-10-24): NIFTY / BANKNIFTY options, stock options, futures and shares; buying and selling options;
holding from intraday to weeks; entries from OI / PCR, charts, news and indicators together. Under 30 trades in the
last 6–12 months, so the journal gives a first look, not firm conclusions.
- [x] **Trade-journal analyser** for your own Dhan tradebook (`python scripts/trade_journal.py <file>`,
  `--horizon intraday|week|month|long|all`): FIFO round trips; results by holding period, buying vs selling,
  instrument, underlying, entry hour, weekday and your own reason/tag column
- [ ] Your tradebook analysed (**needs your Dhan export in `reports/journal/`**, gitignored)
- [ ] One setup written as exact rules (entry, stop, target, exit time), from the journal or your description
- [ ] Coded as a causal signal, leak check passes; tested against baselines with the same gates
- [ ] Keep / drop decision written down

## Phase 6 — Machine-learning models (LightGBM) and stock-option tests
<!-- progress:phase -->
`█████████████████████████` 100% (13/13)
<!-- /progress:phase -->
- [x] Triple-barrier labels; price, volume, structure and market-context features; automatic leak check (0 mismatches)
- [x] Derivatives and flow features (OI change, PCR, delivery %, FII/Client positioning, stock IV), timing-tested
- [x] Purged, embargoed walk-forward; Platt calibration; same-day AUC (stock picking vs market timing)
- [x] Price-only model: **no edge** (same-day AUC 0.505)
- [x] With derivatives/flow features: **no edge** (same-day AUC 0.502)
- [x] Relative strength (beat the other 28 stocks): **no edge** (AUC 0.507, −1.2%/yr after costs)
- [x] Turnover-matched random baseline
- [x] Relative strength with a turnover buffer (re-test): still rejected (−1.0%/yr)
- [x] Move *size* instead of direction: LightGBM AUC 0.503, but **GARCH alone ranks it at 0.573** (in use)
- [x] Condors on the 5 GARCH-quietest stocks: rejected (Sharpe −0.44; stock condors lose money)
- [x] Results-day iron butterfly (IV crush), spec frozen first: 984 trades, **−6.5%/trade → rejected**; results days beat
  random days 100% (the IV crush is real) but trading friction is larger
- [x] Cost diagnosis: +5.5%/trade before costs, break-even at **half** the assumed slippage
- [x] Re-test, only when options look overpriced (spec frozen first): 745 trades, **−4.7%/trade → rejected**

**On hold — dropped at your request (2026-10-23):** further LightGBM work and the MA trend rule (exit gate not met:
AUC 0.506 < 0.55). Comes back only if you ask.

## Phase 7 — Pretrained time-series models
<!-- progress:phase -->
`█████████████████████████` 100% (2/2)
<!-- /progress:phase -->
- [x] Chronos-Bolt-Small (Amazon, free, CPU) tested on 31 symbols, same dates and QLIKE as GARCH, rule fixed in advance
- [x] **Not kept:** 10-session QLIKE GARCH 0.336 vs Chronos calibrated 0.382 (beats GARCH on 8/31) and raw 0.449

## Phase 8 — Ensemble, meta-labelling, sizing
<!-- progress:phase -->
`█████████████████████████` 100% (1/1)
<!-- /progress:phase -->
- [x] ¼-Kelly sizing, capped at 1% risk, your capital as input; lot-rounded quantity (`sizing.py`)

**On hold — needs at least one strategy that has passed its tests:** meta-label model, ensemble of surviving signals,
and its exit gate (beats the best single component). There is nothing to combine yet.

## Phase 9 — Agent integration
<!-- progress:phase -->
`█████████████████████████` 100% (5/5)
<!-- /progress:phase -->
- [x] `get_quant_signal_report` tool (regime, vol forecasts, **expected move**, IV vs forecast, verdicts; only data known before the date)
- [x] Market analyst told to quote it; portfolio manager discounts any unvalidated quant signal
- [x] "VI. Quant Context" section in the Markdown and HTML reports
- [x] Quant report wording fixed (2026-10-24): rule-judged tests showed "gates -" / "Sharpe nan"; now "rejected",
  "rejected (failed the backward holdout)", "predictive check only"; baselines hidden; a backtest pass is never "approved"
- [x] **Exit gate: 10-date replay — passed on reading every flag** (2026-10-24; GPT-5, 2 debate rounds, 101 min):
  799 quant numbers quoted, **0 invented or distorted, 0 validation claims**. The automatic v1 rule did not pass (643
  flags: it also tested other tools' numbers and matched "cross-validated"); check v2 declared for future replays
  ([PA-21](PA_21-phase9-replay-and-report-wording.md))

## Phase 10 — Paper trading and daily operations
<!-- progress:phase -->
`█████████████████████████` 100% (7/7)
<!-- /progress:phase -->
- [x] Daily after-close refresh, **weekdays 19:30** (Windows Task Scheduler): download → store → volatility → regime →
  tracker → Market Map → paper → option quotes
- [x] Paper-trading ledger (`paper.py`): re-runs the frozen simulation nightly, integrity check, kill rules
- [x] Stage 0 spec frozen: `docs/strategies/vrp_condor_pooled.md`
- [x] Stage 2 stress tests passed (costs ×2, slippage ×3, start shifts, bootstrap, drawdown)
- [x] Sizing fixed: 8 condors can be open → ≤ 0.375% of capital each
- [x] **Backward holdout: failed** (2015-08 → 2021-04: −5.6% of risk/trade, beats random 60%) → VRP condor rejected
- [x] VRP condor paper trading kept as **observation only** (your choice), from Mon 2026-10-26; never reported as passing

**On hold — needs a candidate that has passed its backtest:** the Stage 3 targets (≥ 3 months and ≥ 50 paper trades,
results inside the backtest band, slippage ≤ 1.5× model). The VRP condor is observation only, so they don't apply to it.

## Phase 11 — Small live capital (you trade on Dhan)
**On hold — starts only after a strategy passes Stage 3 paper trading** (PROOF_PLAN.md Stage 4): kill switches and
drift monitor, monthly re-check with the same gates, scale-up rules. Needs your capital figure (kept local) then.

## Bug fixes (requested 2026-10-23)
<!-- progress:phase -->
`████████████████████████░` 96% (24/25)
<!-- /progress:phase -->
- [x] 5 old Windows test failures (ChatGPT sign-in file mode, CLI upgrade command, yfinance cache path)
- [x] option_backtester: early exits could land after the planned exit
- [x] option_backtester: commission never deducted from realized P&L
- [x] NSE adapter: expiry valued at last close / untraded wings dropped → now NSE settlement at intrinsic
- [x] Index data gaps: NSE official NIFTY / BANKNIFTY / India VIX bars replace Yahoo
- [x] Stock data gaps (e.g. TCS 22-Oct): filled from NSE equity bhavcopy on Yahoo's adjusted basis
- [x] Index files downloaded for 2018–2026
- [x] Lint pass to the repo's ruff rules (`zip(strict=True)`, invalid escapes)
- [x] Independent logic review: no high-severity issues; 6 medium/low fixed, each with a test
- [x] Lot sizes for 2018–mid-2024 were estimated ±3%; now exact from open interest
- [x] Condor: non-simultaneous end-of-day marks could make a spread cost more than its width; capped
- [x] Future-pandas breakage: `inplace` drops; unsorted date joins under the VRP z-score and GARCH t-stats
- [x] Store writes made atomic
- [x] Webapp lint — whole repo ruff-clean
- [x] Lot-size calculation sped up 100×
- [x] Scheduled refresh never ran (path with spaces, battery, closable window) → windowless `pythonw` + `--log`
- [x] Prices stopped at yesterday even after the close → today's bar included from 16:00
- [x] Condor simulator 100× faster on repeated runs, identical results
- [x] **Weekend NSE sessions were never downloaded** → every weekend since 2015 probed (1,232 weekend days), **11 real sessions recovered** (Budget
  days incl. Sunday 1-Feb-2026, Muhurat sessions, 2024 special live sessions)
- [ ] "Something else" bug you mentioned (**waiting for your description**)

**Found while writing the docs (2026-10-24), not fixed yet** — each needs its own change:
- [x] `NSECalendar.from_nse()` never loaded special sessions → now the 11 verified weekend sessions plus NSE's
  `*`-marked Muhurat holidays (2026-11-08 found live) ([PA-15](PA_15-weekend-nse-sessions.md))
- [x] Web app hard-coded lot sizes (NIFTY 75, BANKNIFTY 35; current 65 / 30) and showed the market open on holidays →
  live lots from Dhan's scrip master, market status from the NSE calendar ([PA-02](PA_02-webapp.md))
- [x] Option backtester's NSE adapter set bid = ask = close, so slippage did nothing → modelled bid/ask from the
  cost model ([PA-05](PA_05-garch-volatility-and-vrp-condor.md))
- [x] Azure: `TRADINGAGENTS_OPENAI_REASONING_EFFORT` was ignored → now forwarded (dropped for non-reasoning
  deployments) ([the Azure reasoning-effort fix](architecture/04-llm-providers-and-configuration.md)). **Your `.env` says `low`: it now takes effect**
- [x] News Analyst prompt now names `get_india_fii_dii_flows`; `ALPHA_VANTAGE_API_KEY` added to `.env.example`;
  the 8 unmarked test files marked `unit` (86 more tests in `-m unit`) ([the small-fixes change](development/testing-and-lint.md))

## Market Map 2021–26 (requested 2026-10-24)
<!-- progress:phase -->
`█████████████████████████` 100% (7/7)
<!-- /progress:phase -->
- [x] Page in the project: `python scripts/market_map.py` → `reports/market_map/india-market-map.html` (open in a
  browser; gitignored because it embeds NSE data). Timeline, impact map, event → impact ledger, market network
- [x] Researched events with sources in `docs/data/market_events_2021_2026.json`: 54 regulatory changes + 53 market
  events (99 entries: 8 market reactions merged into their RBI / Budget rows), plus
  data-detected big days and lot changes
- [x] Every impact measured from NSE files; news figures cross-checked against NSE closes (19/22 exact; 1 date fixed,
  1 intraday figure removed)
- [x] Options activity measured by **value traded**, not contract count (lot-size changes distort counts)
- [x] Findings: elections move NIFTY most (median 2.7% on the day), geopolitics 2.1%, tax and margin rules ~0.2%
  (typical day 0.5%); when BANKNIFTY weeklies ended (Nov-2024) NIFTY options value +33–43%, BANKNIFTY −52–70%
- [x] Rebuilt with the recovered weekend sessions (Sunday 1-Feb-2026 Budget measured on its own session: −1.96%)
- [x] Rebuilt every weekday by the 19:30 job

## Data foundation for a prediction model (requested 2026-10-27)
<!-- progress:phase -->
`██████░░░░░░░░░░░░░░░░░░░` 25% (2/8)
<!-- /progress:phase -->
One step per pull request; each stops for your approval. Details: [PA-31](PA_31-research-splits-and-locked-loader.md).
- [x] Missing weekday files checked against NSE's holiday lists: **FAIL**, 10 NSE archive holes (fo 2021-03-30;
  indices 9 days in 2015–16), documented as unrecoverable
- [x] Step 1: frozen splits (2025+ locked, labelled contaminated; forward holdout from 2026-10-27), locked research
  loader, point-in-time audit (**FAIL in `prices`**: 29 Yahoo bars on the 2026-01-15 holiday), enforcement tests
- [ ] Step 2: F&O 2010–2014, all underlyings (count and size reported first; calendar from NSE's yearly circulars)
- [ ] Step 3: participant, index / VIX history, macro (with release times), events table
- [ ] Step 4: Dhan intraday spot and futures (**needs your renewed Dhan token and Data API status**)
- [ ] Step 5: forward option-chain capture, several times a day (forward-only)
- [ ] Step 6: cost table and measured spread table (**needs your contract note**)
- [ ] Step 7: data catalog and quality report with every PASS / FAIL

**Backlog (optional, after steps 1–3):** mto and participant files 2015-07 to 2017 (never downloaded; the backward
holdout does not use them). **Decided 2026-10-27:** `prices` holiday bars fixed ([PA-32](PA_32-prices-holiday-bars.md));
2021-03-30 stays a hole (no partial rebuild; recorded in the [data catalog](data_catalog.md)).

---

## Where this leaves us (2026-10-24)
**No trading signal has passed its tests.** That is the system doing its job: each one looked good somewhere and fell
apart out of sample, on unseen years, or after real costs.

| Tested | Verdict | Key numbers |
|---|---|---|
| GARCH volatility forecasts | ✅ **in use** (risk input) | beat historical vol on 31/31 symbols out of sample |
| Regime model (HMM) | ✅ **in use** (risk input) | next-month vol calm 11.5% vs choppy 15.1%, p=0.026; not a direction signal |
| 50/200 MA trend | ❌ rejected | beats random timing only 6% |
| VRP iron condor (NIFTY, BANKNIFTY) | ❌ rejected | only 15–19 trades in 5 yrs |
| VRP iron condor, 4 books, pooled (re-test) | ❌ **rejected by holdout** | 2021–26 strong; 2015–21: −5.6%/trade, beats random 60% |
| LightGBM "will it rise" (price; + NSE OI/PCR/flow) | ❌ rejected | same-day AUC 0.505 / 0.502 |
| LightGBM "will it beat the other 28" (+ buffer re-test) | ❌ rejected | AUC 0.507 / 0.510; −1.2% / −1.0% a year after costs |
| LightGBM "how big will the move be" | ❌ no skill | AUC 0.503 — but **GARCH alone ranks it at 0.573** ✅ |
| Condors on the 5 GARCH-quietest stocks | ❌ rejected | Sharpe −0.44 |
| Chronos-Bolt pretrained model | ❌ not kept | QLIKE 0.382 vs GARCH 0.336 |
| Results-day iron butterfly (IV crush) | ❌ rejected | 984 trades, −6.5%/trade; IV crush real, friction larger |
| Results-day fly, only overpriced events (re-test) | ❌ rejected | 745 trades, −4.7%/trade; break-even needs ~½ the measured spread |

Public end-of-day data has not produced a tradable edge in these 29 large, heavily-watched stocks. Costs decide most
verdicts — and they are now measured (real spreads ≈ 0.85× the model), not guessed.

## Shipped — what you can use now
- **Agents' quant report** (section VI of every analysis of the 29 stocks, NIFTY, BANKNIFTY): regime, GARCH volatility,
  **expected move**, implied vol vs forecast, and every test's verdict, worded so nothing reads as validated.
- **For your Dhan trading:** expected move for stop distance and strike width; measured option spreads (which stocks
  are too expensive for multi-leg trades); `sizing.py` once a signal has a measured edge.
- **Market Map** (`reports/market_map/india-market-map.html`): what each law change and event did to the market.
- **Trade journal** (`scripts/trade_journal.py`): what works in your own trades, by holding period.
- **Web app in eight tabs** (`python -m uvicorn webapp.server:app --port 8000`): **Plan** (morning plan + live call
  sized from your risk limit), Today, Risk & Volatility, Options (with measured spreads), AI Analysis, Market Map,
  Research, My Trades ([PA-02](PA_02-webapp.md), [PA-22](PA_22-morning-plan.md)).
- **AI strategist in the Plan tab** ([PA-23](PA_23-ai-strategist-and-nse-option-chain.md)): one defined-risk options strategy
  (or none) for the picked instrument, priced per lot at the live bid / ask, levels on the chart; NSE option chain.
  The risk-limit card was removed: figures are per lot and you choose how many ([PA-22](PA_22-morning-plan.md)).
- **Morning plan** weekdays 08:30 (task "TradingAgents morning plan"): NIFTY + BANKNIFTY data and AI view.
- **Daily refresh** weekdays 19:30. Log: `~/.tradingagents/cache/quant/daily_update.log`; status:
  `~/.tradingagents/cache/quant/daily_status.json`. Remove: `schtasks /Delete /TN "TradingAgents quant daily update" /F`.

---

## Start here
### State
- **Git:** PRs #1–#28 merged into `main`; open: `quant/phase-9-result` (replay results, check v2). Keep `main`
  checked out — the 19:30 job runs whatever is checked out.
  New work: `git checkout main`, `git pull`, `git checkout -b quant/<next-thing>`.
- **Data:** NSE store complete 2018-01-01 → 2026-10-23 (+ 2015–17 F&O and index files) in
  `~/.tradingagents/cache/quant/store/`; option quotes from 2026-10-23 in `.../quant/raw/option_quotes/`.
- **Tests:** unit suite green (~1,370); whole repo ruff-clean.
- **Next scheduled run:** Mon 2026-10-26 19:30 (adds 26-Oct, starts the VRP observation ledger, second quotes snapshot).

### Waiting on you
1. **Your Dhan tradebook** (Excel/CSV, last 6–12 months) in `reports/journal/` → I run the journal with you (Phase 5).
2. **One Dhan contract note** → cost model checked within ₹1 (closes Phase 1).
3. **3–5 real option fills** (screen price vs your fill) → compared with the measured spreads.
4. **"Something else" bug** — ticked on 23-Oct but never described.

## Log
- 2026-10-26 — Plan chart (PA-29): cleaner and larger (only the last price, target and stop keep axis labels; zones are shaded bands). Layer toggles; automatic day levels, swings and EMA crossovers; horizontal / trend line tools; Today / 2D / 5D / All zoom; O/H/L/C readout.
- 2026-10-26 — Backend latency (PA-28): requests now read memory. A background refresh keeps the data in use fresh, and identical requests share one fetch. Measured p99 1,277 → 139 ms and p95 737 → 95 ms. A plan on a stopped feed or saved prices is blocked. Sub-second prices still need the Dhan feed (your decision).
- 2026-10-26 — Docs: 16 small change records folded into the records they belong to; the remaining 27 renumbered PA-01 to PA-27 (the index has an old → new table).
- 2026-10-26 — Risk / Options costs / Research tabs now say which NSE close their end-of-day data is from and when the next 7:30 PM update is due; a missed nightly run is flagged.
- 2026-10-26 — Prices: NSE's free chain is 30-60 s old and updates every ~45 s (measured); Pulse's own extra delay cut to ~25 s, and every price now shows its age. Real time needs the Dhan token.
- 2026-10-26 — Leg orders shown by their job in Dhan: Super order with target / stop only on single options and the SELL leg of credit spreads; protection legs show none; other spread legs show reference prices.
- 2026-10-26 — Plan tab: Pulse trade ranking — concrete trades with strike, entry, target and stop per leg, ranked best first by the evidence score; AI iron butterflies no longer refused.
- 2026-10-26 — AI strategist: Pulse evidence score (0-100, Strong / Moderate / Weak) on every suggestion; debit spreads no longer refused by mistake; one retry when the AI contradicts itself; every suggestion auto-recorded and settled, with results by score.
- 2026-10-26 — Trade Record tab: take the AI strategist's trade as a dummy 1-lot trade; live P&L, target / stop flags (you close it), history with net P&L and win rate.
- 2026-10-26 — Web app: when Yahoo or the internet is unreachable, charts and the live call use the last saved prices (labelled) instead of failing with 502.
- 2026-10-25 — AI trade shown like a Dhan order: per-leg target / stop-loss premiums and P&L per lot, a ticket per leg (premium chart, depth, how to place it), marked on the chain and the chart.
- 2026-10-25 — Plan tab: the risk-limit card (capital, max loss %, money for this trade) removed at the user's request; today's call and the AI strategist show per-lot figures.
- 2026-10-24 — Plan tab: AI options strategist (structure checked, priced and sized by the code; capital never sent to the LLM) and an NSE option chain like the trading apps'.
- 2026-10-24 — Morning plan: 8:30 AM job (data + AI view for NIFTY and BANKNIFTY) and a Plan tab with the session clock and the live call sized from your risk limit.
- 2026-10-24 — Web app rebuilt into seven plain-English tabs (risk, measured spreads, research verdicts, market map, trade journal added).
- 2026-10-24 — Phase 9 replay done: 10 analyses, 0 invented quant numbers, 0 validation claims (on reading every flag); check v2 added.
- 2026-10-24 — Docs restructured: index (docs/README.md), plans/ data/ architecture/ features/ development/ guides/ archive/, one PA record per change (PA_01–PA_26), link checker (`scripts/check_doc_links.py`).
- 2026-10-24 — Tracker cleaned: dropped / not-applicable items moved to "on hold" notes; Phase 9 replay (10 dates) started; quant report wording fixed.
- 2026-10-24 — Phase 5 started from your side: trade-journal analyser for your Dhan tradebook (by holding period: intraday / week / month / longer).
- 2026-10-24 — Real option spreads measured from NSE's closing bid/ask (0.85× the slippage model); captured nightly from now on.
- 2026-10-24 — Results fly cost diagnosis (break-even at ½ the assumed slippage) and overpriced-only re-test: rejected (−4.7%/trade).
- 2026-10-24 — Event-window test: results-day iron butterfly rejected (984 trades, −6.5%/trade); IV crush real but smaller than trading friction.
- 2026-10-24 — Phase 7: Chronos-Bolt volatility forecasts tested against GARCH on 31 symbols → not kept (QLIKE 0.382 vs 0.336).
- 2026-10-24 — Market Map 2021–26 built; its news cross-check exposed the weekend-session bug → fixed, 11 sessions recovered, store rebuilt.
- 2026-10-23 — Plan written; Phase 0 gates and trial log; NSE downloader started; Phase 1 code done.
- 2026-10-23 — Phase 2 harness: random signal rejected, planted edge found; MA trend rejected.
- 2026-10-23 — Phase 3 part 1: GARCH beats historical vol on 31/31 symbols; ATM IV tracks India VIX.
- 2026-10-23 — Bug fixes on two fix branches + data repairs; Phase 4 regime model built, first real run.
- 2026-10-23 — Phase 9 agent tool built.
- 2026-10-23 — Phase 6 pipeline built; caught 3 problems before trusting results (label artifact, `month` feature, merged trades). Price-only model: no edge.
- 2026-10-23 — Main NSE download finished; independent logic review (6 medium/low issues fixed); store built.
- 2026-10-23 — Lot sizes made exact; condor spread cap; atomic store writes; future-pandas fixes.
- 2026-10-23 — Regimes re-run on NSE VIX: Phase 4 passes as a risk input.
- 2026-10-23 — VRP condor rejected on NIFTY and BANKNIFTY (15–19 trades); LightGBM with NSE features: no edge; relative strength rejected.
- 2026-10-23 (evening) — Scheduled refresh fixed and verified (PR #12). Pooled 4-book VRP condor re-test: 84 trades, beats random 100%.
- 2026-10-23 (late) — Proof plan approved. Quiet-stock condor rejected. VRP spec frozen; paper ledger built. Stage 2 stress tests passed. LightGBM / MA trend dropped (your call).
- 2026-10-23 (night) — Backward holdout on 2015–21: the VRP condor failed → rejected; paper trading kept as observation only. Move size predictable by GARCH (AUC 0.573), not LightGBM.

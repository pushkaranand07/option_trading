# Quant Signal Layer — Progress Tracker

> Plan: [QUANT_SIGNAL_LAYER_PLAN.md](QUANT_SIGNAL_LAYER_PLAN.md).
> Bars are recalculated from the checkboxes below (and the live NSE download log) by
> `python scripts/update_progress.py`. Tick a box (`[x]`), run the script, and every bar updates.

<!-- progress:overall -->
**Overall:** `██████████████████░░░░░░░` 72% (56/78 tasks)
<!-- /progress:overall -->

<!-- progress:download -->
**NSE history download:** `█████████████████████████` 100% (9,196/9,196 files)
<!-- /progress:download -->

_Last updated: 2026-10-23 17:32_

| Branch | Phase | Status | In GitHub `main`? |
|---|---|---|---|
| `quant/phase-0-1-foundation` | 0–1 Foundation | data complete and verified; only the contract-note check left | merged (PR #2) |
| `quant/phase-2-harness` | 2 Harness | **exit gate passed** | merged (PR #3) |
| `quant/phase-3-garch` | 3 Volatility / VRP condor | part 1 passed; condor test **running** | merged (PR #4) |
| `quant/phase-4-regime` | 4 Regime (HMM) | **exit gate passed** (as a risk input) | merged (PR #7) |
| `quant/phase-6-lgbm` | 6 LightGBM | price-only: no edge; store-feature run next | not yet |
| `quant/phase-9-agent-tool` | 9 Agent integration + all later fixes | **current working branch**; full suite 1536 passed, ruff-clean | not yet |
| `fix/windows-test-portability` | Bug fix | done | merged (PR #5) |
| `fix/option-backtester-exits` | Bug fix | done | merged (PR #6) |

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
`██████████████████████░░░` 89% (8/9)
<!-- /progress:phase -->
- [x] Resumable, throttled NSE downloader (F&O bhavcopy, participant OI, MTO delivery)
- [x] Parsers + Parquet store with `known_from` on every row
- [x] Yahoo prices through the data layer, stopping at yesterday
- [x] Cost model at 2026 rates with sources (Dhan + statutory)
- [x] Parser fixes: untitled / full-month participant files, lot sizes per day
- [x] Full 2018–2026 download finished (6,503 files; 379 missing, mostly holidays — to confirm in the quality report)
- [x] Store built for every year: participant and delivery on all 2,172 F&O days, 31/31 symbols ≥98%, IV on 65,984 symbol-days; lot sizes exact
- [x] Data-quality report: 0 missing sessions in any dataset; 6,516 index bars from NSE, 58 stock gaps filled from NSE; all 14 stock jumps >20% verified as real events (COVID 23-Mar-2020, Adani, BHEL — checked against NSE prices)
- [ ] Cost model matched to a real Dhan contract note within ₹1 (needs your numbers)

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
`██████████████████░░░░░░░` 71% (5/7)
<!-- /progress:phase -->
- [x] GARCH / GJR / EGARCH forecasts, expanding window, weekly refit, causal (tested)
- [x] Exit check 1: GARCH beats historical vol out of sample (31/31 symbols)
- [x] ATM and 30-day IV from option closes (tracks India VIX)
- [x] End-of-day iron condor simulator (your rules: monthly, 50% TP, 2× SL)
- [x] VRP signal + walk-forward with "enter always" and "random days" baselines
- [ ] VRP condor run on NIFTY and BANKNIFTY with real data
- [ ] Exit check 2: VRP condor passes the gates after costs (or a written reason why not)

## Phase 4 — Regime detection (HMM)
<!-- progress:phase -->
`█████████████████████████` 100% (7/7)
<!-- /progress:phase -->
- [x] Features: returns, realised vol, India VIX, breadth
- [x] 3-state Gaussian HMM, filtered probabilities only (no look-ahead; tested against hmmlearn's smoothed output)
- [x] Stable labels (p > 0.7 for 2 days) — 29 changes in 5.4 years
- [x] Regime gate wired into Phase 2/3 evaluations
- [x] First real run: calm 68% / choppy 30% / stress 2.4% of days (2021–2026); next-21-day vol 11.6% / 15.3% / 14.3%
- [x] Re-run on NSE's VIX: calm 64% / choppy 34% / stress 1.4%; today calm (0.99)
- [x] Exit gate **passed as a risk input**: next-21-day vol calm 11.5% vs choppy 15.1% (p=0.026, non-overlapping windows); returns by regime not significant (p=0.14) → not a direction signal

## Phase 5 — Your own idea as exact rules
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/4)
<!-- /progress:phase -->
- [ ] Idea written in the specification template
- [ ] Coded as a causal signal, leak check passes
- [ ] Walk-forward vs baselines, ≤ 30 combinations
- [ ] Keep / drop decision written down

## Phase 6 — LightGBM model
<!-- progress:phase -->
`███████████████████░░░░░░` 75% (6/8)
<!-- /progress:phase -->
- [x] Triple-barrier labels on closes (label = exit return > 0; the "upper first" label gave AUC 0.55 on pure noise)
- [x] Price, volume, structure and market-context features; automatic leak check (0 mismatches)
- [x] Derivatives and flow features coded and timing-tested (OI change, PCR, delivery %, FII/Client futures positioning, stock IV)
- [x] Purged, embargoed walk-forward; fit / early-stop / calibrate on separate slices
- [x] Calibration (Platt), reliability table, same-day AUC (stock picking vs market timing)
- [x] Price-only run: **no edge** — same-day AUC 0.505, Sharpe 0.97 vs buy-and-hold 1.22, rejected (stability 0.34)
- [ ] Re-run with derivatives/flow features
- [ ] Exit gate: OOS AUC ≥ 0.55, calibrated, passes gates after costs

## Phase 7 — Pretrained time-series models (optional)
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/2)
<!-- /progress:phase -->
- [ ] Chronos / TimesFM features tested
- [ ] Kept only if they improve OOS results

## Phase 8 — Ensemble, meta-labelling, sizing
<!-- progress:phase -->
`██████░░░░░░░░░░░░░░░░░░░` 25% (1/4)
<!-- /progress:phase -->
- [ ] Meta-label model
- [ ] Ensemble of surviving signals
- [x] ¼-Kelly sizing, capped at 1% risk, your capital as input; lot-rounded quantity (`sizing.py`)
- [ ] Exit gate: beats best single component on Sharpe and drawdown

## Phase 9 — Agent integration
<!-- progress:phase -->
`███████████████████░░░░░░` 75% (3/4)
<!-- /progress:phase -->
- [x] `get_quant_signal_report` tool (regime, vol forecasts, IV vs forecast, gate verdicts; only data known before the date)
- [x] Market analyst told to quote it; portfolio manager discounts any unvalidated quant signal
- [x] "VI. Quant Context" section in the Markdown and HTML reports (skipped outside the universe; never breaks a report)
- [ ] Exit gate: 50-date replay, no invented numbers (needs LLM runs — your call on cost)

## Phase 10 — Paper trading
<!-- progress:phase -->
`██████░░░░░░░░░░░░░░░░░░░` 25% (1/4)
<!-- /progress:phase -->
- [x] Daily after-close refresh job (`quant_daily_update.py`: download → store → vol → regime → tracker)
- [ ] Record intended trades each day (needs an approved signal)
- [ ] ≥ 3 months and ≥ 50 paper trades
- [ ] Hit rate inside the backtest band; slippage ≤ 1.5× model

## Phase 11 — Small live capital (you trade on Dhan)
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/3)
<!-- /progress:phase -->
- [ ] Kill switches and drift monitor
- [ ] Monthly retrain with the same gates
- [ ] Scale-up rules followed

## Bug fixes (requested 2026-10-23)
<!-- progress:phase -->
`███████████████████████░░` 94% (15/16)
<!-- /progress:phase -->
- [x] 5 old Windows test failures (ChatGPT sign-in file mode, CLI upgrade command, yfinance cache path)
- [x] option_backtester: early exits could land after the planned exit
- [x] option_backtester: commission never deducted from realized P&L
- [x] NSE adapter: expiry valued at last close / untraded wings dropped → now NSE settlement at intrinsic
- [x] Index data gaps: NSE official NIFTY / BANKNIFTY / India VIX bars replace Yahoo
- [x] Stock data gaps (e.g. TCS 22-Oct): filled from NSE equity bhavcopy on Yahoo's adjusted basis
- [x] Index files downloaded for 2018–2026 (2,173 files)
- [x] Lint pass to the repo's ruff rules: `zip(strict=True)` everywhere lengths must match, invalid `\L`/`\T` escapes in a test docstring (full suite 1518 passed)
- [x] Independent logic review: no high-severity issues (no look-ahead, no split errors); 6 medium/low fixed, each with a test:
  regime gate passed single-regime periods · ML daily returns under-charged back-to-back trades · condor random baseline fired too rarely · condor trades vs daily series windows · expiry with no index close · ledger cost on resizes/flips
- [x] Lot sizes for 2018–mid-2024 were estimated ±3% (NIFTY 72–77); now exact from open interest (99.6% match with NSE's stated lots)
- [x] Condor: non-simultaneous end-of-day marks could make a spread cost more than its width (a trade lost 132% of max risk); capped
- [x] Future-pandas breakage: `inplace` drops in the options engine; unsorted date joins under the VRP z-score and GARCH t-stats
- [x] Store writes made atomic (a second job or a reader never sees half a file; failures raise)
- [x] Webapp lint (ambiguous name, duplicate branch) — whole repo now ruff-clean; full suite 1536 passed
- [x] Lot-size calculation sped up 100× (it would have taken ~50 min to rebuild 2018–2024)
- [ ] "Something else" bug you mentioned (waiting for your description)

---

## Runs after the download
1. Download NSE index files — **done** (2,173 files)
2. Build the store, index data, prices, quality report — **done**
3. Re-run regimes on NSE's VIX — **done**
4. VRP iron condor test on NIFTY / BANKNIFTY — **running** (first NIFTY run: 19 OOS trades, OOS Sharpe 0.04 vs IS 1.29, beats random 64% → heading for *rejected*; re-run with corrected gates in progress)
5. LightGBM with store features (`quant_ml.py --position-value 100000 --with-store`) — next

## Open items needing you
- Numbers from one Dhan contract note (segment, quantity, buy/sell price, each charge line)
- Your own trading idea for Phase 5 (use the template in the plan, section 6)

## Log
- 2026-10-23 — Phases 0, 2 done; Phase 1 code done (download running); Phase 3 part 1 passed, part 2 coded.
- 2026-10-23 — Bug fixes on two fix branches + data repairs; Phase 4 regime model built, first real run (calm today).
- 2026-10-23 — Main NSE download finished; logic-review fixes merged into the branch; store build started.
- 2026-10-23 — Local `main` synced with GitHub (PRs #2–#7 merged). Phase 9 agent tool built.
- 2026-10-23 — All NSE data downloaded, built and verified (0 missing sessions; exact lot sizes). Regimes re-run on NSE VIX: Phase 4 passes as a risk input. Condor test started; fixed its gates (returns on capital, parameter stability).
- 2026-10-23 — Phase 6 pipeline built. Caught 3 problems before trusting results: barrier-width label artifact, `month` feature fitting noise, merged back-to-back trades inflating returns (+6%/trade → +0.47%). Price-only model: no edge.

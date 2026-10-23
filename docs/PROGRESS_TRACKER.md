# Quant Signal Layer — Progress Tracker

> Plan: [QUANT_SIGNAL_LAYER_PLAN.md](QUANT_SIGNAL_LAYER_PLAN.md).
> Bars are recalculated from the checkboxes below (and the live NSE download log) by
> `python scripts/update_progress.py`. Tick a box (`[x]`), run the script, and every bar updates.
>
> **Picking this up? Read [Start here tomorrow](#start-here-tomorrow) first.**

<!-- progress:overall -->
**Overall:** `███████████████████░░░░░░` 75% (61/81 tasks)
<!-- /progress:overall -->

<!-- progress:download -->
**NSE history download:** `█████████████████████████` 100% (9,196/9,196 files)
<!-- /progress:download -->

_Last updated: 2026-10-23 21:01_

| Branch | Phase | Status | In GitHub `main`? |
|---|---|---|---|
| `quant/phase-0-1-foundation` | 0–1 Foundation | data complete and verified; only the contract-note check left | merged (PR #2) |
| `quant/phase-2-harness` | 2 Harness | **exit gate passed** | merged (PR #3) |
| `quant/phase-3-garch` | 3 Volatility / VRP condor | GARCH passed; VRP condor **rejected** (too few trades to prove) | merged (PR #4) |
| `quant/phase-4-regime` | 4 Regime (HMM) | **exit gate passed** (as a risk input) | merged (PR #7) |
| `quant/phase-6-lgbm` | 6 LightGBM | no edge with price or with NSE derivatives/flow features | merged (via PR #8) |
| `quant/phase-9-agent-tool` | 9 Agent integration + all later fixes | full suite green, ruff-clean | merged (PR #8) |
| `quant/phase-6b-relative` | 6 relative-strength model | rejected on real data | merged (PR #9) |
| `quant/phase-10-ship` | Ship what's validated | expected move in the report, daily refresh scheduled | merged (PR #10) |
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
- [x] Full 2018–2026 download finished (6,503 files; the 379 "missing" are market holidays — confirmed: 0 missing sessions)
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
`█████████████████████████` 100% (7/7)
<!-- /progress:phase -->
- [x] GARCH / GJR / EGARCH forecasts, expanding window, weekly refit, causal (tested)
- [x] Exit check 1: GARCH beats historical vol out of sample (31/31 symbols)
- [x] ATM and 30-day IV from option closes (tracks India VIX)
- [x] End-of-day iron condor simulator (your rules: monthly, 50% TP, 2× SL)
- [x] VRP signal + walk-forward with "enter always" and "random days" baselines
- [x] VRP condor run on NIFTY and BANKNIFTY with real data (2021-04 → 2026-05 out of sample, 18 settings, costs + slippage)
- [x] Exit check 2: **rejected on both** — NIFTY 19 trades, OOS Sharpe 0.04 (IS 1.29), beats random 64%; BANKNIFTY 15 trades, +7.45%/trade on risk, OOS Sharpe 0.30, beats random 94%. **Why:** a monthly condor allows ≤12 trades/year and the VRP filter keeps ~3–4, so 5 years give 15–19 trades — the 100-trade gate cannot be met. BANKNIFTY hint: trades in *choppy* regimes averaged +49% of risk, calm −1.8% (too few to trust)

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
`████████████████████░░░░░` 82% (9/11)
<!-- /progress:phase -->
- [x] Triple-barrier labels on closes (label = exit return > 0; the "upper first" label gave AUC 0.55 on pure noise)
- [x] Price, volume, structure and market-context features; automatic leak check (0 mismatches)
- [x] Derivatives and flow features coded and timing-tested (OI change, PCR, delivery %, FII/Client futures positioning, stock IV)
- [x] Purged, embargoed walk-forward; fit / early-stop / calibrate on separate slices
- [x] Calibration (Platt), reliability table, same-day AUC (stock picking vs market timing)
- [x] Price-only run: **no edge** — same-day AUC 0.505, Sharpe 0.97 vs buy-and-hold 1.22, rejected (stability 0.34)
- [x] Re-run with derivatives/flow features (OI, PCR, delivery %, FII/Client positioning, stock IV; leak check 0): **no edge** — same-day AUC 0.502, top features all market-wide, beats random timing 40%, Sharpe 0.68 vs buy-and-hold 1.22
- [ ] Exit gate: OOS AUC ≥ 0.55, calibrated, passes gates after costs — **not met** (AUC 0.506, DSR 0.935, OOS/IS 0.44)
- [x] Second model built and verified: **relative strength** (beat the 29-stock average? top-5 book vs equal weight, hedged, after costs); tests: noise rejected, persistent planted edge found (a one-day edge was found but lost to costs)
- [x] Relative-strength model on real data: **no edge** — same-day AUC 0.507, excess −1.2%/yr after costs and hedge (Sharpe −0.09), top-3/top-8 unstable, DSR 0.42 → rejected. ("Beats random picks 99%" reflects lower turnover, not skill: random picks pay full costs every rebalance)
- [ ] Refinement: turnover-matched random baseline for the relative-strength test (so "beats random" measures skill only)

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
- [x] `get_quant_signal_report` tool (regime, vol forecasts, **expected move**, IV vs forecast, gate verdicts; only data known before the date)
- [x] Market analyst told to quote it; portfolio manager discounts any unvalidated quant signal
- [x] "VI. Quant Context" section in the Markdown and HTML reports (skipped outside the universe; never breaks a report)
- [ ] Exit gate: 50-date replay, no invented numbers (needs LLM runs — your call on cost)

## Phase 10 — Paper trading
<!-- progress:phase -->
`██████░░░░░░░░░░░░░░░░░░░` 25% (1/4)
<!-- /progress:phase -->
- [x] Daily after-close refresh job (`quant_daily_update.py`: download → store → vol → regime → tracker); first end-to-end run OK in 6.6 min; **scheduled weekdays 19:30** (Windows Task Scheduler, `quant_daily_update.cmd`)
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

## Where this leaves us (end of 2026-10-23)
**No trading signal has passed the gates yet.** That is the system doing its job: every one of these looked good
somewhere in-sample and fell apart out of sample or after costs.

| Tested | Verdict | Key numbers |
|---|---|---|
| GARCH volatility forecasts | ✅ **validated** (risk input) | beat historical vol on 31/31 symbols out of sample |
| Regime model (HMM) | ✅ **validated** (risk input) | next-month vol calm 11.5% vs choppy 15.1%, p=0.026; not a direction signal |
| 50/200 MA trend | ❌ rejected | beats random timing only 6% |
| VRP iron condor (NIFTY, BANKNIFTY) | ❌ rejected | only 15–19 trades in 5 yrs; BANKNIFTY closest (beats random 94%) |
| LightGBM "will it rise" — price | ❌ rejected | same-day AUC 0.505; Sharpe 0.97 vs buy-and-hold 1.22 |
| LightGBM "will it rise" — + NSE OI/PCR/delivery/FII/IV | ❌ rejected | same-day AUC 0.502; Sharpe 0.68 |
| LightGBM "will it beat the other 28" | ❌ rejected | same-day AUC 0.507; excess −1.2%/yr after costs |

Public end-of-day data has not produced a tradable edge in these 29 large, heavily-watched stocks, consistent with
how efficiently they are priced. Costs matter a lot: a delivery round trip is ~0.33%, so a strategy rotating 5 stocks
every 10 sessions pays ~16% a year before it earns anything.

## Shipped — what you can use now
- **Agents' quant report** (every analysis of the 29 stocks, NIFTY, BANKNIFTY; section VI of each saved report):
  regime, GARCH volatility forecasts, **expected move** (e.g. RELIANCE ±5.0% / ±Rs 60 over 10 sessions), implied vol
  vs forecast, and every signal's verdict. The portfolio manager is told not to base a direction on unvalidated signals.
- **For your Dhan trading:** expected move for stop distance and option strike width; `sizing.py` (¼-Kelly, max 1% of
  capital at risk) once a signal has a measured edge.
- **Daily refresh** weekdays 19:30 keeps it all current. Log: `~/.tradingagents/cache/quant/daily_update.log`;
  status: `~/.tradingagents/cache/quant/daily_status.json`. Remove: `schtasks /Delete /TN "TradingAgents quant daily update" /F`.

---

## Start here tomorrow
### State
- **Git:** everything is merged into GitHub `main` (PRs #1–#10). Start new work on a new branch from `main`:
  `git checkout main`, `git pull`, `git checkout -b quant/<next-thing>`.
- **Data:** NSE store complete 2018-01-01 to 2026-10-22 (F&O, option chain, participant OI, delivery, index closes,
  prices, IV, exact lot sizes) in `~/.tradingagents/cache/quant/store/`. Tonight's 19:30 refresh adds 23-Oct.
- **Tests:** full suite 1,544 passed on Windows; whole repo ruff-clean.
- **First check tomorrow:** did the 19:30 refresh run? `daily_status.json` should show `"ok": true` with a finish
  time on the evening of 23-Oct. If not (PC off or logged out), run `python scripts/quant_daily_update.py` once.

### Decisions waiting on you (pick any)
1. **Your own trading idea (Phase 5)**: the most promising next step. Describe a pattern you actually trade (entry,
   exit, stop, which data you look at); I code it exactly and run it through the same gates. Template: plan section 6.
2. **Condors, more trades?** Pool NIFTY+BANKNIFTY, add the 29 stocks' monthly options, enter weekly into monthly
   expiries, or use weekly expiries. Needed because 15–19 trades cannot prove anything.
3. **Widen the universe:** smaller, less-watched F&O stocks (less efficient), or event windows (results days, expiry
   weeks). Each new test raises the bar via the deflated Sharpe.
4. **Phase 9 replay:** 50 historical dates through the full agent pipeline to check no invented numbers (costs LLM
   money): run 50, 10, or skip.
5. **Dhan contract note:** one trade's charges, to confirm the cost model within Rs 1 (closes Phase 1).
6. **"Something else" bug:** ticked on 23-Oct but never described.

### Suggested order for tomorrow
1. Verify the overnight refresh (2 min).
2. You: describe your idea (decision 1) and/or send the contract note (decision 5).
3. Me: code and test your idea; meanwhile the small refinement (turnover-matched random baseline).

## Open items needing you
- Your trading idea (Phase 5)
- Condor decision (more trades, or leave rejected)
- Phase 9 replay decision (50 / 10 / skip)
- Dhan contract note numbers
- The "something else" bug description

## Log
- 2026-10-23 — Plan written; Phase 0 gates and trial log; NSE downloader started; Phase 1 code done.
- 2026-10-23 — Phase 2 harness: random signal rejected, planted edge found; MA trend rejected.
- 2026-10-23 — Phase 3 part 1: GARCH beats historical vol on 31/31 symbols; ATM IV tracks India VIX.
- 2026-10-23 — Bug fixes on two fix branches + data repairs; Phase 4 regime model built, first real run.
- 2026-10-23 — Local `main` synced with GitHub (PRs #2–#7 merged). Phase 9 agent tool built.
- 2026-10-23 — Phase 6 pipeline built. Caught 3 problems before trusting results: barrier-width label artifact, `month` feature fitting noise, merged back-to-back trades inflating returns (+6%/trade became +0.47%). Price-only model: no edge.
- 2026-10-23 — Main NSE download finished; independent logic review (6 medium/low issues fixed); store built.
- 2026-10-23 — Lot sizes made exact (GCD of open interest); condor spread cap; atomic store writes; future-pandas fixes.
- 2026-10-23 — All NSE data downloaded, built and verified (0 missing sessions). Regimes re-run on NSE VIX: Phase 4 passes as a risk input.
- 2026-10-23 — VRP condor rejected on NIFTY and BANKNIFTY: too few trades (15–19); BANKNIFTY closest (beats random 94%).
- 2026-10-23 — LightGBM with NSE derivatives/flow features: no edge (same-day AUC 0.502).
- 2026-10-23 — Relative-strength model rejected (same-day AUC 0.507, excess −1.2%/yr).
- 2026-10-23 — Shipped: expected move in the quant report; daily refresh verified and scheduled (19:30 weekdays). PRs #8–#10 merged; everything in `main`.

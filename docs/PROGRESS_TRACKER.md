# Quant Signal Layer — Progress Tracker

> Plan: [QUANT_SIGNAL_LAYER_PLAN.md](QUANT_SIGNAL_LAYER_PLAN.md).
> Bars are recalculated from the checkboxes below (and the live NSE download log) by
> `python scripts/update_progress.py`. Tick a box (`[x]`), run the script, and every bar updates.

<!-- progress:overall -->
**Overall:** `██████████░░░░░░░░░░░░░░░` 41% (26/64 tasks)
<!-- /progress:overall -->

<!-- progress:download -->
**NSE history download:** `███████░░░░░░░░░░░░░░░░░░` 29% (2,649/9,196 files)
<!-- /progress:download -->

_Last updated: 2026-10-23 13:35_

| Branch | Phase | Status |
|---|---|---|
| `quant/phase-0-1-foundation` | 0–1 Foundation | code done; waiting on full data build + contract-note check |
| `quant/phase-2-harness` | 2 Harness | **exit gate passed** |
| `quant/phase-3-garch` | 3 Volatility / VRP condor | part 1 passed; part 2 waiting on data |
| `fix/windows-test-portability` | Bug fix | done, full suite green on Windows (1423 passed) |
| `fix/option-backtester-exits` | Bug fix | done, 3 regression tests (fail before / pass after) |

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
`██████████████░░░░░░░░░░░` 56% (5/9)
<!-- /progress:phase -->
- [x] Resumable, throttled NSE downloader (F&O bhavcopy, participant OI, MTO delivery)
- [x] Parsers + Parquet store with `known_from` on every row
- [x] Yahoo prices through the data layer, stopping at yesterday
- [x] Cost model at 2026 rates with sources (Dhan + statutory)
- [x] Parser fixes: untitled / full-month participant files, lot sizes per day
- [ ] Full 2018–2026 download finished
- [ ] Store built for every year
- [ ] Data-quality report reviewed with you
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
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/5)
<!-- /progress:phase -->
- [ ] Features: returns, realised vol, India VIX, breadth
- [ ] 3-state Gaussian HMM, filtered probabilities only (no look-ahead)
- [ ] Stable labels (p > 0.7 for 2 days)
- [ ] Regime gate wired into Phase 2/3 evaluations
- [ ] Exit gate: causal, states differ out of sample, strategy results differ by state

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
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/5)
<!-- /progress:phase -->
- [ ] Triple-barrier labels
- [ ] Feature set (price, structure, derivatives, flows, regime, calendar)
- [ ] Purged, embargoed walk-forward
- [ ] Calibration (Brier, reliability curve)
- [ ] Exit gate: OOS AUC ≥ 0.55, calibrated, passes gates after costs

## Phase 7 — Pretrained time-series models (optional)
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/2)
<!-- /progress:phase -->
- [ ] Chronos / TimesFM features tested
- [ ] Kept only if they improve OOS results

## Phase 8 — Ensemble, meta-labelling, sizing
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/4)
<!-- /progress:phase -->
- [ ] Meta-label model
- [ ] Ensemble of surviving signals
- [ ] ¼-Kelly sizing with your position-size setting
- [ ] Exit gate: beats best single component on Sharpe and drawdown

## Phase 9 — Agent integration
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/4)
<!-- /progress:phase -->
- [ ] `get_quant_signal_report` tool
- [ ] Risk manager refuses non-significant signals
- [ ] Report in the HTML output
- [ ] Exit gate: 50-date replay, no invented numbers

## Phase 10 — Paper trading
<!-- progress:phase -->
`░░░░░░░░░░░░░░░░░░░░░░░░░` 0% (0/3)
<!-- /progress:phase -->
- [ ] Daily after-close run recording intended trades
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
`███████████████████░░░░░░` 75% (6/8)
<!-- /progress:phase -->
- [x] 5 old Windows test failures (ChatGPT sign-in file mode, CLI upgrade command, yfinance cache path)
- [x] option_backtester: early exits could land after the planned exit
- [x] option_backtester: commission never deducted from realized P&L
- [x] NSE adapter: expiry valued at last close / untraded wings dropped → now NSE settlement at intrinsic
- [x] Index data gaps: NSE official NIFTY / BANKNIFTY / India VIX bars replace Yahoo
- [x] Stock data gaps (e.g. TCS 22-Oct): filled from NSE equity bhavcopy on Yahoo's adjusted basis
- [ ] Index files downloaded for 2018–2026 (runs after the main download)
- [ ] "Something else" bug you mentioned (waiting for your description)

---

## Open items needing you
- Numbers from one Dhan contract note (segment, quantity, buy/sell price, each charge line)
- Your own trading idea for Phase 5 (use the template in the plan, section 6)

## Log
- 2026-10-23 — Phases 0, 2 done; Phase 1 code done (download running); Phase 3 part 1 passed, part 2 coded.

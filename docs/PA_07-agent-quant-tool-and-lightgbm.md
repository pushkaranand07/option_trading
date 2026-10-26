# PA-07 — Quant report tool for the agents (Phase 9), LightGBM pipeline (Phase 6), sizing (Phase 8) and a bug sweep

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | Phase 9: `tradingagents/analytics/quant_report.py`, `tradingagents/agents/tools.py`, `agents/analysts/market_analyst.py`, `agents/managers/portfolio_manager.py`, `tradingagents/reporting.py`. Phase 6: `tradingagents/analytics/ml/{labels,features,model,pipeline,derived}.py`, `scripts/quant_ml.py`. Phase 8: `tradingagents/analytics/sizing.py`. Phase 10 groundwork: `scripts/quant_daily_update.py`. Fixes: `gates.py`, `evaluate.py`, `condor.py`, `vrp.py`, `datastore.py`, `scripts/quant_build_store.py`, lint across quant code. Tests: `tests/test_quant_{ml,report,sizing,daily,gates,condor,evaluate,vrp,datastore}.py` |
| **Related** | [PA-04](PA_04-evaluation-harness-and-baselines.md) · [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [PA-06](PA_06-regime-detection-hmm.md) · [PA-08](PA_08-relative-strength-model.md) · [PA-09](PA_09-ship-expected-move-and-daily-refresh.md) · [PA-09](PA_09-ship-expected-move-and-daily-refresh.md) · [PA-21](PA_21-phase9-replay-and-report-wording.md) · [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md) · [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) · [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) · [architecture/16-quant-context-in-agents.md](architecture/16-quant-context-in-agents.md) |
| **Pull request** | #8 (branch `quant/phase-9-agent-tool`); 18 commits from `157233d` to `f60fa99`. No PR description |
| **Date** | 2026-10-23 |

---

## 1. Problem

- The LLM agents estimated volatility and regime themselves instead of using the measured numbers (plan Phase 9:
  "argue about evidence instead of guessing").
- The plan's Phase 6 needed a machine-learning test: can many weak signals together predict a stock's next
  1–2 weeks?
- Phase 8 needed position sizing from a measured edge.
- The quant code had lint findings, an independent logic review raised issues, and timing the condor run exposed
  two data/accounting bugs.

## 2. Root cause / findings

**Phase 6 — three problems caught before trusting any result** (commit `157233d`, tracker log):

1. **Label artifact:** "upper barrier hit first" depends on barrier width and gave AUC 0.55 on pure noise. The label
   became "exit return > 0".
2. **`month` feature:** ranked first on real data — noise. Raw calendar features removed.
3. **Merged trades:** a run-based ledger merged back-to-back trades, inflating returns (+6%/trade → +0.47%). Now one
   trade per entry, each paying a round trip.

**Independent logic review** (`fdacef1`, `088d6b6`) — no high-severity issues (no look-ahead, no split errors);
6 medium/low:

| Issue | Fix |
|---|---|
| Regime gate passed a test period that saw one (profitable) regime | "Switched off where it loses" now needs a regime actually switched off |
| ML daily series charged one round trip for an exit and re-entry on the same open; the ledger charged two | Series now charges both (`trading_returns()`) |
| VRP random-days baseline drew at the signal's rate over all sessions, incl. years where the z-score cannot exist (fired at ~0.6–0.7× the real rate) | Rate taken from the test windows |
| VRP out-of-sample daily series and trade stats described different windows | Daily series built from the OOS trades' own daily P&L |
| No index close on expiry day → settled at entry prices (outcome erased) | Settle on the last earlier close |
| Trade ledger costs on resizes / flips differed from the daily series | Charged once, split across the boundary |

**Found while timing the condor run** (`9e2fae6`):

- Pre-UDiFF lot sizes estimated from turnover wobbled by a few % (NIFTY 72–77, RELIANCE 988–1021 for true 75 / 1000).
  Now the GCD of near-expiry open interest, stepped to the multiple nearest the turnover estimate on lot-change days.
  Matches NSE's stated lot on 1,482 of 1,488 checked UDiFF symbol-days (the 6 misses are on lot-change days).
- Non-simultaneous end-of-day marks (untraded wing at settlement next to a traded short) could value a spread above
  its width; one trade lost 132% of max risk. Each spread's close cost is now capped at its width and flagged.

## 3. Decisions

- **Quant report uses only values dated before the analysis date**; says plainly that nothing is validated until a
  signal passes the gates; tickers outside the universe get no numbers.
- **Market analyst** must quote the report's regime and volatility figures and repeat its validation status: an
  unvalidated quant number "is context about risk, never a reason to buy or sell".
- **Portfolio manager** may use quant figures for size and risk, but a quant signal supports a direction only if
  listed under "Approved signals"; otherwise it is discounted. (The plan said the risk manager "must refuse"; the
  reason for putting the rule in the portfolio manager instead: not recorded.)
- **Report section "VI. Quant Context"** in the Markdown and HTML reports — the same text the agents saw; omitted
  outside the universe or when quant outputs cannot be read.
- **LightGBM design:** triple-barrier labels on closes, exit at next open (as a manual trader would); all features
  shifted one session; `leak_check` recomputes features on cut and scrambled data; purged folds; fit, early-stop and
  Platt-calibrate on separate purged slices; out-of-sample predictions only; per-fold threshold from the calibration
  slice; **same-day AUC** (ranking stocks against each other on the same day) separates stock picking from market
  timing.
- **NSE store features** (OI change, PCR, delivery %, FII/Client positioning, stock IV) are dated by the file's
  session and shifted, so session *t* sees *t−1*'s files (`a6557d0`; `--with-store`).
- **Sizing:** ¼ Kelly (`f* = p − (1−p)/b`), capped at 1% of capital at risk per trade; no edge → no trade; quantity
  rounded down to whole lots. Capital is the user's input; nothing assumes it.
- **Lint:** `zip(..., strict=True)` where rows must line up, so a mismatch raises instead of silently truncating;
  module-level defaults instead of calls in argument defaults.

## 4. What was built / changed

| Area | Commits | Files |
|---|---|---|
| Phase 6 LightGBM | `157233d`, `a6557d0`, `efaff15` | `ml/labels.py`, `ml/features.py`, `ml/model.py`, `ml/pipeline.py`, `ml/derived.py`, `scripts/quant_ml.py` |
| Phase 9 agent integration | `92a3d71`, `e5c7a27`, `080d262` | `quant_report.py`, `tools.get_quant_signal_report`, analyst / portfolio-manager prompts, `reporting.py`; `quant_build_store.py` saves the 30-day IV table |
| Phase 8 sizing | `0012844` | `sizing.py` |
| Phase 10 groundwork | `387c472` | `scripts/quant_daily_update.py`: download (re-checking recent missing days) → current-year store → vol forecasts → regime → tracker; stops at the first failure; writes `daily_status.json` |
| Store | `dcdc68b` | `quant_build_store.py --datasets` rebuilds only named datasets |
| Fixes | `54d757e`, `fdacef1`, `088d6b6`, `9e2fae6` | See section 2 |
| Tracker | `7e5ef78`, `200b282`, `bc85e2e`, `f60fa99` | `docs/PROGRESS_TRACKER.md` |
| Merge of `main` | `44e88bb` | — |

## 5. Tests

- `test_quant_ml.py`: noise → AUC ~0.50 and rejected; planted momentum → found, calibrated, all applicable gates pass;
  store features see only the previous session's files; same-open exit/re-entry charged twice.
- `test_quant_report.py`: tickers map to store symbols; values dated on the analysis day are not used; the report says
  no signal is validated until one passes; outside-universe symbols get no numbers; missing outputs said plainly;
  prompts and report section checked.
- `test_quant_sizing.py`: Kelly matches the plan's worked example; ¼ Kelly capped at 1%; small edges below the cap;
  no edge → no trade; quantity rounds down to whole lots.
- `test_quant_daily.py`: steps run in order and recheck recent missing days; a failing step stops the run.
- One test per logic-review fix and per `9e2fae6` bug.
- Suite: **1518 passed** after the lint pass; **1526 passed** after the review fixes.

## 6. Results

- **Price-only LightGBM (2021–2026): no edge** — same-day AUC 0.505, Sharpe 0.97 vs buy-and-hold 1.22, rejected
  (threshold stability 0.34).
- **With NSE derivatives/flow features: no edge** (run recorded in `7c5c505`, PR #9) — same-day AUC 0.502, top features
  all market-wide, beats random timing 40%, Sharpe 0.68 vs buy-and-hold 1.22. Phase 6 exit gate not met (AUC 0.506,
  Deflated Sharpe 0.935, OOS/IS 0.44).
- ruff: all quant files clean; 3 pre-existing findings left in `webapp/`.

## 7. Verification

LightGBM runs on the real 29-stock universe; leak check reported 0 mismatches (tracker). Lot sizes checked against
NSE's stated lots (1,482 / 1,488). The quant report's behaviour in a live agent run: not recorded in this PR.

## 8. Risks and open items

- **Phase 9 exit gate** (plan: replay of 50 historical dates, agents never invent numbers) left open — "needs LLM runs,
  your call on cost" (tracker). Done later as a 10-date replay: [PA-21](PA_21-phase9-replay-and-report-wording.md).
- Meta-labelling and ensemble (rest of Phase 8) need a strategy that passed its tests; none has.
- The daily job was not yet scheduled ([PA-09](PA_09-ship-expected-move-and-daily-refresh.md)).
- Further LightGBM work was later dropped at the user's request (tracker, Phase 6 "On hold").
- Research and decision support only; not investment advice.

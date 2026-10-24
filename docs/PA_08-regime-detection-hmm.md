# PA-08 — Market regimes with a hidden Markov model (quant Phase 4), plus data repairs and the progress tracker

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/regime.py`, `tradingagents/analytics/vrp.py`, `scripts/quant_regime.py`, `tests/test_quant_regime.py`; data repairs in `backfill.py`, `datastore.py`, `prices.py`, `dataflows/vendors/nse/derivatives.py`, `scripts/quant_build_store.py`; `docs/PROGRESS_TRACKER.md`, `scripts/update_progress.py`. Also carried the Phase 3 part 2 condor work (see [PA-05](PA_05-garch-volatility-and-vrp-condor.md)) |
| **Related** | [PA-03](PA_03-quant-foundation-nse-data-store.md) · [PA-04](PA_04-evaluation-harness-and-baselines.md) · [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) (regime gate fix) · [PA-10](PA_10-relative-strength-model.md) (re-run on NSE VIX) · [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) · [architecture/11-nse-data-store.md](architecture/11-nse-data-store.md) · [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md) · [architecture/13-volatility-and-regime-models.md](architecture/13-volatility-and-regime-models.md) |
| **Pull request** | #7 (branch `quant/phase-4-regime`); commits `a99eca7`, `9d5941a`, `29b95c3`, `19a2d08`, `53efdd7`, `8fe08e3`, `d1c618d`. No PR description |
| **Date** | 2026-10-23 |

---

## 1. Problem

- Strategies behave differently in calm and stressed markets. The plan's Phase 4 labels each day as one of about
  three market states so a strategy can be judged — and switched off — by state.
- Yahoo's index and stock history had missing sessions.
- Participant-OI files from 2018–19 failed to parse; lot sizes were needed per day.
- Progress was hard to see across phases.

## 2. Root cause / findings

- **Smoothed probabilities peek ahead.** `hmmlearn`'s `predict_proba` uses the whole sample (smoothing), so it uses
  future data; only a forward filter is causal.
- **Yahoo gaps:** about 5 index sessions and about 20 India VIX sessions missing (e.g. 1-Jan-2018); stock sessions
  missing too (e.g. TCS 22-Oct-2026) (`53efdd7`).
- **Participant OI:** 131 of 549 files in 2018–19 had no title line, and some used a full month name ("June 01,
  2018"); the date is now taken from the file name (`a99eca7`).
- **Lot sizes:** stated in UDiFF files; in legacy files derived from turnover (`a99eca7`; made exact later in
  [PA-09](PA_09-agent-quant-tool-and-lightgbm.md)).

## 3. Decisions

- **Model:** 3-state Gaussian HMM on NIFTY returns, realised vol, India VIX and breadth (share of stocks above their
  50-day average). Expanding window, quarterly refits, standardised on training data only.
- **Own forward filter** instead of `hmmlearn`'s smoothed output.
- **State names by volatility** (calm / choppy / stress), so names survive refits.
- **Stable labels:** switch only after 2 days above p = 0.7.
- Covariance floor and several EM starts for robust fits.
- **Regime gate wired in:** `vrp.evaluate_condor` takes the regime known at each session's start and feeds per-regime
  trade results into the gate.
- **NSE official index bars replace Yahoo's**; stock gaps filled from NSE's equity bhavcopy, scaled onto Yahoo's
  adjusted basis; every bar records its source.
- **Tracker bars computed from checkboxes** (and the NSE download log), not typed by hand.

## 4. What was built / changed

| Commit | Change |
|---|---|
| `d1c618d` | `regime.py`; `scripts/quant_regime.py` (fits, saves `regime.parquet` with `known_from`, reports what followed each regime and baselines by regime); regime input to `vrp.evaluate_condor` |
| `53efdd7` | Backfill kind `indices` (NSE `ind_close_all`: official OHLC of NIFTY 50, Nifty Bank, India VIX from 2018); `index_close` dataset; `equity_bhavcopy(day)` in the NSE vendor; NSE bars and gap fills in `prices.py` |
| `a99eca7` | `fo_summary.lot_size`; robust participant-OI parsing; GARCH reuses last converged fit |
| `9d5941a`, `29b95c3` | Condor simulator and VRP walk-forward ([PA-05](PA_05-garch-volatility-and-vrp-condor.md)) |
| `19a2d08`, `8fe08e3` | `docs/PROGRESS_TRACKER.md` and `scripts/update_progress.py`; bug-fix checklist with its own bar |

## 5. Tests

`tests/test_quant_regime.py`: filtered probabilities ignore later data; the forward filter differs from smoothed
probabilities; the stress label finds high-volatility blocks; labels need two confident days to switch; breadth is
the share of stocks above their 50-day average. `tests/test_quant_vrp.py` and `tests/test_quant_datastore.py` cover
the regime input and the data repairs (NSE index bars, gap fills, participant parsing).

## 6. Results

- **First real run** (2021-04 → 2026-10, `d1c618d`): calm 68% / choppy 30% / stress 2.4% of days; following 21-day vol
  11.6% / 15.3% / 14.3%; return differences by regime not significant.
- **Re-run on NSE's India VIX** (recorded in `0e79b17`, PR #9): calm 64% / choppy 34% / stress 1.4%; 29 label changes
  in 5.4 years.
- **Exit gate passed as a risk input** (same record): next-21-day vol calm 11.5% vs choppy 15.1% (p = 0.026,
  non-overlapping windows); returns by regime not significant (p = 0.14) → **not a direction signal**.

## 7. Verification

Run on real NIFTY / India VIX / breadth data. After the full download, data quality showed 0 missing sessions in any
dataset, 6,516 index bars from NSE and 58 stock gaps filled from NSE ([PA-10](PA_10-relative-strength-model.md)).

## 8. Risks and open items

- A single-regime test period could pass the regime gate; fixed in `fdacef1`
  ([PA-09](PA_09-agent-quant-tool-and-lightgbm.md)).
- The regime is **in use** for risk only (volatility), not direction.
- Research and decision support only; not investment advice.

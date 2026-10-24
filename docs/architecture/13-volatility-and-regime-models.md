# Volatility and regime models

> **Status:** Current.
> **Scope:** `tradingagents/analytics/volatility_model.py`, `implied_vol.py`, `regime.py`, `chronos_vol.py`,
> `tradingagents/analytics/ml/`; `scripts/quant_vol_forecasts.py`, `scripts/quant_regime.py`,
> `scripts/quant_chronos.py`, `scripts/quant_ml.py`, `scripts/quant_relative.py`, `scripts/quant_move_size.py`.
> **Last verified against the code:** 2026-10-24

---

## 1. Why volatility

Daily returns are close to unpredictable; their **size** is not. Everything that survived testing in this layer is a
volatility or risk measure, not a direction call ([10](10-quant-layer-overview.md), section 5).

## 2. Volatility forecasts — `volatility_model.py`

| Model | What it is |
|---|---|
| `garch` | GARCH(1,1), Student-t errors |
| `gjr` | GJR-GARCH(1,1,1): falls raise volatility more than rises |
| `egarch` | EGARCH(1,1,1); multi-step forecasts by simulation (300 paths, seeded) |
| `hist` | 20-session historical volatility (baseline) |
| `ewma` | RiskMetrics EWMA, λ = 0.94 (baseline) |

- **Timing.** A forecast dated *t* is made after *t*'s close from returns up to and including *t*, and covers sessions
  *t+1 … t+h*. Horizons `HORIZONS = (5, 10, 21)` sessions; output is annualised volatility.
- **Expanding window, weekly refit.** The first forecast needs `MIN_TRAIN = 756` sessions (3 years). Parameters are
  re-estimated every `REFIT_EVERY = 5` sessions on all data to date and held fixed until the next refit; the variance
  recursion still updates daily. A fit the optimiser did not converge on is not trusted; the last good parameters are
  kept.
- **Scoring: QLIKE** on variances, `RV/F − ln(RV/F) − 1`. It is robust to noise in realised variance and harsher on
  under-forecasting, the costly error when selling options. `realised_vol` gives what actually happened over
  *t+1 … t+h*.
- **`compare`.** Mean QLIKE per model and horizon on the dates every model covers, and a Diebold-Mariano-style
  t-statistic of each model's loss minus a baseline's with a Newey-West standard error (negative = better).

`scripts/quant_vol_forecasts.py` runs all five for every symbol (8 processes by default), saves
`<store>/vol_forecasts/<symbol>.parquet` (columns such as `garch_h21`, `gjr_h5`, `ewma_h10`, `hist_h21`) and
`comparison.csv`, and for NIFTY also scores India VIX against the 21-session horizon.

**Result (tracker, Phase 3 exit check 1):** GARCH beat historical vol out of sample on 31/31 symbols → **in use** for
the expected move and risk. The agents' report adds that EWMA was beaten only narrowly, and for NIFTY India VIX
forecast better than both ([16](16-quant-context-in-agents.md)).

**Expected move.** `quant_report.py` turns the GARCH forecast into a one-standard-deviation move:
`garch_h{h} × √(h / 252)`, shown as a percentage and in rupees on the last known close. About 2 in 3 moves over the
horizon stay inside it. It is a yardstick for stop distance and strike width, not a target.

## 3. Implied volatility — `implied_vol.py`

The same idea as India VIX, from the stored option chain:

1. **Forward from put-call parity** at the strike where call and put closes are nearest: `F = K + e^(rT)(C − P)`. No
   futures price or dividend estimate is needed.
2. **ATM IV** is the mean of the call and put implied vols (**Black-76** on `F`, through the Black-Scholes solver on
   spot `F·e^(−rT)`) at the traded strike nearest `F`.
3. **30-day constant maturity** (`iv30`): total variance (σ²T) is interpolated between the expiries either side of
   `TARGET_DAYS = 30`, matching the 21-session GARCH horizon; if none bracket it, the nearest expiry is used.

Only contracts with at least `MIN_CONTRACTS = 10` traded that day are used (an untraded close is stale), and expiries
closer than `MIN_DAYS = 3` are skipped. A value dated *d* is known from the next session. `atm_iv_table` gives one row
per (day, symbol) with near-expiry IV, forward and `iv30`; `quant_build_store.py` saves it to `<store>/iv/iv30.parquet`.
The tracker records that ATM IV tracks India VIX and that IV exists on every symbol-day with a chain.

## 4. Regime — `regime.py`

**Features** (NIFTY unless stated), each known after day *d*'s close: `r5`, `r20` (5- and 20-session log returns),
`rv20` (20-session realised vol), `vix` (log India VIX), `vix_chg5` (5-session change in log VIX), `breadth` (share
of the 29 stocks above their 50-session average).

**Model.** `hmmlearn.GaussianHMM`, 3 states, full covariance, best of 5 EM starts, `min_covar = 1e-2`. Fitted on an
expanding window (first after 756 sessions), refitted every `REFIT_EVERY = 63` sessions (quarterly). Features are
standardised with the training window's mean and deviation only.

**Filtered probabilities only.** `hmmlearn`'s `predict_proba` is smoothed (forward-backward) and uses later days.
`forward_filter` runs the forward algorithm itself, so the probability on day *d* uses observations up to *d* only.
This was tested against hmmlearn's smoothed output (tracker).

**Stable labels.** State numbers are arbitrary, so states are ordered by the volatility of their mean (`rv20`) and
named `calm`, `choppy`, `stress`. `stable_labels` changes the label only after the new state's probability exceeds
0.7 for 2 sessions in a row.

`scripts/quant_regime.py` saves `<store>/regime/regime.parquet` (probabilities, label, `known_from`) and prints each
regime's share of days and what **followed** it (`describe`).

**Result (tracker, Phase 4).** Re-run on NSE's VIX: calm 64% / choppy 34% / stress 1.4% of days. Passed as a **risk
input** → **in use**: next-21-day vol calm 11.5% vs choppy 15.1% (p = 0.026); returns by regime not significant
(p = 0.14), so it is not a direction signal. The regime label feeds the regime gate ([12](12-evaluation-and-validation.md)).

## 5. Chronos-Bolt — `chronos_vol.py` (tested, not kept)

Amazon `chronos-bolt-small`, run on CPU, is fed the last 512 daily log returns up to *t* and returns quantile
forecasts. Two forecasts were declared before any result:

- `chronos` (raw): per-session σ = (q90 − q10) / 2.5631, variance = σ² + median²;
- `chronos_cal`: the raw forecast times one scale per symbol and horizon, learnt only from earlier forecasts whose
  realised window had closed (at least 252 pairs).

Keep rule (fixed in advance): lower pooled QLIKE than GARCH at 10 sessions **and** better than GARCH on at least two
thirds of symbols. **Result (Phase 7):** 10-session QLIKE GARCH 0.336 vs Chronos calibrated 0.382 (beats GARCH on 8/31)
and raw 0.449 → **not kept**. Needs the optional `chronos` extra (`pip install "tradingagents[chronos]"`, pulls in
PyTorch).

## 6. LightGBM — `ml/` (dropped)

| Module | Role |
|---|---|
| `labels.py` | Triple-barrier labels on closes; `label` = the exit's return is positive (not "upper barrier first", which volatility predicts even on noise); `t1` for purging |
| `features.py` | Price, volume, swing structure and context features, all shifted one session; no raw calendar features; `leak_check` |
| `derived.py`, `inputs.py` | NSE store features (OI change, PCR, delivery %, FII / Client positioning, stock IV) and market context, dated so session *t* sees *t−1* |
| `model.py` | Purged, embargoed walk-forward; each training window cut into fit / early-stop / calibration slices; Platt calibration |
| `pipeline.py` | Out-of-sample probabilities, AUC, same-day AUC, Brier score, reliability; threshold chosen on the calibration slice; gates |
| `relative.py` | "Will this stock beat the other 28?" with cross-sectional ranks, judged on excess return after a NIFTY-futures hedge |
| `move_size.py` | "Will the move be bigger than expected?" scored by same-day AUC against a GARCH ranking |

Results (tracker, Phase 6): price-only same-day AUC 0.505; with derivatives / flow features 0.502; relative strength AUC
0.507 (−1.2% a year after costs), buffer re-test 0.510 (−1.0% a year); move size AUC 0.503, while GARCH alone ranks it
at 0.573. The plan's exit gate was AUC ≥ 0.55. **Further LightGBM work was dropped at the user's request
(2026-10-23)**; it comes back only if asked.

Related: [11 — NSE data store](11-nse-data-store.md), [14 — option strategy simulators](14-option-strategy-simulators-and-costs.md).

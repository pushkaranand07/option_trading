# PA-16 — A pretrained time-series model (Chronos-Bolt) tested against GARCH: not kept

| | |
|---|---|
| **Status** | Done (merged) — model **not kept** |
| **Scope** | `tradingagents/analytics/chronos_vol.py`, `scripts/quant_chronos.py`, `tests/test_quant_chronos.py`, `pyproject.toml` (extra `[chronos]`) |
| **Related** | [PA-05](PA_05-garch-volatility-and-vrp-condor.md) (GARCH, the benchmark), [architecture/13](architecture/13-volatility-and-regime-models.md) |
| **Pull request** | #22 (branch `quant/phase-7-chronos`) |
| **Date** | 2026-10-24 |

## 1. Problem

Phase 7 of the [plan](plans/QUANT_SIGNAL_LAYER_PLAN.md) asked whether a free pretrained forecasting model could improve
on the project's validated volatility forecasts. The user chose this test from four options (user).

## 2. Findings before the test

- Amazon **Chronos-Bolt-Small** runs on CPU: about 9 ms per series in batches of 256, so ~45,000 forecasts take minutes.
- Its forecast is a set of quantiles. The 10–90% spread of daily returns understates variance because returns are
  fat-tailed (first NIFTY check: spread-implied σ 0.59% vs realised 1.56%) — so a calibrated variant was declared too.

## 3. Decisions (fixed in `chronos_vol.py` before any result)

| Variant | Definition |
|---|---|
| `chronos` (raw) | per-session σ = (q90 − q10) / 2.563; variance = σ² + median²; summed over the horizon like GARCH |
| `chronos_cal` | raw × one scale per symbol and horizon, learnt only from earlier forecasts whose window had closed (expanding, ≥ 252 pairs) |

**Keep rule:** pooled 10-session QLIKE below GARCH **and** better than GARCH on at least two thirds of symbols. Two
trials in the trial log. Chronos goes in its own optional extra (`pip install "tradingagents[chronos]"`) because it
pulls in PyTorch (~250 MB); the `[quant]` install is unchanged.

## 4. What was built

- `chronos_forecasts(returns, pipe)` — forecast dated *t* sees returns up to and including *t* only; first forecast on
  the same date as `garch_forecasts`.
- `calibrate(forecasts, realised)` — causal scale (`shift(h)`: at *t* only windows that closed by *t* count).
- `scripts/quant_chronos.py` — 31 symbols, compares with the stored GARCH/GJR/EWMA/historical forecasts on identical
  dates (`volatility_model.compare`, baseline GARCH), saves `<store>/chronos/`, records the trials.

## 5. Tests

A fake pipeline proves each forecast sees only its past (contexts recorded and compared); the quantile → annualised vol
arithmetic; and that calibration fixes a known 2× bias while past calibrated values do not change when the future does.

## 6. Results

| 10-session QLIKE (lower is better) | Score | Beats GARCH on |
|---|---|---|
| **GARCH** | **0.3355** | — |
| GJR-GARCH | 0.3366 | 11/31 |
| EWMA | 0.3696 | 6/31 |
| Chronos, calibrated | 0.3820 | 8/31 (0 significantly; significantly worse on 5) |
| 20-day historical | 0.4479 | 0/31 |
| Chronos, raw | 0.4490 | 2/31 |

Same ordering at 5 and 21 sessions. **Rejected**: a general-purpose pretrained model does not beat a model built for
volatility clustering. GARCH stays the volatility tool.

## 7. Verification

Smoke run on NIFTY and RELIANCE before the full run; full run on 31 symbols; unit suite 1,340 passed; ruff clean.

## 8. Risks and open items

- Only Chronos-Bolt-Small was tested (one model, declared in advance). Larger models were not tried; doing so now
  would be another trial on the same data.

# PA-42 — Point-in-time feature library v1

| | |
|---|---|
| **Status** | Done. No model built; no predictive power measured; no target read |
| **Scope** | new `docs/features_v1.json`, `docs/feature_catalog.md`, `docs/feature_missingness.md`, `docs/features_threshold_report.md`; new `tradingagents/research/features.py`; `tradingagents/research/loader.py`; new `scripts/research_features_threshold.py`, `scripts/quant_build_feature_inputs.py`, `scripts/quant_build_features.py`, `scripts/quant_features_quality.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-41](PA_41-gate-v2-addendum.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `research/features-v1` |
| **Date** | 2026-10-30 |

Research and decision support only, not investment advice. Nothing from 2025-01-01 onward was read, and no request was made.

## 1. Order of work

1. The liquidity threshold was measured on option-chain rows only ([report](features_threshold_report.md)).
2. `features_v1.json` was committed (`5fe90a8`, hash `97129483…`, trial-log event 17) before any feature was built. It has not changed since.
3. Inputs and tables were built (events 18 to 21). Events 19 to 21 are rebuilds after the code fixes in section 5; the spec did not change.

121 features: a 22, b 10, c 13, d 24, e 3, f 17, g 8, h 24. Definitions and missingness per feature are in the [catalog](feature_catalog.md). Trial count: 339, unchanged, because no spec was tested.

## 2. New base tables

Families d, e and f need data the loader refused as live tables, which also start in 2018 and carry the wrong `known_from` on 2021-03-26. `base_participant`, `base_delivery` and `base_index` were built from stored raw files through 2024, with the base's `known_from`. Hole dates carry no rows. `price_events` and `board_notices` came from the stored files the same way.

| Input | Coverage | Gap |
|---|---|---|
| `base_futures`, `base_option_chain` | 2010-2024 | Stock options before 2011 are American and not used |
| `base_participant`, `base_delivery` | 2015-01 to 2015-03, 2018-2024 | **2010-2014, 2015-04 to 2017-12 missing** |
| `base_index`, including India VIX | 2015-2024 | **2010-2014 missing.** `nifty_fut_ret_20` covers trend before 2015 |
| `board_notices` | 29 symbols, from 2017-12 | **Those are today's symbols, so this source has survivorship** |
| Stock spot | None | `basis_spot_index` is NIFTY and BANKNIFTY only; `basis_term` covers stocks |

## 3. Quality checks

| Check | Result | Numbers |
|---|---|---|
| Truncation, synthetic | **PASS** | Test suite, including a planted look-ahead that the check catches |
| Truncation, real store | **PASS** | 7 dates, 102,042 cells, 0 different, 0 rows on one side. GARCH refit on 6 symbols: 0 different |
| `known_from` audit, internal | **PASS** | 8 tables: 0 rows known after the signal, 0 sources on or after it, 0 mismatches with the base |
| `known_from` against raw publication | **UNVERIFIED for history** | Files were fetched the same evening on 2 dates only (20:52 and 21:14). Next-session stamping is later than both. Historical publication times are not stored |
| Corporate actions | **PASS** | 347 discontinuity days: 0 return, gap, range or OI-change values. 134 listed events and 16 scheme-type events on stored days: 0 values |
| ADANIENT 2015-06-03 | **PASS** | `disc_flag` 1, `oi_reset_flag` 1, returns and OI features missing |
| Rolls | **PASS** | 33,185 roll days: `ret_1` always equals the one-contract return. Median absolute OI change is 2.0%, against 11.5% for naive total OI |
| Holes and holidays | **PASS** | 0 rows on hole sessions; 0 `ret_1` values on the session after a hole |
| Infinite values | **PASS** | 0 in every table |
| Missingness | Reported | [By feature, year and universe](feature_missingness.md). Nothing is filled |
| Winsor limits | Fitted | 84 features, signal dates to 2022-12-31, U2 rows; hash `5b8c34fa…`; stored values are not clipped |
| Clusters | Reported | 117 features in, 70 clusters, 26 with more than one member; `reports/features/checks.json` (gitignored) |
| Above 0.95 | Flagged, none dropped | 21 pairs |

The 21 pairs above 0.95: GARCH h1, h5 and h10 (3 pairs); U1 and U2 ranks of the same feature (12 pairs); U1 and U2 breadth (3 pairs); `board_days_to_next` and `results_days_to_next`; `parkinson_20` and `garman_klass_20`; `nifty_ret_20` and `nifty_fut_ret_20`.

## 4. Risks and open items

- **Features are one session staler than the gate's baselines.** Rule 3 says a feature for D reads `known_from` at or before D, and every NSE row's `known_from` is the next session. So a feature for D reads D-1. The gate's baselines use D's own close. The model prompt must decide the alignment; `source_trade_date` is on every row.
- **Undetected discontinuities can remain.** 64 values of `ret_1` above 25% in absolute log terms remain, 20 of them above 35%, the largest 0.509. Each may be a real move or an action with no listing, footprint or reset. Before 2015 there is no action list. Cause UNVERIFIED for all of them; none was removed.
- **Winsor limits use all of development.** That is what the rule says, but in a walk-forward, a fold ending in 2014 would see limits fitted through 2022. `fit_limits` takes any date range, so a model can fit per fold.
- **Board notices are the one exception to a cut at D-1.** A notice stamped before 15:30 on D counts for D, as the spec says. The truncation test cuts notices there.
- **GARCH:** 32 of 309 eligible symbols returned no forecast. Cause UNVERIFIED; they stay missing. GARCH needs more than 600 returns, so forecasts start in 2013. Horizons 1, 5 and 10 are almost identical.
- **Sparse features:** in development on U1, `skew_5` is 79.8% missing and `atm_iv_front` 34.9%. The 25-contract threshold keeps 5.27% of european rows.
- **Risk-free rate** is the repo's constant, 6.5%: ASSUMPTION.
- **Two truncation dates test less than the rest.** 2021-03-31 has 0 rows, because its source is the hole. 2012-06-15 has no GARCH symbol with enough returns.
- **Windows do not cross any symbol link,** flagged or not, so a renamed stock restarts its history.

## 5. Defects the checks caught

| Defect | Caught by | Fix |
|---|---|---|
| A rolling value could appear on a session where the symbol had no row | Hole test | Values exist only where the symbol has a futures row that session |
| Family e had rows for stocks before their futures were listed, so a later listing changed earlier rows | Real-store truncation (3 dates failed) | Same rule for family e; regression test added |
| pandas `pivot` crashed inside the truncation run | First real-store run | Replaced by a direct array fill; all 8 tables were byte-identical |

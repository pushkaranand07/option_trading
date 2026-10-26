# PA-10 — Relative-strength model (Phase 6, second model), data completion, and the remaining bug fixes

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/ml/{relative,inputs}.py`, `scripts/quant_relative.py`, `scripts/quant_ml.py`, `tests/test_quant_relative.py`; fixes in `option_backtester/exits.py`, `tradingagents/analytics/{datastore,prices,volatility_model,vrp}.py`, `scripts/quant_{build_store,regime,vol_forecasts}.py`, `webapp/{market_data,planner}.py`; `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-02](PA_02-webapp.md) · [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [PA-07](PA_05-garch-volatility-and-vrp-condor.md) · [PA-08](PA_08-regime-detection-hmm.md) · [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) · [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) · [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md) · [architecture/11-nse-data-store.md](architecture/11-nse-data-store.md) · [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md) |
| **Pull request** | #9 (branch `quant/phase-6b-relative`); 17 commits from `8df7ad0` to `f1592f2`. No PR description. The real-data verdict was committed in `df898d7` (PR #10) |
| **Date** | 2026-10-23 |

---

## 1. Problem

- The first LightGBM model asked "will this stock rise?" and found nothing. A different question might work: **which
  stocks will beat the other 28** over the next few sessions (stock picking, with the market move hedged away).
- Remaining items on the bug-fix list: code that future pandas versions would break, store writes that a reader could
  see half-written, webapp lint, slow lot-size computation.
- The condor test reported a nonsense annual return.

## 2. Root cause / findings

- **Condor returns on capital** (`7e7b979`): the condor's daily series is a fraction of max risk; compounding it as a
  return on capital assumed all capital was in every condor and turned NIFTY's +0.84%/trade into a −28.8% "annual
  return". Sharpe is unchanged by the scale. Parameter stability had been left `not_evaluated`.
- **Future pandas** (`8df7ad0`): five `DataFrame.drop(inplace=True)` calls in `option_backtester/exits.py`; `concat`
  without `sort=True` in `volatility_model.compare` and `vrp.vrp_series` — once pandas stops sorting by default, dates
  under the Newey-West statistic and the rolling VRP z-score would be silently reordered.
- **Non-atomic writes:** a second job or a reader could see half a Parquet file.
- **Lot sizes:** the open-interest GCD took seconds per file; near expiry, the GCD of very few OI values can be a
  multiple of the lot for a day or two (45 rows of short "blips").
- **Store load** read whole files before filtering symbols (NIFTY chain: 0.66 GB instead of all 15M rows when
  filtered while reading).

## 3. Decisions

- **Relative-strength label:** stock beats the equal-weight universe over the next *H* sessions, open to open.
  Stock features ranked across stocks per day; market context left unranked.
- **Book:** top-*k* stocks, rebalanced every *H* sessions, judged on excess return over the equal-weight universe
  after delivery costs and a NIFTY futures hedge. *k* fixed in advance; neighbouring *k* as a robustness check.
- **Baseline:** random picks on the same schedule.
- **Honest trial count:** the Deflated Sharpe in `quant_relative.py` counts every earlier run.
- **Condor gates** state returns on capital at **2% at risk per trade**; parameter stability computed from
  neighbouring grid points' training Sharpe.
- Every store write goes through a temp file and `os.replace`; failures raise instead of leaving stale data.
- Lot-size runs under 5 sessions flanked by the same lot take that lot; real changes (which never revert within days)
  are kept.

## 4. What was built / changed

| Area | Commits | Change |
|---|---|---|
| Relative strength | `0e3df03`, `e7fc8c0` | `ml/relative.py`, `ml/inputs.py` (market context and store features shared with `quant_ml.py`), `scripts/quant_relative.py` |
| Condor gates | `7e7b979` | `vrp.py`: returns on capital, parameter stability |
| Bug fixes | `8df7ad0` | `inplace` drops reassigned; `concat(sort=True)`; atomic `write_parquet`; webapp: ambiguous name, duplicate branch, string-split literal |
| Lot sizes | `d6c23a8`, `2c6424f` | Universe symbols only, vectorised (seconds → 39 ms per file); blip clean-up run by the build |
| Store / speed | `7497e59`, `88f21cc`, `3ba796f` | Filter symbols while reading Parquet; `quant_build_store.py --skip-iv`; `quant_ml.py` reads the stored IV table (~15 min saved) |
| Tracker | `76117d4`, `0741752`, `0e79b17`, `1d850d7`, `7b914ee`, `554807d`, `7c5c505`, `f1592f2` | Data verified; VRP condor and LightGBM-with-store verdicts; branch table |

## 5. Tests

- `tests/test_quant_relative.py`: labels compare each stock with the universe average; stock features become ranks and
  context stays; perfect-foresight picks beat the universe and random picks do not; **on noise there is no
  stock-picking edge** (same-day AUC ~0.50, rejected); **a persistent planted stock-specific drift is found** (excess
  Sharpe > 1 after costs, beats random picks ≥ 95%). A one-day planted edge was found but lost to costs.
- `tests/test_quant_vrp.py`: returns on capital and stability. `tests/test_quant_datastore.py`: atomic writes,
  lot-size blips.
- Full suite **1536 passed**; whole repo ruff-clean.

## 6. Results

- **Relative strength on real data: no edge → rejected** (`df898d7`): same-day AUC 0.507; excess −1.2% a year after
  costs and hedge (Sharpe −0.09); top-3 / top-8 unstable; Deflated Sharpe 0.42. "Beats random picks 99%" reflected
  lower turnover, not skill — random picks pay full costs at every rebalance.
- **Data complete and verified** (`0e79b17`): 2018–2026 download finished (6,503 files; 379 "missing", mostly
  holidays); participant and delivery data on all 2,172 F&O days; 31/31 symbols ≥ 98%; IV on 65,984 symbol-days;
  0 missing sessions in any dataset; 6,516 index bars from NSE; 58 stock gaps filled from NSE; all 14 stock jumps
  > 20% verified as real events (e.g. COVID 23-Mar-2020, Adani, BHEL).
- Verdicts recorded on this branch: VRP condor rejected ([PA-05](PA_05-garch-volatility-and-vrp-condor.md)), LightGBM
  with NSE features rejected ([PA-09](PA_09-agent-quant-tool-and-lightgbm.md)), regime passes as a risk input
  ([PA-08](PA_08-regime-detection-hmm.md)).
- Lot sizes: 99.6% match with NSE's stated lots (tracker).

## 7. Verification

Relative strength run on the real 29-stock universe with NSE store features; data-quality report over the full
store; stock jumps checked against NSE prices.

## 8. Risks and open items

- A **turnover-matched random baseline** was needed to judge the relative-strength book fairly — added in
  [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md) along with a buffer re-test.
- Remaining warnings come from third-party packages (pandas-ta-classic, empyrical).
- Research and decision support only; not investment advice.

# Quant Signal Layer — Long-Horizon Build Plan

> **Status:** Plan. Nothing in this document is built yet unless marked ✅.
> **Date written:** 2026-10-23
> **Horizon:** about 6–8 months to small live capital. This is deliberately slow; see [section 1](#1-what-success-means-and-why-100-is-not-the-target).
> **Disclaimer:** Research and decision support only, not financial advice. A backtest is not a promise of what will happen live.

---

## Table of contents

1. [What "success" means (and why 100% is not the target)](#1-what-success-means-and-why-100-is-not-the-target)
2. [Core idea: LLMs reason, numbers forecast](#2-core-idea-llms-reason-numbers-forecast)
3. [What already exists in this repo](#3-what-already-exists-in-this-repo)
4. [The calculations this plan relies on](#4-the-calculations-this-plan-relies-on)
5. [Phase-by-phase plan](#5-phase-by-phase-plan)
   - [Phase 0 — Ground rules and success gates](#phase-0--ground-rules-and-success-gates-week-1)
   - [Phase 1 — Point-in-time data foundation](#phase-1--point-in-time-data-foundation-weeks-13)
   - [Phase 2 — Evaluation harness and baselines](#phase-2--evaluation-harness-and-baselines-weeks-34)
   - [Phase 3 — Volatility engine (GARCH)](#phase-3--volatility-engine-garch-weeks-57)
   - [Phase 4 — Regime detection (HMM)](#phase-4--regime-detection-hmm-weeks-78)
   - [Phase 5 — Your own idea as exact rules](#phase-5--your-own-idea-as-exact-rules-weeks-810)
   - [Phase 6 — Gradient-boosting model (LightGBM)](#phase-6--gradient-boosting-model-lightgbm-weeks-1014)
   - [Phase 7 — Pretrained time-series models (optional)](#phase-7--pretrained-time-series-models-optional-weeks-1415)
   - [Phase 8 — Ensemble, meta-labelling and position sizing](#phase-8--ensemble-meta-labelling-and-position-sizing-weeks-1517)
   - [Phase 9 — Agent integration](#phase-9--agent-integration-weeks-1718)
   - [Phase 10 — Paper trading](#phase-10--paper-trading-weeks-1830)
   - [Phase 11 — Small live capital and monitoring](#phase-11--small-live-capital-and-monitoring-week-30)
6. [Idea specification template](#6-idea-specification-template)
7. [Failure catalogue](#7-failure-catalogue)
8. [Dependencies](#8-dependencies)
9. [Weekly operating rhythm](#9-weekly-operating-rhythm)

---

## 1. What "success" means (and why 100% is not the target)

No model, free or paid, gets 100% of trades right. Markets are partly random, and when a pattern becomes widely known, traders trade it away. Anyone who claims 100% is either overfitting or selling something.

What this plan **can** push close to 100% is this:

> **The probability that anything we put real money behind has a real, measured edge, and that our losses stay inside limits we set in advance.**

That is achievable. It comes from discipline, not from a cleverer model:

| Lever | Effect on success |
|---|---|
| Point-in-time data, no lookahead | Removes fake edges that vanish live |
| Walk-forward + Deflated Sharpe | Removes edges that are just luck from trying many ideas |
| Realistic Indian costs (STT, GST, slippage) | Removes edges that only exist before costs |
| Enough trades (hundreds, not dozens) | Separates skill from noise statistically |
| Paper trading before live | Catches execution and data problems |
| Fixed risk per trade + kill switches | Stops one bad period wiping out the account |

A realistic good result looks like this: **a 53–58% hit rate, winners about 1.3–2× the size of losers, after costs, stable across years and regimes.** That compounds well. A 90% hit rate in a backtest is almost always a bug.

---

## 2. Core idea: LLMs reason, numbers forecast

The current agents (market, news, debate, risk) are LLMs. They are good at reading news, filings and reports and weighing arguments. They are poor at turning a column of prices into a forecast.

So the plan adds a **quant signal layer** underneath them:

```
                 ┌──────────────────────────────────────┐
  NSE / yfinance │  Phase 1: point-in-time data store   │
  ───────────────►  (prices, OI, IV, VIX, FII/DII, PCR) │
                 └───────────────┬──────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────────┐
        ▼                        ▼                         ▼
  GARCH volatility        HMM regime label        LightGBM probability
  forecast vs IV          (trend / range /        of a +X% move before
  (Phase 3)               high-vol) (Phase 4)     a −Y% move (Phase 6)
        │                        │                         │
        └──────────┬─────────────┴───────────┬─────────────┘
                   ▼                         ▼
           Your rules (Phase 5)     Ensemble + sizing (Phase 8)
                   └───────────┬─────────────┘
                               ▼
              Agent tool: "quant_signal_report" (Phase 9)
                               ▼
        Market analyst / debate / risk manager read the numbers
        and argue about them, rather than guessing them.
```

Every box must pass the same validation gates before anything downstream may use it.

---

## 3. What already exists in this repo

These are the hardest parts to get right, and they are already here:

| Need | Where | Notes |
|---|---|---|
| No-lookahead swings and patterns | [swings.py](../tradingagents/analytics/swings.py) | `confirmed_swings`, `market_structure`, `double_top_breakdown` |
| Repainting detector for any signal | [swings.py](../tradingagents/analytics/swings.py) | `find_lookahead(signal_fn, df)`: empty list = causal |
| Walk-forward with embargo | [validation.py](../tradingagents/analytics/validation.py) | `walk_forward(data, strategy, grid, train, test, embargo)` |
| Deflated Sharpe ratio | [validation.py](../tradingagents/analytics/validation.py) | `deflated_sharpe_ratio`, `evidence_verdict` (`MIN_TRADES = 30`, `DSR_SIGNIFICANT = 0.95`) |
| Signal building blocks | [option_backtester/signals/](../option_backtester/signals/) | momentum, trend, IV rank, ATR, Bollinger, volume, calendar |
| Option structures and simulator | [option_backtester/](../option_backtester/) | spreads, condors, butterflies, calendars |
| NSE data | [nse/](../tradingagents/dataflows/vendors/nse/) | F&O bhavcopy, delivery data, FII/DII flows, index constituents, holidays |
| Survivorship warning | [indices.py](../tradingagents/dataflows/vendors/nse/indices.py) | `survivorship_warning` |

The new work is the models themselves and the discipline around them.

---

## 4. The calculations this plan relies on

### 4.1 Expectancy: the only number that pays

```
E = p × W − (1 − p) × L − C

p = hit rate, W = average win, L = average loss, C = average cost per trade
```

Example: p = 0.55, W = ₹1,500, L = ₹1,000, C = ₹120
→ E = 825 − 450 − 120 = **₹255 per trade**.

The same idea with p = 0.55 but W = L = ₹1,000 gives E = 550 − 450 − 120 = **₹−20**: costs turn it into a loser. **Always compute E after costs.**

### 4.2 How many trades before a hit rate means anything

To tell a true 55% apart from a coin-flip 50% at 95% confidence:

```
n ≈ z² × p(1 − p) / d²  =  1.96² × 0.25 / 0.05²  ≈  384 trades
```

With 30 trades, a 60% hit rate is easily luck. This is why the plan prefers signals that trade often enough (daily/weekly across many stocks) to reach hundreds of out-of-sample trades, and why `MIN_TRADES = 30` is a floor, not a target.

### 4.3 Deflated Sharpe: correcting for the number of ideas tried

If you try 200 parameter combinations, the best one will show a high Sharpe even on pure noise. The expected best Sharpe from N noise trials grows roughly like `√(2 ln N)`. `deflated_sharpe_ratio` in [validation.py](../tradingagents/analytics/validation.py) accounts for N, skew and fat tails. **Log every trial.** Hiding failed trials is the main way people fool themselves.

### 4.4 Volatility risk premium (VRP)

```
VRP_t = IV_t(ATM, ~30 days) − σ̂_t(GARCH forecast over the same horizon)
```

Option sellers earn money on average because implied volatility usually sits above the volatility that actually follows. The edge is in **when** the gap is unusually wide (sell premium) or negative (buy premium, or stand aside).

### 4.5 Position sizing: fractional Kelly with a hard cap

```
Kelly fraction  f* = p − (1 − p) / b      where b = W / L
```

Example: p = 0.55, b = 1.5 → f* = 0.55 − 0.45/1.5 = **0.25**.

Full Kelly is far too aggressive because p and b are estimates. Use **¼ Kelly**, capped at **1% of capital at risk per trade** in early live trading. Here that means 0.25 × 0.25 = 6.25%, which the 1% cap overrides.

### 4.6 Probability calibration

A model that says "70%" should be right about 70% of the time. Measure it with the **Brier score** and a reliability curve (bucket predictions 50–55%, 55–60%, …, and compare each bucket with its actual hit rate). An uncalibrated model gives wrong Kelly sizes even when its ranking is good.

---

## 5. Phase-by-phase plan

Each phase has a **goal**, the **work**, the **files** it adds, and an **exit gate**. Do not start a phase until the previous gate has passed. If a gate fails, fix the cause or drop the idea; never loosen the gate to let it through.

### Phase 0 — Ground rules and success gates (week 1)

**Goal:** Decide what counts as success before seeing any results, so results can't move the goalposts.

**Work**
- Choose the first universe: start with **Nifty 50 index + Bank Nifty + 20–30 liquid F&O stocks**.
- Choose the holding horizon: **5–20 trading days** (daily bars). Intraday comes later, if ever: its data and cost problems are much harder.
- Write the gates (below) into `config` so code enforces them.
- Create a **trial log** (CSV or SQLite): every backtest run gets a row with idea, params, date, OOS Sharpe, DSR and verdict.

**Global gates (apply to every model and rule set)**

| Gate | Threshold |
|---|---|
| Lookahead check | `find_lookahead` returns an empty list |
| Out-of-sample trades | ≥ 100 (≥ 300 preferred) |
| Deflated Sharpe | ≥ 0.95 |
| OOS / IS Sharpe | ≥ 0.5 (otherwise mostly curve-fit) |
| Expectancy after costs | > 0 in at least 70% of walk-forward folds |
| Max drawdown (OOS) | ≤ 2× the average yearly return |
| Regime stability | Positive expectancy in at least 2 of 3 HMM regimes, or the strategy is explicitly switched off in the losing regime |
| Parameter stability | Neighbouring parameter values give similar results (no lone spike) |

**Files:** `tradingagents/analytics/gates.py`, `tradingagents/analytics/trial_log.py`

**Exit gate:** Gates are written in code and covered by tests; the trial log works.

---

### Phase 1 — Point-in-time data foundation (weeks 1–3)

**Goal:** A local store where every value carries the date it became **known**, not just the date it refers to.

**Work**
1. **Prices:** daily OHLCV for the universe, adjusted for splits and bonuses. Keep raw prices too, because option strikes use raw prices.
2. **F&O:** daily bhavcopy via `fo_bhavcopy` → OI, change in OI, futures basis, PCR (by OI and by volume), ATM IV per expiry.
3. **India VIX** daily.
4. **FII/DII flows** via `get_fii_dii` / `record_history`. Flows publish after market close, so stamp them **known at T+1 open**.
5. **Delivery %** via `delivery_data`.
6. **Index membership history**: use the past membership, not today's list, for any date (survivorship).
7. **Cost model**: brokerage, STT, exchange charges, SEBI fee, stamp duty, 18% GST, plus slippage (start with 0.05% for liquid stocks and 1 tick + 1% of premium for options). **Rates change in budgets: keep them in config and check current rates before any live use.**

**Storage:** Parquet files partitioned by dataset and year under `data_cache/quant/`.

**Files:** `tradingagents/analytics/datastore.py`, `tradingagents/analytics/costs.py`

**Tests:** every derived column passes `find_lookahead`; a flow value for date D is never visible on bar D.

**Exit gate:** at least 8 years of daily history (covering 2018 IL&FS, 2020 crash, 2022 rate hikes) loads in one call with no gaps, and a cost-model test reproduces a broker contract note to within ₹1.

---

### Phase 2 — Evaluation harness and baselines (weeks 3–4)

**Goal:** One command that judges any signal the same way, and baselines it must beat.

**Work**
- Wrap `walk_forward` with: costs, the trade-level ledger (entry, exit, P&L, MAE/MFE), hit rate, payoff ratio, expectancy, drawdown, per-regime and per-year breakdowns.
- **Baselines** every idea must beat:
  1. Buy-and-hold Nifty.
  2. **Random entry, same exits, same holding period**, run 1,000 times. Your strategy must sit above the 95th percentile of this distribution.
  3. A simple 50/200 moving-average trend filter.
- Default split: **train 3 years / test 6 months / embargo 20 days**, rolling forward.

**Files:** `tradingagents/analytics/evaluate.py`, `scripts/evaluate_signal.py`

**Exit gate:** the random-entry baseline correctly comes out `not_significant` (this is a check that the harness isn't biased upward).

---

### Phase 3 — Volatility engine (GARCH) (weeks 5–7)

**Goal:** Forecast volatility (this is the part of markets that is actually predictable) and turn it into option signals.

**Work**
1. Fit **GARCH(1,1)**, **GJR-GARCH** (falls hurt more than rises) and **EGARCH** with Student-t errors on daily log returns, using the `arch` library.
2. Refit on an expanding window **using only data up to t** (refit weekly, forecast daily).
3. Forecast volatility over the life of the option (to expiry).
4. Compare with alternatives: 20-day historical vol and India VIX. Score with **QLIKE** loss against realised volatility. GARCH must beat historical vol to stay.
5. Build signals:
   - `vrp = ATM_IV − garch_vol_to_expiry`
   - `vrp_z` = z-score of VRP over the last 252 days
   - **Sell premium** (iron condor / short strangle with wings) when `vrp_z > +1`
   - **Stand aside or buy premium** when `vrp_z < −1`
6. Backtest through [option_backtester/](../option_backtester/) with real lot sizes and costs.

**Files:** `tradingagents/analytics/volatility_model.py`, `option_backtester/signals/vrp.py`

**Exit gate:** GARCH beats historical vol on QLIKE out-of-sample, and the VRP option strategy passes all Phase 0 gates **after costs**.

---

### Phase 4 — Regime detection (HMM) (weeks 7–8)

**Goal:** Label each day as one of about three market states, so strategies switch on and off by state.

**Work**
1. Features: 5-day and 20-day returns, 20-day realised vol, India VIX level and change, breadth (% of constituents above the 50-day moving average).
2. Fit a **Gaussian HMM with 3 states** (`hmmlearn`) on the training window only.
3. **Filtered** probabilities only (forward algorithm up to t). Do **not** use Viterbi or smoothed states: they use future data and will fail `find_lookahead`.
4. Name the states afterwards by their average return and vol (for example *calm trend*, *choppy range*, *stress*).
5. Make the labels stable: switch label only when the new state's probability is > 0.7 for 2 consecutive days.

**Files:** `tradingagents/analytics/regime.py`

**Exit gate:** passes `find_lookahead`; state average returns and vols differ clearly out of sample; the Phase 3 strategy's results differ meaningfully between states (otherwise the regime adds nothing).

---

### Phase 5 — Your own idea as exact rules (weeks 8–10)

**Goal:** Turn the pattern you believe in into rules a computer can test without judgement calls.

**Work**
1. Fill in the [idea specification template](#6-idea-specification-template) for each idea. Ideas without numbers can't be tested.
2. Code each idea as a pure function `signal(df) -> Series` using only confirmed swings, lagged flows and so on.
3. Run `find_lookahead`, then the Phase 2 harness, then compare with baselines.
4. Test a **small** parameter grid (≤ 30 combinations per idea) and log every run in the trial log.
5. Check **parameter stability**: plot results across the grid. A good idea makes a plateau; a fitted one makes a spike.

**Files:** `tradingagents/analytics/ideas/<idea_name>.py`, one per idea

**Exit gate:** at least one idea passes all gates, **or** a written note on why each idea failed. A failed idea is a useful result: it is money you didn't lose.

---

### Phase 6 — Gradient-boosting model (LightGBM) (weeks 10–14)

**Goal:** A model that combines many weak signals into one calibrated probability.

**Work**
1. **Labels: triple barrier.** For each stock on each day: will price hit `+k × σ` (profit) before `−k × σ` (stop) within H days? Label 1 / 0 / timeout. Start with k = 1.5, H = 10. σ is the GARCH forecast from Phase 3.
2. **Features** (all lagged so they're known at t):
   - Price: returns over 1/5/20/60 days, distance from 20/50/200 DMA, RSI, ATR %, Bollinger position
   - Structure: `market_structure`, days since last confirmed swing high/low
   - Derivatives: OI change %, futures basis, PCR, IV rank, VRP z-score
   - Flows: FII/DII 5-day net (lagged 1 day), delivery % vs its 20-day average
   - Context: HMM regime probabilities, India VIX, Nifty 20-day return, sector relative strength
   - Calendar: days to expiry, month-end, results season
3. **Validation: purged, embargoed walk-forward.** Drop training samples whose label window overlaps the test period. Use the same train/test/embargo split as Phase 2.
4. **Keep the model small**: `num_leaves ≤ 31`, `min_data_in_leaf ≥ 200`, strong regularisation, early stopping on a separate validation slice inside the train window.
5. **Calibrate** with isotonic regression on the validation slice; report Brier score and reliability curve.
6. **Explain** with feature importance / SHAP. If one feature carries everything, suspect leakage.
7. **Trading rule:** enter when calibrated probability > 0.58 (tune within the grid, and log it), with exits on the triple-barrier levels.

**Files:** `tradingagents/analytics/ml/features.py`, `labels.py`, `model.py`, `calibration.py`

**Exit gate:** OOS AUC ≥ 0.55 and stable across folds; calibrated (each bucket within ±5 percentage points of its predicted rate); the trading rule passes all Phase 0 gates after costs. **AUC above 0.65 on daily stock data means: look for leakage first.**

---

### Phase 7 — Pretrained time-series models (optional) (weeks 14–15)

**Goal:** Check whether zero-shot models add anything as **extra features**, not as the forecaster.

**Work**
- Run **Chronos-Bolt** (or TimesFM / Granite TTM) on rolling windows ending at t; take the forecast's median and spread for volatility and volume.
- Add them as LightGBM features and re-run Phase 6.

**Exit gate:** keep them only if OOS AUC or Brier improves in most folds. Otherwise drop them; they cost compute and add a dependency.

---

### Phase 8 — Ensemble, meta-labelling and position sizing (weeks 15–17)

**Goal:** Combine the surviving signals and size trades sensibly.

**Work**
1. **Meta-labelling:** your Phase 5 rule decides *direction*; a second small LightGBM decides *whether to take this particular trade* (trained on the rule's past wins and losses). This usually raises hit rate by filtering out the worst setups.
2. **Ensemble:** combine probabilities with a simple average or logistic regression fitted out of sample. No deep stacking.
3. **Sizing:** ¼ Kelly from calibrated p and the measured payoff ratio b, capped at 1% risk per trade.
4. **Portfolio limits:** at most 5 open positions; at most 2 in one sector; total open risk ≤ 4% of capital; cut size by half in the *stress* regime.

**Files:** `tradingagents/analytics/ensemble.py`, `tradingagents/analytics/sizing.py`

**Exit gate:** the combined system beats its best single component out of sample on Sharpe **and** drawdown, and passes all gates.

---

### Phase 9 — Agent integration (weeks 17–18)

**Goal:** Give the LLM agents the numbers, so they argue about evidence instead of guessing.

**Work**
- New tool `get_quant_signal_report(ticker, date)` in [tools.py](../tradingagents/agents/tools.py) returning plain text like:

  ```
  Regime: choppy range (p = 0.78)
  GARCH 10-day vol: 18.4% annualised | ATM IV: 23.1% | VRP z: +1.6 (rich)
  LightGBM P(+1.5σ before −1.5σ in 10d): 0.61 (calibrated; base rate 0.47)
  Rule "FII-reversal": triggered today
  Validation: OOS 412 trades, hit 56%, payoff 1.4, DSR 0.97 → significant
  Suggested risk: 0.8% of capital
  ```

- The market analyst cites it; the risk manager **must refuse** any trade whose underlying signal has verdict `not_significant` or `insufficient_evidence`.
- Add the report to the HTML output in [report_html.py](../tradingagents/report_html.py).

**Exit gate:** in a replay of 50 historical dates, agent decisions match the quant signal's direction and size limits, and the agents never invent numbers that aren't in the tool output.

---

### Phase 10 — Paper trading (weeks 18–30)

**Goal:** Prove the live pipeline behaves like the backtest.

**Work**
- Run the full pipeline every trading day after close; record the intended orders with timestamps **before** the next open.
- Fill at the next day's actual open plus modelled slippage.
- Track: live vs backtest hit rate, slippage vs model, data delays, missed runs.

**Exit gate (all of these):**
- ≥ 3 months **and** ≥ 50 paper trades
- Hit rate within the backtest's 95% confidence band
- Realised slippage ≤ 1.5× the model
- No missed runs in the last 4 weeks

---

### Phase 11 — Small live capital and monitoring (week 30+)

**Goal:** Go live small, grow only on evidence.

**Work**
- Start with capital you can afford to lose entirely, at **0.5% risk per trade**.
- **Kill switches** (automatic stop and alert):
  - Drawdown > 2× the backtest's worst monthly drawdown
  - 8 losses in a row
  - Rolling 50-trade hit rate below the lower edge of the backtest band
  - Data feed stale or missing
- **Drift monitor:** each month, compare live feature distributions with training data (population stability index > 0.25 → retrain or pause).
- **Retrain** monthly on the expanding window, and only deploy a new model if it passes the same gates.
- **Scale up** risk in steps (0.5% → 0.75% → 1%) only after every 100 live trades stay within the band.
- **Compliance:** before automating order placement through a broker API, check the current SEBI retail algo framework and your broker's rules (algo registration, order-rate limits, static IP). Until then, the system only *recommends* and you place orders by hand.

---

## 6. Idea specification template

Copy this for each idea into `docs/ideas/<idea_name>.md`:

```markdown
# Idea: <short name>

## Hypothesis (one sentence)
When <condition>, <instrument> tends to <move> over <N days>, because <reason>.

## Universe
<Nifty / Bank Nifty / F&O stocks list / ...>

## Entry (exact, all numbers)
- Condition 1: e.g. FII net cash sell > ₹3,000 cr on each of the last 3 days (known T+1)
- Condition 2: e.g. Nifty PCR (OI) > 1.3
- Condition 3: e.g. price closes above the last confirmed swing high
- Enter at: next day's open

## Exit (exact)
- Stop: e.g. 1.5 × ATR(14) below entry
- Target: e.g. 2.5 × ATR(14) above entry
- Time stop: e.g. exit at close of day 10

## Instrument
<cash / futures / option structure, strike and expiry rule>

## Parameters to test (≤ 30 combinations)
- threshold: [2000, 3000, 4000]
- PCR: [1.2, 1.3, 1.4]
- ...

## Why it should keep working
<who is on the other side of the trade, and why they keep doing it>

## Results (filled by the harness)
- OOS trades / hit rate / payoff / expectancy after costs:
- DSR / verdict:
- Best and worst regime:
- Decision: keep / drop, and why
```

---

## 7. Failure catalogue

| Problem | What it looks like | Fix in this plan |
|---|---|---|
| Lookahead / repainting | Great backtest, poor live results | `find_lookahead` on every signal (Phases 1, 4, 5) |
| Survivorship bias | Universe = today's index members | Historical membership (Phase 1) |
| Flows used too early | FII data used on the day it refers to | Stamp as known T+1 (Phase 1) |
| Overfitting via many trials | High IS Sharpe, low OOS | Trial log + Deflated Sharpe (Phases 0, 2) |
| Label overlap leakage | ML AUC suspiciously high | Purged, embargoed walk-forward (Phase 6) |
| Ignoring costs | Profitable gross, losing net | Cost model on every test (Phases 1, 2) |
| Too few trades | 60% hit rate from 25 trades | ≥ 100 OOS trades gate (Phase 0) |
| Regime dependence | Works 2020–21, fails 2022 | Per-regime gates (Phases 0, 4) |
| Overconfident probabilities | Kelly sizes too large | Calibration (Phase 6) |
| Model drift | Live hit rate slowly drops | PSI monitor + kill switches (Phase 11) |
| Smoothed HMM states | Regime looks perfect in hindsight | Filtered probabilities only (Phase 4) |
| LLM invents numbers | Agent cites figures not in data | Tool-only numbers + replay check (Phase 9) |
| Expiry/lot-size changes | Option backtest uses wrong lots | Bhavcopy-derived lots (existing NSE code) |

---

## 8. Dependencies

All free and CPU-friendly. Add as an optional extra in [pyproject.toml](../pyproject.toml):

```toml
[project.optional-dependencies]
quant = [
    "arch>=7.0",          # GARCH family (Phase 3)
    "hmmlearn>=0.3",      # regime HMM (Phase 4)
    "lightgbm>=4.3",      # gradient boosting (Phase 6)
    "scikit-learn>=1.5",  # calibration, metrics (Phase 6)
    "pyarrow>=16",        # Parquet store (Phase 1)
    "shap>=0.45",         # explanations (Phase 6, optional)
]
foundation = [
    "chronos-forecasting>=1.4",  # Phase 7 only, pulls in torch
]
```

---

## 9. Weekly operating rhythm

| When | What |
|---|---|
| Daily (after close) | Update data, run signals, write recommendations (paper/live), check kill switches |
| Weekly | Refit GARCH; review the trial log; update the idea backlog |
| Monthly | Retrain HMM and LightGBM on the expanding window; drift report; live vs backtest review |
| Quarterly | Re-check cost rates and regulations; prune ideas that have decayed |

**Rule of thumb:** if something looks too good, it is a bug until proven otherwise.

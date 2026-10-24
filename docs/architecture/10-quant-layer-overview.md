# Quant signal layer — overview

> **Status:** Current.
> **Scope:** `tradingagents/analytics/` (and `tradingagents/analytics/ml/`), the `scripts/quant_*.py` scripts,
> `scripts/market_map.py`, `scripts/trade_journal.py`, `scripts/update_progress.py`, `scripts/quant_daily_update.py`
> and `scripts/quant_daily_update.cmd`.
> **Last verified against the code:** 2026-10-24

Research and decision support only, not investment advice.

---

## 1. Purpose

The agents (market, news, debate, risk) are language models. They read news and argue well, but they are poor at
turning a column of prices into a forecast. The quant signal layer sits underneath them and supplies numbers that have
been tested, with their test status attached.

Its aim is to raise predictability **honestly**:

| Discipline | Where it is enforced |
|---|---|
| Point-in-time data: every row carries the session it became known (`known_from`) | `datastore.py`, `prices.py` ([11](11-nse-data-store.md)) |
| Walk-forward testing: settings chosen on past data, judged only on the next, unseen window | `evaluate.py`, `validation.py`, `vrp.py` ([12](12-evaluation-and-validation.md)) |
| Real Indian costs: Dhan brokerage, STT, exchange charges, SEBI fee, stamp duty, GST, slippage | `costs.py` ([14](14-option-strategy-simulators-and-costs.md)) |
| Eight success gates fixed before results are seen | `gates.py` ([12](12-evaluation-and-validation.md)) |
| Every trial logged, so the deflated Sharpe ratio counts all ideas tried | `trial_log.py` |
| Rules frozen in git before a test; forward paper trading as the decisive test | [../plans/PROOF_PLAN.md](../plans/PROOF_PLAN.md), `paper.py` ([15](15-daily-refresh-and-paper-trading.md)) |

**Signals only.** Nothing here places orders. The user trades by hand on Dhan; the layer produces numbers, verdicts and
reports. Position size is always a value the user sets (`sizing.py` takes the capital as an input and stores nothing).

The full plan is [../plans/QUANT_SIGNAL_LAYER_PLAN.md](../plans/QUANT_SIGNAL_LAYER_PLAN.md); progress is in
[../PROGRESS_TRACKER.md](../PROGRESS_TRACKER.md). How the layer fits the rest of the system is in
[01-system-overview.md](01-system-overview.md).

## 2. Module map — `tradingagents/analytics/`

| Module | One line |
|---|---|
| `universe.py` | The fixed research universe: 29 F&O stocks + NIFTY, BANKNIFTY; Yahoo tickers; the survivorship note |
| `backfill.py` | Resumable, throttled download of NSE archive files (F&O bhavcopy, participant OI, delivery, index closes) with a manifest |
| `datastore.py` | Parses the raw files into a point-in-time Parquet store; `known_from`, `as_of`, atomic writes, lot sizes |
| `prices.py` | Daily OHLCV from Yahoo, NSE index bars replacing Yahoo's, stock gaps filled from NSE, quality report |
| `quotes.py` | Nightly NSE option bid/ask snapshot and real half-spread vs the slippage model |
| `costs.py` | Dhan + statutory charges at 2026 rates, and the `Slippage` model |
| `gates.py` | The eight success gates and their thresholds |
| `validation.py` | Walk-forward splits, Sharpe, probabilistic and deflated Sharpe ratio, evidence verdict |
| `trial_log.py` | SQLite log of every backtest run; the honest trial count |
| `evaluate.py` | The Phase 2 harness: walk-forward with costs, trade ledger, baselines, random entry, leak check, gates |
| `swings.py` | Swing points that carry the date they were confirmed; `find_lookahead` repaint detector |
| `volatility_model.py` | GARCH / GJR / EGARCH, historical and EWMA forecasts; QLIKE scoring and model comparison |
| `implied_vol.py` | Black-76 ATM implied vol per expiry and a 30-day constant-maturity IV |
| `regime.py` | 3-state Gaussian HMM with forward-filtered probabilities and stable labels |
| `chronos_vol.py` | Chronos-Bolt pretrained volatility forecasts (tested, not kept) |
| `condor.py` | End-of-day iron-condor simulator, including staggered books |
| `vrp.py` | Volatility risk premium signal and its walk-forward test on condors; pooling across indices |
| `quiet_condor.py` | Condors on the 5 stocks GARCH predicts quietest (rejected) |
| `events.py` | Results-day iron butterfly on stock options, overpriced filter (both rejected) |
| `stress.py` | Stage 2 stress helpers: scaled costs and slippage, block bootstrap, drawdown Monte Carlo |
| `holdout.py` | Backward holdout of the frozen VRP condor on 2015–2021, built in memory |
| `sizing.py` | ¼-Kelly position sizing capped at 1% risk; lot-rounded quantity |
| `paper.py` | Forward paper-trading ledger: integrity check, kill rules, report |
| `paper_strategies.py` | The strategies admitted to paper trading (the pooled VRP condor, observation only) |
| `quant_report.py` | Plain-text quant context for the agents (`quant_signal_text`) |
| `replay_check.py` | Phase 9 check rules: unsupported numbers and validation claims in agent text |
| `journal.py` | Trade journal: the user's own Dhan tradebook as FIFO round trips and breakdowns |
| `ml/` | LightGBM pipeline: labels, features, purged walk-forward, calibration, relative strength, move size (dropped) |

## 3. Scripts map — `scripts/`

| Script | What it does | Detail |
|---|---|---|
| `quant_backfill.py` | Downloads NSE archive files (`--start`, `--end`, `--kinds`, `--interval`, `--retry-missing`) | [11](11-nse-data-store.md) |
| `quant_build_store.py` | Builds the Parquet store, prices, quality report and 30-day IV (`--years`, `--datasets`, `--skip-prices`, `--skip-iv`) | [11](11-nse-data-store.md) |
| `quant_vol_forecasts.py` | GARCH / GJR / EGARCH / hist / EWMA forecasts per symbol and the QLIKE comparison | [13](13-volatility-and-regime-models.md) |
| `quant_regime.py` | Fits the regime HMM on NIFTY, saves probabilities and labels | [13](13-volatility-and-regime-models.md) |
| `quant_evaluate.py` | Runs a signal through the Phase 2 harness (`--signal`, `--position-value`) | [12](12-evaluation-and-validation.md) |
| `quant_vrp_condor.py` | VRP condor walk-forward on NIFTY and BANKNIFTY | [14](14-option-strategy-simulators-and-costs.md) |
| `quant_quiet_condor.py` | Quiet-stock condor test | [14](14-option-strategy-simulators-and-costs.md) |
| `quant_results_fly.py` | Results-day iron butterfly (`--overpriced` for the re-test) | [14](14-option-strategy-simulators-and-costs.md) |
| `quant_stress.py` | Stage 2 stress tests of the frozen VRP condor | [12](12-evaluation-and-validation.md) |
| `quant_holdout.py` | Backward holdout of the frozen VRP condor | [12](12-evaluation-and-validation.md) |
| `quant_ml.py`, `quant_relative.py`, `quant_move_size.py` | LightGBM tests (direction, relative strength, move size) | [13](13-volatility-and-regime-models.md) |
| `quant_chronos.py` | Chronos-Bolt vs GARCH | [13](13-volatility-and-regime-models.md) |
| `quant_paper.py` | Updates the paper-trading ledger and prints reports (`--report`) | [15](15-daily-refresh-and-paper-trading.md) |
| `quant_option_quotes.py` | Captures the option bid/ask snapshot and reports spreads (`--report`) | [../features/option-quotes.md](../features/option-quotes.md) |
| `quant_daily_update.py` / `.cmd` | The after-close refresh that runs all of the above that must be refreshed daily | [15](15-daily-refresh-and-paper-trading.md) |
| `quant_replay.py` | Phase 9 replay of 10 full agent analyses and the check | [16](16-quant-context-in-agents.md) |
| `market_map.py` (+ `market_map_template.html`) | Builds the Market Map HTML page | [17](17-market-map.md) |
| `trade_journal.py` | Analyses the user's own Dhan tradebook | [../features/trade-journal.md](../features/trade-journal.md) |
| `update_progress.py` | Recalculates the bars in `docs/PROGRESS_TRACKER.md` | — |

## 4. Data flow

```
 NSE archives (F&O bhavcopy, participant OI,          Yahoo Finance (daily OHLCV,
 MTO delivery, official index closes)                 through the data layer)
            │  backfill.py (manifest, throttled)                │
            ▼                                                   │
 ~/.tradingagents/cache/quant/raw/<kind>/<year>/  ──────────────┤
            │  datastore.build_year                             │  prices.py
            ▼                                                   ▼  (NSE index bars, NSE gap fills)
 ~/.tradingagents/cache/quant/store/
   fo_summary · option_chain · participant · delivery · index_close · prices · iv
            │
   ┌────────┼──────────────────────┬──────────────────────────┐
   ▼        ▼                      ▼                          ▼
 volatility_model     implied_vol (iv30)            regime (HMM)             condor / vrp / events
 vol_forecasts/       iv/iv30.parquet               regime/regime.parquet    (backtests → trial_log.sqlite)
   │                      │                              │                          │
   └──────────────────────┴───────────────┬──────────────┘                          │
                                          ▼                                         ▼
                        quant_report.quant_signal_text  ◄──── validation status ── trial log
                                          │
             ┌────────────────────────────┼─────────────────────────┐
             ▼                            ▼                         ▼
   get_quant_signal_report tool   report section "VI. Quant Context"   quant_replay / replay_check
   (market analyst)               (Markdown + HTML)                    (Phase 9 exit check)

 Daily job (weekdays 19:30): download → store → volatility → regime → tracker → market_map → paper → quotes
```

## 5. What is in use, and what was rejected

As recorded in [../PROGRESS_TRACKER.md](../PROGRESS_TRACKER.md) ("Where this leaves us", 2026-10-24). **No trading
signal has passed its tests.** What is in use is used as a **risk input**, never as a reason to buy or sell.

### In use (risk inputs)

| Item | Evidence |
|---|---|
| GARCH volatility forecasts | Beat 20-session historical vol out of sample on 31/31 symbols |
| Regime model (HMM) | Next-21-day vol calm 11.5% vs choppy 15.1% (p = 0.026); returns by regime not significant (p = 0.14), so not a direction signal |
| Expected move (1 standard deviation from the GARCH forecast) | Built on the GARCH result; GARCH alone also ranks next-move size at AUC 0.573 |

### Rejected or not kept

| Tested | Verdict | Key numbers |
|---|---|---|
| 50/200 moving-average trend | rejected | beats random timing only 6% |
| VRP iron condor (NIFTY, BANKNIFTY) | rejected | only 15–19 trades in 5 years |
| VRP iron condor, 4 books, pooled (re-test) | rejected by the backward holdout | 2021–26 strong (84 trades); 2015–21: −5.6% of risk per trade, beats random 60% |
| LightGBM "will it rise" (price; + NSE OI/PCR/flow) | rejected | same-day AUC 0.505 / 0.502 |
| LightGBM "will it beat the other 28" (+ buffer re-test) | rejected | AUC 0.507 / 0.510; −1.2% / −1.0% a year after costs |
| LightGBM "how big will the move be" | no skill | AUC 0.503 (GARCH alone: 0.573) |
| Condors on the 5 GARCH-quietest stocks | rejected | Sharpe −0.44 |
| Chronos-Bolt pretrained model | not kept | 10-session QLIKE 0.382 vs GARCH 0.336 |
| Results-day iron butterfly | rejected | 984 trades, −6.5% of max risk per trade |
| Results-day fly, only overpriced events | rejected | 745 trades, −4.7% of max risk per trade |

The pooled VRP condor still runs in paper trading as **observation only** (the user's choice), from 2026-10-26; it is
never reported as passing. Further LightGBM work and the MA trend rule were dropped at the user's request
(2026-10-23).

## 6. Where to read next

- [11 — NSE data store](11-nse-data-store.md)
- [12 — Evaluation and validation](12-evaluation-and-validation.md)
- [13 — Volatility and regime models](13-volatility-and-regime-models.md)
- [14 — Option strategy simulators and costs](14-option-strategy-simulators-and-costs.md)
- [15 — Daily refresh and paper trading](15-daily-refresh-and-paper-trading.md)
- [16 — Quant context in the agents](16-quant-context-in-agents.md)
- [17 — Market Map](17-market-map.md)
- [18 — Executive summary](18-executive-summary.md)

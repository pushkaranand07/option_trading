# 08 — Option backtester (optopsy engine)

> **Status:** Current.
> **Scope:** `option_backtester/` (the options engine moved in from optopsy, AGPL-3.0),
> `tradingagents/integrations/optopsy/` (`bridge.py`, `adapter.py`), and the fixes made to them. The quant layer's
> own strategy simulators are separate: [14-option-strategy-simulators-and-costs.md](14-option-strategy-simulators-and-costs.md).
> **Last verified against the code:** 2026-10-24

---

## 1. What it is

`option_backtester` is an options-strategy backtesting library. It came from the separate optopsy project (version
string `__version__ = "2.3.0"` in `option_backtester/__init__.py`) and was moved into this repository so it runs in
TradingAgents' own Python environment. Why it was moved: the optopsy environment ran Python 3.13.2 with pandas 3.0.1
and `pandas-ta-classic`; TradingAgents ran Python 3.13.5 with pandas 3.0.6 and no `pandas-ta-classic`
(build plan problem P-15, section 13 of
[INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md](../plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md)).

What was brought over: the engine core, `strategies/`, `signals/`, and its `LICENSE`. What was left out: optopsy's chat
UI, its EODHD downloader and parquet cache, and its tests, docs and samples. `load_cached_options` /
`load_cached_stocks` still exist but raise an error saying the EODHD cache is not part of TradingAgents.

Its two extra dependencies are pinned in `pyproject.toml` to the versions optopsy was tested with:
`pandas-ta-classic>=0.3.59,<0.4` and `empyrical-reloaded>=0.5.12,<0.6` (plus `pydantic>=2.0,<3.0`).

Nothing in the agent pipeline calls this engine today. It is used by `scripts/india_live_check.py` and the tests.

## 2. License

optopsy is AGPL-3.0-or-later; TradingAgents is Apache-2.0. `option_backtester/LICENSE` holds the AGPL text and is
shipped as package data (`[tool.setuptools.package-data]`). From the build plan: private use of the combined code is
fine; distributing it, or letting others use it over a network, brings the AGPL's source-sharing obligations for the
combined work. Keep the LICENSE file and get legal advice before distributing. Ruff excludes `option_backtester`
(`extend-exclude` in `pyproject.toml`): it keeps its upstream style.

## 3. Package structure

| Module | Role |
|---|---|
| `__init__.py` | Public API: data feeds, strategies, signals, metrics, `simulate`, `simulate_portfolio` |
| `datafeeds.py` | `csv_data()` (map CSV columns by index), `options_data()` (validate a named DataFrame) |
| `types.py` | Pydantic models — `StrategyParams`, `CalendarStrategyParams`, `Commission`, `TargetRange`, `SimulatorParams`: the single source of defaults and validation (`extra="forbid"` catches typos) |
| `checks.py` | Parameter and schema validation before a run |
| `core.py` | The pipeline: validate → evaluate → build legs → apply rules → price → output |
| `evaluation.py` | Entry/exit matching per contract; `_calls` / `_puts` filters |
| `filters.py` | Row filters: DTE, OTM %, delta, bid/ask, signal dates |
| `rules.py` | Strike / expiration rules for multi-leg structures |
| `pricing.py` | Fill prices under slippage models, commissions, P&L |
| `exits.py` | Early exits: stop-loss, take-profit, `max_hold_days` |
| `calendar.py` | Calendar and diagonal spreads (different expirations) |
| `output.py`, `definitions.py` | Raw trade rows or grouped statistics (with `win_rate`, `profit_factor`) |
| `metrics.py` | Sharpe, Sortino, Calmar, VaR, CVaR, max drawdown, omega, tail ratio, profit factor, win rate |
| `simulator.py` | `simulate()` — chronological replay with capital, position limits and an equity curve |
| `plugins.py` | Entry-point discovery for extra strategies and signals |
| `timestamps.py` | Date normalisation for joining chains with signal data |
| `strategies/` | The strategy functions (section 4) |
| `signals/` | Entry/exit signals (section 5) |

### 3.1 Input schema

A chain is one row per contract per quote date. `options_data()` requires `underlying_symbol, option_type,
expiration, quote_date, strike, bid, ask, delta`; extra columns (volume, open interest, IV) pass through.

### 3.2 Main parameters (`StrategyParams`)

| Parameter | Default | Meaning |
|---|---|---|
| `max_entry_dte` | 90 | Enter only contracts with at most this many days to expiry (DTE) |
| `exit_dte` | 0 | Planned exit at this DTE (0 = hold to expiry) |
| `exit_dte_tolerance`, `dte_interval`, `delta_interval` | 0, 7, 0.05 | Matching and grouping |
| `min_bid_ask` | 0.05 | Minimum quote |
| `leg1_delta` … `leg4_delta` | None | Per-leg delta target, as `{"target", "min", "max"}` |
| `entry_dates`, `exit_dates` | None | Pre-computed signal dates |
| `slippage` | `"spread"` | `mid`, `spread`, `liquidity` or `per_leg` |
| `commission` | None | Per-contract float, dict or `Commission(per_contract, per_share, base_fee, min_fee)` |
| `stop_loss`, `take_profit` | None | P&L thresholds (stop negative, take-profit positive) |
| `max_hold_days` | None | Time exit |
| `raw` | False | Return individual trades instead of grouped statistics |

`simulate(data, strategy, capital=100_000.0, quantity=1, max_positions=1, multiplier=100, selector="nearest", ...)`
replays the raw trades. `multiplier` defaults to 100 (US equity options); for NSE pass the lot size.

## 4. Strategies

40 strategy functions (`strategies/__init__.py`, `__all__` minus `Side`):

| Family | Functions |
|---|---|
| Singles | `long_calls`, `long_puts`, `short_calls`, `short_puts` |
| Straddles / strangles | `long_straddles`, `short_straddles`, `long_strangles`, `short_strangles` |
| Vertical spreads | `long_call_spread`, `short_call_spread`, `long_put_spread`, `short_put_spread` |
| Ratio spreads | `call_back_spread`, `put_back_spread`, `call_front_spread`, `put_front_spread` |
| Stock-and-option | `covered_call`, `protective_put`, `collar`, `cash_secured_put` |
| Butterflies | `long_call_butterfly`, `long_put_butterfly`, `short_call_butterfly`, `short_put_butterfly` |
| Condors | `long_call_condor`, `long_put_condor`, `short_call_condor`, `short_put_condor` |
| Iron | `iron_condor`, `reverse_iron_condor`, `iron_butterfly`, `reverse_iron_butterfly` |
| Calendar / diagonal | `long_call_calendar`, `short_call_calendar`, `long_put_calendar`, `short_put_calendar`, `long_call_diagonal`, `short_call_diagonal`, `long_put_diagonal`, `short_put_diagonal` |

(An iron condor sells a put spread and a call spread together; losses are capped by the bought wings.)

Each public function builds leg definitions `(Side.long/short, filter, quantity)` and calls the core pipeline.

**Trap:** the vertical spreads default both legs to 0.30 delta, which puts them on the same strike and returns an
empty result. Always pass distinct `leg1_delta` / `leg2_delta`. The engine default is left as upstream wrote it;
`OptopsyBridge.run_strategy` documents it.

## 5. Signals

`option_backtester/signals/` exports 107 names (the `Signal` type, combinators such as `and_signals`, and indicator
signals: moving-average crosses, RSI, Bollinger, ATR, ADX, IV rank, day-of-week, volume and more), built on
`pandas-ta-classic`. They produce `entry_dates` / `exit_dates` for the strategies.

## 6. The bridge (`tradingagents/integrations/optopsy/bridge.py`)

`OptopsyBridge` is TradingAgents' entry point to the engine:

| Method | What it does |
|---|---|
| `doctor()` | `{"healthy": True, python, pandas, numpy, option_backtester version and location, pandas_ta_classic, empyrical}`, or `{"healthy": False, "error": ...}` — a missing dependency is an answer, not a crash |
| `info()` | The same versions, raising on failure |
| `list_components()` | Every public strategy and signal with its one-line summary and signature |
| `run_strategy(name, chain, **params)` | Runs `option_backtester.<name>` on `options_data(chain)`. Converts `expiration` and `quote_date` to `datetime64[us]` first: under pandas 3 dates become `datetime64[s]`, which the engine's schema check rejects |

`OptopsyUnavailableError` is raised if the engine or a dependency cannot be imported.

## 7. Adapting NSE data (`tradingagents/integrations/optopsy/adapter.py`)

No free source has historical bid/ask for Indian options (build plan P-07). `bhavcopy_to_optopsy(bhav, symbol,
underlying=None, risk_free=0.065)` builds an end-of-day chain from the unified F&O bhavcopy rows produced by
`nse/derivatives.fo_bhavcopy` (see [07-india-market-layer.md](07-india-market-layer.md)):

| Step | Rule |
|---|---|
| Rows | Options of `symbol` only (`option_type` CE/PE) |
| Untraded contracts | Dropped (zero `contracts`): their close is a stale reference. **Except on expiry day** |
| Underlying | From the bhavcopy's `underlying_price` (UDiFF), or from `underlying` (trade date → spot close), which legacy-format rows need |
| Bid and ask | close ∓ a modelled half-spread, rounded outward to the ₹0.05 tick; default `cost_model_half_spread` = 1 tick + 1% of price (`half_spread=None` restores `bid = ask = close`) — [PA-05](../PA_05-garch-volatility-and-vrp-condor.md) |
| Time to expiry | Calendar days ÷ 365, at least 0.25 day |
| Delta | Black-Scholes delta, using the implied volatility solved from the close by bisection (`implied_vol`, range 0.005–5.0) |
| Non-invertible prices | Dropped and counted (close below intrinsic or otherwise outside what any volatility gives) |
| Expiry day | Every contract — traded or not — is valued at **intrinsic** against the underlying close: `bid = ask = max(0, spot − strike)` for calls, `max(0, strike − spot)` for puts; delta ±1 in the money, 0 otherwise |

`DEFAULT_RISK_FREE = 0.065` is noted in the code as roughly the India 91-day T-bill; pass the period's actual rate for
history. Every returned frame carries `attrs["approximations"]`: the close-as-bid/ask note, the risk-free rate used,
and the counts of untraded, expiry-settled and non-invertible contracts.

## 8. Fixes made to the engine and adapter

Commit `5dbb797` ("Fix three option_backtester / NSE adapter bugs", 2026-10-23), with regression tests in
`tests/test_option_backtester_fixes.py` that fail without each fix:

| # | Bug | Fix | Where |
|---|---|---|---|
| 1 | Early exits ignored the planned exit: with `exit_dte > 0`, the take-profit / stop-loss scan ran to the contract's last quote, so a threshold crossed *after* the planned exit could replace it | `_get_intermediate_snapshots` keeps only quotes with more than `exit_dte` days left | `option_backtester/exits.py` |
| 2 | Commission never reached realized P&L in the simulator's trade log | `_normalise_trades` carries `total_commission`; `_build_trade_log` deducts commission × quantity from `realized_pnl` and restates `pct_change` on the currency basis when commission is set | `option_backtester/simulator.py` |
| 3 | Expiry-day value used the option's last close, and untraded expiry-day contracts were dropped, so trades with an untraded wing vanished | Every expiry-day contract is valued at intrinsic against the underlying close (NSE final settlement) | `adapter.py` |

Commit `8df7ad0` (2026-10-23) replaced five `DataFrame.drop(inplace=True)` calls in `exits.py`, which pandas is
removing, with reassignment.

## 9. Known limitations

- **Modelled, not real, spreads.** NSE has no historical option bid/ask; the adapter builds bid/ask from the close
  with the project's cost model, which measured closing quotes put at ~1.2× the real spread on liquid strikes (some
  stocks are 3–5× wider). The `spread`, `liquidity` and `per_leg` slippage modes now act on it; until 2026-10-24
  `bid = ask = close` made them a no-op ([PA-05](../PA_05-garch-volatility-and-vrp-condor.md)).
- **End-of-day only.** One quote per contract per day; intraday stops are not modelled.
- **Close is not a tradeable price** for thinly traded strikes even when `contracts > 0`.
- **Delta depends on the assumed risk-free rate** and on the close being a fair price.
- **Not wired into the agents.** The analysts do not run option backtests.

How to run one: [../features/option-backtester.md](../features/option-backtester.md).

This is research tooling, not investment advice.

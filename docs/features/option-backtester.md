# Option backtester

> **Status:** Current.
> **Scope:** running an options-strategy backtest with `option_backtester` on NSE data via
> `tradingagents/integrations/optopsy/` — inputs, outputs, known limitations.
> Architecture: [../architecture/08-option-backtester.md](../architecture/08-option-backtester.md).
> **Last verified against the code:** 2026-10-24

---

## 1. What it does

Backtests options strategies (40 built in: singles, straddles, strangles, vertical and ratio spreads, butterflies,
condors, iron condors / butterflies, calendars, diagonals) on a historical option chain. For NSE, the chain is built
from NSE's end-of-day F&O bhavcopies. There is no CLI command or agent tool for it; it is used from Python
(and by `scripts/india_live_check.py`).

Results are research only and, on NSE data, optimistic (section 5). Not investment advice.

## 2. Check the install

```python
from tradingagents.integrations.optopsy import OptopsyBridge

bridge = OptopsyBridge()
print(bridge.doctor())               # {"healthy": True, "python": ..., "pandas": ..., ...}
comps = bridge.list_components()     # {"strategies": {...}, "signals": {...}}
```

The engine's dependencies (`pandas-ta-classic`, `empyrical-reloaded`, `pydantic`) are core dependencies in
`pyproject.toml`, so `pip install -e .` installs them.

## 3. Running a backtest on NSE data

This mirrors `p15_optopsy()` in `scripts/india_live_check.py`. It needs the network the first time (bhavcopies are
then cached forever under `~/.tradingagents/cache/nse/`).

```python
from datetime import timedelta
import pandas as pd

from tradingagents.dataflows.vendors.nse import NSECalendar, now_ist
from tradingagents.dataflows.vendors.nse.derivatives import fo_bhavcopy
from tradingagents.integrations.optopsy import OptopsyBridge, bhavcopy_to_optopsy

cal = NSECalendar.from_nse()
end = cal.latest_session(now_ist().date() - timedelta(days=1))
frames = [fo_bhavcopy(day) for day in cal.sessions_between(end - timedelta(days=45), end)]
bhav = pd.concat(frames, ignore_index=True)

nifty = bhav[bhav["symbol"] == "NIFTY"]
spot = nifty.groupby("trade_date")["underlying_price"].first()
near = nifty[(nifty["strike"] - nifty["trade_date"].map(spot)).abs() <= 1000]   # strikes within 1,000 points

chain = bhavcopy_to_optopsy(near, "NIFTY")
print(chain.attrs["approximations"])

legs = {"leg1_delta": {"target": 0.10, "min": 0.05, "max": 0.20},   # long (protective) put
        "leg2_delta": {"target": 0.30, "min": 0.20, "max": 0.40}}   # short put
bridge = OptopsyBridge()
stats = bridge.run_strategy("short_put_spread", chain, max_entry_dte=14, exit_dte=0, **legs)
trades = bridge.run_strategy("short_put_spread", chain, max_entry_dte=14, exit_dte=0, raw=True, **legs)
```

(A short put spread sells a put and buys a further out-of-the-money put; the loss is capped by the bought put.)

The script wraps each `fo_bhavcopy` call in `try/except` and skips days that fail; do the same.

### 3.1 Simulating with capital and lot size

`run_strategy` returns per-trade or grouped returns. For a chronological replay with capital, position limits and an
equity curve, call the engine's `simulate` on a chain prepared the same way. Pass the NSE lot size as `multiplier`
(the default 100 is for US options) — read it from `get_india_fo_contract_info` or `LotSizeHistory`, never from
memory.

```python
import option_backtester as op

data = op.options_data(chain.assign(
    expiration=pd.to_datetime(chain["expiration"]).astype("datetime64[us]"),
    quote_date=pd.to_datetime(chain["quote_date"]).astype("datetime64[us]")))
result = op.simulate(data, op.short_put_spread, capital=<capital>, quantity=1, multiplier=<lot size>,
                     max_entry_dte=14, exit_dte=0, commission=<₹ per contract>, **legs)
result.trade_log; result.equity_curve; result.summary
```

The `datetime64[us]` conversion is what `run_strategy` does for you: under pandas 3 the dates would otherwise be
`datetime64[s]`, which the engine rejects.

## 4. Inputs and outputs

### 4.1 Inputs

| Input | Notes |
|---|---|
| Chain | Columns `underlying_symbol, option_type, expiration, quote_date, strike, bid, ask, delta` (+ optional `implied_volatility`, `volume`, `open_interest`). From `bhavcopy_to_optopsy`, or any CSV via `op.csv_data` |
| `bhavcopy_to_optopsy(bhav, symbol, underlying=None, risk_free=0.065)` | `underlying` (trade date → spot close) is required for bhavcopies in the legacy format (before 2024-07-08), which carry no underlying price |
| Strategy parameters | `max_entry_dte` (default 90), `exit_dte` (0 = hold to expiry), `legN_delta`, `stop_loss`, `take_profit`, `max_hold_days`, `commission`, `slippage`, `raw` — full list in [08](../architecture/08-option-backtester.md#32-main-parameters-strategyparams). Unknown names are rejected |

### 4.2 Outputs

| Call | Returns |
|---|---|
| strategy with `raw=False` (default) | Grouped statistics by DTE and delta bucket: count, mean, std, quartiles of `pct_change`, plus `win_rate` and `profit_factor` |
| strategy with `raw=True` | One row per trade, with leg strikes, entry / exit prices, `pct_change` (and `exit_type` when early exits apply) |
| `op.simulate(...)` | `SimulationResult(trade_log, equity_curve, summary)`; the summary includes Sharpe, Sortino, VaR, CVaR, Calmar and drawdown |
| `chain.attrs["approximations"]` | What was approximated and how many contracts were dropped or settled at intrinsic |

## 5. Known limitations

- **No real bid/ask.** NSE has no free historical option bid/ask, so `bid = ask = close`. The slippage models scale
  the bid-ask half-spread, which is then zero, so `slippage` settings change nothing. Add costs through
  `commission`, and treat P&L as optimistic.
- **End-of-day only.** Stops and targets are checked on daily closes.
- **Untraded contracts are dropped** (except on expiry day), so a strategy may find no candidates on thin strikes.
- **Delta is model-derived** (Black-Scholes, with IV solved from the close and an assumed 6.5% risk-free rate).
- **Expiry-day value is intrinsic** against the underlying's close, which is how NSE settles index options; the
  underlying close is the bhavcopy's underlying price.
- **Vertical-spread default trap.** Without distinct `leg1_delta` / `leg2_delta`, the result is empty.
- **License.** The engine is AGPL-3.0; see [08](../architecture/08-option-backtester.md#2-license) before
  distributing.

For the quant layer's own condor / fly simulators with Indian costs, see
[../architecture/14-option-strategy-simulators-and-costs.md](../architecture/14-option-strategy-simulators-and-costs.md).

## 6. Files and tests

`option_backtester/`, `tradingagents/integrations/optopsy/bridge.py`, `tradingagents/integrations/optopsy/adapter.py`;
tests `tests/test_optopsy_bridge_compliance.py` and `tests/test_option_backtester_fixes.py`.

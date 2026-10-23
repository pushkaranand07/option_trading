"""Phase 2 of the quant plan: the evaluation harness.

The exit gate of Phase 2: random strategies must come out not significant, so
the harness is not biased upward; and a planted real edge must be found.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import evaluate as ev


def synthetic(n=1500, symbols=("A", "B", "C", "D", "E"), phi=0.0, sigma=0.02, seed=0):
    """Open = close = a price whose session returns follow AR(1) with coefficient ``phi``."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    cols = {}
    for s in symbols:
        e = rng.normal(0, sigma, n)
        r = np.zeros(n)
        for i in range(1, n):
            r[i] = phi * r[i - 1] + e[i]
        cols[s] = 100 * np.exp(np.cumsum(r))
    price = pd.DataFrame(cols, index=idx)
    long = price.stack().rename("close").reset_index()
    long.columns = ["trade_date", "symbol", "close"]
    long["trade_date"] = long["trade_date"].dt.date
    for c in ("open", "high", "low", "adj_close"):
        long[c] = long["close"]
    long["volume"] = 1e6
    return ev.panel(long)


def lagged_momentum(data, params):
    """Sign of the last known session return; uses closes up to t-1 only."""
    close = data["close"]
    return np.sign(close.pct_change(params.get("n", 1))).shift(1).fillna(0.0)


def coin_flip(data, params):
    rng = np.random.default_rng(params["seed"])
    return pd.DataFrame(rng.choice([-1.0, 0.0, 1.0], size=data["close"].shape),
                        index=data.index, columns=data["close"].columns)


def peeks_today(data, params):
    return np.sign(data["close"].pct_change()).fillna(0.0)


def peeks_tomorrow(data, params):
    return np.sign(data["close"].pct_change().shift(-1)).fillna(0.0)


@pytest.mark.unit
def test_session_return_runs_open_to_next_open():
    data = synthetic(n=5, symbols=("A",))
    r = ev.session_returns(data)["A"]
    opens = data["open"]["A"]
    assert r.iloc[0] == pytest.approx(opens.iloc[1] / opens.iloc[0] - 1)
    assert np.isnan(r.iloc[-1])


@pytest.mark.unit
def test_costs_are_charged_on_position_changes_only():
    data = synthetic(n=6, symbols=("A",))
    pos = pd.DataFrame({"A": [0, 1, 1, 1, 0, 0]}, index=data.index, dtype=float)
    cost = pd.Series({"A": 0.004})
    net = ev.strategy_returns(data, pos, cost)["A"]
    gross = ev.session_returns(data)["A"].fillna(0)
    assert net.iloc[1] == pytest.approx(gross.iloc[1] - 0.002)       # entry: half a round trip
    assert net.iloc[2] == pytest.approx(gross.iloc[2])               # holding: free
    assert net.iloc[4] == pytest.approx(-0.002)                      # exit
    trades = ev.trade_ledger(data, pos, cost)
    assert len(trades) == 1 and trades[0].sessions == 3
    expected = (1 + gross.iloc[1:4]).prod() - 1 - 0.004
    assert trades[0].net_return == pytest.approx(expected)


@pytest.mark.unit
def test_leak_check_passes_honest_signals_and_catches_peeking():
    data = synthetic(n=400, symbols=("A", "B"))
    assert ev.same_bar_leaks(lagged_momentum, data, {}) == []
    assert ev.same_bar_leaks(peeks_today, data, {})
    assert ev.same_bar_leaks(peeks_tomorrow, data, {})


@pytest.mark.unit
def test_neighbours_are_one_step_away_in_one_parameter():
    grid = [{"a": a, "b": b} for a in (1, 2, 3) for b in (10, 20)]
    got = ev._neighbours(grid, {"a": 2, "b": 10})
    assert {(g["a"], g["b"]) for g in got} == {(1, 10), (3, 10), (2, 20)}


@pytest.mark.unit
def test_random_strategy_is_never_approved(tmp_path, monkeypatch):
    monkeypatch.setattr(ev.trial_log, "default_path", lambda: tmp_path / "t.sqlite")
    data = synthetic(phi=0.0, seed=3)
    result = ev.evaluate("coin-flip", coin_flip, [{"seed": s} for s in range(5)], data,
                         position_value=100_000, train=500, test=125, embargo=5, random_runs=200)
    assert result.verdict != "significant"
    assert not result.gates.approved
    assert result.leaks == []
    assert result.stats.n > 100
    assert len(ev.trial_log.load("coin-flip")) == 1


@pytest.mark.unit
def test_a_planted_edge_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(ev.trial_log, "default_path", lambda: tmp_path / "t.sqlite")
    data = synthetic(phi=0.5, seed=4)   # lag-2 autocorrelation 0.25: momentum on t-2 pays
    result = ev.evaluate("momentum", lagged_momentum, [{"n": 1}, {"n": 2}], data,
                         position_value=500_000, train=500, test=125, embargo=5, random_runs=200)
    assert result.oos_sharpe > 1.0, result.summary()
    assert result.deflated_sharpe > 0.95
    assert result.random_percentile >= 0.95
    assert result.stats.expectancy > 0
    assert "Same-bar leaks: 0" in result.summary()


@pytest.mark.unit
def test_panel_puts_opens_on_the_dividend_adjusted_basis():
    prices = pd.DataFrame({
        "trade_date": [date(2026, 1, 1), date(2026, 1, 2)], "symbol": "A",
        "open": [100.0, 110.0], "high": [101.0, 111.0], "low": [99.0, 109.0],
        "close": [100.0, 110.0], "adj_close": [98.0, 110.0], "volume": [1.0, 1.0],
    })
    data = ev.panel(prices)
    assert data["open"]["A"].iloc[0] == pytest.approx(98.0)
    assert data["close"]["A"].iloc[0] == pytest.approx(98.0)

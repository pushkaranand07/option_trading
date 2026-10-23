"""One harness that judges every signal the same way (plan, Phase 2).

Conventions, enforced rather than trusted:

- **Data** is a wide DataFrame indexed by session date with MultiIndex columns
  ``(field, symbol)``: ``open``/``high``/``low``/``close``/``volume`` from
  adjusted prices, plus any feature fields. A feature row dated *d* holds what
  was published about session *d* (NSE files: after its close).
- **A signal** is ``signal(data, params) -> DataFrame`` of target positions in
  [-1, 1] per (session, symbol). The position for session *t* may use rows
  strictly before *t* only. :func:`same_bar_leaks` checks this by scrambling
  row *t* and seeing whether the position at *t* moves.
- **Execution**: a position for session *t* is entered at *t*'s open and its
  return runs open(t) -> open(t+1). This is when a manual trader can act on
  post-close data.
- **Costs**: each change in position pays half a round trip (``costs.py``) per
  unit changed, at the position size the caller passes. Size is never assumed.
- **Portfolio**: equal capital per symbol; the portfolio return is the mean of
  the symbols' returns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingagents.analytics import trial_log
from tradingagents.analytics.costs import (
    DEFAULT_RATES,
    DEFAULT_SLIPPAGE,
    ChargeRates,
    Slippage,
    cost_fraction,
)
from tradingagents.analytics.gates import (
    Evidence,
    GateReport,
    annual_return,
    check_gates,
    max_drawdown,
)
from tradingagents.analytics.validation import (
    deflated_sharpe_ratio,
    evidence_verdict,
    sharpe,
    walk_forward_splits,
)

Signal = Callable[[pd.DataFrame, dict], pd.DataFrame]

# Plan, Phase 2 defaults: 3 years train, 6 months test, 20-session embargo.
TRAIN, TEST, EMBARGO = 756, 126, 20


# ---------------------------------------------------------------- data shape

def panel(prices: pd.DataFrame, features: Mapping[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Wide (field, symbol) frame from the long ``prices`` table, with opens/highs/lows
    put on the same dividend-adjusted basis as ``adj_close``."""
    p = prices.copy()
    p["trade_date"] = pd.to_datetime(p["trade_date"])
    factor = p["adj_close"] / p["close"]
    wide = {
        "open": p["open"] * factor, "high": p["high"] * factor, "low": p["low"] * factor,
        "close": p["adj_close"], "volume": p["volume"],
    }
    parts = {name: pd.DataFrame({"trade_date": p["trade_date"], "symbol": p["symbol"], "v": col})
             .pivot(index="trade_date", columns="symbol", values="v") for name, col in wide.items()}
    for name, frame in (features or {}).items():
        parts[name] = frame
    out = pd.concat(parts, axis=1).sort_index()
    out.columns.names = ["field", "symbol"]
    return out


def session_returns(data: pd.DataFrame) -> pd.DataFrame:
    """Return of holding through session t: open(t) -> open(t+1). The last session has none."""
    opens = data["open"]
    return opens.shift(-1) / opens - 1.0


# ---------------------------------------------------------------- causality

def same_bar_leaks(signal: Signal, data: pd.DataFrame, params: dict, samples: int = 25,
                   start: int = 300, seed: int = 0) -> list[pd.Timestamp]:
    """Sessions whose position depends on that session's own row or on later rows.

    The position for session t must be decided before t opens. For each sampled t:
    the position computed on data cut after t must equal the full-history one (no
    future rows used), and must not move when row t's values are scrambled (no
    same-session data used).
    """
    rng = np.random.default_rng(seed)
    n = len(data)
    if n <= start:
        start = max(1, n // 2)
    picks = sorted(set(rng.integers(start, n, size=min(samples, n - start)).tolist()))
    full = signal(data, params)
    leaks = []

    def same(a: pd.Series, b: pd.Series) -> bool:
        return np.allclose(a.fillna(0).to_numpy(float), b.fillna(0).to_numpy(float))

    for i in picks:
        cut = data.iloc[: i + 1].copy()
        honest = signal(cut, params).iloc[-1]
        numeric = cut.select_dtypes("number").columns
        cut.loc[cut.index[-1], numeric] = cut.loc[cut.index[-1], numeric] * rng.uniform(0.5, 1.5, len(numeric))
        scrambled = signal(cut, params).iloc[-1]
        if not (same(honest, full.iloc[i]) and same(honest, scrambled)):
            leaks.append(data.index[i])
    return leaks


# ---------------------------------------------------------------- returns and trades

def strategy_returns(data: pd.DataFrame, positions: pd.DataFrame, cost_per_unit: pd.Series) -> pd.DataFrame:
    """Per-symbol net returns: position x session return, minus cost on each change.

    ``cost_per_unit`` is the round-trip cost fraction per symbol; each unit of
    position change pays half of it.
    """
    pos = positions.reindex_like(data["open"]).fillna(0.0).clip(-1.0, 1.0)
    gross = pos * session_returns(data).fillna(0.0)
    turnover = pos.diff().abs()
    turnover.iloc[0] = pos.iloc[0].abs()
    return gross - turnover * (cost_per_unit.reindex(pos.columns).fillna(0.0) / 2.0)


@dataclass
class Trade:
    symbol: str
    direction: float
    entry: pd.Timestamp
    exit: pd.Timestamp
    sessions: int
    net_return: float


def trade_ledger(data: pd.DataFrame, positions: pd.DataFrame, cost_per_unit: pd.Series) -> list[Trade]:
    """Trades are runs of an unchanged non-zero position. A trade's return compounds
    its sessions' gross returns and pays half a round trip per unit of position
    changed on its way in and on its way out, as ``strategy_returns`` charges (so a
    1 -> 0.5 -> 0 path pays one round trip in total, not one and a half)."""
    rets = session_returns(data).reindex(positions.index).fillna(0.0)
    trades = []
    for symbol in positions.columns:
        pos = positions[symbol].fillna(0.0)
        before = pos.shift(1).fillna(0.0)
        after = pos.shift(-1).fillna(0.0)
        half = float(cost_per_unit.get(symbol, 0.0)) / 2.0
        run_id = (pos != pos.shift()).cumsum()
        for _, idx in pos.groupby(run_id).groups.items():
            size = float(pos.loc[idx[0]])
            if size == 0:
                continue
            gross = float((1.0 + size * rets[symbol].loc[idx]).prod() - 1.0)
            # A change between two non-flat runs (a resize or a flip) is one set of
            # orders, so each side of that boundary takes half of its charge.
            b, a = before.loc[idx[0]], after.loc[idx[-1]]
            moved = abs(size - b) * (0.5 if b else 1.0) + abs(a - size) * (0.5 if a else 1.0)
            net = gross - half * moved
            trades.append(Trade(symbol, size, idx[0], idx[-1], len(idx), net))
    return trades


@dataclass
class TradeStats:
    n: int
    hit_rate: float
    avg_win: float
    avg_loss: float
    payoff: float
    expectancy: float

    @classmethod
    def of(cls, trades: list[Trade]) -> TradeStats:
        r = np.array([t.net_return for t in trades], dtype=float)
        if len(r) == 0:
            return cls(0, np.nan, np.nan, np.nan, np.nan, np.nan)
        wins, losses = r[r > 0], r[r <= 0]
        avg_win = float(wins.mean()) if len(wins) else 0.0
        avg_loss = float(-losses.mean()) if len(losses) else 0.0
        return cls(len(r), float((r > 0).mean()), avg_win, avg_loss,
                   avg_win / avg_loss if avg_loss else np.inf, float(r.mean()))


# ---------------------------------------------------------------- baselines

def buy_and_hold(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=data.index, columns=data["open"].columns)


def moving_average_trend(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    close = data["close"]
    fast, slow = close.rolling(params.get("fast", 50)).mean(), close.rolling(params.get("slow", 200)).mean()
    return (fast > slow).astype(float).shift(1).fillna(0.0)


def random_entry_sharpes(trades: list[Trade], index: pd.Index, returns: pd.DataFrame, cost_per_unit: pd.Series,
                         runs: int = 1000, seed: int = 0) -> np.ndarray:
    """Portfolio Sharpes of the same trades (symbol, direction, length) at random start dates."""
    rng = np.random.default_rng(seed)
    n = len(index)
    by_symbol: dict[str, list[Trade]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)
    rets = returns.reindex(index).fillna(0.0).to_numpy(float)
    half_cost = (cost_per_unit.reindex(returns.columns).fillna(0.0) / 2.0).to_numpy(float)
    cols = {s: returns.columns.get_loc(s) for s in by_symbol}
    out = np.empty(runs)
    pos = np.zeros_like(rets)
    for k in range(runs):
        pos[:] = 0.0
        for symbol, ts in by_symbol.items():
            col = cols[symbol]
            for t in ts:
                length = min(t.sessions, n)
                s = int(rng.integers(0, n - length + 1))
                pos[s: s + length, col] = t.direction
        turnover = np.abs(np.diff(pos, axis=0, prepend=0.0))
        port = (pos * rets - turnover * half_cost).mean(axis=1)
        sd = port.std(ddof=1)
        out[k] = port.mean() / sd * np.sqrt(252) if sd > 0 else 0.0
    return out


# ---------------------------------------------------------------- walk-forward evaluation

@dataclass
class Evaluation:
    name: str
    position_value: float
    folds: list[dict]
    oos_positions: pd.DataFrame
    oos_net: pd.DataFrame
    trades: list[Trade]
    stats: TradeStats
    oos_sharpe: float
    in_sample_sharpe: float
    deflated_sharpe: float
    verdict: str
    leaks: list[pd.Timestamp]
    random_percentile: float | None
    baselines: dict[str, float]
    by_year: pd.DataFrame
    by_regime: dict[str, float] = field(default_factory=dict)
    gates: GateReport | None = None

    @property
    def portfolio_returns(self) -> pd.Series:
        return self.oos_net.mean(axis=1)

    def summary(self) -> str:
        s = self.stats
        r = self.portfolio_returns
        lines = [
            f"== {self.name} (position value Rs {self.position_value:,.0f}) ==",
            f"Out-of-sample: {r.index[0]:%Y-%m-%d} to {r.index[-1]:%Y-%m-%d}, {len(self.folds)} folds",
            f"Trades {s.n} | hit {s.hit_rate:.1%} | avg win {s.avg_win:.2%} | avg loss {s.avg_loss:.2%} | "
            f"payoff {s.payoff:.2f} | expectancy {s.expectancy:+.3%} per trade (after costs)",
            f"Sharpe IS {self.in_sample_sharpe:.2f} -> OOS {self.oos_sharpe:.2f} | DSR {self.deflated_sharpe:.2f} | "
            f"annual {annual_return(r):+.1%} | max DD {max_drawdown(r):.1%} | verdict {self.verdict}",
            "Baselines (OOS Sharpe): " + ", ".join(f"{k} {v:.2f}" for k, v in self.baselines.items()),
        ]
        if self.random_percentile is not None:
            lines.append(f"Beats random entry with the same trades in {self.random_percentile:.0%} of runs "
                         f"(needs >= 95%)")
        lines.append(f"Same-bar leaks: {len(self.leaks)}")
        if self.by_regime:
            lines.append("By regime (mean trade return): "
                         + ", ".join(f"{k} {v:+.3%}" for k, v in self.by_regime.items()))
        lines.append("By year:\n" + self.by_year.to_string(float_format=lambda x: f"{x:.3f}"))
        if self.gates is not None:
            lines.append(self.gates.summary())
        return "\n".join(lines)


def _neighbours(grid: list[dict], chosen: dict) -> list[dict]:
    """Grid points that differ from ``chosen`` in one parameter, by one step of its sorted values."""
    keys = list(chosen)
    values = {k: sorted({g[k] for g in grid if k in g}) for k in keys}
    out = []
    for g in grid:
        diff = [k for k in keys if g.get(k) != chosen.get(k)]
        if len(diff) == 1:
            k = diff[0]
            try:
                if abs(values[k].index(g[k]) - values[k].index(chosen[k])) == 1:
                    out.append(g)
            except ValueError:
                continue
    return out


def evaluate(
    name: str,
    signal: Signal,
    grid: list[dict],
    data: pd.DataFrame,
    position_value: float,
    segment: str = "futures",
    train: int = TRAIN,
    test: int = TEST,
    embargo: int = EMBARGO,
    regimes: pd.Series | None = None,
    regimes_switched_off: frozenset[str] = frozenset(),
    random_runs: int = 1000,
    rates: ChargeRates = DEFAULT_RATES,
    slippage: Slippage = DEFAULT_SLIPPAGE,
    log: bool = True,
    universe_note: str = "",
) -> Evaluation:
    """Walk-forward evaluation with costs, trade ledger, baselines and gates.

    ``position_value`` (Rs per position) must be given: flat brokerage makes the
    cost fraction depend on it, and the user sets it.
    """
    if not grid:
        raise ValueError("empty parameter grid")
    last_close = data["close"].ffill().iloc[-1]
    cost = pd.Series({s: cost_fraction(segment, float(px), position_value / float(px), rates, slippage)
                      for s, px in last_close.items() if pd.notna(px) and px > 0})

    folds, oos_pos, is_srs, trial_srs, neighbour_ratio_parts = [], [], [], [], []
    for split in walk_forward_splits(data.index, train, test, embargo=embargo):
        train_data = data.loc[split.train]
        scored = []
        for params in grid:
            r = strategy_returns(train_data, signal(train_data, params), cost).mean(axis=1)
            scored.append((sharpe(r), params))
            trial_srs.append(sharpe(r, 1))
        best_sr, best = max(scored, key=lambda s: s[0] if np.isfinite(s[0]) else -np.inf)
        neighbours = [sr for sr, p in scored if p in _neighbours(grid, best)]
        if neighbours and best_sr > 0:
            neighbour_ratio_parts.append(float(np.median(neighbours)) / best_sr)
        warm = data.loc[split.train[0]: split.test[-1]]
        pos = signal(warm, best).reindex(split.test)
        oos_pos.append(pos)
        is_srs.append(best_sr)
        folds.append({"params": best, "train_sharpe": best_sr,
                      "test_start": split.test[0], "test_end": split.test[-1]})
    if not folds:
        raise ValueError(f"{len(data)} sessions cannot fit train={train} + embargo={embargo} + test={test}")

    positions = pd.concat(oos_pos).fillna(0.0)
    oos_data = data.loc[positions.index[0]: positions.index[-1]]
    # Costs and returns over the stitched OOS span, so fold boundaries pay for real position changes.
    net = strategy_returns(oos_data, positions, cost)
    port = net.mean(axis=1)
    trades = trade_ledger(oos_data, positions, cost)
    stats = TradeStats.of(trades)
    oos_sr = sharpe(port)
    is_sr = float(np.mean(is_srs))
    dsr = deflated_sharpe_ratio(port, len(grid), trial_sharpes=trial_srs)
    verdict = evidence_verdict(stats.n, dsr)

    leaks = same_bar_leaks(signal, data, folds[-1]["params"])

    baselines = {}
    for bname, bsig in (("buy_and_hold", buy_and_hold), ("ma_50_200", moving_average_trend)):
        baselines[bname] = sharpe(strategy_returns(oos_data, bsig(data, {}).reindex(oos_data.index), cost)
                                  .mean(axis=1))
    random_pct = None
    if trades and random_runs:
        rand = random_entry_sharpes(trades, oos_data.index, session_returns(oos_data), cost, random_runs)
        random_pct = float((rand < oos_sr).mean())

    years = port.groupby(port.index.year)
    trades_per_year = pd.Series([t.entry.year for t in trades], dtype=int).value_counts()
    by_year = pd.DataFrame({
        "return": years.apply(lambda r: (1 + r).prod() - 1),
        "sharpe": years.apply(sharpe),
        "trades": trades_per_year.reindex(list(years.groups)).fillna(0).astype(int),
    })

    by_regime = {}
    if regimes is not None and trades:
        labels = regimes.reindex(pd.DatetimeIndex([t.entry for t in trades]), method="ffill")
        frame = pd.DataFrame({"regime": labels.to_numpy(), "r": [t.net_return for t in trades]}).dropna()
        by_regime = frame.groupby("regime")["r"].mean().to_dict()

    fold_returns = [float((1 + port.loc[f["test_start"]: f["test_end"]]).prod() - 1) for f in folds]
    evidence = Evidence(
        oos_returns=port, fold_returns=fold_returns, n_oos_trades=stats.n, deflated_sharpe=dsr,
        in_sample_sharpe=is_sr, oos_sharpe=oos_sr, lookahead_mismatches=len(leaks),
        regime_expectancy=by_regime or None, regimes_switched_off=regimes_switched_off,
        # The gate compares median(neighbours) / chosen. Each fold already gave that
        # ratio on its own training window, so pass their mean against a chosen of 1.
        chosen_sharpe=1.0 if neighbour_ratio_parts else None,
        neighbour_sharpes=[float(np.mean(neighbour_ratio_parts))] if neighbour_ratio_parts else None,
    )
    report = check_gates(evidence)

    result = Evaluation(name, position_value, folds, positions, net, trades, stats, oos_sr, is_sr, dsr, verdict,
                        leaks, random_pct, baselines, by_year, by_regime, report)
    if log:
        trial_log.record(trial_log.Trial(
            idea=name, params={"grid": grid, "position_value": position_value, "segment": segment},
            universe=universe_note, data_start=str(port.index[0].date()), data_end=str(port.index[-1].date()),
            n_trials=len(grid), n_oos_trades=stats.n, is_sharpe=is_sr, oos_sharpe=oos_sr, dsr=dsr,
            verdict=verdict, gate_verdict=report.verdict))
    return result

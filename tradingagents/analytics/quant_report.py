"""Plain-text quant context for the LLM agents (plan, Phase 9).

Reads only precomputed outputs (regimes, volatility forecasts, implied vol,
trial log) and only what was known on the analysis date: a value dated *d*
(published after *d*'s close) is used from session *d+1*. Nothing is fitted
here, so a tool call is fast and cannot change a result.

Every number carries its validation status. While no signal has passed the
gates, the report says so in so many words: the agents may use the numbers
as context (how volatile, what regime), never as a trade trigger.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.analytics import trial_log
from tradingagents.analytics.datastore import store_root
from tradingagents.analytics.universe import SURVIVORSHIP_NOTE, SYMBOLS, YAHOO_TICKERS

_FROM_YAHOO = {v.upper(): k for k, v in YAHOO_TICKERS.items()}


def store_symbol(ticker: str) -> str | None:
    """RELIANCE.NS / RELIANCE / ^NSEI -> the store's symbol, or None if outside the universe."""
    t = ticker.strip().upper()
    if t in _FROM_YAHOO:
        return _FROM_YAHOO[t]
    base = t.removesuffix(".NS").removesuffix(".BO")
    return base if base in SYMBOLS else None


def _known_rows(df: pd.DataFrame, on: date) -> pd.DataFrame:
    """Rows dated before ``on``: published after an earlier close, so known when ``on`` opens."""
    dates = pd.to_datetime(df.get("trade_date", df.index))
    return df[np.asarray(dates < pd.Timestamp(on))]


def _regime_lines(on: date, root: Path) -> list[str]:
    f = root / "regime" / "regime.parquet"
    if not f.exists():
        return ["Regime: not available (scripts/quant_regime.py has not been run)."]
    known = _known_rows(pd.read_parquet(f), on)
    if known.empty:
        return ["Regime: no estimate before this date."]
    last = known.iloc[-1]
    since = known[known["regime"] != last["regime"]]
    start = known.loc[since.index[-1] + 1, "trade_date"] if len(since) else known["trade_date"].iloc[0]
    return [f"Market regime (NIFTY, HMM, as of close {last['trade_date']}): {last['regime'].upper()} "
            f"since {start} (p calm {last['p_calm']:.2f}, choppy {last['p_choppy']:.2f}, "
            f"stress {last['p_stress']:.2f}). Regimes separate future volatility, not direction "
            "(return differences by regime were not significant)."]


def _vol_lines(symbol: str, on: date, root: Path) -> tuple[list[str], float | None]:
    f = root / "vol_forecasts" / f"{symbol}.parquet"
    if not f.exists():
        return [f"Volatility forecast: not available for {symbol}."], None
    known = _known_rows(pd.read_parquet(f), on)
    if known.empty:
        return ["Volatility forecast: none before this date."], None
    last, when = known.iloc[-1], known.index[-1]
    lines = [f"Volatility forecast for {symbol} (annualised, made after the close of {when:%Y-%m-%d}):"]
    for h in (5, 10, 21):
        lines.append(f"  next {h:>2} sessions: GARCH {last[f'garch_h{h}']:.1%}, GJR {last[f'gjr_h{h}']:.1%}, "
                     f"EWMA {last[f'ewma_h{h}']:.1%}")
    lines.append(f"  20-session historical: {last['hist_h21']:.1%}. Out of sample, GARCH beat historical vol "
                 "on all 31 symbols and EWMA only narrowly; for NIFTY, India VIX forecast better than both.")
    lines += _expected_move_lines(symbol, on, last, root)
    return lines, float(last["garch_h21"])


def _expected_move_lines(symbol: str, on: date, forecast: pd.Series, root: Path) -> list[str]:
    """One-standard-deviation move implied by the GARCH forecast: about 2 in 3 moves over the
    horizon stay inside it. A risk yardstick for stop distance and strike width, not a target."""
    close = None
    f = root / "prices" / "prices.parquet"
    if f.exists():
        p = _known_rows(pd.read_parquet(f, filters=[("symbol", "==", symbol)]), on)
        if len(p):
            close = float(p.sort_values("trade_date")["close"].iloc[-1])
    lines = ["Expected move (1 standard deviation, from the GARCH forecast; ~2 in 3 moves stay inside):"]
    for h in (5, 10, 21):
        pct = float(forecast[f"garch_h{h}"]) * (h / 252) ** 0.5
        rupees = f" = ±Rs {close * pct:,.0f} on the last close Rs {close:,.0f}" if close else ""
        lines.append(f"  next {h:>2} sessions: ±{pct:.1%}{rupees}")
    return lines


def _iv_lines(symbol: str, on: date, garch21: float | None, root: Path) -> list[str]:
    f = root / "iv" / "iv30.parquet"
    if not f.exists():
        return ["Implied vol: not available yet (the option-chain store is still being built)."]
    iv = _known_rows(pd.read_parquet(f).query("symbol == @symbol"), on)
    if iv.empty:
        return [f"Implied vol: none for {symbol} before this date."]
    last = iv.iloc[-1]
    lines = [f"30-day ATM implied vol ({last['trade_date']}): {last['iv30']:.1%}"]
    if garch21 is not None:
        vrp = iv.set_index(pd.to_datetime(iv["trade_date"]))["iv30"]
        lines.append(f"  IV minus GARCH 21-session forecast: {last['iv30'] - garch21:+.1%} "
                     "(positive = options priced above forecast volatility)")
        hist = vrp.iloc[-252:]
        if len(hist) > 60:
            pct = float((hist < last["iv30"]).mean())
            lines.append(f"  IV percentile over the past year: {pct:.0%}")
    return lines


BASELINE_IDEAS = {"random"}           # comparison baselines in the trial log, not signals
VERDICT_TEXT = {
    "reject": "rejected", "rejected": "rejected", "keep": "kept as a forecast input (not a trade signal)",
    "pass": "passed its backtest; forward paper trading pending, NOT approved",
    "predictive_check": "predictive check only (not a trade signal)",
    "holdout_fail": "rejected (failed the backward holdout)",
}


def _validation_lines(path: Path | None = None) -> list[str]:
    try:
        trials = trial_log.load(path=path)
    except Exception:
        trials = []
    latest = {}
    for t in trials:
        latest[t.idea] = t
    lines = ["Validation status of quant signals (latest run of each; gates = walk-forward, costs, "
             "deflated Sharpe, regime and parameter stability):"]
    if not latest:
        lines.append("  no signal has been tested yet.")
    for idea, t in sorted(latest.items()):
        if idea in BASELINE_IDEAS:
            continue
        # Tests judged by their own pre-declared rules (no gate run) record only a verdict.
        status = f"gates {t.gate_verdict}" if t.gate_verdict else VERDICT_TEXT.get(t.verdict, t.verdict or "not judged")
        sharpe = "" if t.oos_sharpe is None or t.oos_sharpe != t.oos_sharpe else f", Sharpe {t.oos_sharpe:.2f}"
        lines.append(f"  {idea}: {status}; {t.n_oos_trades or 0} out-of-sample trades{sharpe}")
    approved = [i for i, t in latest.items() if t.gate_verdict == "approved"]
    if approved:
        lines.append(f"Approved signals: {', '.join(approved)}.")
    else:
        lines.append("NO quant signal has passed the gates. Use the numbers above as context (volatility, "
                     "regime), NOT as a reason to buy or sell, and do not describe any of them as validated.")
    return lines


def quant_signal_text(ticker: str, on: str | date, root: Path | None = None,
                      trial_path: Path | None = None) -> str:
    root = root or store_root()
    day = pd.Timestamp(on).date()
    symbol = store_symbol(ticker)
    if symbol is None:
        return (f"Quant context: {ticker} is outside the research universe (29 NSE F&O stocks + NIFTY, "
                "BANKNIFTY), so no quant numbers exist for it.")
    vol, garch21 = _vol_lines(symbol, day, root)
    parts = [f"QUANT CONTEXT for {symbol} as known before the open of {day} (research only, not advice)",
             *_regime_lines(day, root), *vol, *_iv_lines(symbol, day, garch21, root),
             *_validation_lines(trial_path), SURVIVORSHIP_NOTE]
    return "\n".join(parts)


# ---------------------------------------------------------------- structured (web app)

def quant_signal_data(ticker: str, on: str | date, root: Path | None = None) -> dict:
    """The same numbers as ``quant_signal_text``, as a dict for the web app. Same timing rule: only
    values published before ``on`` opens. Missing pieces are ``None`` (never estimated)."""
    root = root or store_root()
    day = pd.Timestamp(on).date()
    symbol = store_symbol(ticker)
    out = {"symbol": symbol, "in_universe": symbol is not None, "as_of_open": str(day),
           "regime": None, "vol": None, "expected_move": None, "iv": None}
    f = root / "regime" / "regime.parquet"
    if f.exists():
        known = _known_rows(pd.read_parquet(f), day)
        if len(known):
            last = known.iloc[-1]
            since = known[known["regime"] != last["regime"]]
            start = known.loc[since.index[-1] + 1, "trade_date"] if len(since) else known["trade_date"].iloc[0]
            out["regime"] = {"name": str(last["regime"]), "since": str(start), "as_of": str(last["trade_date"]),
                             "p": {k: float(last[f"p_{k}"]) for k in ("calm", "choppy", "stress")}}
    if symbol is None:
        return out
    f = root / "vol_forecasts" / f"{symbol}.parquet"
    garch21 = None
    if f.exists():
        known = _known_rows(pd.read_parquet(f), day)
        if len(known):
            last, when = known.iloc[-1], known.index[-1]
            garch21 = float(last["garch_h21"])
            out["vol"] = {"as_of": f"{when:%Y-%m-%d}", "historical_20d": float(last["hist_h21"]),
                          **{f"h{h}": {m: float(last[f"{m}_h{h}"]) for m in ("garch", "gjr", "ewma")}
                             for h in (5, 10, 21)}}
            close = None
            pf = root / "prices" / "prices.parquet"
            if pf.exists():
                p = _known_rows(pd.read_parquet(pf, filters=[("symbol", "==", symbol)]), day)
                if len(p):
                    close = float(p.sort_values("trade_date")["close"].iloc[-1])
            moves = {}
            for h in (5, 10, 21):
                pct = float(last[f"garch_h{h}"]) * (h / 252) ** 0.5
                moves[f"h{h}"] = {"pct": pct, "rupees": close * pct if close else None}
            out["expected_move"] = {"close": close, **moves}
    f = root / "iv" / "iv30.parquet"
    if f.exists():
        iv = _known_rows(pd.read_parquet(f).query("symbol == @symbol"), day)
        if len(iv):
            last = iv.iloc[-1]
            hist = iv["iv30"].iloc[-252:]
            out["iv"] = {"as_of": str(last["trade_date"]), "iv30": float(last["iv30"]),
                         "minus_garch21": float(last["iv30"]) - garch21 if garch21 is not None else None,
                         "percentile_1y": float((hist < last["iv30"]).mean()) if len(hist) > 60 else None}
    return out

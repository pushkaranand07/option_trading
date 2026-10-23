"""Forward paper trading: the decisive, un-overfittable test (PROOF_PLAN.md, Stage 3).

A strategy's rules are frozen (docs/strategies/<name>.md). Every evening the
frozen backtest simulation is re-run on all data to date, and the trades it
enters on or after the strategy's paper start date are the paper trades. Nothing
is re-implemented for "live": the simulation is the strategy, and it is causal
(tested), so these are exactly the trades it would have made in real time.

Integrity: once recorded, a trade may only change from open to closed. If a
recorded trade later differs or disappears, data was revised or something peeked
ahead; the ledger records an integrity event and the report flags it.

Stored in SQLite (``<data_cache_dir>/quant/paper_ledger.sqlite``).
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import NormalDist

from tradingagents.dataflows.config import get_config

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS trades (
        key TEXT PRIMARY KEY, strategy TEXT NOT NULL, symbol TEXT, entry_date TEXT, expiry TEXT,
        strikes TEXT, credit REAL, lot INTEGER, max_risk REAL, status TEXT, exit_date TEXT,
        exit_reason TEXT, pnl REAL, return_on_risk REAL, first_seen TEXT, updated TEXT)""",
    """CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, strategy TEXT, kind TEXT, detail TEXT)""",
]


@dataclass(frozen=True)
class PaperStrategy:
    name: str
    spec: str                                   # docs/strategies/<name>.md
    start: date                                 # paper trades are those entered on or after this
    simulate: Callable[[], list]                # -> condor.CondorTrade list (open ones included)
    backtest_mean: float                        # backtest mean return on risk per trade
    backtest_sd: float                          # and its spread, for the band and the kill rules


def default_path() -> Path:
    path = Path(get_config()["data_cache_dir"]) / "quant"
    path.mkdir(parents=True, exist_ok=True)
    return path / "paper_ledger.sqlite"


def _connect(path: Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_path())
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


def _row(strategy: str, t) -> dict:
    strikes = json.dumps({k: float(v) for k, v in sorted(t.strikes.items())})
    symbol = getattr(t, "symbol", "")
    key = f"{strategy}|{symbol}|{t.entry_date}|{t.expiry}|{strikes}"
    closed = t.exit_date is not None
    return {"key": key, "strategy": strategy, "symbol": symbol, "entry_date": str(t.entry_date),
            "expiry": str(t.expiry), "strikes": strikes, "credit": round(float(t.credit), 6), "lot": int(t.lot),
            "max_risk": round(float(t.max_risk), 6), "status": "closed" if closed else "open",
            "exit_date": str(t.exit_date) if closed else None, "exit_reason": t.exit_reason or None,
            "pnl": round(float(t.pnl), 2) if closed else None,
            "return_on_risk": round(float(t.return_on_risk), 6) if closed else None}


_COMPARE = ("credit", "lot", "max_risk", "exit_date", "exit_reason", "pnl", "return_on_risk")


def update(strategy: PaperStrategy, trades: list, path: Path | None = None, now: datetime | None = None) -> dict:
    """Record the strategy's trades entered on/after its start date. Returns counts of
    new, newly closed and integrity events."""
    now = (now or datetime.now()).isoformat(timespec="seconds")
    fresh = {r["key"]: r for r in (_row(strategy.name, t) for t in trades)
             if date.fromisoformat(r["entry_date"]) >= strategy.start}
    counts = {"new": 0, "closed": 0, "integrity": 0}
    with closing(_connect(path)) as conn, conn:
        cols = ["key", *list(fresh[next(iter(fresh))].keys())[1:]] if fresh else []
        stored = {row[0]: dict(zip([c[0] for c in conn.execute("SELECT * FROM trades LIMIT 0").description],
                                   row, strict=True))
                  for row in conn.execute("SELECT * FROM trades WHERE strategy = ?", (strategy.name,))}
        for key, r in fresh.items():
            old = stored.get(key)
            if old is None:
                conn.execute(f"INSERT INTO trades ({', '.join(cols)}, first_seen, updated) "
                             f"VALUES ({', '.join('?' * len(cols))}, ?, ?)", [r[c] for c in cols] + [now, now])
                counts["new"] += 1
            elif old["status"] == "open" and r["status"] == "closed":
                conn.execute("UPDATE trades SET status='closed', exit_date=?, exit_reason=?, pnl=?, "
                             "return_on_risk=?, updated=? WHERE key=?",
                             (r["exit_date"], r["exit_reason"], r["pnl"], r["return_on_risk"], now, key))
                counts["closed"] += 1
            elif old["status"] == "closed" and any(old[c] != r[c] for c in _COMPARE):
                conn.execute("INSERT INTO events (at, strategy, kind, detail) VALUES (?, ?, ?, ?)",
                             (now, strategy.name, "changed", f"{key}: was {[old[c] for c in _COMPARE]}, "
                                                             f"now {[r[c] for c in _COMPARE]}"))
                counts["integrity"] += 1
        for key in stored:
            if key not in fresh:
                conn.execute("INSERT INTO events (at, strategy, kind, detail) VALUES (?, ?, ?, ?)",
                             (now, strategy.name, "disappeared", key))
                counts["integrity"] += 1
    return counts


@dataclass
class PaperReport:
    strategy: str
    start: date
    open_trades: int
    closed: list[float]
    integrity_events: int
    backtest_mean: float
    backtest_sd: float

    @property
    def n(self) -> int:
        return len(self.closed)

    @property
    def mean(self) -> float:
        return sum(self.closed) / self.n if self.n else float("nan")

    @property
    def p_value(self) -> float:
        """One-sided p of 'mean return on risk > 0' (normal approximation)."""
        if self.n < 2:
            return float("nan")
        m = self.mean
        sd = math.sqrt(sum((x - m) ** 2 for x in self.closed) / (self.n - 1))
        return 1.0 - NormalDist().cdf(m / (sd / math.sqrt(self.n))) if sd > 0 else float("nan")

    @property
    def trades_needed(self) -> int:
        """Trades for a 2-sigma result if the backtest's mean and spread hold."""
        return math.ceil((2 * self.backtest_sd / self.backtest_mean) ** 2) if self.backtest_mean > 0 else 0

    @property
    def losing_streak(self) -> int:
        worst = run = 0
        for x in self.closed:
            run = run + 1 if x <= 0 else 0
            worst = max(worst, run)
        return worst

    @property
    def below_band(self) -> bool:
        """Running total below the backtest's 5th-percentile path (kill rule)."""
        if not self.n:
            return False
        floor = self.n * self.backtest_mean - 1.645 * self.backtest_sd * math.sqrt(self.n)
        return sum(self.closed) < floor

    @property
    def kill(self) -> list[str]:
        reasons = []
        if self.below_band:
            reasons.append("running result below the backtest's 5th-percentile path")
        if self.losing_streak >= 8:
            reasons.append(f"{self.losing_streak} losing trades in a row")
        if any(x < -1.10 for x in self.closed):
            reasons.append("a trade lost more than its defined max risk (+10% costs): pricing or rule bug")
        if self.integrity_events:
            reasons.append(f"{self.integrity_events} integrity event(s): a recorded trade changed or vanished")
        return reasons

    def summary(self) -> str:
        lines = [f"== Paper: {self.strategy} (since {self.start}) ==",
                 f"Closed trades {self.n} | open {self.open_trades} | needed {max(30, self.trades_needed)} "
                 f"(at least 30; {self.trades_needed} at the backtest's mean {self.backtest_mean:+.1%} "
                 f"and spread {self.backtest_sd:.0%} of risk)"]
        if self.n:
            wins = sum(x > 0 for x in self.closed) / self.n
            lines.append(f"Mean return on risk {self.mean:+.2%} | wins {wins:.0%} | one-sided p(mean > 0) "
                         f"{self.p_value:.3f} | longest losing streak {self.losing_streak}")
        verdict = ("KILL: " + "; ".join(self.kill) if self.kill
                   else "PASS (Stage 3)" if self.n >= max(30, self.trades_needed) and self.p_value < 0.05
                   else "collecting evidence")
        lines.append(f"Status: {verdict}")
        return "\n".join(lines)


def report(strategy: PaperStrategy, path: Path | None = None) -> PaperReport:
    with closing(_connect(path)) as conn:
        rows = conn.execute("SELECT status, return_on_risk FROM trades WHERE strategy = ? ORDER BY exit_date, key",
                            (strategy.name,)).fetchall()
        events = conn.execute("SELECT COUNT(*) FROM events WHERE strategy = ?", (strategy.name,)).fetchone()[0]
    closed = [r for s, r in rows if s == "closed" and r is not None]
    return PaperReport(strategy.name, strategy.start, sum(s == "open" for s, _ in rows), closed, events,
                       strategy.backtest_mean, strategy.backtest_sd)

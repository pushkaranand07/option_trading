"""Every backtest run, kept forever, so the number of ideas tried is never hidden.

The deflated Sharpe ratio corrects for how many trials were run; that only works
if failed trials are counted too. Each run of an idea writes one row here, and
:func:`trial_count` gives the honest N for the next deflated Sharpe.

Stored in SQLite (standard library) under ``<data_cache_dir>/quant/trial_log.sqlite``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.dataflows.config import get_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TEXT NOT NULL,
    idea          TEXT NOT NULL,
    params        TEXT NOT NULL,
    universe      TEXT NOT NULL DEFAULT '',
    data_start    TEXT,
    data_end      TEXT,
    n_trials      INTEGER,
    n_oos_trades  INTEGER,
    is_sharpe     REAL,
    oos_sharpe    REAL,
    dsr           REAL,
    verdict       TEXT,
    gate_verdict  TEXT,
    notes         TEXT NOT NULL DEFAULT ''
)
"""

# Things that are not trials but must sit beside them: a split frozen, a holdout unlocked. Kept in their own
# table so they never change trial_count (the deflated Sharpe's N).
_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    detail  TEXT NOT NULL
)
"""


@dataclass
class Trial:
    idea: str
    params: dict
    universe: str = ""
    data_start: str | None = None
    data_end: str | None = None
    n_trials: int | None = None
    n_oos_trades: int | None = None
    is_sharpe: float | None = None
    oos_sharpe: float | None = None
    dsr: float | None = None
    verdict: str | None = None
    gate_verdict: str | None = None
    notes: str = ""
    run_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    id: int | None = None


def default_path() -> Path:
    path = Path(get_config()["data_cache_dir"]) / "quant"
    path.mkdir(parents=True, exist_ok=True)
    return path / "trial_log.sqlite"


def _connect(path: Path | None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_path())
    conn.execute(_SCHEMA)
    conn.execute(_EVENTS_SCHEMA)
    return conn


_COLUMNS = ("run_at", "idea", "params", "universe", "data_start", "data_end", "n_trials",
            "n_oos_trades", "is_sharpe", "oos_sharpe", "dsr", "verdict", "gate_verdict", "notes")


def record(trial: Trial, path: Path | None = None) -> int:
    values = [json.dumps(trial.params, sort_keys=True, default=str) if c == "params" else getattr(trial, c)
              for c in _COLUMNS]
    with closing(_connect(path)) as conn, conn:
        cur = conn.execute(f"INSERT INTO trials ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                           values)
        return int(cur.lastrowid)


def load(idea: str | None = None, path: Path | None = None) -> list[Trial]:
    query, args = "SELECT id, " + ", ".join(_COLUMNS) + " FROM trials", ()
    if idea is not None:
        query, args = query + " WHERE idea = ?", (idea,)
    with closing(_connect(path)) as conn:
        rows = conn.execute(query + " ORDER BY id", args).fetchall()
    trials = []
    for row in rows:
        data = dict(zip(("id",) + _COLUMNS, row, strict=True))
        data["params"] = json.loads(data["params"])
        trials.append(Trial(**data))
    return trials


def trial_count(idea: str | None = None, path: Path | None = None) -> int:
    """Total parameter combinations tried, for the deflated Sharpe's N.

    Each run counts its own ``n_trials`` (grid size), or 1 if it didn't say.
    """
    return sum(t.n_trials or 1 for t in load(idea, path))


def log_event(kind: str, detail: dict, path: Path | None = None) -> int:
    run_at = datetime.now(UTC).isoformat(timespec="seconds")
    with closing(_connect(path)) as conn, conn:
        cur = conn.execute("INSERT INTO events (run_at, kind, detail) VALUES (?, ?, ?)",
                           (run_at, kind, json.dumps(detail, sort_keys=True, default=str)))
        return int(cur.lastrowid)


def load_events(kind: str | None = None, path: Path | None = None) -> list[dict]:
    query, args = "SELECT id, run_at, kind, detail FROM events", ()
    if kind is not None:
        query, args = query + " WHERE kind = ?", (kind,)
    with closing(_connect(path)) as conn:
        rows = conn.execute(query + " ORDER BY id", args).fetchall()
    return [{"id": i, "run_at": r, "kind": k, "detail": json.loads(d)} for i, r, k, d in rows]

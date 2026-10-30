"""Forward signal registry: append-only, hash-chained, written before the entry session opens (docs/gate_v1.json).

One JSON line per entry. Each line holds the hash of the line before it, so an edit, deletion or reorder breaks the
chain. A signal registered at or after 09:15 IST on its entry date is refused. A trade not registered before entry does not
count. A missed day is recorded as missed and can never be filled in later.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path

import pytz

IST = pytz.timezone("Asia/Kolkata")
ENTRY_OPEN = time(9, 15)
GENESIS = "0" * 64


class RegistryError(RuntimeError):
    """A late signal, a duplicate, a backfill, or a broken hash chain."""


def _hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def verify(path: Path) -> int:
    """Check the whole chain; returns the number of entries, or raises."""
    prev = GENESIS
    rows = read(path)
    for i, row in enumerate(rows):
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("prev_hash") != prev or _hash(body) != row.get("hash"):
            raise RegistryError(f"hash chain broken at entry {i}")
        prev = row["hash"]
    return len(rows)


def _append(path: Path, body: dict) -> dict:
    verify(path)
    rows = read(path)
    body = {**body, "prev_hash": rows[-1]["hash"] if rows else GENESIS}
    row = {**body, "hash": _hash(body)}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _entry_open(entry: date) -> datetime:
    return IST.localize(datetime.combine(entry, ENTRY_OPEN))


def register(path: Path, *, signal_date: date, entry_date: date, symbol: str, direction: int, spec_hash: str,
             universe: str, horizon: int, now: datetime) -> dict:
    """Append a signal. ``now`` must be timezone-aware and before the entry session opens."""
    if now.tzinfo is None:
        raise RegistryError("timestamp must be timezone-aware")
    if now >= _entry_open(entry_date):
        raise RegistryError(f"too late: {symbol} entry {entry_date} opened at 09:15 IST")
    if direction not in (-1, 0, 1):
        raise RegistryError("direction is long (1), short (-1) or no trade (0)")
    if entry_date <= signal_date:
        raise RegistryError("entry must be after the signal")
    for r in read(path):
        if r["type"] == "signal" and (r["symbol"], r["entry_date"], r["spec_hash"], r["horizon"]) == \
                (symbol, entry_date.isoformat(), spec_hash, horizon):
            raise RegistryError("this signal is already registered")
        if r["type"] == "missed" and (r["date"], r["spec_hash"]) == (signal_date.isoformat(), spec_hash):
            raise RegistryError(f"{signal_date} was recorded as missed; it cannot be backfilled")
    return _append(path, {"type": "signal", "timestamp": now.isoformat(), "signal_date": signal_date.isoformat(),
                          "entry_date": entry_date.isoformat(), "symbol": symbol, "direction": direction,
                          "spec_hash": spec_hash, "universe": universe, "horizon": horizon})


def record_missed(path: Path, *, day: date, spec_hash: str, now: datetime, reason: str) -> dict:
    return _append(path, {"type": "missed", "timestamp": now.isoformat(), "date": day.isoformat(),
                          "spec_hash": spec_hash, "reason": reason})


def counts(path: Path, *, symbol: str, entry_date: date, spec_hash: str, horizon: int) -> bool:
    """Whether a trade counts: it must be in a valid chain, registered before its entry opened."""
    verify(path)
    for r in read(path):
        if r["type"] == "signal" and r["symbol"] == symbol and r["entry_date"] == entry_date.isoformat() \
                and r["spec_hash"] == spec_hash and r["horizon"] == horizon:
            return datetime.fromisoformat(r["timestamp"]) < _entry_open(entry_date)
    return False

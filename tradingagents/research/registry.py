"""Forward signal registry: append-only, hash-chained, written before the entry session opens (docs/gate_v1.json).

One JSON line per entry. Each line holds the hash of the line before it, so an edit, deletion or reorder breaks the
chain. A signal registered at or after 09:15 IST on its entry date is refused. A trade not registered before entry does not
count. A missed day is recorded as missed and can never be filled in later.

Every check-then-append holds ``locked(path)`` (audit H3): a per-registry in-process lock plus an OS lock on a ``<registry>.lock``
file next to the registry, so two analyses running at once (threads or processes) can't both pass a duplicate check or
chain two rows to the same previous row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time as _clock
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
ENTRY_OPEN = time(9, 15)
GENESIS = "0" * 64


class RegistryError(RuntimeError):
    """A late signal, a duplicate, a backfill, or a broken hash chain."""


_GUARD = threading.Lock()                 # guards _locks only; never held while waiting
_locks: dict[str, threading.RLock] = {}   # lock file -> its re-entrant in-process lock (threads); the OS lock covers processes
_held: dict[str, list] = {}               # lock file -> [open handle, depth]; touched only by the thread holding that path's RLock
LOCK_TIMEOUT = 30.0

if os.name == "nt":
    import msvcrt

    def _try_os_lock(fh) -> bool:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _os_unlock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_os_lock(fh) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _os_unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def locked(path: Path, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """Hold the registry at ``path`` for a read -> check -> append sequence. Re-entrant in the same thread; other threads
    and other processes wait up to ``timeout`` seconds in all, then get a RegistryError. Each registry has its own lock,
    so holding one never blocks a writer of another. The OS releases the file lock if the process dies, so a crash
    leaves no stale lock."""
    lock_file = Path(str(path) + ".lock")
    key = os.path.normcase(os.path.abspath(lock_file))
    deadline = _clock.monotonic() + timeout
    with _GUARD:
        lk = _locks.setdefault(key, threading.RLock())
    if not lk.acquire(timeout=max(timeout, 0.0)):
        raise RegistryError(f"{Path(path).name} is locked by another writer in this process")
    try:
        if key in _held:                  # this thread already holds it: just nest
            _held[key][1] += 1
            try:
                yield
            finally:
                _held[key][1] -= 1
            return
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_file, "a+b")       # noqa: SIM115 (held across the yield)
        while not _try_os_lock(fh):
            if _clock.monotonic() >= deadline:
                fh.close()
                raise RegistryError(f"{Path(path).name} is locked by another process")
            _clock.sleep(0.05)
        _held[key] = [fh, 1]
        try:
            yield
        finally:
            del _held[key]
            try:
                _os_unlock(fh)
            finally:
                fh.close()
    finally:
        lk.release()


def _hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read(path: Path) -> list[dict]:
    """The registry's rows. Readers take no lock, and every append ends with a newline, so a final line without one is
    an append still being written: it is left out (logged at debug), never parsed. A complete bad line still raises."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text, _, partial = text.rpartition("\n")
        logger.debug("%s: left out a final line with no newline (an append in progress): %r", p.name, partial[:80])
    return [json.loads(x) for x in text.splitlines() if x.strip()]


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
    with locked(path):
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
             universe: str, horizon: int, now: datetime, action_list_sha256: str) -> dict:
    """Append a signal. ``now`` must be timezone-aware and before the entry session opens. ``action_list_sha256`` is the
    hash of the action list as it stood at signal time (gate v2 addendum)."""
    if len(action_list_sha256) != 64 or set(action_list_sha256) - set("0123456789abcdef"):
        raise RegistryError("action_list_sha256 must be a sha256 hex digest")
    if now.tzinfo is None:
        raise RegistryError("timestamp must be timezone-aware")
    if now >= _entry_open(entry_date):
        raise RegistryError(f"too late: {symbol} entry {entry_date} opened at 09:15 IST")
    if direction not in (-1, 0, 1):
        raise RegistryError("direction is long (1), short (-1) or no trade (0)")
    if entry_date <= signal_date:
        raise RegistryError("entry must be after the signal")
    with locked(path):
        for r in read(path):
            if r["type"] == "signal" and (r["symbol"], r["entry_date"], r["spec_hash"], r["horizon"]) == \
                    (symbol, entry_date.isoformat(), spec_hash, horizon):
                raise RegistryError("this signal is already registered")
            if r["type"] == "missed" and (r["date"], r["spec_hash"]) == (signal_date.isoformat(), spec_hash):
                raise RegistryError(f"{signal_date} was recorded as missed; it cannot be backfilled")
        return _append(path, {"type": "signal", "timestamp": now.isoformat(), "signal_date": signal_date.isoformat(),
                              "entry_date": entry_date.isoformat(), "symbol": symbol, "direction": direction,
                              "spec_hash": spec_hash, "universe": universe, "horizon": horizon,
                              "action_list_sha256": action_list_sha256})


def record_missed(path: Path, *, day: date, spec_hash: str, now: datetime, reason: str) -> dict:
    return _append(path, {"type": "missed", "timestamp": now.isoformat(), "date": day.isoformat(),
                          "spec_hash": spec_hash, "reason": reason})


def register_structure(path: Path, *, day: date, symbol: str, expiry: str | None, spec_hash: str, now: datetime, outcome: str, structure: str | None,
                       direction: str | None, legs: list[dict], max_risk_indicative: float | None) -> dict:
    """The AI strategist's forward test (docs/ai_strategist_test_v1.json): one answer per session, written before any entry price exists."""
    if now.tzinfo is None:
        raise RegistryError("timestamp must be timezone-aware")
    if outcome not in ("trade", "no_trade", "rejected"):
        raise RegistryError("outcome is trade, no_trade or rejected")
    if outcome == "trade" and not (structure and legs and expiry and direction and max_risk_indicative):
        raise RegistryError("a trade needs its structure, strikes, expiry, direction and max risk")
    if now.date() != day:
        raise RegistryError("a session is registered on that session, never later")
    with locked(path):
        for r in read(path):
            if r["type"] in ("strategist", "missed") and (r["date"], r["spec_hash"]) == (day.isoformat(), spec_hash):
                raise RegistryError(f"{day} already has an entry; it cannot be replaced")
        return _append(path, {"type": "strategist", "timestamp": now.isoformat(), "date": day.isoformat(), "symbol": symbol, "expiry": expiry, "spec_hash": spec_hash,
                              "outcome": outcome, "structure": structure, "direction": direction, "legs": legs, "max_risk_indicative": max_risk_indicative})


def record_entry(path: Path, *, registration: str, now: datetime, status: str, **fields) -> dict:
    """The paper entry of a registered trade. It must follow its registration, and only once."""
    with locked(path):
        rows = read(path)
        row = next((r for r in rows if r.get("hash") == registration and r["type"] == "strategist" and r["outcome"] == "trade"), None)
        if row is None:
            raise RegistryError("no registered trade to enter: a trade not registered before entry does not count")
        if now < datetime.fromisoformat(row["timestamp"]):
            raise RegistryError("the entry is older than its registration")
        if any(r["type"] == "strategist_entry" and r["registration"] == registration for r in rows):
            raise RegistryError("this trade already has an entry")
        return _append(path, {"type": "strategist_entry", "timestamp": now.isoformat(), "registration": registration, "status": status, **fields})


def counts(path: Path, *, symbol: str, entry_date: date, spec_hash: str, horizon: int) -> bool:
    """Whether a trade counts: it must be in a valid chain, registered before its entry opened."""
    verify(path)
    for r in read(path):
        if r["type"] == "signal" and r["symbol"] == symbol and r["entry_date"] == entry_date.isoformat() \
                and r["spec_hash"] == spec_hash and r["horizon"] == horizon:
            return datetime.fromisoformat(r["timestamp"]) < _entry_open(entry_date)
    return False

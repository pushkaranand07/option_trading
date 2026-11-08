"""Audit H3 follow-up: the lock timeout also holds between threads of one process, and one registry being held never
blocks a writer of another registry."""

import threading
import time

import pytest

from tradingagents.research import registry


def _hold(path, seconds, ready):
    with registry.locked(path):
        ready.set()
        time.sleep(seconds)


@pytest.mark.unit
def test_a_thread_waiting_past_its_timeout_gets_an_error(tmp_path):
    path, ready = tmp_path / "r.jsonl", threading.Event()
    holder = threading.Thread(target=_hold, args=(path, 3.0, ready))
    holder.start()
    try:
        assert ready.wait(10)
        started = time.monotonic()
        with pytest.raises(registry.RegistryError, match="locked"), registry.locked(path, timeout=0.5):
            pass
        assert time.monotonic() - started < 1.5
    finally:
        holder.join(10)


@pytest.mark.unit
def test_another_registry_is_not_blocked(tmp_path):
    ready = threading.Event()
    holder = threading.Thread(target=_hold, args=(tmp_path / "a.jsonl", 3.0, ready))
    holder.start()
    try:
        assert ready.wait(10)
        started = time.monotonic()
        with registry.locked(tmp_path / "b.jsonl", timeout=0.5):
            pass
        assert time.monotonic() - started < 1.0
    finally:
        holder.join(10)


@pytest.mark.unit
def test_the_same_thread_can_still_nest(tmp_path):
    path = tmp_path / "r.jsonl"
    with registry.locked(path, timeout=0.5), registry.locked(path, timeout=0.5):
        pass
    with registry.locked(path, timeout=0.5):                       # released after nesting
        pass

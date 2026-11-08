"""Audit M5 (trade_record part): the global lock must not be held during a network call. overview(), refresh_open()
and close() used to fetch every open trade's chain while holding ``_lock``, so a delete (or a Take) waited for NSE.
Now the rows are snapshotted under the lock, the chains fetched outside it, and the writers re-take the lock to
merge by trade id, skipping trades whose status changed meanwhile. Threading events, no sleeps."""

import json
import threading

import pytest

from tests.test_trade_record import RESULT, _q, chain
from webapp import trade_record as tr

WAIT = 10                                                      # seconds: a ceiling for a hang, never slept


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)


def slow(prices):
    """A chain fetch that blocks until released, and says when it has started."""
    started, release = threading.Event(), threading.Event()

    def fetch(symbol, expiry):
        started.set()
        assert release.wait(WAIT), "the test never released the fetch"
        return prices(symbol, expiry)
    return fetch, started, release


def in_thread(fn, *args):
    box = {}

    def run():
        try:
            box["result"] = fn(*args)
        except Exception as exc:                               # noqa: BLE001  (reported by the test)
            box["error"] = exc
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th, box


def two_trades():
    a = tr.take(RESULT)
    b = tr.take(RESULT | {"plan": RESULT["plan"] | {"strategy": "bull_put_spread"}})  # another direction: no question
    return a, b


INSIDE = chain(22600, _q(130, 129, 131), _q(88, 87, 89))
AT_TARGET = chain(22470, _q(80, 79, 81), _q(58, 57, 59))


@pytest.mark.unit
@pytest.mark.parametrize("reader", ["overview", "refresh_open", "close"])
def test_a_delete_does_not_wait_for_a_slow_chain_fetch(reader):
    a, b = two_trades()
    fetch, started, release = slow(INSIDE)
    call = {"overview": lambda: tr.overview(fetch), "refresh_open": lambda: tr.refresh_open(fetch),
            "close": lambda: tr.close(a["id"], fetch)}[reader]
    slow_th, slow_box = in_thread(call)
    try:
        assert started.wait(WAIT), "the fetch never started"
        del_th, del_box = in_thread(tr.delete, b["id"])
        del_th.join(WAIT / 2)
        finished_first = not del_th.is_alive()
    finally:
        release.set()
    slow_th.join(WAIT)
    del_th.join(WAIT)
    assert finished_first, f"delete() waited for the chain fetch inside {reader}()"
    assert "error" not in slow_box and "error" not in del_box, (slow_box, del_box)
    assert b["id"] not in [t["id"] for t in tr._load()]        # the delete is not undone by the slower writer


@pytest.mark.unit
def test_refresh_open_skips_a_trade_closed_by_hand_while_it_was_fetching():
    a, _ = two_trades()
    fetch, started, release = slow(AT_TARGET)
    th, box = in_thread(tr.refresh_open, fetch)
    try:
        assert started.wait(WAIT)
        closed = tr.close(a["id"], INSIDE)                      # the user closes it meanwhile
    finally:
        release.set()
    th.join(WAIT)
    assert "error" not in box, box
    row = next(t for t in json.loads(tr.STORE.read_text(encoding="utf-8")) if t["id"] == a["id"])
    assert row["reason"] == closed["reason"] == "closed by you" and row["closed_at"] == closed["closed_at"]

"""Audit: GET must have no side effects. ``overview()`` (GET /api/trades) used to settle target / stop / expiry hits,
repair rows, write events.log and save trades.json. Now it only reads: it shows the live marks and what the rules
*would* do (``live["would_settle"]``); ``refresh_open()`` settles and saves (the monitor calls it)."""

import json

import pytest

from tests.test_trade_record import CONDOR, RESULT, _q, chain, condor_chain
from webapp import trade_record as tr

AT_TARGET = chain(22470, _q(80, 79, 81), _q(58, 57, 59))          # NIFTY below the 22,480 target


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)


def files():
    log = tr.STORE.parent / "events.log"
    return tr.STORE.read_bytes(), log.read_bytes() if log.exists() else b""


@pytest.mark.unit
def test_overview_on_a_trade_at_its_target_writes_nothing_and_refresh_open_settles_it():
    t = tr.take(RESULT)
    before = files()
    o = tr.overview(AT_TARGET)
    assert files() == before                                     # trades.json and events.log byte-identical
    [shown] = o["open"]
    assert shown["id"] == t["id"] and shown["live"]["flags"] == ["target"] and shown["live"]["would_settle"] == "target reached"
    o = tr.refresh_open(AT_TARGET)
    assert o["open"] == [] and o["closed"][0]["reason"] == "target reached"
    assert json.loads(tr.STORE.read_text(encoding="utf-8"))[0]["status"] == "closed"
    assert b" closed " in files()[1]


@pytest.mark.unit
def test_overview_does_not_settle_an_expired_trade_or_save_flags():
    tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650})
    before = files()
    o = tr.overview(lambda *a: pytest.fail("no chain after expiry"))
    assert files() == before and o["open"][0]["live"]["would_settle"] == "expired"
    assert tr.refresh_open(lambda *a: pytest.fail("no chain after expiry"))["closed"][0]["reason"] == "expired"


@pytest.mark.unit
def test_overview_shows_an_old_condor_repaired_but_does_not_save_the_repair():
    tr.take(CONDOR, source="ai")
    rows = json.loads(tr.STORE.read_text(encoding="utf-8"))
    rows[0].pop("range")
    rows[0].update(index_target=22550, index_stop=22400)
    tr.STORE.write_text(json.dumps(rows), encoding="utf-8")
    before = files()
    o = tr.overview(condor_chain(22560))
    assert o["ai"]["open"][0]["range"] == [22500.0, 22600.0] and files() == before
    tr.refresh_open(condor_chain(22560))
    assert json.loads(tr.STORE.read_text(encoding="utf-8"))[0]["range"] == [22500.0, 22600.0]


@pytest.mark.unit
def test_inside_the_targets_nothing_would_settle():
    tr.take(RESULT)
    o = tr.overview(chain(22600, _q(130, 129, 131), _q(88, 87, 89)))
    assert o["open"][0]["live"]["would_settle"] is None

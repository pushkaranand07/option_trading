"""Audit H1: a damaged trades.json must never wipe the history.

Before the fix ``_load()`` returned [] on a parse error and the next write saved only the new row, so three rows
plus a stray comma became one row. Now the damaged file is copied once to ``trades.json.corrupt-<stamp>``, every
write path raises StoreCorrupt without writing, the read paths show an empty view that carries the problem, and
``store_problem()`` says what is wrong."""

import pytest

from tests.test_trade_record import RESULT, _q, chain
from webapp import strategist as st, trade_record as tr

RUN = {"day": "2026-11-09", "trades": [{"symbol": "NIFTY", "expiry": "27-Oct-2099", "spot": 22600, "rank": 1,
                                         "plan": RESULT["plan"], "priced": RESULT["priced"]}]}


@pytest.fixture
def damaged(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    monkeypatch.setattr(st, "load_run", lambda run_id: RUN if run_id == "run1" else None)
    tr.take(RESULT)
    tr.take(RESULT, confirm=True)
    tr.take(RESULT, source="ai")
    ids = [t["id"] for t in __import__("json").loads(tr.STORE.read_text(encoding="utf-8"))]
    assert len(ids) == 3
    bad = tr.STORE.read_bytes() + b","                     # the audit's reproduction: one stray comma
    tr.STORE.write_bytes(bad)
    return {"bytes": bad, "ids": ids, "dir": tmp_path}


def backups(d):
    return sorted(d.glob("trades.json.corrupt-*"))


@pytest.mark.unit
def test_a_take_on_a_damaged_store_keeps_every_byte_and_says_why(damaged):
    err = None
    try:
        tr.take(RESULT | {"plan": RESULT["plan"] | {"strategy": "bull_put_spread"}})
    except Exception as exc:                               # noqa: BLE001  (the old code raised nothing)
        err = exc
    assert tr.STORE.read_bytes().count(b'"taken_at"') == 3  # the old code left 1 row (the new one)
    assert tr.STORE.read_bytes() == damaged["bytes"]       # all 3 original rows, byte for byte
    assert isinstance(err, tr.StoreCorrupt) and isinstance(err, tr.TradeError)
    [copy] = backups(damaged["dir"])
    assert copy.read_bytes() == damaged["bytes"]
    assert tr.store_problem() and copy.name in tr.store_problem()


WRITES = {
    "take": lambda d: tr.take(RESULT | {"plan": RESULT["plan"] | {"strategy": "bull_put_spread"}}),
    "record_refused": lambda d: tr.record_refused("run1", 0, tr.TradeError("stale"), "you"),
    "close": lambda d: tr.close(d["ids"][0], chain(22600, _q(130, 129, 131), _q(88, 87, 89))),
    "delete": lambda d: tr.delete(d["ids"][0]),
    "refresh_open": lambda d: tr.refresh_open(chain(22470, _q(80, 79, 81), _q(58, 57, 59))),
}


@pytest.mark.unit
@pytest.mark.parametrize("path", list(WRITES))
def test_every_write_path_refuses_without_writing_and_backs_up_once(damaged, path):
    for _ in range(3):                                     # repeated calls: still one backup copy
        with pytest.raises(tr.StoreCorrupt):
            WRITES[path](damaged)
    assert tr.STORE.read_bytes() == damaged["bytes"]
    assert len(backups(damaged["dir"])) == 1


@pytest.mark.unit
def test_the_read_paths_show_an_empty_view_that_carries_the_problem(damaged):
    o = tr.overview(chain(22600, _q(130, 129, 131), _q(88, 87, 89)))
    assert o["store_problem"] and o["open"] == [] and o["closed"] == [] and o["stats"]["closed"] == 0
    assert o["ai"]["open"] == [] and o["you"]["not_taken"] == []
    csv = tr.history_csv()
    assert csv.splitlines()[0].startswith("view,source,status") and "damaged" in csv
    assert tr.STORE.read_bytes() == damaged["bytes"]


@pytest.mark.unit
def test_a_repaired_file_clears_the_problem(damaged):
    with pytest.raises(tr.StoreCorrupt):
        tr.delete(damaged["ids"][0])
    tr.STORE.write_bytes(damaged["bytes"][:-1])            # the user removed the comma
    assert tr.store_problem() is None and tr.overview()["store_problem"] is None
    tr.delete(damaged["ids"][0])
    assert len(tr._load()) == 2


@pytest.mark.unit
def test_no_file_yet_is_not_a_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    assert tr.store_problem() is None and tr._load() == []
    assert not backups(tmp_path)

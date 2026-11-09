"""Audit follow-up (A-tick-quiet): with a damaged trades.json the monitor logged a full traceback every 60 s, day and
night, because it read the file before asking whether the market is open. Now a closed market reads nothing, and a
damaged store's traceback is logged once per distinct problem (later ticks at debug), still counted. Backup names
are unique within a second, so two different damaged contents cannot overwrite each other's copy."""

import logging
from datetime import datetime

import pytest
import pytz

from webapp import signals, trade_record as tr

FROZEN = pytz.timezone("Asia/Kolkata").localize(datetime(2026, 11, 9, 10, 0, 0))


@pytest.fixture
def damaged(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_monitor", {"running": False, "last_ok_at": None, "last_error": None, "fail_count": 0})
    monkeypatch.setattr(tr, "_backups", {})
    monkeypatch.setattr(tr, "_logged_problem", None, raising=False)
    tr.STORE.write_text('[{"id": "a", "status": "open"}],', encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_a_closed_market_does_not_read_the_store_or_log(damaged, monkeypatch, caplog):
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    with caplog.at_level(logging.DEBUG, logger=tr.logger.name):
        assert tr._monitor_tick() is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not list(damaged.glob("trades.json.corrupt-*"))          # the file was not even read


@pytest.mark.unit
def test_a_damaged_store_logs_one_traceback_per_problem_and_counts_every_tick(damaged, monkeypatch, caplog):
    monkeypatch.setattr(signals, "market_open", lambda *a: True)
    with caplog.at_level(logging.DEBUG, logger=tr.logger.name):
        for _ in range(3):
            assert tr._monitor_tick() is False
    tracebacks = [r for r in caplog.records if r.exc_info and r.levelno >= logging.ERROR]
    assert len(tracebacks) == 1 and tr.monitor_status()["fail_count"] == 3
    assert [r for r in caplog.records if r.levelno == logging.DEBUG and "failed" in r.getMessage()]
    tr.STORE.write_text('[{"id": "b"', encoding="utf-8")            # a different damage: a new problem, logged again
    with caplog.at_level(logging.DEBUG, logger=tr.logger.name):
        tr._monitor_tick()
    assert len([r for r in caplog.records if r.exc_info and r.levelno >= logging.ERROR]) == 2


@pytest.mark.unit
def test_two_damaged_contents_in_the_same_second_keep_both_copies(damaged, monkeypatch):
    monkeypatch.setattr(tr, "_clock", lambda: FROZEN)
    first = tr.STORE.read_bytes()
    with pytest.raises(tr.StoreCorrupt):
        tr._load()
    second = b'[{"id": "b"'
    tr.STORE.write_bytes(second)
    with pytest.raises(tr.StoreCorrupt):
        tr._load()
    copies = sorted(p.read_bytes() for p in damaged.glob("trades.json.corrupt-*"))
    assert copies == sorted([first, second])
    assert all(p.name.startswith("trades.json.corrupt-20261109-100000") for p in damaged.glob("trades.json.corrupt-*"))

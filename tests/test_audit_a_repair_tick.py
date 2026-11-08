"""Audit follow-up (A-repair-tick): an iron condor closed by the old directional rule, with no other trade open,
was never repaired by the monitor: ``_monitor_tick`` looked for open trades on the raw rows, before the range repair,
found none, and never called refresh_open(). overview() showed it reopened while the CSV said closed and close()
said "already closed". The tick now repairs first (in memory) while the market is open, so the repair is saved."""

import json

import pytest

from tests.test_trade_record import CONDOR, condor_chain
from webapp import option_chain as oc, signals, trade_record as tr


@pytest.fixture
def bug_closed_condor(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    monkeypatch.setattr(signals, "market_open", lambda *a: True)
    monkeypatch.setattr(oc, "full_chain", lambda *a, **k: condor_chain(22560)(*a), raising=False)  # inside the range
    monkeypatch.setattr(tr, "_monitor", {"running": False, "last_ok_at": None, "last_error": None, "fail_count": 0})
    t = tr.take(CONDOR, source="ai")
    rows = json.loads(tr.STORE.read_text(encoding="utf-8"))          # as the old rule left it
    for r in rows:
        r.pop("range")
        r.update(index_target=22550, index_stop=22400, status="closed", reason="target reached", closed_at="x", net_pnl=-275.0)
        for leg in r["legs"]:
            leg["exit"] = leg["entry"]
    tr.STORE.write_text(json.dumps(rows), encoding="utf-8")
    return t


@pytest.mark.unit
def test_the_monitor_tick_saves_the_repair_of_a_bug_closed_condor(bug_closed_condor):
    assert tr._monitor_tick() is True
    [row] = json.loads(tr.STORE.read_text(encoding="utf-8"))
    assert row["status"] == "open" and row["range"] == [22500.0, 22600.0] and "bug" in row["note"]
    assert "net_pnl" not in row and all("exit" not in x for x in row["legs"])
    csv_status = tr.history_csv().splitlines()[1].split(",")[2]
    assert csv_status == "open"                                      # the CSV and the page agree
    assert tr.close(bug_closed_condor["id"], condor_chain(22560))["status"] == "closed"


@pytest.mark.unit
def test_with_the_market_closed_the_tick_writes_nothing(bug_closed_condor, monkeypatch):
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    before = tr.STORE.read_bytes()
    assert tr._monitor_tick() is True and tr.STORE.read_bytes() == before

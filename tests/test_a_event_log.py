"""A: every trade write, refusal, settle and "exit pending" leaves one line in events.log beside the trade record:
the time, the row id, what happened and why. A day can then be reconstructed without the server's terminal."""

import pytest

from tests.test_bug1_far_legs import NEAR, chain
from tests.test_take_honest_entry import take
from webapp import option_chain as oc, trade_record as tr


def events():
    path = tr.STORE.parent / "events.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.mark.unit
def test_a_take_and_a_refusal_each_log_a_line(world):
    t = take(world).json()
    line = next(x for x in events() if t["id"] in x)
    assert " taken " in line and "long_call" in line and "you" in line
    world["live"]["chain"] = chain({}) | {"timestamp": "12-Nov-2026 09:55:00"}
    take(world, candidate=1)
    refused = [x for x in events() if " refused " in x]
    assert refused and "s old" in refused[-1]


@pytest.mark.unit
def test_a_settle_and_an_exit_pending_each_log_a_line(condor, monkeypatch):
    monkeypatch.setattr(oc, "full_chain", lambda *a, **k: chain(NEAR), raising=False)   # both puts unquoted: pending
    tr.refresh_open()
    assert any(" exit_pending " in x and condor["id"] in x and "23600 PE" in x for x in events())
    t = tr._load()[0]
    tr._settle(t, [9.3, 7.25, 592, 455], 24557.6, "range broken")
    assert any(" closed " in x and condor["id"] in x and "range broken" in x for x in events())

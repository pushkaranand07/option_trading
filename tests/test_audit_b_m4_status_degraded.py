"""M4: /api/status returned 500 when one sub-check failed (a server running code older than the files on disk). Now
each part is checked on its own: a failure is listed under ``degraded`` as {"part", "reason"} and the rest is still
returned with 200. The status also carries the trade store's problem and the trade monitor's health (Track A), and
``code`` says whether the running commit differs from the checked-out one."""

import pytest

from tests.test_audit_b_support import client, loopback  # noqa: F401  (fixtures)
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import ai_test, build_info, signals, trade_record as tr

V2 = {"version": 3, "state": "NOT YET", "reason": "no answer yet", "fingerprint_problem": None}
MONITOR = {"running": True, "last_ok_at": "2026-11-09T10:00:00+05:30", "last_error": None, "fail_count": 0}


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    monkeypatch.setattr(ai_test, "today_status", lambda *a, **k: dict(V2))
    monkeypatch.setattr(tr, "store_problem", lambda: None, raising=False)
    monkeypatch.setattr(tr, "monitor_status", lambda: dict(MONITOR), raising=False)


def _boom(*a, **k):
    raise AttributeError("module 'webapp.x' has no attribute 'new_thing'")


@pytest.mark.unit
def test_a_healthy_status_has_every_part_and_nothing_degraded(client, healthy):
    r = client.get("/api/status")
    assert r.status_code == 200, r.text
    s = r.json()
    for key in ("dhan", "azure", "azure_problem", "market_open", "muhurat", "calendar_warning", "v2", "code", "indices",
                "store_problem", "monitor", "degraded"):
        assert key in s, key
    assert s["degraded"] == [] and s["v2"] == V2 and s["monitor"] == MONITOR and s["store_problem"] is None
    assert set(s["code"]) >= {"running", "repo", "started_at", "stale"}


@pytest.mark.unit
@pytest.mark.parametrize(("part", "target", "key"), [
    ("market_open", (signals, "market_open"), "market_open"),
    ("muhurat", (signals, "muhurat_today"), "muhurat"),
    ("v2", (ai_test, "today_status"), "v2"),
    ("code", (build_info, "status"), "code"),
    ("store_problem", (tr, "store_problem"), "store_problem"),
    ("monitor", (tr, "monitor_status"), "monitor"),
])
def test_one_failing_part_is_degraded_and_the_rest_still_returns(client, healthy, monkeypatch, part, target, key):
    monkeypatch.setattr(*target, _boom, raising=False)
    r = client.get("/api/status")
    assert r.status_code == 200, r.text
    s = r.json()
    assert [d["part"] for d in s["degraded"]] == [part]
    assert "new_thing" not in s["degraded"][0]["reason"]                     # no Python text; an id to find the log
    assert s["indices"] and "code" in s and "v2" in s
    if part == "v2":
        assert s["v2"]["state"] == "ERROR"
    else:
        assert s[key] is None


@pytest.mark.unit
def test_a_failing_calendar_is_degraded_with_a_warning(client, healthy, monkeypatch):
    monkeypatch.setattr(signals, "nse_calendar", _boom)
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: False)
    monkeypatch.setattr(signals, "muhurat_today", lambda *a, **k: None)
    r = client.get("/api/status")
    assert r.status_code == 200
    s = r.json()
    assert [d["part"] for d in s["degraded"]] == ["calendar"] and "calendar" in s["calendar_warning"].lower()


@pytest.mark.unit
def test_v2_answering_error_is_listed_as_degraded(client, healthy, monkeypatch):
    monkeypatch.setattr(ai_test, "today_status", lambda *a, **k: V2 | {"state": "ERROR", "reason": "registry unreadable"})
    s = client.get("/api/status").json()
    assert s["degraded"] == [{"part": "v2", "reason": "registry unreadable"}] and s["v2"]["state"] == "ERROR"


@pytest.mark.unit
def test_without_track_a_the_store_and_monitor_are_null_not_an_error(client, healthy, monkeypatch):
    monkeypatch.delattr(tr, "store_problem", raising=False)
    monkeypatch.delattr(tr, "monitor_status", raising=False)
    s = client.get("/api/status").json()
    assert s["store_problem"] is None and s["monitor"] is None and s["degraded"] == []


@pytest.mark.unit
def test_a_store_problem_is_shown(client, healthy, monkeypatch):
    monkeypatch.setattr(tr, "store_problem", lambda: "trades.json is corrupt: writes are refused", raising=False)
    assert client.get("/api/status").json()["store_problem"] == "trades.json is corrupt: writes are refused"


@pytest.mark.unit
def test_code_says_stale_when_the_checkout_moved(client, healthy, monkeypatch):
    monkeypatch.setattr(build_info, "repo_head", lambda: "f" * 40)
    code = client.get("/api/status").json()["code"]
    assert code["stale"] is (build_info.CODE_VERSION is not None) and code["repo"] == "f" * 40
    assert code["running"] == build_info.CODE_VERSION

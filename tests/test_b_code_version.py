"""B: every new row records the code that wrote it (the git commit the server started on) and when the server started;
the page warns when the running server is older than the commit now checked out (a restart was missed). The 15:33
row and the duplicates were written by a server running code from before the fixes, with nothing to show it."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_take_honest_entry import chain, take
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import build_info, server, signals, trade_record as tr

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_new_rows_record_the_code_version_and_the_server_start(world):
    t = take(world).json()
    assert re.fullmatch(r"[0-9a-f]{40}", t["code_version"]) and t["server_started_at"] == build_info.STARTED_AT
    world["live"]["chain"] = chain() | {"timestamp": "05-Nov-2026 09:55:00"}
    take(world, candidate=1)
    refused = tr.overview(lambda *a: chain())["you"]["not_taken"][0]
    assert refused["code_version"] == t["code_version"] and refused["server_started_at"] == build_info.STARTED_AT


@pytest.mark.unit
def test_the_status_says_when_the_server_runs_older_code_than_the_checkout(monkeypatch):
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    monkeypatch.setattr(build_info, "repo_head", lambda: build_info.CODE_VERSION)
    assert server.status()["code"]["stale"] is False
    monkeypatch.setattr(build_info, "repo_head", lambda: "f" * 40)               # a newer commit is checked out
    code = server.status()["code"]
    assert code["stale"] is True and code["running"] == build_info.CODE_VERSION and code["started_at"] == build_info.STARTED_AT


@pytest.mark.unit
def test_the_page_shows_a_restart_warning_only_when_stale():
    def banners(status):
        out = subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), "JSON.stringify(bannerTexts(ARGS[0]))"], input=json.dumps([status]),
                             capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)
    stale = banners({"code": {"stale": True, "running": "a" * 40, "repo": "b" * 40, "started_at": "2026-11-04T13:50:02"}})
    assert "Restart the server" in stale["code"] and "aaaaaaa" in stale["code"] and "bbbbbbb" in stale["code"]
    assert banners({"code": {"stale": False}})["code"] is None
    page = (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="codeWarn"[^>]*class="notice danger"', page)

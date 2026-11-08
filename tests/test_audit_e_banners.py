"""E-banners: /api/status health shown with the page-wide banners. An unreadable trade record and a failing
auto-settle get a red banner, degraded parts a notice; each key is optional (an older server sends none of them).
Each warning is visible text in exactly one role="alert" banner, never behind an icon or a collapsed box."""

import json
import re

import pytest

from tests.test_ui_regressions import ROOT, pytestmark as _needs_node, render

pytestmark = _needs_node
PAGE = (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")


def banners(status):
    return json.loads(render("JSON.stringify(bannerTexts(ARGS[0]))", status))


@pytest.mark.unit
def test_an_unreadable_trade_record_gives_a_red_banner_saying_writes_are_blocked():
    b = banners({"store_problem": "trades.json is not valid JSON (line 3)"})
    assert "trades.json is not valid JSON (line 3)" in b["store"]
    assert "blocked" in b["store"] and "backup" in b["store"]


@pytest.mark.unit
def test_auto_settle_failing_three_times_gives_a_red_banner_with_the_last_error():
    b = banners({"monitor": {"running": True, "last_ok_at": "2026-11-09 10:02", "last_error": "quotes timed out", "fail_count": 3}})
    assert "quotes timed out" in b["monitor"] and "3" in b["monitor"] and "10:02" in b["monitor"]
    assert "settle" in b["monitor"].lower()
    assert banners({"monitor": {"running": True, "last_ok_at": None, "last_error": "x", "fail_count": 2}})["monitor"] is None


@pytest.mark.unit
def test_degraded_parts_give_a_notice_naming_each_part_and_why():
    b = banners({"degraded": [{"part": "NSE holiday list", "reason": "download failed"}, {"part": "news", "reason": "no key"}]})
    for s in ("NSE holiday list", "download failed", "news", "no key"):
        assert s in b["degraded"]
    assert banners({"degraded": []})["degraded"] is None


@pytest.mark.unit
def test_an_older_server_without_the_new_keys_gives_no_new_banner():
    b = banners({"code": {"stale": False}, "v2": {"fingerprint_problem": None}})
    assert b["store"] is None and b["monitor"] is None and b["degraded"] is None


@pytest.mark.unit
def test_every_banner_has_one_visible_alert_box_on_the_page():
    app = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
    loader = app[app.index("async function loadStatus"):][:1500]
    wired = {key: el for el, key in re.findall(r'banner\("#(\w+)", b\.(\w+)\)', loader)}
    assert set(wired) == set(banners({})), "every banner text is put into an element when the status loads"
    assert {"store": "storeWarn", "monitor": "monitorWarn", "degraded": "degradedWarn", "code": "codeWarn"}.items() <= wired.items()
    for key, el in wired.items():
        tag = re.search(rf'<div id="{el}"[^>]*>', PAGE)
        assert tag and 'role="alert"' in tag.group(0) and "hidden" in tag.group(0), key      # hidden until it has text
        assert PAGE.count(f'id="{el}"') == 1
    for red in ("storeWarn", "monitorWarn", "codeWarn", "v2Warn"):
        assert re.search(rf'id="{red}"[^>]*class="notice danger"', PAGE), red
    assert "<details" not in PAGE[:PAGE.index('id="instArea"')]                          # the banners are not in a collapsed box


@pytest.mark.unit
def test_a_status_with_every_problem_shows_each_warning_once():
    st = {"store_problem": "bad json", "monitor": {"fail_count": 4, "last_error": "timeout", "running": True, "last_ok_at": None},
          "degraded": [{"part": "news", "reason": "no key"}], "calendar_warning": "holiday list missing",
          "code": {"stale": True, "running": "abcdef0123", "repo": "1234567abc", "started_at": "2026-11-09T09:00:00"},
          "v2": {"fingerprint_problem": "the prompt differs"}}
    shown = " | ".join(t for t in banners(st).values() if t)
    for s in ("bad json", "timeout", "no key", "holiday list missing", "Restart the server", "the prompt differs"):
        assert shown.count(s) == 1, s

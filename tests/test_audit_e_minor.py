"""E-minor: the degraded notice leaves out what other banners already show (calendar, v2) and survives a malformed
list; api() keeps headers given as a Headers object; --day / --draw are legible as text."""

import json

import pytest

from tests.test_audit_e_a11y import DARK, LIGHT, ratio, rgba
from tests.test_ui_regressions import pytestmark as _needs_node, render  # same Node requirement


def banners(status):
    return json.loads(render("JSON.stringify(bannerTexts(ARGS[0]))", status))


@pytest.mark.unit
@_needs_node
def test_the_degraded_notice_leaves_out_parts_another_banner_already_shows():
    b = banners({"degraded": [{"part": "calendar", "reason": "could not be checked (error id a1)"},
                              {"part": "v2", "reason": "today's v2 status could not be checked"},
                              {"part": "azure", "reason": "could not be checked (error id b2)"}]})
    assert "azure" in b["degraded"] and "calendar" not in b["degraded"] and "v2" not in b["degraded"]
    only_shown_elsewhere = [{"part": "calendar", "reason": "x"}, {"part": "v2", "reason": "y"}]
    assert banners({"degraded": only_shown_elsewhere})["degraded"] is None


@pytest.mark.unit
@_needs_node
@pytest.mark.parametrize("bad", [{"part": "azure"}, "azure failed", 3, [None, "x", {"reason": "no part"}]])
def test_a_malformed_degraded_value_does_not_stop_the_other_banners(bad):
    b = banners({"degraded": bad, "store_problem": "The trade record file trades.json cannot be opened (x)."})
    assert b["store"].endswith("cannot be opened (x).") and b["degraded"] is None


@pytest.mark.unit
@_needs_node
def test_api_keeps_headers_given_as_a_headers_object():
    sent = json.loads(render("""
      var SENT = [];
      fetch = (path, opts) => { SENT.push(Object.fromEntries(new Headers(opts.headers))); return Promise.resolve({ ok: true, status: 200, json: async () => ({}) }); };
      api('/api/trades', { method: 'POST', headers: new Headers({ 'Content-Type': 'application/json' }), body: '{}' }).then(() => JSON.stringify(SENT[0]))"""))
    assert sent == {"content-type": "application/json", "x-pulse-request": "1"}


@pytest.mark.unit
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_day_and_draw_colours_have_4_5_to_1_contrast_as_text(theme):
    t = {"light": LIGHT, "dark": DARK}[theme]
    low = [f"{fg} on {bg} {ratio(rgba(t[fg]), rgba(t[bg])):.2f}" for fg in ("day", "draw") for bg in ("panel", "bg", "panel-2")
           if ratio(rgba(t[fg]), rgba(t[bg])) < 4.5]
    assert not low, low

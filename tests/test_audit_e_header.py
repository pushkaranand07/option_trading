"""E-header: every non-GET request from the page carries X-Pulse-Request: 1 (the server refuses a state-changing
request without it), merged into the caller's headers; GETs stay plain. An internal error's error_id is shown."""

import json

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render  # same Node requirement

pytestmark = _needs_node

# Replace the page's fetch with a recorder that answers {status, body}, then make one api() call and report what was sent.
CALL = """
var SENT = [];
fetch = (path, opts) => { SENT.push({ path, method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {} });
  return Promise.resolve({ ok: ARGS[1] < 400, status: ARGS[1], json: async () => ARGS[2] }); };
api(ARGS[0].path, ARGS[0].opts).then((body) => JSON.stringify({ SENT, body }), (e) => JSON.stringify({ SENT, error: e.message }))
"""


def sent(path, opts=None, status=200, body=None):
    return json.loads(render(CALL, {"path": path, "opts": opts}, status, body or {}))


@pytest.mark.unit
@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH"])
def test_a_non_get_request_carries_the_pulse_header(method):
    s = sent("/api/trades/x", {"method": method})["SENT"][0]
    assert s["method"] == method and s["headers"].get("X-Pulse-Request") == "1"


@pytest.mark.unit
def test_the_header_is_merged_with_the_callers_headers():
    h = sent("/api/trades", {"method": "POST", "headers": {"Content-Type": "application/json"}, "body": "{}"})["SENT"][0]["headers"]
    assert h == {"Content-Type": "application/json", "X-Pulse-Request": "1"}


@pytest.mark.unit
@pytest.mark.parametrize("opts", [None, {}, {"method": "GET"}, {"method": "get"}])
def test_a_get_request_has_no_pulse_header(opts):
    assert "X-Pulse-Request" not in sent("/api/status", opts)["SENT"][0]["headers"]


@pytest.mark.unit
def test_an_internal_error_shows_its_error_id_and_a_plain_error_shows_its_detail():
    internal = sent("/api/trades", {"method": "POST"}, 500, {"detail": "Internal error", "error_id": "a1b2c3"})
    assert "Internal error" in internal["error"] and "a1b2c3" in internal["error"]
    plain = sent("/api/optionchain/NIFTY?expiry=x", None, 400, {"detail": "unknown expiry x; valid: 13-Nov-2026, 20-Nov-2026"})
    assert plain["error"] == "unknown expiry x; valid: 13-Nov-2026, 20-Nov-2026"

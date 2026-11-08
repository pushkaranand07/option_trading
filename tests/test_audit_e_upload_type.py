"""E-upload-type: the tradebook upload sends Content-Type: application/octet-stream (the server answers 415 to a body
without an accepted type) together with X-Pulse-Request: 1, both through api()."""

import json

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render  # same Node requirement

pytestmark = _needs_node


@pytest.mark.unit
def test_the_journal_upload_sends_octet_stream_and_the_pulse_header():
    sent = json.loads(render("""
      var SENT = [];
      fetch = (path, opts) => { SENT.push({ path, method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {},
        bytes: opts && opts.body ? opts.body.byteLength : null });
        return Promise.resolve({ ok: true, status: 200, json: async () => (path.startsWith('/api/journal/upload') ? { name: 'tb.xlsx' } : []) }); };
      uploadJournal({ name: 'tb.xlsx', arrayBuffer: async () => new ArrayBuffer(3) }).then(() => JSON.stringify(SENT[0]))"""))
    assert sent["path"] == "/api/journal/upload?name=tb.xlsx" and sent["method"] == "POST" and sent["bytes"] == 3
    assert sent["headers"] == {"Content-Type": "application/octet-stream", "X-Pulse-Request": "1"}

"""Architecture (audit track B): importing webapp.server starts nothing (the refresh-ahead thread, the trade monitor
and the v2 startup check run in the app's lifespan); blocking calls in async endpoints run in the thread pool, not
on the event loop; POST /api/trades has a typed body {run_id: str, candidate: int >= 0, confirm: bool = False}."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_audit_b_support import HEADER, SAME_ORIGIN, client, loopback  # noqa: F401  (fixtures)
from webapp import market_data as md, morning, quant, server, signals, strategist, trade_record as tr

ROOT = Path(__file__).resolve().parents[1]

PROBE = r"""
import json, socket, threading
def refuse(*a, **k):
    raise OSError("network blocked in this probe")
socket.socket.connect = refuse
socket.socket.connect_ex = refuse
socket.getaddrinfo = refuse
from webapp import ai_test, market_data as md, trade_record as tr
calls = []
md.start_refresh_ahead = lambda *a, **k: calls.append("refresh-ahead")
tr.start_monitor = lambda *a, **k: calls.append("trade-monitor")
ai_test.fingerprint_problem = lambda *a, **k: calls.append("v2-check")
before = {t.name for t in threading.enumerate()}
import webapp.server
print(json.dumps({"calls": calls, "new_threads": sorted({t.name for t in threading.enumerate()} - before)}))
"""


@pytest.mark.unit
def test_importing_the_server_starts_no_threads_and_runs_no_startup_work():
    env = os.environ | {"TRADINGAGENTS_NO_DOTENV": "1", "DHAN_CLIENT_ID": "", "DHAN_ACCESS_TOKEN": "",
                        "AZURE_OPENAI_API_KEY": "", "AZURE_OPENAI_ENDPOINT": "", "AZURE_OPENAI_DEPLOYMENT_NAME": ""}
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen == {"calls": [], "new_threads": []}


@pytest.mark.unit
def test_the_lifespan_runs_the_startup_work_once(loopback, monkeypatch):
    calls = []
    monkeypatch.setattr(md, "start_refresh_ahead", lambda *a, **k: calls.append("refresh-ahead"))
    monkeypatch.setattr(tr, "start_monitor", lambda *a, **k: calls.append("trade-monitor"))
    monkeypatch.setattr(server, "v2_startup_check", lambda: calls.append("v2-check"))
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/latency").status_code == 200
    assert sorted(calls) == ["refresh-ahead", "trade-monitor", "v2-check"]


def _off_loop(log, name):
    """A fake that records whether it ran on the event loop's thread (it must not)."""
    try:
        asyncio.get_running_loop()
        log.append((name, "ON THE EVENT LOOP"))
    except RuntimeError:
        log.append((name, "thread pool"))


@pytest.fixture
def blocking(monkeypatch, tmp_path):
    log = []
    monkeypatch.setattr(md, "instrument", lambda s: _off_loop(log, "md.instrument") or {"symbol": s.upper()})
    idx = pd.date_range("2026-11-09 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}, index=idx)
    monkeypatch.setattr(md, "candles", lambda s, tf: (df, "yahoo"))
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: _off_loop(log, "signals.market_open") or False)
    monkeypatch.setattr(morning, "load", lambda day=None: _off_loop(log, "morning.load") or {"day": str(day)})
    monkeypatch.setattr(morning, "ai_status", lambda: None)
    monkeypatch.setattr(morning, "context", lambda s, d: {"symbol": s})
    monkeypatch.setattr(quant, "save_upload", lambda name, data: _off_loop(log, "quant.save_upload") or name)
    monkeypatch.setattr(quant, "JOURNAL_DIR", tmp_path / "journal")
    monkeypatch.setattr("webapp.option_chain.chain", lambda s, e=None, **k: {"symbol": s})
    monkeypatch.setattr(strategist, "rank", lambda s, e=None, **k: {"symbol": s})
    return log


@pytest.mark.unit
@pytest.mark.parametrize(("request_", "names"), [
    (("get", "/api/candles/NIFTY"), {"signals.market_open"}),
    (("get", "/api/morning"), {"morning.load"}),
    (("get", "/api/morning?date=2026-11-09"), {"morning.load"}),
    (("get", "/api/morning/context/NIFTY"), {"md.instrument"}),
    (("get", "/api/chain/NIFTY"), {"md.instrument"}),
    (("get", "/api/rank/NIFTY"), {"md.instrument"}),
    (("post", "/api/journal/upload?name=t.csv"), {"quant.save_upload"}),
])
def test_blocking_calls_run_in_the_thread_pool(client, blocking, request_, names):
    method, path = request_
    kw = {"content": b"a,b\n", "headers": HEADER | SAME_ORIGIN | {"Content-Type": "text/csv"}} if method == "post" else {}
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 200, r.text
    seen = {n for n, _ in blocking}
    assert names <= seen
    assert [x for x in blocking if x[1] != "thread pool"] == []


@pytest.fixture
def taken(monkeypatch):
    got = []
    monkeypatch.setattr(tr, "take_from_run", lambda run_id, candidate, confirm=False: got.append((run_id, candidate, confirm)) or {"id": "t1"})
    monkeypatch.setattr(tr, "record_refused", lambda *a, **k: None)
    return got


@pytest.mark.unit
@pytest.mark.parametrize("body", [{}, {"run_id": "r1"}, {"candidate": 0}, {"run_id": "r1", "candidate": -1},
                                  {"run_id": "r1", "candidate": "abc"}, {"run_id": "r1", "candidate": 1.5},
                                  {"run_id": "r1", "candidate": True}, {"run_id": None, "candidate": 0},
                                  {"run_id": "r1", "candidate": 0, "confirm": "maybe"}])
def test_a_badly_typed_take_is_422_and_nothing_is_taken(client, taken, body):
    r = client.post("/api/trades", json=body, headers=HEADER)
    assert r.status_code == 422, r.text
    assert taken == []


@pytest.mark.unit
def test_a_typed_take_reaches_the_record_and_prices_in_the_body_are_ignored(client, taken):
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 1, "priced": {"legs": [{"price": 1.0}]}}, headers=HEADER)
    assert r.status_code == 200 and taken == [("r1", 1, False)]
    client.post("/api/trades", json={"run_id": "r1", "candidate": 0, "confirm": True}, headers=HEADER)
    assert taken[-1] == ("r1", 0, True)


@pytest.mark.unit
def test_the_take_endpoint_declares_its_model():
    assert server.TakeRequest.model_json_schema()["required"] == ["run_id", "candidate"]

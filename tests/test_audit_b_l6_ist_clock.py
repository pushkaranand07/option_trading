"""L6 (track B's files): "now" and "today" come from webapp.timeutil (India time), not the PC's local clock, in
server.py (morning context, the CSV's file name), quant.py (data freshness, the risk view's day) and build_info.py
(when the server started). Each test moves only timeutil's clock to a day far from the real one."""

import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from tests import test_audit_b_support as support
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import market_data as md, morning, quant, timeutil, trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures
ROOT = Path(__file__).resolve().parents[1]
DAY = date(2031, 3, 5)                                       # a Wednesday, years from the real clock
NOW = timeutil.IST.localize(datetime(2031, 3, 5, 23, 0)) if hasattr(timeutil.IST, "localize") else datetime(2031, 3, 5, 23, 0, tzinfo=timeutil.IST)


@pytest.fixture
def ist(monkeypatch):
    monkeypatch.setattr(timeutil, "today_ist", lambda: DAY)
    monkeypatch.setattr(timeutil, "now_ist", lambda: NOW)


@pytest.mark.unit
def test_freshness_uses_the_ist_clock(ist):
    f = quant.freshness("2031-03-05", calendar=NSECalendar(holidays={}))
    assert f["expected"] == "2031-03-05" and f["stale"] is False and f["today_is_session"] is True


@pytest.mark.unit
def test_risk_defaults_to_the_ist_day(ist, monkeypatch):
    keys = []
    monkeypatch.setattr(md._cache, "get", lambda key, ttl, fn: keys.append(key) or {})
    quant.risk("NIFTY")
    assert keys[0][2] == DAY


@pytest.mark.unit
def test_the_morning_context_and_csv_name_use_the_ist_day(client, ist, monkeypatch):
    seen = []
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})
    monkeypatch.setattr(morning, "context", lambda s, d: seen.append(d) or {"symbol": s})
    assert client.get("/api/morning/context/NIFTY").status_code == 200 and seen == [DAY]
    monkeypatch.setattr(tr, "history_csv", lambda: "a,b\n")
    r = client.get("/api/trades.csv")
    assert r.status_code == 200 and "trade_history_2031-03-05.csv" in r.headers["content-disposition"]


PROBE = r"""
import json
from datetime import datetime
from webapp import timeutil
timeutil.now_ist = lambda: datetime(2031, 3, 5, 9, 15, 7, tzinfo=timeutil.IST)
from webapp import build_info
print(json.dumps(build_info.STARTED_AT))
"""


@pytest.mark.unit
def test_the_server_start_time_is_ist_and_keeps_its_format():
    env = os.environ | {"TRADINGAGENTS_NO_DOTENV": "1"}
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == "2031-03-05T09:15:07"     # IST wall time, no offset (the page shows it)

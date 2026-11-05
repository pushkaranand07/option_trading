"""Bug 2(b): a row entered while the market was closed (its taken_at outside the NSE session) is still listed, marked
"entered while market closed: not counted", and left out of every count: the stats, v2-counted stats and the calendar.
Read-time only: the stored row is never edited."""

import json
import subprocess
from pathlib import Path

import pytest

from tests.test_ui_regressions import closed_trade
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import signals, trade_record as tr

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rows(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    late = closed_trade(id="late", source="ai", taken_at="2026-11-04 15:33", net_pnl=2545.0, reason="target reached")
    weekend = closed_trade(id="sat", source="ai", taken_at="2026-11-07 10:00", net_pnl=900.0, reason="target reached")
    fine = closed_trade(id="ok", source="ai", taken_at="2026-11-04 14:28", net_pnl=2444.0, reason="target reached")
    tr._save([late, weekend, fine])
    return tr.overview(lambda *a: {"spot": 0, "rows": []})


@pytest.mark.unit
def test_rows_entered_outside_the_session_are_listed_but_not_counted(rows):
    ai = rows["ai"]
    assert {t["id"] for t in ai["closed"]} == {"late", "sat", "ok"}                  # still listed
    assert {t["id"]: t["outside_session"] for t in ai["closed"]} == {"late": True, "sat": True, "ok": False}
    assert (ai["stats"]["closed"], ai["stats"]["net"]) == (1, 2444.0)                # only the one entered in session


@pytest.mark.unit
def test_the_stored_rows_are_not_edited(rows):
    assert all("outside_session" not in t for t in tr._load())


@pytest.mark.unit
def test_the_page_says_not_counted_and_the_calendar_leaves_them_out(rows):
    ai = rows["ai"]
    html = subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), "S.recView = 'ai'; S.recMonth = { ai: '2026-11' }; recordHtml(ARGS[0])"],
                          input=json.dumps([{"you": {"open": [], "closed": [], "not_taken": [], "stats": rows["you"]["stats"]}, "ai": ai,
                                             "open": [], "closed": [], "stats": rows["you"]["stats"]}]),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert html.returncode == 0, html.stderr
    out = html.stdout
    assert out.count("entered while market closed: not counted") == 2
    out = out[out.index('data-view="ai"'):]                                          # the AI #1 view's own calendar
    cal = out[out.index("Day by day"):out.index("Open", out.index("Day by day"))]
    assert "₹2,444" in cal and "₹4,989" not in cal and "₹900" not in cal          # 4 Nov counts only the 14:28 trade

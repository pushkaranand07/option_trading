"""Phase 3 coverage: webapp/server.py routes and their error branches, through FastAPI's TestClient as the page
talks to it (Host 127.0.0.1, X-Pulse-Request: 1 on writes). Upstream sources are faked: the NSE client behind
option_chain, Dhan behind the guard transport, Yahoo, and the LLM-facing starters (ai.start, strategist.start,
morning.build / start_ai_build), which are replaced before any request reaches them. No socket leaves loopback."""

from __future__ import annotations

import logging
import types
from datetime import date

import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient

from tests import test_audit_b_support as support
from tradingagents.dataflows.errors import VendorError
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import (ai, ai_test, build_info, latency, market_data as md, morning, option_chain as nse_oc, planner, quant,
                    server, signals, strategist, trade_record as tr)

client, loopback = support.client, support.loopback          # the shared fixtures
H = support.HEADER
IST = "Asia/Kolkata"


def _no_llm(*a, **k):
    raise AssertionError("an LLM-facing starter was reached")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every LLM-facing entry point fails the test if reached; the calendar is a fixed one (no NSE fetch)."""
    monkeypatch.setattr(ai, "start", _no_llm)
    monkeypatch.setattr(strategist, "start", _no_llm)
    monkeypatch.setattr(morning, "start_ai_build", _no_llm)
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar({}))
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "index_lots", lambda: {})
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())


# ---------- page, middleware, status ----------

@pytest.mark.unit
def test_index_names_the_script_by_version_and_is_never_cached(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert "/static/app.js?v=" in r.text and "/static/style.css?v=" in r.text


@pytest.mark.unit
def test_writes_need_the_header_and_a_local_origin_and_hosts_are_checked(client):
    r = client.delete("/api/trades/x")
    assert r.status_code == 403 and "X-Pulse-Request: 1" in r.json()["detail"]
    r = client.delete("/api/trades/x", headers=H | {"Origin": "http://evil.example"})
    assert r.status_code == 403 and "another site" in r.json()["detail"]
    r = client.get("/api/latency", headers={"Host": "attacker.example"})
    assert r.status_code == 400
    assert server.local_origin("http://localhost:8000") and not server.local_origin("localhost")


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(ai_test, "today_status", lambda *a, **k: {"version": 3, "state": "NOT YET", "reason": None,
                                                                   "fingerprint_problem": None})
    monkeypatch.setattr(tr, "store_problem", lambda: None, raising=False)
    monkeypatch.setattr(tr, "monitor_status", lambda: {"running": False}, raising=False)
    monkeypatch.setattr(build_info, "status", lambda: {"running": "a", "repo": "a", "started_at": "t", "stale": False})


@pytest.mark.unit
@pytest.mark.parametrize(("source", "warning"), [
    ("nse", None), ("weekends only", "only weekends count as closed"), ("unknown", "could not be checked")])
def test_status_warns_by_calendar_source(client, healthy, monkeypatch, source, warning):
    monkeypatch.setattr(signals, "nse_calendar", lambda: types.SimpleNamespace(source=source))
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: True)
    monkeypatch.setattr(signals, "muhurat_today", lambda *a, **k: None)
    monkeypatch.setattr(ai, "azure_problem", lambda: "Set AZURE_OPENAI_ENDPOINT.")
    s = client.get("/api/status").json()
    assert s["azure"] is False and s["azure_problem"] == "Set AZURE_OPENAI_ENDPOINT."
    assert s["market_open"] is True and s["dhan"] is False and s["degraded"] == []
    assert (s["calendar_warning"] is None) if warning is None else (warning in s["calendar_warning"])
    assert {"symbol": "NIFTY", "name": "NIFTY 50"} in s["indices"]


@pytest.mark.unit
def test_status_lists_a_failing_azure_check_as_degraded(client, healthy, monkeypatch):
    monkeypatch.setattr(ai, "azure_problem", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    s = client.get("/api/status").json()
    assert [d["part"] for d in s["degraded"]] == ["azure"] and "error id" in s["degraded"][0]["reason"]
    assert s["azure"] is False and s["azure_problem"] == "The Azure settings could not be checked."


@pytest.mark.unit
def test_latency_reports_the_routes_called(client):
    client.get("/api/search", params={"q": "nifty"})
    rep = client.get("/api/latency").json()
    assert rep["api GET /api/search"]["count"] >= 1
    assert set(rep["api GET /api/search"]) == {"count", "p50_ms", "p95_ms", "p99_ms", "max_ms"}
    assert "api GET /api/latency" in latency.report()                 # the report's own request, timed after it


# ---------- search, quotes, candles ----------

@pytest.mark.unit
def test_search_answers_from_the_instrument_table(client):
    r = client.get("/api/search", params={"q": "bank"})
    assert r.status_code == 200 and r.json()[0] == {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "kind": "INDEX"}


@pytest.mark.unit
def test_quotes_drop_blanks_and_cap_at_30_symbols(client, monkeypatch):
    seen = []
    monkeypatch.setattr(md, "quotes", lambda syms: seen.append(syms) or {s: {"ltp": 1} for s in syms})
    names = ",".join(f"S{i}" for i in range(40))
    r = client.get("/api/quotes", params={"symbols": "NIFTY,," + names})
    assert r.status_code == 200 and len(seen[0]) == 30 and seen[0][0] == "NIFTY" and "" not in seen[0]


@pytest.mark.unit
def test_quotes_upstream_error_is_502_with_its_message(client, monkeypatch):
    def down(_):
        raise requests.ConnectionError("Yahoo unreachable")
    monkeypatch.setattr(md, "quotes", down)
    r = client.get("/api/quotes", params={"symbols": "NIFTY"})
    assert r.status_code == 502 and r.json() == {"detail": "Yahoo unreachable"}


def _bars(n=3, end="2026-11-03 10:00"):
    idx = pd.date_range(end=pd.Timestamp(end, tz=IST), periods=n, freq="5min")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": [float(i) for i in range(n)], "volume": 10.0},
                        index=idx)


@pytest.mark.unit
def test_candles_live_and_limited(client, monkeypatch):
    now = pd.Timestamp("2026-11-03 10:02", tz=IST).to_pydatetime()
    monkeypatch.setattr(md, "candles", lambda s, tf: (_bars(10), "dhan"))
    monkeypatch.setattr(md, "bar_age", lambda df, at=None: ((at or now) - df.index[-1].to_pydatetime()).total_seconds())
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: True)
    r = client.get("/api/candles/nifty", params={"tf": "5m", "limit": 4})
    body = r.json()
    assert r.status_code == 200 and body["symbol"] == "NIFTY" and body["source"] == "dhan"
    assert [b["close"] for b in body["bars"]] == [6.0, 7.0, 8.0, 9.0]
    assert body["bars"][-1]["time"] == int(pd.Timestamp("2026-11-03 10:00", tz=IST).timestamp())
    assert body["data"] == {"last_bar_age_s": 120, "stale": False, "live": True}


@pytest.mark.unit
def test_candles_saved_bars_are_not_live_and_old_bars_are_stale(client, monkeypatch):
    monkeypatch.setattr(md, "candles", lambda s, tf: (_bars(2, "2026-11-02 15:25"), "saved (last bar 02-Nov 15:25)"))
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: True)
    d = client.get("/api/candles/NIFTY").json()["data"]
    assert d["stale"] is True and d["live"] is False and d["last_bar_age_s"] > 600


@pytest.mark.unit
def test_candles_errors(client, monkeypatch, caplog):
    r = client.get("/api/candles/NIFTY", params={"tf": "2h"})
    assert r.status_code == 502 and r.json()["detail"] == "Unknown timeframe 2h"
    assert client.get("/api/candles/NIFTY", params={"limit": 0}).status_code == 422

    def bug(s, tf):
        raise ZeroDivisionError("secret detail")
    monkeypatch.setattr(md, "candles", bug)
    with caplog.at_level(logging.ERROR, logger="webapp.server"):
        r = client.get("/api/candles/NIFTY")
    assert r.status_code == 500 and r.json()["detail"] == "Internal error" and "secret" not in r.text
    assert r.json()["error_id"] in caplog.text


# ---------- plan, Dhan option chain, expiries ----------

@pytest.mark.unit
def test_plan_and_its_vendor_error(client, monkeypatch):
    monkeypatch.setattr(planner, "plan", lambda s: {"symbol": s, "verdict": "WAIT"})
    assert client.get("/api/plan/NIFTY").json() == {"symbol": "NIFTY", "verdict": "WAIT"}

    def throttled(s):
        raise VendorError("NSE throttled the request; try again in a minute.")
    monkeypatch.setattr(planner, "plan", throttled)
    r = client.get("/api/plan/NIFTY")
    assert r.status_code == 502 and "throttled" in r.json()["detail"]


@pytest.mark.unit
def test_dhan_routes_without_dhan_say_so(client):
    for path in ("/api/expiries/NIFTY", "/api/optionchain/NIFTY", "/api/optionchain/NIFTY?expiry=2026-11-10"):
        r = client.get(path)
        assert r.status_code == 502 and "needs Dhan" in r.json()["detail"], path


@pytest.mark.unit
def test_dhan_option_chain_through_the_guard_carries_the_view(client, monkeypatch, tmp_path):
    from tests.test_audit_p3_cov_market_data import Resp, Transport, _chain_body
    from webapp import dhan_guard

    monkeypatch.setenv("DHAN_CLIENT_ID", "fake-client")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(md, "dhan", md.Dhan())
    monkeypatch.setattr(dhan_guard, "_sleep", lambda s: None)
    t = Transport()
    t.routes["/v2/optionchain/expirylist"] = Resp(200, {"status": "success", "data": ["2026-11-10", "2026-11-17"]})
    t.routes["/v2/optionchain"] = Resp(200, _chain_body())
    monkeypatch.setattr(dhan_guard.requests, "request", t)

    assert client.get("/api/expiries/NIFTY").json() == ["2026-11-10", "2026-11-17"]
    r = client.get("/api/optionchain/NIFTY", params={"expiry": "2026-11-17"})
    body = r.json()
    assert r.status_code == 200 and body["expiry"] == "2026-11-17" and body["spot"] == 25010.0
    assert body["view"]["atm"] == 25000.0 and body["view"]["pcr"] == round(4500 / 9010, 2)
    assert body["view"]["bias"] == "BEARISH"
    r = client.get("/api/optionchain/NIFTY", params={"expiry": "2030-01-01"})
    assert r.status_code == 400 and r.json()["detail"]["valid_expiries"] == ["2026-11-10", "2026-11-17"]


# ---------- AI jobs (refused or faked; nothing reaches an LLM) ----------

@pytest.mark.unit
def test_ai_start_refused_without_azure_and_job_lookup(client, monkeypatch):
    monkeypatch.setattr(ai, "azure_problem", lambda: "Azure is not configured.")
    r = client.post("/api/ai", json={"symbol": "NIFTY"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"] == "Azure is not configured."
    assert client.get("/api/ai/nope").status_code == 404
    monkeypatch.setattr(ai, "get", lambda j: {"id": j, "state": "done"} if j == "j1" else None)
    assert client.get("/api/ai/j1").json() == {"id": "j1", "state": "done"}


@pytest.mark.unit
def test_ai_start_with_a_faked_starter(client, monkeypatch):
    monkeypatch.setattr(ai, "azure_problem", lambda: None)
    started = []
    monkeypatch.setattr(ai, "start", lambda sym, yahoo, analysts: started.append((sym, yahoo, analysts)) or "job-1")
    r = client.post("/api/ai", json={"symbol": "banknifty", "analysts": ["market"]}, headers=H)
    assert r.json() == {"job": "job-1"} and started == [("BANKNIFTY", "^NSEBANK", ["market"])]


# ---------- morning ----------

PLAN = {"date": "2026-11-03", "indices": {"NIFTY": {"context": {"bias": "UP"}}}}


@pytest.mark.unit
def test_morning_saved_plan_by_date_and_bad_dates(client, monkeypatch):
    monkeypatch.setattr(morning, "ai_status", lambda: {"running": False})
    assert client.get("/api/morning", params={"date": "03-11-2026"}).json() == {"detail": "date must be YYYY-MM-DD"}
    r = client.get("/api/morning", params={"date": "2026-11-03"})
    assert r.status_code == 404 and r.json()["detail"] == "No saved plan for 2026-11-03"
    morning.save(PLAN, date(2026, 11, 3))
    r = client.get("/api/morning", params={"date": "2026-11-03"})
    assert r.status_code == 200 and r.json() == PLAN | {"ai_job": {"running": False}}


@pytest.mark.unit
def test_morning_today_loads_or_builds_without_ai(client, monkeypatch):
    monkeypatch.setattr(morning, "ai_status", lambda: {"running": True})
    built = []
    monkeypatch.setattr(morning, "build", lambda day, with_ai: built.append((day, with_ai)) or {"built": True})
    monkeypatch.setattr(morning, "load", lambda day=None: None)
    assert client.get("/api/morning").json() == {"built": True, "ai_job": {"running": True}}
    assert built == [(None, False)]
    monkeypatch.setattr(morning, "load", lambda day=None: dict(PLAN))
    assert client.get("/api/morning").json() == PLAN | {"ai_job": {"running": True}}
    assert len(built) == 1

    r = client.post("/api/morning/refresh", headers=H)
    assert r.json() == {"built": True, "ai_job": {"running": True}} and built[-1] == (None, False)


@pytest.mark.unit
def test_morning_context_and_ai(client, monkeypatch):
    seen = []
    monkeypatch.setattr(morning, "context", lambda sym, day: seen.append((sym, day)) or {"bias": "DOWN"})
    r = client.get("/api/morning/context/finnifty")
    assert r.json() == {"context": {"bias": "DOWN"}, "ai": None} and seen[0][0] == "FINNIFTY"
    monkeypatch.setattr(ai, "azure_problem", lambda: "no Azure")
    r = client.post("/api/morning/ai", headers=H)
    assert r.status_code == 400 and r.json()["detail"] == "no Azure"
    monkeypatch.setattr(ai, "azure_problem", lambda: None)
    monkeypatch.setattr(morning, "start_ai_build", lambda: {"running": True, "started": "now"})
    assert client.post("/api/morning/ai", headers=H).json() == {"running": True, "started": "now"}


# ---------- NSE chain, contract, rank (fake NSE client) ----------

class _NSE:
    def __init__(self, expiries=("10-Nov-2026", "17-Nov-2026"), chart=None, fail=None):
        self.expiries, self.chart, self.fail, self.asked = list(expiries), chart, fail, []

    def get_json(self, path, params, ttl=None):
        self.asked.append((path, dict(params)))
        if self.fail:
            raise self.fail
        if path == nse_oc.CONTRACT_INFO:
            data = {"expiryDates": self.expiries}
        elif path == nse_oc.CHART:
            data = self.chart
        else:
            data = {"records": {"underlyingValue": 25010.0, "timestamp": "03-Nov-2026 11:00:00", "data": [
                {"strikePrice": k, "CE": {"openInterest": 10, "lastPrice": 100.0, "impliedVolatility": 12.0,
                                          "identifier": f"OPTIDXNIFTY10-11-2026CE{k}.00"},
                 "PE": {"openInterest": 20, "lastPrice": 90.0, "impliedVolatility": 13.0}}
                for k in (24900, 25000, 25100)]}}
        return types.SimpleNamespace(data=data)


@pytest.mark.unit
def test_nse_chain_from_a_fake_nse(client, monkeypatch):
    nse = _NSE()
    monkeypatch.setattr(nse_oc, "_client", lambda: nse)
    r = client.get("/api/chain/nifty", params={"expiry": "17-Nov-2026"})
    body = r.json()
    assert r.status_code == 200 and body["expiry"] == "17-Nov-2026" and body["atm"] == 25000.0
    assert body["lot"] == 65 and body["rows"][1]["ce"]["oi"] == 650 and body["summary"]["pcr"] == 2.0
    r = client.get("/api/chain/NIFTY", params={"expiry": "01-Jan-2030"})
    assert r.status_code == 400 and r.json()["detail"]["valid_expiries"] == ["10-Nov-2026", "17-Nov-2026"]


@pytest.mark.unit
def test_nse_chain_with_no_expiries_or_nse_down(client, monkeypatch):
    monkeypatch.setattr(nse_oc, "_client", lambda: _NSE(expiries=()))
    r = client.get("/api/chain/SENSEX")
    assert r.status_code == 404 and "lists no option expiries" in r.json()["detail"]
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(nse_oc, "_client", lambda: _NSE(fail=requests.ConnectionError("NSE refused the connection")))
    r = client.get("/api/chain/NIFTY")
    assert r.status_code == 502 and r.json()["detail"] == "NSE refused the connection"


@pytest.mark.unit
def test_contract_points_and_errors(client, monkeypatch):
    nse = _NSE(chart={"grapthData": [[1762160400000, 101.5], [1762160410000, None], [1762160420000, 99.0]],
                      "closePrice": 95.0})
    monkeypatch.setattr(nse_oc, "_client", lambda: nse)
    ident = "OPTIDXNIFTY10-11-2026CE25000.00"
    body = client.get("/api/contract", params={"id": ident}).json()
    assert body == {"id": ident, "points": [[1762160400, 101.5], [1762160420, 99.0]], "prev_close": 95.0,
                    "high": 101.5, "low": 99.0, "last": 99.0}
    r = client.get("/api/contract", params={"id": "RELIANCE"})
    assert r.status_code == 400 and r.json()["detail"] == "Not an NSE option identifier."
    monkeypatch.setattr(nse_oc, "_client", lambda: _NSE(fail=requests.Timeout("NSE timed out")))
    r = client.get("/api/contract", params={"id": "OPTIDXNIFTY10-11-2026PE25000.00"})
    assert r.status_code == 502 and r.json()["detail"] == "NSE timed out"


@pytest.mark.unit
def test_rank_errors_map_to_404_and_502(client, monkeypatch):
    monkeypatch.setattr(nse_oc, "valid_expiries", lambda s: ["10-Nov-2026"])
    monkeypatch.setattr(strategist, "rank", lambda s, e=None: {"symbol": s, "expiry": e, "candidates": []})
    assert client.get("/api/rank/nifty").json() == {"symbol": "NIFTY", "expiry": None, "candidates": []}

    def no_chain(s, e=None):
        raise nse_oc.ChainError("NSE returned an empty option chain.")
    monkeypatch.setattr(strategist, "rank", no_chain)
    r = client.get("/api/rank/NIFTY")
    assert r.status_code == 404 and r.json()["detail"] == "NSE returned an empty option chain."

    def vendor(s, e=None):
        raise VendorError("NSE throttled")
    monkeypatch.setattr(strategist, "rank", vendor)
    assert client.get("/api/rank/NIFTY", params={"expiry": "10-Nov-2026"}).json() == {"detail": "NSE throttled"}


# ---------- strategy ----------

@pytest.mark.unit
def test_strategy_start_refusals_and_a_faked_start(client, monkeypatch):
    monkeypatch.setattr(ai, "azure_problem", lambda: "Azure missing")
    r = client.post("/api/strategy", json={"symbol": "NIFTY", "mode": "quick"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"] == "Azure missing"
    monkeypatch.setattr(ai, "azure_problem", lambda: None)
    assert client.post("/api/strategy", json={"symbol": "NIFTY", "mode": "fast"}, headers=H).status_code == 422

    def no_research(sym, expiry, mode):
        raise strategist.NoResearch("Run a Complete analysis first.")
    monkeypatch.setattr(strategist, "start", no_research)
    r = client.post("/api/strategy", json={"symbol": "NIFTY", "mode": "quick"}, headers=H)
    assert r.status_code == 400 and r.json()["detail"] == "Run a Complete analysis first."
    monkeypatch.setattr(strategist, "start", lambda sym, expiry, mode: f"{sym}-{expiry}-{mode}")
    r = client.post("/api/strategy", json={"symbol": "banknifty", "expiry": "17-Nov-2026"}, headers=H)
    assert r.json() == {"job": "BANKNIFTY-17-Nov-2026-full"}


@pytest.mark.unit
def test_strategy_research_latest_and_status(client, monkeypatch):
    monkeypatch.setattr(morning, "load", lambda day=None: None)
    assert client.get("/api/strategy/research/NIFTY").json() == {}
    assert client.get("/api/strategy/latest/NIFTY").json() == {}
    strategist.save_research("NIFTY", {"rating": "BUY", "minutes": 12, "notes": "long text"})
    r = client.get("/api/strategy/research/nifty").json()
    assert r["source"] == "complete analysis" and r["rating"] == "BUY" and r["minutes"] == 12 and "notes" not in r

    strategist.save_run({"symbol": "NIFTY", "run_id": "r1", "day": "2001-01-01", "candidates": []})
    run = client.get("/api/strategy/latest/NIFTY").json()
    assert run["run_id"] == "r1" and run["expired"] is True
    monkeypatch.setattr(strategist, "run_expired", lambda run: False)
    assert client.get("/api/strategy/latest/NIFTY").json()["expired"] is False

    assert client.get("/api/strategy/nojob").status_code == 404
    monkeypatch.setattr(strategist, "job", lambda j: {"id": j, "state": "running"} if j == "k" else None)
    assert client.get("/api/strategy/k").json() == {"id": "k", "state": "running"}


# ---------- quant routes, market map, journal ----------

@pytest.mark.unit
def test_quant_routes_pass_through_and_map_vendor_errors(client, monkeypatch):
    monkeypatch.setattr(quant, "risk", lambda s: {"symbol": s, "var": 1.5})
    monkeypatch.setattr(quant, "spreads", lambda s: {"symbol": s, "rows": []})
    monkeypatch.setattr(quant, "research", lambda: {"trials": 1532})
    assert client.get("/api/risk/NIFTY").json() == {"symbol": "NIFTY", "var": 1.5}
    assert client.get("/api/spreads/NIFTY").json() == {"symbol": "NIFTY", "rows": []}
    assert client.get("/api/research").json() == {"trials": 1532}

    def missing(s):
        raise md.DataError("No price data for NIFTY (Yahoo unreachable and nothing saved yet)")
    monkeypatch.setattr(quant, "risk", missing)
    r = client.get("/api/risk/NIFTY")
    assert r.status_code == 502 and r.json()["detail"].startswith("No price data for NIFTY")


@pytest.mark.unit
def test_market_map_missing_then_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(quant, "MARKET_MAP", tmp_path / "map.html")
    r = client.get("/market-map")
    assert r.status_code == 404 and "python scripts/market_map.py" in r.json()["detail"]
    (tmp_path / "map.html").write_text("<html>map</html>", encoding="utf-8")
    r = client.get("/market-map")
    assert r.status_code == 200 and r.text == "<html>map</html>"


@pytest.mark.unit
def test_journal_upload_list_and_read(client, monkeypatch):
    monkeypatch.setattr(quant, "journal_files", lambda: [{"name": "a.csv"}])
    assert client.get("/api/journal/files").json() == [{"name": "a.csv"}]

    up = H | {"Content-Type": "text/csv"}
    r = client.post("/api/journal/upload", params={"name": "a.csv"}, content=b"x", headers=H | {"Content-Type": "text/plain"})
    assert r.status_code == 415 and "application/octet-stream" in r.json()["detail"]

    def bad_name(name, data):
        raise ValueError("Only .csv or .xlsx files.")
    monkeypatch.setattr(quant, "save_upload", bad_name)
    r = client.post("/api/journal/upload", params={"name": "a.exe"}, content=b"x,y\n", headers=up)
    assert r.status_code == 400 and r.json()["detail"] == "Only .csv or .xlsx files."
    saved = []
    monkeypatch.setattr(quant, "save_upload", lambda name, data: saved.append(data) or name)
    r = client.post("/api/journal/upload", params={"name": "a.csv"}, content=b"x,y\n", headers=up)
    assert r.json() == {"name": "a.csv"} and saved == [b"x,y\n"]
    monkeypatch.setattr(quant, "MAX_UPLOAD", 3)
    r = client.post("/api/journal/upload", params={"name": "a.csv"}, content=b"x,y\n", headers=up)
    assert r.status_code == 413 and r.json()["detail"] == "File is larger than 3 bytes."

    def bad_horizon(name, horizon):
        raise ValueError(f"Unknown horizon {horizon}")
    monkeypatch.setattr(quant, "journal", bad_horizon)
    r = client.get("/api/journal", params={"name": "a.csv", "horizon": "decade"})
    assert r.status_code == 400 and r.json()["detail"] == "Unknown horizon decade"
    monkeypatch.setattr(quant, "journal", lambda name, horizon: {"name": name, "horizon": horizon, "trades": 3})
    assert client.get("/api/journal", params={"name": "a.csv"}).json() == {"name": "a.csv", "horizon": "all", "trades": 3}


# ---------- trades ----------

@pytest.mark.unit
def test_trades_overview_and_csv_download(client, monkeypatch):
    monkeypatch.setattr(tr, "overview", lambda: {"mine": {"open": [], "closed": []}})
    assert client.get("/api/trades").json() == {"mine": {"open": [], "closed": []}}
    monkeypatch.setattr("webapp.timeutil.now_ist", lambda: pd.Timestamp("2026-11-03 11:00", tz=IST).to_pydatetime())
    r = client.get("/api/trades.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="trade_history_2026-11-03.csv"'
    assert r.text.splitlines()[0].split(",")[:3] == ["view", "source", "status"]


@pytest.mark.unit
def test_take_maps_each_refusal(client, monkeypatch):
    refused = []
    monkeypatch.setattr(tr, "record_refused", lambda run_id, cand, exc, src: refused.append((run_id, cand, str(exc), src)))

    def take(run_id, candidate, confirm=False):
        if candidate == 0:
            return {"id": "t1", "run_id": run_id, "confirm": confirm}
        if candidate == 1:
            raise tr.BetExists("Adds to a running bet.", {"bet_id": "b1"})
        if candidate == 2:
            raise tr.TradeError("the market is closed")
        if candidate == 3:
            raise KeyError("unknown direction")
        raise tr.StoreCorrupt("trades.json can't be read")
    monkeypatch.setattr(tr, "take_from_run", take)

    assert client.post("/api/trades", json={"run_id": "r1", "candidate": 0, "confirm": True}, headers=H).json() == \
        {"id": "t1", "run_id": "r1", "confirm": True}
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 1}, headers=H)
    assert r.status_code == 409 and r.json()["detail"] == {"message": "Adds to a running bet.", "bet_id": "b1"}
    r = client.post("/api/trades", json={"run_id": None, "candidate": 2}, headers=H)
    assert r.status_code == 400 and r.json()["detail"] == "Not taken: the market is closed"
    assert refused == [("", 2, "the market is closed", "you")]
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 3}, headers=H)
    assert r.status_code == 400 and "unknown direction" in r.json()["detail"]
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 4}, headers=H)
    assert r.status_code == 503 and "trades.json can't be read" in r.json()["detail"]
    assert client.post("/api/trades", json={"run_id": "r1", "candidate": "1"}, headers=H).status_code == 422


@pytest.mark.unit
def test_trades_refresh_branches(client, monkeypatch):
    monkeypatch.delattr(tr, "refresh_open")
    r = client.post("/api/trades/refresh", headers=H)
    assert r.status_code == 501 and "update and restart" in r.json()["detail"]
    monkeypatch.setattr(tr, "refresh_open", lambda: {"settled": 2}, raising=False)
    assert client.post("/api/trades/refresh", headers=H).json() == {"ok": True, "result": {"settled": 2}}
    monkeypatch.setattr(tr, "refresh_open", lambda: object(), raising=False)
    assert client.post("/api/trades/refresh", headers=H).json() == {"ok": True, "result": None}
    for exc, code in ((tr.StoreCorrupt("damaged"), 503), (tr.TradeError("no open trades"), 400)):
        monkeypatch.setattr(tr, "refresh_open", lambda exc=exc: (_ for _ in ()).throw(exc), raising=False)
        r = client.post("/api/trades/refresh", headers=H)
        assert r.status_code == code and str(exc) in r.json()["detail"]


@pytest.mark.unit
def test_close_and_delete_branches(client, monkeypatch):
    monkeypatch.setattr(tr, "close", lambda tid: {"id": tid, "status": "closed"})
    monkeypatch.setattr(tr, "delete", lambda tid: None)
    assert client.post("/api/trades/t1/close", headers=H).json() == {"id": "t1", "status": "closed"}
    assert client.delete("/api/trades/t1", headers=H).json() == {"ok": True}
    for exc, close_code, delete_code in ((tr.StoreCorrupt("damaged"), 503, 503), (tr.TradeError("No trade t9"), 400, 404)):
        def fail(tid, exc=exc):
            raise exc
        monkeypatch.setattr(tr, "close", fail)
        monkeypatch.setattr(tr, "delete", fail)
        r = client.post("/api/trades/t9/close", headers=H)
        assert r.status_code == close_code and str(exc) in r.json()["detail"]
        r = client.delete("/api/trades/t9", headers=H)
        assert r.status_code == delete_code and str(exc) in r.json()["detail"]


# ---------- lifespan ----------

@pytest.mark.unit
def test_lifespan_starts_and_stops_each_part_and_survives_a_failing_one(loopback, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(md, "start_refresh_ahead", lambda: calls.append("refresh-ahead"))
    monkeypatch.setattr(tr, "start_monitor", lambda: (_ for _ in ()).throw(RuntimeError("monitor broke")))
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: "v2 code changed: ask_rank_llm")
    monkeypatch.setattr(tr, "refresh_open", lambda: calls.append("settle"), raising=False)
    monkeypatch.setattr(md, "stop_refresh_ahead", lambda: calls.append("stop refresh-ahead"), raising=False)
    monkeypatch.setattr(tr, "stop_monitor", lambda: (_ for _ in ()).throw(RuntimeError("stop broke")), raising=False)
    with caplog.at_level(logging.ERROR, logger="webapp.server"):
        with TestClient(server.app, base_url="http://127.0.0.1") as c:
            assert c.get("/api/latency").status_code == 200
        for _ in range(200):                                          # the settle runs in its own thread
            if "settle" in calls:
                break
            import time
            time.sleep(0.01)
    assert calls[0] == "refresh-ahead" and "settle" in calls and "stop refresh-ahead" in calls
    assert "Start-up step failed: trade monitor" in caplog.text and "Shutdown step failed: trade monitor" in caplog.text
    assert "v2 forward test: v2 code changed" in caplog.text


@pytest.mark.unit
def test_background_refresh_does_nothing_without_refresh_open(monkeypatch):
    monkeypatch.delattr(tr, "refresh_open")
    assert server._refresh_in_background() is None
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None)
    assert server.v2_startup_check() is None

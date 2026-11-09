"""Audit L6 (track D): the clock reads in market_data, option_chain, ai, the analytics files and the NSE calendar /
flows modules use India time, not the PC's local time. Each test runs on a PC whose clock is in UTC: 20:00 UTC on
8 Nov 2026 is 01:30 IST on 9 Nov. On an IST machine nothing changes: the stamps keep their naive form.

Windows can't switch the process time zone, so the "UTC machine" is a datetime / date whose naive ``now()`` /
``today()`` return UTC wall-clock values, patched into the module under test. No network, no LLM."""

import csv
import datetime as dt
import json
import os
import sqlite3
import types
from datetime import UTC, date, datetime, timedelta

import pytest

from tradingagents.dataflows.vendors.nse import calendar as nse_cal

INSTANT = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)          # 01:30 IST on 9 Nov


def utc_machine(instant=INSTANT):
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)    # naive = UTC wall clock

        @classmethod
        def today(cls):
            return cls.now()

    class FakeDate(date):
        @classmethod
        def today(cls):
            return instant.date()

    return FakeDatetime, FakeDate


@pytest.fixture
def clock(monkeypatch):
    """Patch a UTC-machine clock into the given modules (and the shared IST helpers)."""
    def apply(*modules, instant=INSTANT):
        fdt, fdate = utc_machine(instant)
        for m in (*modules, nse_cal):
            monkeypatch.setattr(m, "datetime", fdt, raising=False)
            if hasattr(m, "date"):
                monkeypatch.setattr(m, "date", fdate)
        ist = instant.astimezone(nse_cal.IST)
        monkeypatch.setattr("webapp.timeutil.now_ist", lambda: ist)
        monkeypatch.setattr("webapp.signals.now_ist", lambda: ist)
        return fdt, fdate
    return apply


@pytest.mark.unit
def test_scrip_master_downloaded_today_in_india_is_not_downloaded_again(clock, monkeypatch, tmp_path):
    from webapp import market_data as md

    monkeypatch.setattr(md, "CACHE_DIR", tmp_path)
    path = tmp_path / "dhan-scrip-master.csv"
    path.write_text("x", encoding="utf-8")
    saved = datetime(2026, 11, 8, 19, 45, tzinfo=UTC).timestamp()         # 01:15 IST on 9 Nov: today in India
    os.utime(path, (saved, saved))
    clock(md)
    fetched = []
    monkeypatch.setattr(md.dhan_guard, "request", lambda *a, **k: fetched.append(a) or (_ for _ in ()).throw(OSError))
    assert md._scrip_master_path() == path
    assert fetched == []


@pytest.mark.unit
def test_option_chain_stamps_and_stock_lot_window_use_india_time(clock, monkeypatch):
    from tradingagents.analytics import datastore as ds
    from webapp import option_chain as oc

    _, fdate = clock(oc)
    monkeypatch.setattr(dt, "date", fdate)                  # lot_size imports ``date`` inside the function
    seen = {}

    def load(name, symbols=None, start=None, **k):
        seen["start"] = start
        import pandas as pd
        return pd.DataFrame({"trade_date": [date(2026, 11, 6)], "lot_size": [500]})

    monkeypatch.setattr(ds, "load", load)
    assert oc.lot_size("RELIANCE") == 500
    assert seen["start"] == date(2026, 11, 9) - timedelta(days=30)

    raw = {"records": {"underlyingValue": 100.0, "data": [{"strikePrice": 100, "CE": {"lastPrice": 1, "openInterest": 1}}]}}
    monkeypatch.setattr(oc, "_raw_chain", lambda *a: raw)
    assert oc._chain("NIFTY", "17-Nov-2026", ["17-Nov-2026"], 65, None)["fetched"] == "01:30:00"


@pytest.mark.unit
def test_ai_job_times_and_trade_date_are_india_time(clock, monkeypatch):
    import tradingagents.agents.rating as rating
    import tradingagents.graph.trading_graph as tg
    from webapp import ai

    clock(ai)
    monkeypatch.setattr(ai.threading, "Thread", lambda *a, **k: types.SimpleNamespace(start=lambda: None))
    job_id = ai.start("NIFTY", "^NSEI", ["market"])                 # the job thread is never started
    assert ai.get(job_id)["started"] == "01:30"

    seen = {}

    class FakeGraph:                                                 # no LLM: nothing is built or called
        def __init__(self, selected_analysts, config):
            self.config = config
            self.propagator = types.SimpleNamespace(get_graph_args=lambda: {})

        def create_run_state(self, ticker, trade_date):
            seen["trade_date"] = trade_date
            return {}

        def stream_run(self, init, **kw):
            return iter(())

        def record_decision(self, *a):
            pass

    monkeypatch.setattr(tg, "TradingAgentsGraph", FakeGraph)
    monkeypatch.setattr(rating, "run_rating", lambda state: "HOLD")
    ai._run(job_id, "^NSEI", ["market"])
    job = ai.get(job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["trade_date"] == "2026-11-09" and job["finished"] == "01:30"


@pytest.mark.unit
def test_backfill_and_base_store_stamps_are_india_time(clock, tmp_path):
    from tradingagents.analytics import backfill, base_store

    clock(backfill, base_store)
    assert backfill._now() == "2026-11-09T01:30:00"                 # naive, as before
    src = tmp_path / "data" / "fo_2026.parquet"
    src.parent.mkdir(parents=True)
    src.write_text("x", encoding="utf-8")
    assert base_store._snapshot(src).name == "fo_2026-20261109-013000.parquet"


@pytest.mark.unit
def test_board_meetings_window_ends_today_in_india(clock, tmp_path):
    from tradingagents.analytics import events

    clock(events)
    seen = {}

    class Client:
        def get_json(self, path, params=None, ttl=None):
            seen.update(params)
            return types.SimpleNamespace(data=[])

    events.fetch_board_meetings("RELIANCE", client=Client(), root=tmp_path)
    assert seen["to_date"] == "09-11-2026"


@pytest.mark.unit
def test_paper_ledger_stamps_are_india_time(clock, tmp_path):
    from tradingagents.analytics import paper

    clock(paper)
    strategy = paper.PaperStrategy("s", "x", date(2026, 1, 1), lambda: [], 0.0, 1.0)
    trade = types.SimpleNamespace(strikes={"sp": 100.0}, symbol="NIFTY", entry_date=date(2026, 11, 6),
                                  expiry=date(2026, 11, 17), credit=10.0, lot=65, max_risk=100.0, exit_date=None,
                                  exit_reason=None, pnl=0.0, return_on_risk=0.0)
    db = tmp_path / "ledger.sqlite"
    assert paper.update(strategy, [trade], path=db)["new"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT first_seen FROM trades").fetchone()[0] == "2026-11-09T01:30:00"


@pytest.mark.unit
def test_last_complete_session_follows_the_india_clock(clock):
    from tradingagents.analytics import prices

    clock(prices, instant=datetime(2026, 11, 9, 11, 0, tzinfo=UTC))       # 16:30 IST: today's bar is final
    assert prices.last_complete_session_date() == date(2026, 11, 9)
    assert prices.last_complete_session_date(datetime(2026, 11, 9, 15, 0)) == date(2026, 11, 8)   # given: unchanged


@pytest.mark.unit
def test_holiday_list_and_flow_history_stamps_are_india_time(clock, monkeypatch, tmp_path):
    from tradingagents.dataflows.vendors.nse import flows

    clock(flows)
    monkeypatch.setattr(nse_cal, "SAVED_HOLIDAYS", str(tmp_path / "holidays.json"))
    nse_cal._save_holidays({date(2026, 11, 10): "Diwali-Balipratipada"})
    assert json.loads((tmp_path / "holidays.json").read_text(encoding="utf-8"))["saved_at"] == "2026-11-09T01:30:00"

    path = tmp_path / "flows.csv"
    row = types.SimpleNamespace(category="FII", buy_cr=1.0, sell_cr=2.0, net_cr=-1.0)
    flows.record_history(date(2026, 11, 6), [row], "nse", path=path)
    with path.open(encoding="utf-8") as fh:
        assert next(csv.DictReader(fh))["fetched_at"] == "2026-11-09T01:30:00"

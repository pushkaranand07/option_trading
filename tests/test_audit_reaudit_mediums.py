"""Re-audit Mediums (audit 2026-11).

S2: after 15:30 on expiry day the default expiry was still the expired one, so /api/rank priced dead contracts. The
    default now moves to the next expiry once today's has expired; a named expiry and the 09:30-15:00 forward-test
    window are unaffected.
S3: an expired trade settled at last_spot, however old (e.g. the server was off on expiry day). It now settles at
    the expiry day's close from the daily bars; only if that is unavailable does it use the last price seen, and
    the reason says so.
S4: one row that was valid JSON but malformed (e.g. expiry "bad-date") made overview() raise, so GET /api/trades was
    a 500 and every monitor tick failed. A malformed row is now set aside and named; everything else works, and the
    row is never dropped from the file.
"""

import json
from datetime import datetime

import pandas as pd
import pytest
import pytz

from webapp import option_chain as oc, signals, trade_record as tr

IST = pytz.timezone("Asia/Kolkata")
EXPS = ["09-Nov-2026", "17-Nov-2026", "24-Nov-2026"]


# ---------------------------------------------------------------- S2


@pytest.mark.unit
@pytest.mark.parametrize(("hour", "minute", "expected"), [(15, 29, "09-Nov-2026"), (15, 30, "17-Nov-2026"), (20, 40, "17-Nov-2026")])
def test_the_default_expiry_moves_on_once_todays_has_expired(monkeypatch, hour, minute, expected):
    monkeypatch.setattr(oc.timeutil, "now_ist", lambda: IST.localize(datetime(2026, 11, 9, hour, minute)))
    assert oc._pick_expiry(None, EXPS, strict=False) == expected


@pytest.mark.unit
def test_a_named_expiry_is_kept_even_after_the_close(monkeypatch):
    monkeypatch.setattr(oc.timeutil, "now_ist", lambda: IST.localize(datetime(2026, 11, 9, 20, 0)))
    assert oc._pick_expiry("09-Nov-2026", EXPS, strict=False) == "09-Nov-2026"
    assert oc._pick_expiry(None, ["09-Nov-2026"], strict=False) == "09-Nov-2026"     # nothing later listed: keep it


# ---------------------------------------------------------------- S3


def _expired_trade(**kw):
    t = {"id": "e1", "status": "open", "source": "you", "taken_at": "2026-11-05 10:00", "symbol": "NIFTY",
         "expiry": "06-Nov-2026", "strategy": "long_call", "lot": 65, "lots": 1, "net_entry": -100.0, "debit": True,
         "spot_at_entry": 24000.0, "last_spot": 24100.0,                       # last seen on the 5th: stale
         "legs": [{"action": "BUY", "type": "CE", "strike": 24500.0, "entry": 100.0}]}
    return t | kw


@pytest.mark.unit
def test_an_expired_trade_settles_at_the_expiry_days_close(monkeypatch):
    bars = pd.DataFrame({"close": [24900.0, 25030.35]},
                        index=pd.to_datetime(["2026-11-05", "2026-11-06"]).tz_localize("Asia/Kolkata"))
    monkeypatch.setattr(tr, "_daily_close", lambda symbol, day: float(bars["close"][bars.index.date == day].iloc[0]))
    monkeypatch.setattr(tr, "_clock", lambda: IST.localize(datetime(2026, 11, 9, 11, 0)))
    t = _expired_trade()
    d = tr._settle_decision(t, tr.mark(t))
    assert d[0] == "settle" and d[2] == 25030.35                     # the 6 Nov close, not the stale 24,100
    assert d[1] == [pytest.approx(530.35)]                           # intrinsic of the 24,500 call at 25,030.35


@pytest.mark.unit
def test_without_the_expiry_close_it_uses_the_last_price_and_says_so(monkeypatch):
    monkeypatch.setattr(tr, "_daily_close", lambda symbol, day: None)
    monkeypatch.setattr(tr, "_clock", lambda: IST.localize(datetime(2026, 11, 9, 11, 0)))
    t = _expired_trade()
    d = tr._settle_decision(t, tr.mark(t))
    assert d[0] == "settle" and d[2] == 24100.0 and "last price seen" in d[3]


# ---------------------------------------------------------------- S4


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(signals, "market_open", lambda *a: True)
    good = _expired_trade(id="g1", status="closed", closed_at="2026-11-06 15:30", reason="expired", net_pnl=-100.0,
                          gross_pnl=-90.0, charges=10.0)
    bad = _expired_trade(id="bad1", expiry="bad-date")
    tr.STORE.write_text(json.dumps([good, bad]), encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_one_malformed_row_does_not_break_the_record(store):
    view = tr.overview(lambda *a: pytest.fail("no chain for a set-aside row"))
    assert [t["id"] for t in view["you"]["closed"]] == ["g1"]
    assert view.get("bad_rows") == ["bad1"]


@pytest.mark.unit
def test_refresh_keeps_a_malformed_row_in_the_file_untouched(store):
    before = json.loads(tr.STORE.read_text(encoding="utf-8"))
    tr.refresh_open(lambda *a: pytest.fail("no chain for a set-aside row"))
    after = json.loads(tr.STORE.read_text(encoding="utf-8"))
    assert [r for r in after if r["id"] == "bad1"] == [r for r in before if r["id"] == "bad1"]
    assert {r["id"] for r in after} == {"g1", "bad1"}


@pytest.mark.unit
def test_the_monitor_tick_survives_a_malformed_row(store, monkeypatch):
    monkeypatch.setattr(tr, "_monitor", {"running": False, "last_ok_at": None, "last_error": None, "fail_count": 0})
    monkeypatch.setattr(tr, "refresh_open", lambda *a, **k: None)
    assert tr._monitor_tick() is True

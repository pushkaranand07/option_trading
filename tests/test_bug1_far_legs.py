"""Bug 1: an open trade whose legs drift outside the display window of the chain (ATM +/- 15 strikes) could not be
priced, closed or settled, and waited without saying so. Held legs are now priced from the full chain (the same NSE
fetch), and a leg with no quote anywhere shows "exit pending: <leg> quote missing" (an alert, a log line), no crash."""

import json
import subprocess
from pathlib import Path

import pytest

from webapp import option_chain as oc, trade_record as tr

ROOT = Path(__file__).resolve().parents[1]


def _q(ltp, bid, ask):
    return {"ltp": ltp, "bid": bid, "ask": ask, "oi": 1, "iv": 14.0, "chg_oi": 0, "chg": 0, "volume": 0}


CONDOR_LEGS = [{"action": "SELL", "type": "PE", "strike": 23600.0, "price": 110.6}, {"action": "BUY", "type": "PE", "strike": 23450.0, "price": 68.0},
               {"action": "SELL", "type": "CE", "strike": 24000.0, "price": 91.9}, {"action": "BUY", "type": "CE", "strike": 24150.0, "price": 57.4}]
CONDOR = {"symbol": "NIFTY", "expiry": "27-Nov-2099", "spot": 23800, "strategy_text": "x", "charges_per_lot": 180.0,
          "plan": {"strategy": "iron_condor", "bias": "neutral", "underlying_target": 23750, "underlying_stop": 23580},
          "priced": {"lot": 65, "net_per_unit": 77.1, "debit": False, "max_loss_per_lot": 4738.5, "max_profit_per_lot": 5011.5, "legs": CONDOR_LEGS},
          "levels": {"legs": []}}
NEAR = {24000.0: {"ce": _q(592, 590, 592), "pe": _q(23, 22.75, 22.8)}, 24150.0: {"ce": _q(457, 455, 456), "pe": _q(36, 36.25, 36.35)}}
FAR = {23600.0: {"pe": _q(9.25, 9.25, 9.3)}, 23450.0: {"pe": _q(7.2, 7.25, 7.3)}}


def chain(rows, spot=24557.6):
    return {"spot": spot, "expiry": "27-Nov-2099", "timestamp": None,
            "rows": [{"strike": k, "ce": v.get("ce"), "pe": v.get("pe")} for k, v in sorted(rows.items())]}


# The ``condor`` fixture these tests use is in tests/fixtures_shared.py (shared with other modules).


@pytest.mark.unit
def test_legs_outside_the_display_window_are_priced_from_the_full_chain_and_settle(condor, monkeypatch):
    monkeypatch.setattr(oc, "full_chain", lambda *a, **k: chain(NEAR | FAR), raising=False)
    o = tr.refresh_open()                                                          # the default path the monitor uses
    c = next(t for t in o["ai"]["closed"] if t["id"] == condor["id"])
    assert c["reason"] == "range broken" and [x["exit"] for x in c["legs"]] == [9.3, 7.25, 592, 455]


@pytest.mark.unit
def test_close_by_hand_uses_the_full_chain(condor, monkeypatch):
    monkeypatch.setattr(oc, "full_chain", lambda *a, **k: chain(NEAR | FAR), raising=False)
    monkeypatch.setattr(tr, "_flags", lambda *a, **k: [])                         # no rule exit: the user closes it
    c = tr.close(condor["id"])
    assert c["status"] == "closed" and c["reason"] == "closed by you"


@pytest.mark.unit
def test_a_leg_missing_even_from_the_full_chain_is_exit_pending_not_a_crash(condor, monkeypatch, caplog):
    monkeypatch.setattr(oc, "full_chain", lambda *a, **k: chain(NEAR | {23600.0: FAR[23600.0]}), raising=False)  # 23450 PE nowhere
    o = tr.refresh_open()
    t = next(x for x in o["ai"]["open"] if x["id"] == condor["id"])
    assert t["live"]["pnl"] is None and t["live"]["pending"] == ["23450 PE"]
    assert [a["kind"] for a in t["alerts"]].count("exit_pending") == 1 and t["alerts"][-1]["legs"] == ["23450 PE"]
    assert any("exit pending" in r.getMessage() and "23450 PE" in r.getMessage() for r in caplog.records)
    tr.refresh_open()                                                            # a second look adds no second alert
    assert [a["kind"] for a in tr._load()[0]["alerts"]].count("exit_pending") == 1
    html = subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), "openRowHtml(ARGS[0])"], input=json.dumps([t]),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert html.returncode == 0, html.stderr
    assert "Exit pending" in html.stdout and "23450 PE quote missing" in html.stdout


@pytest.mark.unit
def test_the_display_chain_is_unchanged_and_one_nse_fetch_serves_both(monkeypatch):
    raw = {"records": {"underlyingValue": 24557.6, "timestamp": "05-Nov-2026 13:58:58", "data": [
        {"strikePrice": 23000 + 50 * i, "CE": {"lastPrice": 10, "buyPrice1": 9, "sellPrice1": 11}, "PE": {"lastPrice": 10, "buyPrice1": 9, "sellPrice1": 11}}
        for i in range(60)]}}
    calls = []

    class Client:
        def get_json(self, path, params=None, ttl=None):
            calls.append(path)
            return type("F", (), {"data": raw})()

    monkeypatch.setattr(oc, "expiries", lambda symbol, client=None: ["27-Nov-2099"])
    oc.md._cache._d.clear()
    shown = oc.chain("NIFTY", "27-Nov-2099", lot=65, client=Client())
    full = oc.full_chain("NIFTY", "27-Nov-2099", lot=65, client=Client())
    assert len(shown["rows"]) == 31 and len(full["rows"]) == 60 and shown["spot"] == full["spot"]
    assert calls.count(oc.CHAIN) == 1                                              # one NSE fetch for both

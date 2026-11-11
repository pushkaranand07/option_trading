"""The Scanner tab (webapp/scanner.py): every index and header stock screened by today's tape and an option one lot of fits
the budget; the top few built as the Plan tab prices them; one AI call orders them. Display only. Synthetic bars and
chains, a fake LLM; no network."""

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from tests.test_strategist import _q
from tests.test_ui_regressions import render, text
from tests.test_v4_tape_direction import bars
from webapp import scanner, server, signals, strategist as st, trade_record as tr

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")


def chain(spot=100.0, lot=1000, step=5.0, price=lambda k, kind: 4.0):
    rows = []
    for k in np.arange(spot - 5 * step, spot + 5 * step + 1, step):
        rows.append({"strike": float(k), "ce": _q(price(k, "ce"), price(k, "ce") - 0.05, price(k, "ce")),
                     "pe": _q(price(k, "pe"), price(k, "pe") - 0.05, price(k, "pe")), "pcr": 1.0})
    return {"spot": spot, "atm": float(spot), "lot": lot, "expiry": "23-Nov-2099", "timestamp": "11-Nov-2026 10:00:00", "rows": rows,
            "summary": {"pcr": 1.1, "resistance": spot + 20, "support": spot - 20, "atm_iv": 20.0}}


def daily(trend_up=True, n=80):
    idx = pd.date_range("2026-07-01", periods=n, freq="B", tz="Asia/Kolkata")
    idx = idx[idx.date < pd.Timestamp("2026-11-11").date()][-60:]
    rng = np.random.default_rng(1)
    close = 100 * np.cumprod(1 + rng.normal(0.004 if trend_up else -0.004, 0.01, len(idx)))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 0}, index=idx)


def candles_for(path, up_trend=True):
    def fn(symbol, tf):
        return (bars(path), "test") if tf == "5m" else (daily(up_trend), "test")
    return fn


UP = np.linspace(100, 102.5, 18)
FLAT = np.r_[np.linspace(100, 102, 9), np.linspace(102, 100.6, 9)]


@pytest.mark.unit
def test_the_option_is_the_nearest_strike_one_lot_of_fits_the_budget():
    rich = chain(price=lambda k, kind: 20.0 - abs(k - 100) * 3 if kind == "ce" else 20.0)
    opt, why = scanner.pick_option(rich, "up", 15000)                        # ATM 20 x 1000 = 20,000: too much
    assert why is None and opt["strike"] == 105.0 and opt["steps_out"] == 1 and opt["cost"] == 5000.0 and opt["type"] == "CE"
    assert scanner.pick_option(chain(), "down", 15000)[0]["strike"] == 100.0  # 4 x 1000 fits at the money
    none, why = scanner.pick_option(chain(price=lambda k, kind: 50.0), "up", 15000)
    assert none is None and "₹50,000" in why and "budget ₹15,000" in why
    dead = chain()
    for r in dead["rows"]:
        r["ce"] = _q(4, 0, 0)
    assert scanner.pick_option(dead, "up", 15000) == (None, "no live bid / ask near the money")


@pytest.mark.unit
def test_a_clear_tape_with_an_affordable_option_scores_and_a_mixed_one_does_not():
    up = scanner.screen("ITC", 15000, chain_fn=lambda s: chain(102.5), candles_fn=candles_for(UP))
    assert up["tape"] == "up" and up["score"] > 0 and up["option"]["type"] == "CE" and up["why"] is None
    assert up["move_pct"] == pytest.approx(2.5, abs=0.1) and up["move_z"] > 0 and up["trend"] == "up" and up["trend_vs_tape"] == "agrees"
    against = scanner.screen("ITC", 15000, chain_fn=lambda s: chain(102.5), candles_fn=candles_for(UP, up_trend=False))
    assert 0 < against["score"] < up["score"] and against["trend_vs_tape"] == "against"
    mixed = scanner.screen("ITC", 15000, chain_fn=lambda s: chain(100.6), candles_fn=candles_for(FLAT))
    assert mixed["score"] == 0 and mixed["why"] == "tape mixed: no clear direction today"

    def down(s):
        raise RuntimeError("NSE is down")
    assert scanner.screen("ITC", 15000, chain_fn=down, candles_fn=candles_for(UP))["why"] == "data unavailable: NSE is down"


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "_runs_dir", lambda: tmp_path)
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    paths = {"ITC": UP, "SBIN": UP * 1.0, "TCS": FLAT}
    trade = {"symbol": "X", "expiry": "23-Nov-2099", "plan": {"strategy": "long_call", "underlying_entry_low": 102, "underlying_entry_high": 103,
             "underlying_target": 106, "underlying_stop": 100.5}, "priced": {"lot": 1000, "outlay_per_lot": 4000},
             "levels": {"legs": [{"strike": 105.0, "type": "CE", "price": 4.0, "premium_at_target": 6.0, "premium_at_stop": 3.0,
                                  "pnl_target_per_lot": 2000, "pnl_stop_per_lot": -1000}]}}
    seen = {}

    def llm(finalists):
        seen["finalists"] = finalists
        return scanner.ScanAnswer(market_read="banks lead", left_out="",
                                  picks=[scanner.ScanPick(symbol=s, why=f"w {s}", confidence="medium") for s in ("SBIN", "NOPE", "SBIN", "ITC")])
    return {"kw": {"chain_fn": lambda s: chain(102.5), "candles_fn": lambda s, tf: candles_for(paths[s])(s, tf),
                   "build_fn": lambda row, budget: trade | {"symbol": row["symbol"]}, "llm": llm}, "seen": seen}


@pytest.mark.unit
def test_the_scan_keeps_the_ais_order_drops_unknown_names_and_records_nothing(fake):
    res = scanner.scan(15000, symbols=["ITC", "SBIN", "TCS"], **fake["kw"])
    assert [p["symbol"] for p in res["picks"]] == ["SBIN", "ITC"] and [p["rank"] for p in res["picks"]] == [1, 2]
    assert res["picks"][0]["why"] == "w SBIN" and res["market_read"] == "banks lead"
    assert {f["symbol"] for f in fake["seen"]["finalists"]} == {"ITC", "SBIN"}                    # TCS's mixed tape never reached the AI
    assert fake["seen"]["finalists"][0]["trade"]["buy"] == "105 CE" and fake["seen"]["finalists"][0]["trade"]["cost_one_lot"] == 4000
    assert [r["symbol"] for r in res["scanned"]][-1] == "TCS" and len(res["scanned"]) == 3
    assert not tr.STORE.exists()                                                                  # display only
    json.dumps(res, default=str)


@pytest.mark.unit
def test_a_failed_ai_step_keeps_the_screens_order_and_says_so(fake):
    def broken(finalists):
        raise RuntimeError("Azure timeout")
    res = scanner.scan(15000, symbols=["ITC", "TCS"], **(fake["kw"] | {"llm": broken}))
    assert [p["symbol"] for p in res["picks"]] == ["ITC"] and res["picks"][0]["why"] is None and "Azure timeout" in res["ai_error"]


@pytest.mark.unit
def test_a_muhurat_day_gives_no_picks(fake, monkeypatch):
    cal = type("C", (), {"muhurat_days": {signals.now_ist().date()}})()
    monkeypatch.setattr(signals, "nse_calendar", lambda: cal)
    monkeypatch.setattr(tr, "entry_allowed", lambda: None)
    res = scanner.scan(15000, symbols=["ITC"], **fake["kw"])
    assert res["muhurat"] and res["picks"] == [] and "Muhurat" in res["market_read"] and "finalists" not in fake["seen"]


@pytest.mark.unit
def test_the_last_scan_is_saved_and_served(fake):
    res = scanner.scan(15000, symbols=["ITC"], **fake["kw"])
    assert server.scan_latest() == {}
    scanner.save(res)
    assert server.scan_latest()["picks"][0]["symbol"] == "ITC"


@pytest.mark.unit
def test_the_universe_is_the_nse_indices_and_the_header_stocks(monkeypatch):
    from webapp import market_data as md
    monkeypatch.setattr(md, "fo_stocks", lambda: [{"symbol": "HINDPETRO", "name": "h"}, {"symbol": "NIFTY", "name": "n"}])
    assert scanner.universe() == ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "HINDPETRO"]   # no SENSEX (BSE), no repeat


@pytest.mark.unit
@needs_node
def test_the_page_shows_each_pick_and_everything_scanned(fake):
    res = json.loads(json.dumps(scanner.scan(15000, symbols=["ITC", "SBIN", "TCS"], **fake["kw"]), default=str))
    page = text(render("S.foStocks = []; scannerHtml(ARGS[0])", {"result": res}))
    assert "#1 SBIN trend up · buy a CALL" in page and "BUY SBIN 23 NOV 105 CALL" in page and "Buy at ₹4.00 or less" in page
    assert "Take profit: sell at ₹6.00" in page and "Stop loss: sell at ₹3.00" in page and "w SBIN" in page
    assert "Everything scanned (3)" in page and "tape mixed: no clear direction today" in page
    assert "Nothing is recorded" in page and json.loads(render("JSON.stringify(TABS.includes('scanner'))")) is True
    idle = text(render("S.foStocks = []; scannerHtml({})"))
    assert "Scan now" in idle and "Picks" not in idle

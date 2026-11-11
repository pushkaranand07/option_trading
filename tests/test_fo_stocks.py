"""F&O stocks beside the indices: every NSE stock with options gets its lot from Dhan's scrip master, per expiry
(a lot under revision differs by month), so its NSE option chain loads; the header offers 20 of them as shortcuts.
A small scrip-master file and mocked lots; no network."""

import json
import shutil

import pytest

from tests.test_ui_regressions import render, text
from webapp import market_data as md, option_chain as oc, server

HEAD = "SEM_EXM_EXCH_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_EXPIRY_DATE"
ROWS = """NSE,OPTSTK,HDFCBANK-Nov2026-420-CE,650.0,2026-11-23 14:30:00
NSE,OPTSTK,HDFCBANK-Nov2026-420-PE,650.0,2026-11-23 14:30:00
NSE,OPTSTK,HDFCBANK-Jan2027-420-CE,750.0,2027-01-25 14:30:00
NSE,OPTSTK,BAJAJ-AUTO-Nov2026-6800-CE,75.0,2026-11-23 14:30:00
NSE,OPTSTK,HINDPETRO-Nov2026-210-CE,2025.0,2026-11-23 14:30:00
NSE,OPTSTK,HINDPETRO-Nov2026-210-PE,bad,2026-11-23 14:30:00
BSE,OPTSTK,HINDPETRO-Nov2026-210-CE,999.0,2026-11-23 14:30:00
NSE,OPTIDX,NIFTY-Nov2026-25000-CE,65.0,2026-11-24 14:30:00
NSE,FUTSTK,HINDPETRO-Nov2026-FUT,2025.0,2026-11-23 14:30:00
"""
LOTS = {"HDFCBANK": {"2026-11-23": 650, "2027-01-25": 750}, "BAJAJ-AUTO": {"2026-11-23": 75}, "HINDPETRO": {"2026-11-23": 2025}}


@pytest.fixture
def lots(monkeypatch):
    monkeypatch.setattr(md, "stock_lots", lambda: LOTS)
    import pandas as pd

    from tradingagents.analytics import datastore as ds
    monkeypatch.setattr(ds, "load", lambda *a, **k: pd.DataFrame())          # the NSE store knows none of them
    return LOTS


@pytest.mark.unit
def test_the_scrip_master_gives_each_stocks_lot_per_expiry(tmp_path):
    f = tmp_path / "master.csv"
    f.write_text(HEAD + "\n" + ROWS, encoding="utf-8")
    assert md.load_stock_lots(f) == LOTS                                    # NSE stock options only; a hyphen in the symbol


@pytest.mark.unit
def test_a_stocks_lot_is_the_one_of_the_expiry_asked_for(lots):
    assert oc.lot_size("HINDPETRO", "23-Nov-2026") == 2025                  # before: "not in the NSE F&O store"
    assert oc.lot_size("HDFCBANK", "23-Nov-2026") == 650 and oc.lot_size("HDFCBANK", "25-Jan-2027") == 750
    assert oc.lot_size("HDFCBANK") == 650 and oc.lot_size("HDFCBANK", "29-Dec-2026") == 650   # unknown month: the nearest
    assert oc.lot_size("BAJAJ-AUTO", "not a date") == 75
    with pytest.raises(oc.ChainError, match="not known"):
        oc.lot_size("NOSUCHSTOCK", "23-Nov-2026")


@pytest.mark.unit
def test_the_nse_store_still_answers_when_the_scrip_master_has_no_such_expiry(monkeypatch):
    import pandas as pd

    from tradingagents.analytics import datastore as ds
    monkeypatch.setattr(md, "stock_lots", lambda: {})
    monkeypatch.setattr(ds, "load", lambda *a, **k: pd.DataFrame({"trade_date": ["2026-11-09"], "lot_size": [500]}))
    assert oc.lot_size("RELIANCE", "23-Nov-2026") == 500


@pytest.mark.unit
def test_the_chain_of_a_stock_carries_the_lot_of_its_expiry(lots, monkeypatch):
    raw = {"records": {"underlyingValue": 1000.0, "timestamp": "11-Nov-2026 11:00:12", "data": [
        {"strikePrice": 900 + 20 * i, "CE": {"lastPrice": 10, "openInterest": 2}, "PE": {"lastPrice": 10, "openInterest": 3}} for i in range(10)]}}
    asked = []

    class Client:
        def get_json(self, path, params=None, ttl=None):
            asked.append(params)
            data = {"expiryDates": ["23-Nov-2026", "25-Jan-2027"]} if path == oc.CONTRACT_INFO else raw
            return type("F", (), {"data": data})()

    monkeypatch.setattr(md, "_cache", md._TTLCache())
    near, far = oc.chain("hdfcbank", client=Client()), oc.chain("HDFCBANK", "25-Jan-2027", client=Client())
    assert (near["lot"], near["expiry"], far["lot"]) == (650, "23-Nov-2026", 750)
    assert near["rows"][0]["ce"]["oi"] == 2 * 650 and far["rows"][0]["pe"]["oi"] == 3 * 750   # OI in units of that lot
    assert {"type": "Equity", "symbol": "HDFCBANK", "expiry": "23-Nov-2026"} in asked


@pytest.mark.unit
def test_the_header_offers_twenty_stocks_and_drops_one_without_options(monkeypatch):
    assert len(md.FO_STOCKS) == len(set(md.FO_STOCKS)) == 20 and {"HINDPETRO", "JIOFIN"} <= set(md.FO_STOCKS)
    assert not set(md.FO_STOCKS) & set(md.INDICES)
    monkeypatch.setattr(md, "equities", lambda: {"HINDPETRO": (1, "Hindustan Petroleum")})
    monkeypatch.setattr(md, "stock_lots", lambda: {})                       # the file could not be read: offer them all
    assert len(md.fo_stocks()) == 20 and md.fo_stocks()[0] == {"symbol": "HINDPETRO", "name": "Hindustan Petroleum"}
    monkeypatch.setattr(md, "stock_lots", lambda: {s: {"2026-11-23": 1} for s in md.FO_STOCKS if s != "JIOFIN"})
    assert "JIOFIN" not in [s["symbol"] for s in md.fo_stocks()] and len(md.fo_stocks()) == 19
    assert server.status()["fo_stocks"] == md.fo_stocks()


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")
def test_the_page_shows_the_stock_shortcuts_and_marks_the_one_on_screen():
    stocks = [{"symbol": "HINDPETRO", "name": "Hindustan Petroleum"}, {"symbol": "M&M", "name": "M&M"}]
    html = render("S.foStocks = ARGS[0]; S.sym = 'HINDPETRO'; stockChipsHtml()", stocks)
    assert text(html) == "F&O stocks HINDPETRO M&M"
    assert 'class="chip active" data-sym="HINDPETRO"' in html and 'data-sym="M&amp;M"' in html
    assert json.loads(render("S.foStocks = []; JSON.stringify(stockChipsHtml().includes('chip'))")) is False

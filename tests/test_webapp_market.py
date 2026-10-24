"""Web app: live index lot sizes from Dhan's scrip master; market status from the NSE calendar."""

from datetime import date, datetime

import pytest

from tradingagents.dataflows.vendors.nse.calendar import IST, NSECalendar
from webapp import market_data as md, signals as sg

HEADER = ("SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,"
          "SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL\n")


@pytest.mark.unit
def test_index_lots_come_from_the_scrip_master_most_common_lot_wins(tmp_path):
    rows = ["NSE,D,1,OPTIDX,0,NIFTY-Nov2026-22600-CE,65.0,x", "NSE,D,2,OPTIDX,0,NIFTY-Nov2026-22600-PE,65.0,x",
            "NSE,D,3,OPTIDX,0,NIFTY-Dec2026-22600-CE,75.0,x",          # an old-lot contract during a revision
            "NSE,D,4,OPTIDX,0,BANKNIFTY-Nov2026-50000-CE,30.0,x",
            "NSE,D,5,OPTSTK,0,RELIANCE-Nov2026-1400-CE,500.0,x",        # stock options are ignored
            "NSE,E,6,EQUITY,0,RELIANCE,1.0,x"]
    path = tmp_path / "scrip.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    assert md.load_index_lots(path) == {"NIFTY": 65, "BANKNIFTY": 30}


@pytest.mark.unit
def test_instrument_uses_the_live_lot_and_falls_back_to_the_table(monkeypatch):
    monkeypatch.setattr(md, "index_lots", lambda: {"NIFTY": 65})
    assert md.instrument("nifty")["lot"] == 65
    monkeypatch.setattr(md, "index_lots", lambda: {})                   # scrip master unreachable
    assert md.instrument("BANKNIFTY")["lot"] == md.INDICES["BANKNIFTY"][4] == 30


CAL = NSECalendar({date(2026, 11, 10): "Diwali-Balipratipada"}, special_sessions={date(2026, 2, 1)},
                  muhurat_days={date(2026, 11, 8)})


def ist(*a):
    return IST.localize(datetime(*a))


@pytest.mark.unit
@pytest.mark.parametrize("moment, is_open", [
    (ist(2026, 11, 9, 11, 0), True),          # an ordinary Monday
    (ist(2026, 11, 9, 16, 0), False),         # after the close
    (ist(2026, 11, 10, 11, 0), False),        # a weekday holiday (was shown open before)
    (ist(2026, 11, 8, 11, 0), False),         # Muhurat Sunday: closed in regular hours
    (ist(2026, 2, 1, 11, 0), True),           # Budget Sunday session
    (ist(2026, 1, 31, 11, 0), False),         # an ordinary Saturday
])
def test_market_open_follows_the_nse_calendar(moment, is_open):
    assert sg.market_open(moment, calendar=CAL) is is_open

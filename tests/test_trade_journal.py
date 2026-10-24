"""Trade journal: reading a broker tradebook, FIFO round trips, holding periods, styles and charges."""

import pandas as pd
import pytest

from tradingagents.analytics import journal as jr

TRADEBOOK = """Trade Book Report
Client: XXXX

Trade Date,Trade Time,Symbol,Buy/Sell,Quantity,Trade Price,Reason
20-10-2026,15:10:00,MARUTI,SELL,10,11000,
24-09-2026,09:30:00,MARUTI,BUY,10,10000,breakout
08-10-2026,09:20:00,RELIANCE 27 OCT 1200 PE,BUY,500,10,
06-10-2026,10:00:00,RELIANCE 27 OCT 1200 PE,SELL,500,20,PCR
06-10-2026,11:00:00,NIFTY 06 OCT 22600 CE,SELL,75,120,
06-10-2026,10:05:00,NIFTY 06 OCT 22600 CE,BUY,75,100,VWAP
"""


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "tradebook.csv"
    path.write_text(TRADEBOOK, encoding="utf-8")
    return jr.read_tradebook(path)


@pytest.mark.unit
def test_header_found_after_preamble_and_newest_first_file_put_in_time_order(book):
    assert len(book) == 6
    assert book["datetime"].is_monotonic_increasing
    assert book.iloc[0]["symbol"] == "MARUTI" and book.iloc[0]["side"] == 1
    assert book.iloc[0]["datetime"] == pd.Timestamp("2026-09-24 09:30")      # day first, time combined


@pytest.mark.unit
def test_round_trips_holding_periods_and_styles(book):
    trips, still_open = jr.round_trips(book)
    assert still_open.empty
    by_symbol = {t.symbol: t for t in trips}
    nifty, rel, maruti = by_symbol["NIFTY 06 OCT 22600 CE"], by_symbol["RELIANCE 27 OCT 1200 PE"], by_symbol["MARUTI"]
    assert (nifty.horizon, nifty.style, nifty.gross, nifty.index) == ("intraday", "option buying", 1500.0, True)
    assert (rel.horizon, rel.style, rel.gross, rel.index) == ("up to 1 week", "option selling", 5000.0, False)
    assert (maruti.horizon, maruti.style, maruti.gross) == ("1-4 weeks", "shares long", 10000.0)
    assert (nifty.reason, rel.reason, maruti.reason) == ("VWAP", "PCR", "breakout")
    assert all(t.charges > 0 for t in trips)


@pytest.mark.unit
def test_fifo_matching_with_partial_fills_leaves_the_rest_open():
    t = pd.DataFrame({"datetime": pd.to_datetime(["2026-10-01 10:00", "2026-10-01 10:30", "2026-10-01 14:00"]),
                      "symbol": ["TCS"] * 3, "side": [1, 1, -1], "qty": [100, 100, 150], "price": [10.0, 12.0, 15.0]})
    trips, still_open = jr.round_trips(t)
    assert [(x.qty, x.entry, x.exit) for x in trips] == [(100, 10.0, 15.0), (50, 12.0, 15.0)]
    assert still_open.to_dict("records")[0] | {"opened": None} == {"symbol": "TCS", "direction": "long", "qty": 50,
                                                                   "price": 12.0, "opened": None}


@pytest.mark.unit
def test_charges_from_the_file_are_used_when_present():
    t = pd.DataFrame({"datetime": pd.to_datetime(["2026-10-01 10:00", "2026-10-01 11:00"]), "symbol": ["SBIN"] * 2,
                      "side": [1, -1], "qty": [10, 10], "price": [800.0, 810.0], "charges": [12.0, 18.0]})
    (trip,), _ = jr.round_trips(t)
    assert trip.charges == pytest.approx(30.0) and trip.net == pytest.approx(70.0)


@pytest.mark.unit
def test_same_day_shares_are_charged_as_intraday_not_delivery():
    def trip(close):
        t = pd.DataFrame({"datetime": pd.to_datetime(["2026-10-01 10:00", close]), "symbol": ["SBIN"] * 2,
                          "side": [1, -1], "qty": [100, 100], "price": [800.0, 800.0]})
        return jr.round_trips(t)[0][0]
    assert trip("2026-10-01 15:00").charges < trip("2026-10-05 15:00").charges


@pytest.mark.unit
@pytest.mark.parametrize("symbol, kind, under, index", [
    ("NIFTY 06 OCT 22600 CE", "option", "NIFTY", True), ("BANKNIFTY28OCT52000PE", "option", "BANKNIFTY", True),
    ("RELIANCE 27 OCT 1200 PE", "option", "RELIANCE", False), ("RELIANCEOCTFUT", "future", "RELIANCE", False),
    ("NIFTY 27 OCT FUT", "future", "NIFTY", True), ("MARUTI", "equity", "MARUTI", False),
    ("RELIANCE-EQ", "equity", "RELIANCE", False), ("M&M", "equity", "M&M", False),
])
def test_classify(symbol, kind, under, index):
    inst = jr.classify(symbol)
    assert (inst.kind, inst.underlying, inst.index) == (kind, under, index)


@pytest.mark.unit
def test_summary_numbers():
    trips = [jr.RoundTrip("A", "equity", "A", False, 1, pd.Timestamp("2026-10-01 10:00"),
                          pd.Timestamp("2026-10-01 11:00"), 1, 100, 100 + g, 10.0) for g in (110, 60, -40)]
    s = jr.summarize(trips).iloc[0]
    assert s["trades"] == 3 and s["win_rate"] == pytest.approx(2 / 3)
    assert s["net_per_trade"] == pytest.approx((100 + 50 - 50) / 3)
    assert s["charges_share_of_gross_profit"] == pytest.approx(30 / 170)
    assert s["profit_factor"] == pytest.approx(150 / 50)


@pytest.mark.unit
def test_missing_columns_are_reported_by_name(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Symbol,Quantity,Price\nTCS,1,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="side"):
        jr.read_tradebook(p)

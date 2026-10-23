"""Phase 1 of the quant plan: raw NSE file parsers and the point-in-time store."""

from datetime import date

import pandas as pd
import pytest

from tradingagents.analytics import datastore as ds

PARTICIPANT = (
    b'""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 16, 2026"",,,,,,,,,,,,,,\n'
    b"Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,"
    b"Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,"
    b"Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,"
    b"Total Long Contracts      ,Total Short Contracts\n"
    b"Client,276618,56704,3453649,294863,3823581,4191151,3767056,4682637,2396725,1064078,1365136,1205337,15205802,11371733\n"
    b"FII,39966,312965,3616748,2840084,707527,1318296,981202,797059,310336,414657,467996,290447,6407530,5689753\n"
)

MTO = (
    b"Security Wise Delivery Position - Compulsory Rolling Settlement\n"
    b"10,MTO,16102026,2213873385,0003417\n"
    b"Trade Date <16-OCT-2026>,Settlement Type <N>\n"
    b"Record Type,Sr No,Name of Security,Quantity Traded,Deliverable Quantity(gross across client level),"
    b"% of Deliverable Quantity to Traded Quantity\n"
    b"20,1,1003IIFL29,NC,115,115,100.00\n"
    b"20,1865,M&M,EQ,2541998,1443221,56.78\n"
    b"20,2533,RELIANCE,EQ,17225283,10258039,59.55\n"
)


def fo_rows():
    base = {"trade_date": date(2026, 10, 16), "underlying_price": 100.0, "settle": 0.0, "open": 0, "high": 0,
            "low": 0, "turnover": 1.0, "lot_size": 1, "format": "udiff", "oi_change": 0}
    rows = [
        {"instrument": "FUTSTK", "symbol": "ABC", "expiry": date(2026, 11, 24), "strike": None, "option_type": None,
         "close": 102.0, "open_interest": 50, "contracts": 5},
        {"instrument": "FUTSTK", "symbol": "ABC", "expiry": date(2026, 10, 27), "strike": None, "option_type": None,
         "close": 101.0, "open_interest": 100, "contracts": 10},
        {"instrument": "OPTSTK", "symbol": "ABC", "expiry": date(2026, 10, 27), "strike": 100.0, "option_type": "CE",
         "close": 2.0, "open_interest": 200, "contracts": 40},
        {"instrument": "OPTSTK", "symbol": "ABC", "expiry": date(2026, 10, 27), "strike": 100.0, "option_type": "PE",
         "close": 1.5, "open_interest": 300, "contracts": 20},
        {"instrument": "OPTSTK", "symbol": "ABC", "expiry": date(2026, 10, 27), "strike": 200.0, "option_type": "CE",
         "close": 0.05, "open_interest": 10, "contracts": 1},       # 100% out of the money: dropped from chain
        {"instrument": "OPTSTK", "symbol": "ABC", "expiry": date(2027, 3, 30), "strike": 100.0, "option_type": "CE",
         "close": 9.0, "open_interest": 10, "contracts": 1},        # too far out: dropped from chain
        {"instrument": "OPTSTK", "symbol": "XYZ", "expiry": date(2026, 10, 27), "strike": 100.0, "option_type": "CE",
         "close": 1.0, "open_interest": 999, "contracts": 999},     # not in the universe
    ]
    return pd.DataFrame([{**base, **r} for r in rows])


@pytest.mark.unit
def test_participant_file_parses_every_category_and_the_date():
    df = ds.parse_participant(PARTICIPANT, date(2026, 10, 16))
    assert list(df["category"]) == ["Client", "FII"]
    assert (df["trade_date"] == date(2026, 10, 16)).all()
    fii = df.set_index("category").loc["FII"]
    assert fii["fut_idx_short"] == 312965 and fii["total_short"] == 5689753


@pytest.mark.unit
def test_participant_files_without_a_title_or_with_a_full_month_name_parse():
    untitled = PARTICIPANT.split(b"\n", 1)[1]
    assert ds.parse_participant(untitled, date(2018, 6, 13))["trade_date"].iloc[0] == date(2018, 6, 13)
    full_month = PARTICIPANT.replace(b"Oct 16, 2026", b"June 01, 2018")
    assert len(ds.parse_participant(full_month, date(2018, 6, 1))) == 2
    with pytest.raises(ValueError):
        ds.parse_participant(PARTICIPANT, date(2026, 10, 15))   # title disagrees with the file name


@pytest.mark.unit
def test_mto_rows_keep_their_series_column_the_header_omits():
    df = ds.parse_mto(MTO)
    assert df["trade_date"].iloc[0] == date(2026, 10, 16)
    mm = df.set_index("symbol").loc["M&M"]
    assert (mm["series"], mm["traded_qty"], mm["deliverable_qty"], mm["deliv_pct"]) == ("EQ", 2541998, 1443221, 56.78)


@pytest.mark.unit
def test_fo_summary_uses_the_nearest_future_and_totals_open_interest():
    summary = ds.fo_summary(fo_rows(), symbols=["ABC"]).set_index("symbol").loc["ABC"]
    assert summary["near_expiry"] == date(2026, 10, 27)
    assert summary["fut_close"] == 101.0
    assert summary["fut_oi"] == 150
    assert summary["pcr_oi"] == pytest.approx(300 / 220)
    assert summary["pcr_volume"] == pytest.approx(20 / 42)


@pytest.mark.unit
def test_option_chain_keeps_only_near_dated_near_the_money_universe_contracts():
    fo = fo_rows()
    chain = ds.option_chain(fo, ds.fo_summary(fo, symbols=["ABC"]), symbols=["ABC"])
    assert len(chain) == 2
    assert set(chain["option_type"]) == {"CE", "PE"}
    assert (chain["strike"] == 100.0).all()


@pytest.mark.unit
def test_rows_become_usable_only_from_the_next_session():
    days = [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 21)]  # 20th: holiday
    sessions = ds.next_sessions(days)
    assert sessions[date(2026, 10, 16)] == date(2026, 10, 19)
    assert sessions[date(2026, 10, 19)] == date(2026, 10, 21)
    assert sessions[date(2026, 10, 21)] == date(2026, 10, 22)
    df = ds.add_known_from(pd.DataFrame({"trade_date": days, "x": range(4)}), sessions)
    assert list(ds.as_of(df, date(2026, 10, 19))["x"]) == [0, 1]
    # Data for the 19th is not visible during the 19th itself.
    assert date(2026, 10, 19) not in set(ds.as_of(df, date(2026, 10, 19))["trade_date"])


@pytest.mark.unit
def test_load_filters_by_date_and_symbol(tmp_path):
    df = pd.DataFrame({"trade_date": [date(2025, 12, 31), date(2026, 1, 2), date(2026, 1, 5)],
                       "symbol": ["A", "A", "B"], "known_from": [date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 6)]})
    ds._write(df.iloc[:1], tmp_path, "delivery", 2025)
    ds._write(df.iloc[1:], tmp_path, "delivery", 2026)
    assert len(ds.load("delivery", root=tmp_path)) == 3
    assert list(ds.load("delivery", start=date(2026, 1, 1), root=tmp_path)["symbol"]) == ["A", "B"]
    assert list(ds.load("delivery", symbols=["B"], root=tmp_path)["trade_date"]) == [date(2026, 1, 5)]
    with pytest.raises(ValueError):
        ds.load("nope", root=tmp_path)


def yahoo_frame(dates, closes, splits=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize("Asia/Kolkata")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Adj Close": c, "Volume": 1000.0,
                         "Dividends": 0.0, "Stock Splits": splits or [0.0] * len(c)}, index=idx)


@pytest.mark.unit
def test_prices_are_normalised_stamped_and_quality_checked(tmp_path):
    from tradingagents.analytics import prices as px

    frames = {"^NSEI": yahoo_frame(["2026-10-15", "2026-10-19"], [100, 101]),
              "TATASTEEL.NS": yahoo_frame(["2026-10-15", "2026-10-16", "2026-10-19"], [100, 10, 13], [0, 10, 0])}
    got = px.fetch_prices(["NIFTY", "TATASTEEL"], date(2026, 10, 15), date(2026, 10, 19),
                          history=lambda t, s, e: frames[t])
    assert set(got["symbol"]) == {"NIFTY", "TATASTEEL"}
    assert isinstance(got["trade_date"].iloc[0], date)

    nse_days = [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19)]
    issues = px.quality_report(got, nse_days)
    assert ("NIFTY", date(2026, 10, 16), "missing_session") in set(zip(issues.symbol, issues.trade_date, issues.issue))
    jumps = issues[issues.issue == "jump_no_split"]
    # The -90% day has a split recorded; the +30% day after it does not.
    assert list(zip(jumps.symbol, jumps.trade_date)) == [("TATASTEEL", date(2026, 10, 19))]

    px.save_prices(got, nse_days, root=tmp_path)
    loaded = px.load_prices(["NIFTY"], root=tmp_path)
    assert list(loaded["known_from"]) == [date(2026, 10, 16), date(2026, 10, 20)]

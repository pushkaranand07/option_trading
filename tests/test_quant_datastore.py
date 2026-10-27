"""Phase 1 of the quant plan: raw NSE file parsers and the point-in-time store."""

from datetime import date
from pathlib import Path

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
    assert ("NIFTY", date(2026, 10, 16), "missing_session") in set(zip(issues.symbol, issues.trade_date, issues.issue, strict=True))
    jumps = issues[issues.issue == "jump_no_split"]
    # The -90% day has a split recorded; the +30% day after it does not.
    assert list(zip(jumps.symbol, jumps.trade_date, strict=True)) == [("TATASTEEL", date(2026, 10, 19))]

    px.save_prices(got, nse_days, root=tmp_path)
    loaded = px.load_prices(["NIFTY"], root=tmp_path)
    assert list(loaded["known_from"]) == [date(2026, 10, 16), date(2026, 10, 20)]


def _bars(days):
    return pd.DataFrame({"trade_date": days, "symbol": "RELIANCE", "open": 1.0, "high": 1.0, "low": 1.0,
                         "close": 1.0, "adj_close": 1.0, "volume": 1.0, "dividend": 0.0, "split": 0.0,
                         "source": "yahoo"})


def _assert_on_sessions(df, sessions):
    """The regression rule: no bar dated on a non-session, no known_from on a non-session."""
    assert set(df["trade_date"]) <= sessions
    last = max(sessions)
    assert all(k in sessions or k > last for k in df["known_from"])


@pytest.mark.unit
def test_a_yahoo_bar_on_an_nse_holiday_is_dropped_and_known_from_skips_it(tmp_path):
    from tradingagents.analytics import prices as px

    # 2026-01-15: exchange holiday (Maharashtra municipal election); Yahoo still had a bar
    nse_days = [date(2026, 1, 14), date(2026, 1, 16), date(2026, 1, 19)]
    bars = _bars([date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 16), date(2026, 1, 19)])
    kept, dropped = px.drop_non_sessions(bars, px.price_sessions(nse_days, bars["trade_date"]))
    assert list(dropped["trade_date"]) == [date(2026, 1, 15)]
    px.save_prices(bars, nse_days, root=tmp_path)
    loaded = px.load_prices(root=tmp_path)
    assert list(loaded["trade_date"]) == [date(2026, 1, 14), date(2026, 1, 16), date(2026, 1, 19)]
    assert list(loaded["known_from"]) == [date(2026, 1, 16), date(2026, 1, 19), date(2026, 1, 20)]
    _assert_on_sessions(loaded, set(nse_days))


@pytest.mark.unit
def test_an_archive_hole_stays_a_session(tmp_path):
    from tradingagents.analytics import prices as px

    # 2021-03-30 traded, but NSE's F&O file for it is gone: Yahoo's bar is real
    nse_days = [date(2021, 3, 26), date(2021, 3, 31)]
    px.save_prices(_bars([date(2021, 3, 26), date(2021, 3, 30), date(2021, 3, 31)]), nse_days, root=tmp_path)
    loaded = px.load_prices(root=tmp_path)
    assert list(loaded["trade_date"]) == [date(2021, 3, 26), date(2021, 3, 30), date(2021, 3, 31)]
    assert list(loaded["known_from"])[:2] == [date(2021, 3, 30), date(2021, 3, 31)]


@pytest.mark.unit
def test_todays_bar_before_nse_files_is_kept_only_on_a_calendar_session(tmp_path):
    from tradingagents.analytics import prices as px
    from tradingagents.dataflows.vendors.nse.calendar import NSECalendar

    cal = NSECalendar({date(2026, 10, 28): "a holiday"})
    nse_days = [date(2026, 10, 26)]
    bars = _bars([date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)])
    px.save_prices(bars, nse_days, root=tmp_path, calendar=cal)
    loaded = px.load_prices(root=tmp_path)
    assert list(loaded["trade_date"]) == [date(2026, 10, 26), date(2026, 10, 27)]
    assert list(loaded["known_from"])[0] == date(2026, 10, 27)


INDEX_CLOSE = (
    b"Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
    b"Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
    b"Nifty 50,01-01-2018,10531.7,10537.85,10423.1,10435.55,-95.15,-.9,134532090,7546.56,26.68,3.51,1.09\n"
    b"Nifty Next 50,01-01-2018,1,2,0.5,1.5,0,0,1,1,1,1,1\n"
    b"Nifty Bank,01-01-2018,25565.75,25588,25271.55,25318.1,-221.35,-.87,57576913,2037.55,29.31,2.94,.18\n"
    b"India VIX,01-01-2018,12.67,13.6125,12.545,13.35,.68,5.39,-,-,-,-,-\n"
)


@pytest.mark.unit
def test_index_close_keeps_nifty_banknifty_and_vix_with_official_values():
    df = ds.parse_index_close(INDEX_CLOSE, date(2018, 1, 1)).set_index("symbol")
    assert set(df.index) == {"NIFTY", "BANKNIFTY", "INDIAVIX"}
    assert df.loc["NIFTY", "close"] == 10435.55 and df.loc["BANKNIFTY", "open"] == 25565.75
    assert df.loc["INDIAVIX", "close"] == 13.35 and pd.isna(df.loc["INDIAVIX", "volume"])


@pytest.mark.unit
def test_nse_index_bars_replace_yahoo_and_fill_its_gaps():
    from tradingagents.analytics import prices as px

    yahoo = px.normalize_history(yahoo_frame(["2018-01-02", "2018-01-03"], [10442.2, 10443.2]), "NIFTY")
    nse = pd.DataFrame({"trade_date": [date(2018, 1, 1), date(2018, 1, 2)], "symbol": "NIFTY",
                        "open": [10531.7, 10477.55], "high": [10537.85, 10495.2], "low": [10423.1, 10404.65],
                        "close": [10435.55, 10442.2], "volume": [1.0, 1.0]})
    merged = px.merge_nse_indices(yahoo, nse).set_index("trade_date")
    assert list(merged.index) == [date(2018, 1, 1), date(2018, 1, 2), date(2018, 1, 3)]
    assert merged.loc[date(2018, 1, 1), "close"] == 10435.55          # Yahoo had no 1-Jan bar
    assert list(merged["source"]) == ["nse", "nse", "yahoo"]


@pytest.mark.unit
def test_a_missing_stock_session_is_filled_on_yahoos_adjusted_basis():
    from tradingagents.analytics import prices as px

    # Yahoo is split-adjusted 1:10 relative to NSE's traded prices, and lacks 2026-10-22.
    frame = yahoo_frame(["2026-10-21", "2026-10-23"], [250.0, 260.0])
    frame["Adj Close"] = frame["Close"] * 0.98                          # a past dividend
    yahoo = px.normalize_history(frame, "TCS")
    nse_days = {date(2026, 10, 21): 2500.0, date(2026, 10, 22): 2550.0, date(2026, 10, 23): 2600.0}

    def fetch(d):
        c = nse_days[d]
        return pd.DataFrame({"symbol": ["TCS"], "open": [c], "high": [c], "low": [c], "close": [c], "volume": [9.0]})

    filled = px.fill_stock_gaps(yahoo, list(nse_days), fetch).set_index("trade_date")
    bar = filled.loc[date(2026, 10, 22)]
    assert bar["close"] == pytest.approx(255.0)                         # NSE +2% applied to Yahoo's 250
    assert bar["adj_close"] == pytest.approx(255.0 * 0.98)
    assert bar["source"] == "nse_fill"
    assert px.quality_report(filled.reset_index(), list(nse_days)).empty


@pytest.mark.unit
def test_build_year_rebuilds_only_the_named_datasets(tmp_path):
    from tradingagents.analytics.backfill import ManifestRow, _append_manifest

    raw, root = tmp_path / "raw", tmp_path / "store"
    day = date(2018, 1, 1)
    (raw / "indices" / "2018").mkdir(parents=True)
    (raw / "indices" / "2018" / "ind_close_all_01012018.csv").write_bytes(INDEX_CLOSE)
    for kind, url in (("fo", "/x/fo01JAN2018bhav.csv.zip"), ("indices", "/x/ind_close_all_01012018.csv")):
        _append_manifest(raw, ManifestRow(day, kind, "ok", url, 1, ""))
    # The F&O file is not even on disk: asking for index_close only must not touch it.
    counts = ds.build_year(2018, raw=raw, root=root, datasets=("index_close",))
    assert counts == {"index_close": 3}
    assert not (root / "fo_summary").exists()
    with pytest.raises(ValueError):
        ds.build_year(2018, raw=raw, root=root, datasets=("nope",))


@pytest.mark.unit
def test_parquet_writes_are_whole_or_not_at_all(tmp_path, monkeypatch):
    path = tmp_path / "x" / "a.parquet"
    ds.write_parquet(pd.DataFrame({"v": [1, 2]}), path)
    assert list(pd.read_parquet(path)["v"]) == [1, 2]

    def broken(self, target, **kwargs):
        Path(target).write_bytes(b"half a file")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", broken)
    with pytest.raises(OSError):
        ds.write_parquet(pd.DataFrame({"v": [9]}), path)
    monkeypatch.undo()
    assert list(pd.read_parquet(path)["v"]) == [1, 2]            # the old file is intact
    assert [p.name for p in path.parent.iterdir()] == ["a.parquet"]  # no temp file left behind


@pytest.mark.unit
def test_lot_blips_are_removed_but_real_changes_kept():
    lots = pd.Series([75, 75, 75, 225, 75, 75, 50, 50, 50, 50, 50, 50, 25.0])
    out = ds.despike_lots(lots)
    assert list(out) == [75, 75, 75, 75, 75, 75, 50, 50, 50, 50, 50, 50, 25]   # 225 was a blip; 25 at the end stays


@pytest.mark.unit
def test_todays_bar_is_used_only_after_the_close():
    from datetime import datetime

    from tradingagents.analytics.prices import last_complete_session_date

    assert last_complete_session_date(datetime(2026, 10, 23, 14, 0)) == date(2026, 10, 22)   # market open
    assert last_complete_session_date(datetime(2026, 10, 23, 19, 30)) == date(2026, 10, 23)  # after the close

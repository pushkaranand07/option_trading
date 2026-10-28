"""The stored base: every underlying, quality flags that never drop rows, UNVERIFIED pre-2018 lots (docs/PA_34)."""

import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import base_store as bs, datastore as ds
from tradingagents.research import loader


def _legacy_zip(tmp_path, day: date, rows: list[dict]):
    cols = ["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH", "LOW", "CLOSE",
            "SETTLE_PR", "CONTRACTS", "VAL_INLAKH", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP"]
    df = pd.DataFrame(rows)[cols[:-1]].assign(TIMESTAMP=day.strftime("%d-%b-%Y").upper())
    name = f"fo{day:%d}{day.strftime('%b').upper()}{day:%Y}bhav.csv.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name[:-4], df.to_csv(index=False))
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return path


def _row(inst, sym, expiry, strike, typ, close, contracts=10, oi=750, chg=75):
    return {"INSTRUMENT": inst, "SYMBOL": sym, "EXPIRY_DT": expiry, "STRIKE_PR": strike, "OPTION_TYP": typ,
            "OPEN": close, "HIGH": close, "LOW": close, "CLOSE": close, "SETTLE_PR": close, "CONTRACTS": contracts,
            "VAL_INLAKH": contracts * 75 * (strike + close if typ != "XX" else close) / 1e5,
            "OPEN_INT": oi, "CHG_IN_OI": chg}


@pytest.fixture
def day_file(tmp_path):
    exp = "28-JAN-2016"
    rows = [
        _row("FUTIDX", "NIFTY", exp, 0, "XX", 1000.0),
        # parity holds at 1000: C - P ~ F - K
        _row("OPTIDX", "NIFTY", exp, 1000, "CE", 20.0), _row("OPTIDX", "NIFTY", exp, 1000, "PE", 20.0),
        # parity broken at 1050: C - P = 40, F - K = -50
        _row("OPTIDX", "NIFTY", exp, 1050, "CE", 60.0), _row("OPTIDX", "NIFTY", exp, 1050, "PE", 20.0),
        # a 900 call trading far below its intrinsic value (~100)
        _row("OPTIDX", "NIFTY", exp, 900, "CE", 50.0),
        # an untraded put: never tested
        _row("OPTIDX", "NIFTY", exp, 950, "PE", 0.0, contracts=0),
        _row("FUTSTK", "OLDCO", exp, 0, "XX", 200.0, oi=1500, chg=500),
        _row("OPTSTK", "OLDCO", exp, 200, "CE", 5.0, oi=1000, chg=500),
    ]
    return _legacy_zip(tmp_path, date(2016, 1, 13), rows)


@pytest.mark.unit
def test_every_underlying_is_kept_with_its_kind_and_a_derived_lot(day_file):
    summary, chain = bs.build_day((str(day_file), day_file.name))
    assert dict(zip(summary["symbol"], summary["kind"], strict=True)) == {"NIFTY": "index", "OLDCO": "stock"}
    assert set(summary["lot_source"]) == {"derived_oi"}
    assert set(chain["symbol"]) == {"NIFTY", "OLDCO"}


@pytest.mark.unit
def test_quality_flags_mark_rows_and_never_drop_them(day_file):
    _, chain = bs.build_day((str(day_file), day_file.name))
    by = chain.set_index(["strike", "option_type"])
    assert len(chain) == 7                                   # every option row inside the filter is kept
    assert not by.loc[(1000.0, "CE"), "flag_parity"] and by.loc[(1000.0, "CE"), "parity_tested"]
    assert by.loc[(1050.0, "CE"), "flag_parity"] and by.loc[(1050.0, "PE"), "flag_parity"]
    assert by.loc[(900.0, "CE"), "flag_below_intrinsic"]
    assert not by.loc[(950.0, "PE"), "intrinsic_tested"] and not by.loc[(950.0, "PE"), "parity_tested"]


@pytest.mark.unit
def test_only_lots_stated_in_the_file_are_verified():
    s = pd.DataFrame({"trade_date": [date(2017, 12, 29), date(2018, 1, 1), date(2024, 8, 1), date(2016, 1, 4)],
                      "lot_source": ["derived_oi", "derived_oi", "stated", "none"]})
    assert list(bs._lot_status(s)) == [bs.UNVERIFIED, bs.UNVERIFIED, "stated", bs.UNVERIFIED]


@pytest.mark.unit
def test_loader_masks_unverified_lots_unless_asked(tmp_path):
    root = tmp_path / "store"
    (root / "base_fo_summary").mkdir(parents=True)
    pd.DataFrame({"trade_date": [date(2016, 1, 13), date(2018, 1, 2)], "known_from": [date(2016, 1, 14), date(2018, 1, 3)],
                  "symbol": ["OLDCO", "OLDCO"], "lot_size": [500.0, 250.0],
                  "lot_status": [bs.UNVERIFIED, "stated"]}).to_parquet(root / "base_fo_summary" / "2016.parquet")
    df = loader.load("base_fo_summary", start=date(2016, 1, 1), end=date(2016, 12, 31), root=root,
                     log_path=tmp_path / "t.sqlite")
    assert np.isnan(df["lot_size"].iloc[0]) and df["lot_size_unverified"].iloc[0] == 500.0
    raw = loader.load("base_fo_summary", start=date(2016, 1, 1), end=date(2016, 12, 31), root=root,
                      log_path=tmp_path / "t.sqlite", allow_unverified_lots=True)
    assert raw["lot_size"].iloc[0] == 500.0
    assert list(loader.mask_unverified_lots(pd.DataFrame({"lot_size": [250.0], "lot_status": ["stated"]}))
                ["lot_size"]) == [250.0]


@pytest.mark.unit
def test_alternating_lot_blips_settle_the_way_repeated_nightly_despiking_does():
    # around a lot change, open-interest GCDs can alternate day to day (DIVISLAB 2022-06, WIPRO 2022-12)
    lots = pd.Series([1000.0] * 6 + [2000, 1000, 2000, 1000, 2000] + [1000.0] * 6)
    once = ds.despike_lots(lots)
    stable = bs.despike_until_stable(lots)
    assert (stable == 1000.0).all()
    assert not once.equals(stable)                     # a single pass is not enough
    s = pd.DataFrame({"symbol": "WIPRO", "trade_date": pd.bdate_range("2022-11-21", periods=len(lots)).date,
                      "lot_size": lots, "lot_source": "derived_oi"})
    fixed, changed = bs.stable_lots(s)
    assert (fixed["lot_size"] == 1000.0).all() and changed == 3
    s["lot_source"] = "stated"                         # stated lots are never touched
    assert bs.stable_lots(s)[1] == 0


@pytest.mark.unit
def test_lot_despiking_that_oscillates_or_never_settles_raises_and_returns_nothing(monkeypatch):
    a, b = pd.Series([100.0, 200.0, 100.0]), pd.Series([100.0, 100.0, 100.0])
    flip = {a.to_numpy().tobytes(): b, b.to_numpy().tobytes(): a}
    monkeypatch.setattr(ds, "despike_lots", lambda s: flip[s.to_numpy(dtype=float).tobytes()].copy())
    with pytest.raises(bs.LotsDidNotSettle, match="oscillates"):
        bs.despike_until_stable(a)
    counter = iter(range(10_000))
    monkeypatch.setattr(ds, "despike_lots", lambda s: s + next(counter) + 1)    # always a new state
    with pytest.raises(bs.LotsDidNotSettle, match="after 5 passes"):
        bs.despike_until_stable(pd.Series([1.0, 2.0]), max_passes=5)
    s = pd.DataFrame({"symbol": "X", "trade_date": [date(2016, 1, 4), date(2016, 1, 5), date(2016, 1, 6)],
                      "lot_size": [100.0, 200.0, 100.0], "lot_source": "derived_oi"})
    monkeypatch.setattr(ds, "despike_lots", lambda x: flip.get(x.to_numpy(dtype=float).tobytes(), b).copy())
    with pytest.raises(bs.LotsDidNotSettle):
        bs.stable_lots(s)


@pytest.mark.unit
def test_american_ca_pa_options_are_kept_as_calls_and_puts_and_never_parity_tested(tmp_path):
    exp = "28-JAN-2010"
    rows = [_row("FUTSTK", "OLDCO", exp, 0, "XX", 200.0, oi=1500, chg=500),
            _row("OPTSTK", "OLDCO", exp, 200, "CA", 8.0), _row("OPTSTK", "OLDCO", exp, 200, "PA", 30.0),
            _row("FUTIDX", "NIFTY", exp, 0, "XX", 1000.0),
            _row("OPTIDX", "NIFTY", exp, 1000, "CE", 20.0), _row("OPTIDX", "NIFTY", exp, 1000, "PE", 20.0)]
    f = _legacy_zip(tmp_path, date(2010, 1, 13), rows)
    _, chain = bs.build_day((str(f), f.name))
    old = chain[chain["symbol"] == "OLDCO"].set_index("option_type")
    assert set(old.index) == {"CE", "PE"} and set(old["exercise_style"]) == {"american"}
    assert not old["parity_tested"].any() and not old["intrinsic_tested"].any()
    nifty = chain[chain["symbol"] == "NIFTY"]
    assert set(nifty["exercise_style"]) == {"european"} and nifty["parity_tested"].all()
    # a 2015+ legacy file and the live parser are unchanged: every row European, CE / PE only
    assert bs.parse_fo_with_style(f.read_bytes(), f.name)["option_type"].dropna().isin(["CE", "PE"]).all()


@pytest.mark.unit
def test_a_reissued_file_with_two_digit_years_and_a_footer_row_parses(tmp_path):
    rows = [_row("FUTIDX", "NIFTY", "31-May-12", 0, "XX", 5000.0), _row("OPTIDX", "NIFTY", "31-May-12", 5000, "CE", 90.0)]
    df = pd.DataFrame(rows).assign(TIMESTAMP="14-May-12")
    df = pd.concat([df, pd.DataFrame([{"INSTRUMENT": "*Updated"}])], ignore_index=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fo14MAY2012bhav.csv", df.to_csv(index=False))
    fo = bs.parse_fo_with_style(buf.getvalue(), "fo14MAY2012bhav.csv.zip")
    assert len(fo) == 2 and set(fo["trade_date"]) == {date(2012, 5, 14)} and set(fo["expiry"]) == {date(2012, 5, 31)}

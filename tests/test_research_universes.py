"""Universe membership: sealed ranking, no look-ahead, real exits (docs/data/universes_v1.json, docs/PA_37)."""

import logging
import os
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.research import universes as uv

# distinctive values that must never escape the sealed ranking
SECRET = [7_123_456_789.25, 6_987_654_321.75, 5_555_444_333.5]


def _summary(rows):
    """rows: (trade_date, symbol, kind, turnover). known_from is the next weekday."""
    out = []
    for d, sym, kind, t in rows:
        k = d + timedelta(days=1)
        while k.weekday() >= 5:
            k += timedelta(days=1)
        out.append({"trade_date": d, "known_from": k, "symbol": sym, "kind": kind,
                    "fut_turnover": t, "opt_turnover": 0.0})
    return uv.with_series(pd.DataFrame(out), {})


def _days(start, end):
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def two_years():
    rows = []
    for d in _days(date(2015, 1, 1), date(2016, 12, 31)):
        for sym, t in (("AAA", SECRET[0]), ("BBB", SECRET[1]), ("CCC", SECRET[2]), ("DDD", 1.0)):
            if sym == "BBB" and d > date(2016, 6, 30):      # BBB exits mid-2016
                continue
            rows.append((d, sym, "stock", t))
        rows.append((d, "NIFTY", "index", 1.0))
    return _summary(rows)


def _no_secret(text: str):
    for v in SECRET:
        for form in (f"{v}", f"{v:.0f}", f"{v:,.2f}", f"{v:.6e}", f"{int(v)}"):
            assert form not in text, f"turnover value {form} leaked"


@pytest.mark.unit
def test_sealed_ranking_returns_only_member_ids_and_leaks_nothing(two_years, caplog, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.DEBUG)
    got = uv.sealed_top_n(two_years, 2016, n=2)
    assert got == frozenset({"AAA", "BBB"}) and all(isinstance(x, str) for x in got)
    _no_secret(repr(got))
    out, err = capsys.readouterr()
    _no_secret(out + err + caplog.text)
    assert out == err == "" and list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_a_failing_sealed_ranking_carries_no_values(two_years, caplog, capsys, monkeypatch):
    def leaky(turnover, n):            # an internal bug that would put values into its error
        raise ValueError(f"bad ranking: {turnover.to_dict()} rank gap {turnover.iloc[0] - turnover.iloc[1]}")

    monkeypatch.setattr(uv, "_top", leaky)
    with pytest.raises(uv.SealedRankingError) as info:
        uv.sealed_top_n(two_years, 2016, n=2)
    exc = info.value
    assert exc.__context__ is None and exc.__cause__ is None
    text = "".join(traceback.format_exception(exc)) + str(exc) + repr(exc) + str(exc.args)
    _no_secret(text)
    out, err = capsys.readouterr()
    _no_secret(out + err + caplog.text)


@pytest.mark.unit
def test_ranking_inputs_never_include_the_modelled_year(two_years):
    base = uv.sealed_top_n(two_years, 2016, n=2)
    # DDD trades enormously in 2016 itself: must not change 2016's membership
    boosted = two_years.copy()
    boosted.loc[(boosted["symbol"] == "DDD") & (pd.to_datetime(boosted["trade_date"]).dt.year == 2016),
                "fut_turnover"] = 1e18
    assert uv.sealed_top_n(boosted, 2016, n=2) == base
    rows = uv._turnover(two_years, 2016)
    assert set(rows.index) == {"AAA", "BBB", "CCC", "DDD"}


@pytest.mark.unit
def test_membership_on_d_is_identical_from_data_truncated_at_d_minus_1(two_years):
    full_top = {2016: uv.sealed_top_n(two_years, 2016, n=2)}
    full = uv.membership(two_years, "U1", full_top)
    for d in (date(2016, 1, 1), date(2016, 1, 4), date(2016, 6, 30), date(2016, 7, 1), date(2016, 7, 4),
              date(2016, 12, 30)):
        truncated = two_years[two_years["trade_date"] < d]          # data truncated at D-1
        want = frozenset(full.loc[full["date"] == d, "series"])
        assert uv.members_on(truncated, d, "U1", n=2) == want
        assert uv.members_on(two_years, d, "U1", n=2) == want


@pytest.mark.unit
def test_a_name_leaves_on_its_real_exit_and_is_not_replaced(two_years):
    top = {2016: uv.sealed_top_n(two_years, 2016, n=2)}
    m = uv.membership(two_years, "U1", top)
    stocks = m[m["kind"] == "stock"].groupby("date")["series"].apply(frozenset)
    assert stocks[date(2016, 7, 1)] == frozenset({"AAA", "BBB"})     # BBB's last row 2016-06-30 is public 07-01
    assert stocks[date(2016, 7, 4)] == frozenset({"AAA"})            # gone, and CCC does not replace it
    assert set(m.loc[m["kind"] == "index", "series"]) == {"NIFTY"}
    # stocks only in a ranked year (2016 here); indices in every U1 year (from 2011)
    assert pd.to_datetime(m.loc[m["kind"] == "stock", "date"]).dt.year.unique().tolist() == [2016]
    assert m.loc[m["kind"] == "index", "date"].min() == date(2015, 1, 2)


@pytest.mark.unit
def test_ties_break_alphabetically_and_open_ranking_refuses_the_protected_year():
    rows = [(d, s, "stock", 10.0) for d in _days(date(2024, 1, 1), date(2024, 1, 5)) for s in ("ZED", "ABC", "MID")]
    s = _summary(rows)
    assert uv.sealed_top_n(s, 2025, n=2) == frozenset({"ABC", "MID"})
    with pytest.raises(PermissionError):
        uv.open_ranking(s, 2026)
    assert list(uv.open_ranking(s, 2025)["series"]) == ["ABC", "MID", "ZED"]


@pytest.mark.unit
def test_renamed_symbols_are_one_series_only_for_mapped_links():
    m = pd.DataFrame({"old": ["A1", "B1", "X1"], "new": ["A2", "B2", "X2"], "status": ["mapped", "mapped", "unmapped: x"]})
    m = pd.concat([m, pd.DataFrame({"old": ["A2"], "new": ["A3"], "status": ["mapped"]})], ignore_index=True)
    ids = uv.series_ids(m, ["A1", "A2", "A3", "B1", "X1", "X2", "Q"])
    assert ids["A1"] == ids["A2"] == ids["A3"] == "A3" and ids["B1"] == "B2"
    assert ids["X1"] == "X1" and ids["X2"] == "X2" and ids["Q"] == "Q"


@pytest.mark.unit
def test_addendum_matches_the_split_file_and_the_symbol_map(tmp_path, monkeypatch):
    rules = uv.addendum()
    assert rules["universes"]["U1"]["stocks"]["cutoff"].startswith("rank <= 100")
    changed = tmp_path / "symbol_map_v1.csv"
    changed.write_bytes(uv.SYMBOL_MAP.read_bytes() + b"\nX,Y,2020-01-01,,,,,mapped\n")
    monkeypatch.setattr(uv, "SYMBOL_MAP", changed)
    with pytest.raises(uv.AddendumMismatch):
        uv.addendum()


STORE = Path(os.environ.get("RESEARCH_STORE_DIR", "-"))


@pytest.mark.skipif(not (STORE / "base_fo_summary").is_dir(), reason="set RESEARCH_STORE_DIR")
def test_real_store_membership_on_d_matches_truncated_rebuild(tmp_path):
    from tradingagents.research import loader

    s = loader.load("base_fo_summary", start=date(2014, 1, 1), end=date(2016, 12, 31), root=STORE,
                    log_path=tmp_path / "t.sqlite")
    s = uv.with_series(s, uv.series_ids(pd.read_csv(uv.SYMBOL_MAP), s["symbol"]))
    for d in (date(2015, 1, 1), date(2015, 6, 1), date(2016, 3, 1), date(2016, 12, 30)):
        sessions = sorted(x for x in set(s["known_from"]) if x <= d)
        d = sessions[-1]
        full = uv.membership(s, "U1", {d.year: uv.sealed_top_n(s, d.year)})
        assert uv.members_on(s[s["trade_date"] < d], d, "U1") == frozenset(full.loc[full["date"] == d, "series"])

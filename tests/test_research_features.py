"""Feature library v1: look-ahead, handling of splits, schemes, rolls and holes, liquidity, spec (docs/features_v1.json, docs/PA_42)."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.research import features as fx, gate as g, loader


def _sessions(n=330):
    out, d = [], date(2019, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _expiries(s):
    out, seen = [], set()
    for d in s:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(date(d.year, d.month, 25) if d.month != 2 else date(d.year, 2, 25))
    return out + [date(2021, 1, 28), date(2021, 2, 25), date(2021, 3, 25), date(2021, 4, 29)]


def _world(seed=0, symbols=30):
    """Futures on two expiries, a summary, index, participant, delivery and membership for ``symbols`` stocks plus NIFTY."""
    rng = np.random.default_rng(seed)
    s = _sessions()
    ex = _expiries(s)
    known = {d: s[i + 1] for i, d in enumerate(s[:-1])}
    rows, summ = [], []
    names = [f"S{i:02d}" for i in range(symbols)] + ["NIFTY"]
    for name in names:
        px = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(s))))
        oi = 1e6 * np.exp(np.cumsum(rng.normal(0, 0.01, len(s))))
        for i, d in enumerate(s):
            nxt = [e for e in ex if e >= d][:2]
            for j, e in enumerate(nxt):
                c = px[i] * (1 + 0.004 * (j + 1))
                o = oi[i] * (0.8 if j == 0 else 0.2)
                prev = oi[i - 1] * (0.8 if j == 0 else 0.2) if i else o
                rows.append({"trade_date": d, "symbol": name, "instrument": "FUTIDX" if name == "NIFTY" else "FUTSTK", "expiry": e, "open": c * 0.999, "high": c * 1.01,
                             "low": c * 0.99, "close": c, "settle": c, "open_interest": o, "oi_change": o - prev, "contracts": 100.0, "turnover": 1e7 * (1 + rng.random()), "known_from": known.get(d)})
            if d in known:
                summ.append({"trade_date": d, "known_from": known[d], "symbol": name, "kind": "index" if name == "NIFTY" else "stock"})
    fut = g.clean_futures(pd.DataFrame(rows))
    summary = pd.DataFrame(summ)
    m = summary.assign(date=summary["known_from"], series=summary["symbol"])[["date", "series", "symbol", "kind"]]
    idx = pd.DataFrame([{"trade_date": d, "symbol": n, "open": v, "high": v, "low": v, "close": v, "volume": 1.0} for i, d in enumerate(s)
                        for n, v in (("NIFTY", 1e4 + i), ("BANKNIFTY", 2e4 + i), ("INDIAVIX", 15 + np.sin(i)))])
    part = pd.DataFrame([{"trade_date": d, "category": c, **dict.fromkeys(("fut_idx_long", "fut_stk_long", "opt_idx_call_long", "opt_idx_put_long"), 100 + i + j),
                          **dict.fromkeys(("fut_idx_short", "fut_stk_short", "opt_idx_call_short", "opt_idx_put_short"), 90 + 2 * i)}
                         for i, d in enumerate(s) for j, c in enumerate(fx.CATEGORIES)])
    deliv = pd.DataFrame([{"trade_date": d, "symbol": n, "series": "EQ", "deliv_pct": 40 + 5 * np.sin(i + k)} for i, d in enumerate(s) for k, n in enumerate(names[:-1])])
    return {"futures": fut, "summary": summary, "participant": part, "delivery": deliv, "index_close": idx,
            "events": pd.DataFrame(columns=["symbol", "ex_date", "subject"]), "notices": pd.DataFrame(columns=["symbol", "meeting", "notice", "results"]), "U1": m, "U2": m, "holes": []}


def _chain(inputs, last=None):
    """A small liquid chain around each future, priced at 30% vol, for the first expiry with at least 7 days."""
    rows = []
    for r in inputs["futures"].itertuples():
        if r.trade_date.day % 7 or (r.expiry - r.trade_date).days < 7 or r.symbol.endswith("1"):
            continue
        T = (r.expiry - r.trade_date).days / 365
        for m in (0.9, 0.95, 1.0, 1.05, 1.1):
            k = round(r.close * m, 2)
            for typ, call in (("CE", True), ("PE", False)):
                price = float(fx.black76(np.array([r.close]), np.array([k]), np.array([T]), fx.RISK_FREE, np.array([0.30]), np.array([call]))[0])
                rows.append({"trade_date": r.trade_date, "symbol": r.symbol, "expiry": r.expiry, "strike": k, "option_type": typ, "close": price, "contracts": 100.0,
                             "open_interest": 1000.0, "flag_parity": False, "flag_below_intrinsic": False, "exercise_style": "european"})
    return pd.DataFrame(rows)


def _build(inputs, chain=None):
    o, a = fx.options_from_chain(chain) if chain is not None and len(chain) else (pd.DataFrame(columns=["t", "symbol", "front_expiry", *["atm_iv_front", "atm_iv_next", "iv_term_slope", "iv_term_ratio", "skew_5", "skew_5_norm", "pcr_volume_liquid", "pcr_oi_liquid", "max_pain_dist", "n_liquid_pairs"]]), pd.DataFrame(columns=["t", "symbol", "expiry", "atm_iv"]))
    return fx.build(inputs, o, a)[0]


def _cut(inputs, day):
    """Every input row with trade_date before ``day``."""
    out = dict(inputs)
    for k in ("futures", "participant", "delivery", "index_close", "summary"):
        out[k] = inputs[k][pd.to_datetime(inputs[k]["trade_date"]) < pd.Timestamp(day)]
    return out


@pytest.mark.unit
def test_spec_is_frozen_and_every_feature_has_formula_window_known_from():
    spec = fx.read_spec()
    assert spec["liquidity"]["chosen_contracts"] == fx.LIQUID_CONTRACTS == 25
    for name, f in spec["features"].items():
        assert f["formula"] and f["window"] and f["known_from"] and f["family"] in "abcdefgh", name


@pytest.mark.unit
def test_a_changed_spec_is_refused(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(fx.SPEC_FILE.read_text(encoding="utf-8").replace('"version": 1', '"version": 2'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        fx.read_spec(p)


@pytest.mark.unit
def test_builders_make_exactly_the_spec_columns():
    w = _world()
    t = _build(w, _chain(w))
    spec = fx.read_spec()
    made = {c for x in t.values() for c in x.columns} - {"signal_date", "source_trade_date", "known_from", "symbol"}
    assert made == set(spec["features"])


@pytest.mark.unit
def test_truncation_features_for_d_are_identical_when_built_from_data_cut_at_d_minus_1():
    w = _world()
    chain = _chain(w)
    full = _build(w, chain)
    days = _sessions()
    with_chain = [days[i] for i in range(261, len(days)) if days[i - 1].day % 7 == 0]      # the source session has options
    for day in (with_chain[0], with_chain[-1]):
        cut =_build(_cut(w, day), chain[pd.to_datetime(chain["trade_date"]) < pd.Timestamp(day)])
        for fam in full:
            a = full[fam][full[fam]["signal_date"] == pd.Timestamp(day)].sort_index(axis=1)
            b = cut[fam][cut[fam]["signal_date"] == pd.Timestamp(day)].sort_index(axis=1)
            keys = ["symbol"] if "symbol" in a else ["signal_date"]
            assert len(a), fam
            pd.testing.assert_frame_equal(a.sort_values(keys).reset_index(drop=True), b.sort_values(keys).reset_index(drop=True), check_dtype=False)


@pytest.mark.unit
def test_a_later_listing_adds_no_earlier_delivery_row():
    w = _world()
    days = _sessions()
    f = w["futures"]
    w = {**w, "futures": f[(f["symbol"] != "S07") | (f["trade_date"] >= days[200])]}
    e = _build(w)["e"]
    assert pd.to_datetime(e.loc[e["symbol"] == "S07", "source_trade_date"]).min() == pd.Timestamp(days[200])


@pytest.mark.unit
def test_the_truncation_check_catches_a_feature_that_looks_ahead():
    w = _world()
    day = _sessions()[260]
    t = _build(w)["a"]
    leaked = t.sort_values(["symbol", "signal_date"]).copy()
    leaked["ret_1"] = leaked.groupby("symbol")["ret_1"].shift(-1)        # next session's return
    c = _build(_cut(w, day))["a"]
    a = leaked[leaked["signal_date"] == pd.Timestamp(day)].sort_values("symbol")["ret_1"].to_numpy()
    b = c[c["signal_date"] == pd.Timestamp(day)].sort_values("symbol")["ret_1"].to_numpy()
    assert not np.allclose(a, b, equal_nan=True)


@pytest.mark.unit
def test_every_row_is_known_by_its_signal_date_and_reads_an_earlier_session():
    t = _build(_world())
    for fam, x in t.items():
        assert (pd.to_datetime(x["known_from"]) <= pd.to_datetime(x["signal_date"])).all(), fam
        assert (pd.to_datetime(x["source_trade_date"]) < pd.to_datetime(x["signal_date"])).all(), fam


def _shock(w, symbol, day_index, price_factor, oi_factor, reset=False):
    """From this session on, the symbol's prices are multiplied and its OI scaled, as a corporate action does."""
    day = _sessions()[day_index]
    f = w["futures"].copy()
    hit = (f["symbol"] == symbol) & (f["trade_date"] >= day)
    for c in ("open", "high", "low", "close", "settle"):
        f.loc[hit, c] *= price_factor
    f.loc[hit, "open_interest"] *= oi_factor
    if reset:
        on = (f["symbol"] == symbol) & (f["trade_date"] == day)
        f.loc[on, "oi_change"] = f.loc[on, "open_interest"]
    return {**w, "futures": f}, day


PRICE_FEATURES = ["ret_1", "ret_5", "ret_20", "gap_1", "range_1", "close_loc_1"]


def _on(t, symbol, day):
    x = t[(t["symbol"] == symbol) & (pd.to_datetime(t["source_trade_date"]) == pd.Timestamp(day))]
    assert len(x) == 1
    return x.iloc[0]


@pytest.mark.unit
@pytest.mark.parametrize(("price", "oi", "reset", "listed"), [(0.5, 2.0, False, False), (0.174, 1.0, True, True), (0.7, 1.0, False, True), (0.2, 1.0, False, False)],
                         ids=["split_footprint", "scheme_with_reset", "listed_scheme_small_move", "unlisted_extreme_move"])
def test_a_corporate_action_never_shows_as_a_feature_value(price, oi, reset, listed):
    w, day = _shock(_world(), "S05", 200, price, oi, reset)
    if listed:
        w = {**w, "events": pd.DataFrame({"symbol": ["S05"], "ex_date": [day], "subject": ["Scheme Of Arrangement"]})}
    t = _build(w)
    r = _on(t["a"], "S05", day)
    assert r[PRICE_FEATURES].isna().all()
    b = _on(t["b"], "S05", day)
    assert np.isnan(b["oi_chg_1"]) and np.isnan(b["oi_z_60"]) and b["disc_flag"] == 1
    assert b["oi_reset_flag"] == (1 if reset else 0)
    a = t["a"][t["a"]["symbol"] == "S05"]
    assert a[PRICE_FEATURES[:3]].abs().max().max() < 0.5 * abs(np.log(0.5)) + 0.5         # no window holds the jump
    for n in (5, 20):
        ahead = _sessions()[200 + n - 1]
        assert np.isnan(_on(t["a"], "S05", ahead)[f"ret_{n}"])
        assert not np.isnan(_on(t["a"], "S05", _sessions()[200 + n])[f"ret_{n}"])


@pytest.mark.unit
def test_oi_history_restarts_after_a_reset():
    w, day = _shock(_world(), "S05", 200, 0.5, 2.0, True)
    b = _build(w)["b"]
    days = _sessions()
    assert np.isnan(_on(b, "S05", days[200 + 30])["oi_z_60"])
    assert not np.isnan(_on(b, "S05", days[200 + 45])["oi_z_60"])
    assert _on(b, "S05", days[200 + 45])["sessions_since_disc"] == 45


@pytest.mark.unit
def test_the_flags_are_marked_as_never_a_signal():
    spec = fx.read_spec()["features"]
    assert {n for n, f in spec.items() if f["role"] == "handling_flag"} == {"oi_reset_flag", "disc_flag", "sessions_since_disc"}


@pytest.mark.unit
def test_a_roll_shows_in_neither_returns_nor_oi_change():
    """Everything moves from near to next and next trades at a premium: no return and no OI change appears."""
    s = _sessions(40)
    e1, e2 = date(2019, 1, 25), date(2019, 2, 25)
    rows = []
    for i, d in enumerate(s):
        for e, close, oi in ((e1, 100.0, 1000.0 - 25 * i), (e2, 110.0, 25.0 * i + 1)):
            if d <= e:
                prev = (1000.0 - 25 * (i - 1)) if e == e1 else (25.0 * (i - 1) + 1)
                rows.append({"trade_date": d, "symbol": "AAA", "instrument": "FUTSTK", "expiry": e, "open": close, "high": close, "low": close, "close": close, "settle": close,
                             "open_interest": oi, "oi_change": oi - prev if i else 0.0, "contracts": 10.0, "turnover": 1.0})
    fut = g.clean_futures(pd.DataFrame(rows))
    sessions = pd.DatetimeIndex(pd.to_datetime(s))
    f = fx.contract_panel(fut, sessions)
    near = fx.near_rows(f)
    syms = pd.Index(["AAA"])
    disc, reset = fx.discontinuities(f, near, pd.DataFrame(columns=["symbol", "ex_date"]), sessions, syms)
    assert not disc.to_numpy().any()
    lr = fx.source_returns(near, disc, sessions, syms)
    assert lr.abs().max().max() == 0.0
    b = fx.family_b(f, near, disc, reset, pd.DataFrame(columns=["trade_date", "symbol", "close"]))
    assert b["oi_chg_1"].loc[pd.Timestamp(date(2019, 1, 15)), "AAA"] == pytest.approx(0.0, abs=1e-9)      # a contract-to-contract move
    gone = pd.Timestamp(date(2019, 1, 28))                # the first session without the near contract: only the next contract's own change counts
    assert b["oi_chg_1"].loc[gone, "AAA"] == pytest.approx(25 / 1001)


@pytest.mark.unit
def test_a_hole_is_a_session_with_no_data_and_nothing_is_filled():
    w = _world()
    days = _sessions()
    hole = days[150]
    f = w["futures"]
    w = {**w, "futures": f[f["trade_date"] != hole], "holes": [hole]}
    a = _build(w)["a"]
    x = a[a["symbol"] == "S01"]
    assert not (pd.to_datetime(x["source_trade_date"]) == pd.Timestamp(hole)).any()
    after = _on(a, "S01", days[151])
    assert np.isnan(after["ret_1"]) and np.isnan(after["gap_1"])
    assert not np.isnan(_on(a, "S01", days[152])["ret_1"])
    assert np.isnan(_on(a, "S01", days[155])["ret_20"])


@pytest.mark.unit
def test_a_session_absent_from_the_signal_map_has_no_row():
    w = _world()
    t = _build(w)["a"]
    assert pd.to_datetime(t["signal_date"]).max() == pd.Timestamp(_sessions()[-1])
    assert pd.to_datetime(t["source_trade_date"]).max() == pd.Timestamp(_sessions()[-2])


def _one_expiry(strikes, contracts=100.0, flag=False, style="european", vol=0.30, days=30):
    d, e = date(2020, 1, 1), date(2020, 1, 1) + timedelta(days=days)
    rows = []
    for k, n in zip(strikes, np.broadcast_to(contracts, len(strikes)), strict=True):
        for typ, call in (("CE", True), ("PE", False)):
            p = float(fx.black76(np.array([100.0]), np.array([k]), np.array([days / 365]), fx.RISK_FREE, np.array([vol]), np.array([call]))[0])
            rows.append({"trade_date": d, "symbol": "AAA", "expiry": e, "strike": float(k), "option_type": typ, "close": p, "contracts": n, "open_interest": 100.0,
                         "flag_parity": flag, "flag_below_intrinsic": False, "exercise_style": style})
    return pd.DataFrame(rows)


@pytest.mark.unit
def test_atm_iv_recovers_a_known_vol():
    o, _ = fx.options_from_chain(_one_expiry([90, 95, 100, 105, 110]))
    assert o["atm_iv_front"].iloc[0] == pytest.approx(0.30, abs=1e-4)
    assert o["skew_5"].iloc[0] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.unit
def test_american_rows_are_refused():
    with pytest.raises(loader.AmericanOptionsError):
        fx.options_from_chain(_one_expiry([100], style="american"))


@pytest.mark.unit
@pytest.mark.parametrize(("contracts", "flag"), [(24.0, False), (100.0, True)], ids=["below_threshold", "parity_flagged"])
def test_a_thin_or_flagged_pair_gives_no_iv(contracts, flag):
    o, _ = fx.options_from_chain(_one_expiry([90, 95, 100, 105, 110], contracts, flag))
    assert "atm_iv_front" not in o or o["atm_iv_front"].isna().all()
    assert o["n_liquid_pairs"].iloc[0] == 0.0


@pytest.mark.unit
def test_the_threshold_is_inclusive():
    o, _ = fx.options_from_chain(_one_expiry([90, 95, 100, 105, 110], 25.0))
    assert o["n_liquid_pairs"].iloc[0] == pytest.approx(np.log1p(5))


@pytest.mark.unit
def test_max_pain_finds_the_strike_with_least_payout():
    c = _one_expiry([90, 95, 100, 105, 110])
    c.loc[(c["strike"] == 110) & (c["option_type"] == "CE"), "open_interest"] = 1e6
    c.loc[(c["strike"] == 110) & (c["option_type"] == "PE"), "open_interest"] = 0.0
    c.loc[(c["strike"] == 90) & (c["option_type"] == "PE"), "open_interest"] = 1e6
    o, _ = fx.options_from_chain(c)
    assert o["max_pain_dist"].iloc[0] == pytest.approx(np.log(100 / 100.0), abs=0.06)


@pytest.mark.unit
def test_a_board_notice_counts_only_after_its_own_timestamp():
    w = _world()
    days = _sessions()
    notice_day = pd.Timestamp(days[220])
    w = {**w, "notices": pd.DataFrame({"symbol": ["S03"], "meeting": [pd.Timestamp(days[230])], "notice": [notice_day + pd.Timedelta(hours=18)], "results": [True]})}
    t = _build(w)["g"]
    x = t[t["symbol"] == "S03"]
    def at(d):
        return x[pd.to_datetime(x["signal_date"]) == pd.Timestamp(d)].iloc[0]
    assert np.isnan(at(days[220])["results_days_to_next"])       # stamped 18:00, after that day's close
    assert at(days[221])["results_days_to_next"] == (pd.Timestamp(days[230]) - pd.Timestamp(days[221])).days
    assert np.isnan(_on(t, "S04", days[225])["board_days_to_next"])


@pytest.mark.unit
def test_ranks_use_that_date_only_and_only_members():
    w = _world()
    t = _build(w)
    a, h = t["a"], t["h"]
    day = pd.Timestamp(_sessions()[250])
    x = a[(a["signal_date"] == day) & (a["symbol"] != "NIFTY")].set_index("symbol")["ret_5"]
    r = h[h["signal_date"] == day].set_index("symbol")["rank_U1_ret_5"]
    pd.testing.assert_series_equal(r.sort_index(), x.rank(pct=True).sort_index(), check_names=False)
    assert "NIFTY" not in r.index


@pytest.mark.unit
def test_limits_clip_without_filling():
    frame = pd.DataFrame({"x": [1.0, np.nan, 100.0]})
    out = fx.apply_limits(frame, {"x": (0.0, 10.0)})
    assert out["x"].iloc[2] == 10.0 and np.isnan(out["x"].iloc[1])


@pytest.mark.unit
def test_the_builders_read_no_lots_returns_target_or_store_directly():
    text = Path(fx.__file__).read_text(encoding="utf-8")
    for word in ("lot_size", "targets(", "build_trades", "datastore", "store_root"):
        assert word not in text, word


@pytest.mark.unit
def test_features_refuse_a_locked_period(tmp_path):
    with pytest.raises(loader.HoldoutLocked):
        loader.load_features("a", end=date(2025, 1, 1), root=tmp_path)
    with pytest.raises(loader.HoldoutLocked):
        loader.load_board_notices(end=date(2025, 1, 1), root=tmp_path)
    with pytest.raises(loader.HoldoutLocked):
        loader.load_price_events(end=date(2025, 1, 1), root=tmp_path)


@pytest.mark.unit
def test_garch_features_recover_a_known_volatility_in_annual_terms():
    """Regression, addendum 7: fractions went in where percent was expected, so values were about 77 times too small."""
    days = pd.bdate_range("2015-01-01", periods=900)
    r = pd.Series(np.random.default_rng(0).standard_t(6, 900) * 0.02 / np.sqrt(6 / 4), index=days)
    out = fx.garch_one(("AAA", r))
    annual = 0.02 * np.sqrt(252)
    for c in ("garch_h1", "garch_h5", "garch_h10"):
        assert 0.6 * annual < out[c].median() < 1.4 * annual, c

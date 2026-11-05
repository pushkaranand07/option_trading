"""Step 5, one bet: trades on the same view of the same index count as one bet.

A bet is source + symbol + direction (bullish / bearish / neutral); the expiry is not part of it. A trade joins a bet
when, at its taken_at, a trade of that bet was open (overnight too), or it is on the same day as one; chains count.
Won / lost is decided per bet by the sum of its trades' net; open bets are shown apart ("N bets open"). Net is closed
trades only; the open trades' P&L is its own line. Not-taken rows and rows entered outside the session are in no bet."""

import pytest

from webapp import strategist as st, trade_record as tr


# ---------------------------------------------------------------- one direction function

@pytest.mark.unit
@pytest.mark.parametrize("strategy", [s for s in st.STRATEGIES if s != "no_trade"])
def test_every_strategy_in_the_app_has_one_direction(strategy):
    assert tr.direction_of(strategy) in ("bullish", "bearish", "neutral")


@pytest.mark.unit
def test_the_directions_are_the_ones_the_strategies_bet_on():
    assert {s: tr.direction_of(s) for s in st.STRATEGIES if s != "no_trade"} == {
        "long_call": "bullish", "bull_call_spread": "bullish", "bull_put_spread": "bullish",
        "long_put": "bearish", "bear_put_spread": "bearish", "bear_call_spread": "bearish", "iron_condor": "neutral"}


@pytest.mark.unit
@pytest.mark.parametrize("strategy", ["no_trade", "straddle", "", None])
def test_an_unknown_strategy_is_an_error_not_a_default(strategy):
    with pytest.raises(ValueError, match="no direction"):
        tr.direction_of(strategy)


# ---------------------------------------------------------------- grouping (read time) and the stats per bet

def row(id, strategy, taken_at, closed_at=None, net=None, source="you", expiry="27-Oct-2099", status=None, symbol="NIFTY"):
    return {"id": id, "source": source, "status": status or ("closed" if closed_at else "open"), "symbol": symbol,
            "expiry": expiry, "strategy": strategy, "taken_at": taken_at, "closed_at": closed_at, "net_pnl": net,
            "lot": 65, "lots": 1, "legs": [], "alerts": []} | ({"range": [22400, 22800]} if strategy in tr.RANGE else {})


def no_prices(*a):
    raise RuntimeError("no prices in this test")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    return lambda *rows: tr._save(list(rows))


def bets(o, who="you"):
    """{trade id: (bet_id, bet_index, bet_size)} for every trade in a bet."""
    v = o[who]
    return {t["id"]: (t.get("bet_id"), t.get("bet_index"), t.get("bet_size")) for t in v["open"] + v["closed"] + v["not_taken"]}


@pytest.mark.unit
def test_a_bullish_trade_open_overnight_and_a_new_bullish_one_at_0915_are_one_bet(store):
    store(row("a", "bull_call_spread", "2026-11-04 14:00"), row("b", "long_call", "2026-11-05 09:15"))
    assert bets(tr.overview(no_prices)) == {"a": ("a", 1, 2), "b": ("a", 2, 2)}


@pytest.mark.unit
def test_closed_overnight_after_the_new_one_was_taken_still_one_bet(store):
    store(row("a", "bull_call_spread", "2026-11-04 14:00", "2026-11-05 09:30", 100.0), row("b", "long_call", "2026-11-05 09:15"))
    assert bets(tr.overview(no_prices))["b"] == ("a", 2, 2)


@pytest.mark.unit
def test_the_same_day_another_expiry_the_same_direction_is_one_bet(store):
    store(row("a", "bull_put_spread", "2026-11-05 09:20", "2026-11-05 10:00", 50.0, expiry="11-Nov-2099"),
          row("b", "bull_call_spread", "2026-11-05 11:00", expiry="18-Nov-2099"))
    assert bets(tr.overview(no_prices))["b"] == ("a", 2, 2)


@pytest.mark.unit
def test_a_chain_of_overlaps_is_one_bet(store):
    store(row("a", "long_call", "2026-11-03 10:00", "2026-11-04 10:00", 10.0),
          row("b", "long_call", "2026-11-03 15:00", "2026-11-05 10:00", 10.0),        # open when c is taken
          row("c", "long_call", "2026-11-05 09:30", "2026-11-05 11:00", 10.0))        # a is long closed by then
    assert {k: v[0] for k, v in bets(tr.overview(no_prices)).items()} == {"a": "a", "b": "a", "c": "a"}


@pytest.mark.unit
def test_the_opposite_direction_and_neutral_are_bets_of_their_own(store):
    store(row("a", "long_call", "2026-11-05 09:20"), row("b", "bear_call_spread", "2026-11-05 09:30"),
          row("c", "iron_condor", "2026-11-05 09:40"), row("d", "long_put", "2026-11-05 10:00"))
    assert bets(tr.overview(no_prices)) == {"a": ("a", 1, 1), "b": ("b", 1, 2), "c": ("c", 1, 1), "d": ("b", 2, 2)}


@pytest.mark.unit
def test_no_overlap_and_the_next_day_is_a_new_bet(store):
    store(row("a", "long_call", "2026-11-04 10:00", "2026-11-04 14:00", 10.0), row("b", "long_call", "2026-11-05 09:30"))
    assert bets(tr.overview(no_prices)) == {"a": ("a", 1, 1), "b": ("b", 1, 1)}


@pytest.mark.unit
def test_another_source_or_symbol_is_another_bet(store):
    store(row("a", "long_call", "2026-11-05 09:20"), row("b", "long_call", "2026-11-05 09:30", source="ai"),
          row("c", "long_call", "2026-11-05 09:40", symbol="BANKNIFTY"))
    o = tr.overview(no_prices)
    assert bets(o) == {"a": ("a", 1, 1), "c": ("c", 1, 1)} and bets(o, "ai") == {"b": ("b", 1, 1)}


@pytest.mark.unit
def test_not_taken_rows_and_rows_entered_outside_the_session_are_in_no_bet(store, monkeypatch):
    monkeypatch.setattr(tr, "_market_open", lambda at=None: at is None or (9, 15) <= (at.hour, at.minute) < (15, 30))
    store(row("a", "long_call", "2026-11-05 09:20"), row("n", "long_call", "2026-11-05 09:25", status="not_taken"),
          row("x", "long_call", "2026-11-05 15:33", "2026-11-05 15:40", 500.0))
    o = tr.overview(no_prices)
    assert bets(o) == {"a": ("a", 1, 1), "n": (None, None, None), "x": (None, None, None)}
    assert o["you"]["stats"]["bets"] == 1


@pytest.mark.unit
def test_won_and_lost_are_decided_per_bet_by_the_sum_of_its_trades(store, monkeypatch):
    store(row("a", "long_call", "2026-11-05 09:20", "2026-11-05 10:00", -300.0),
          row("b", "bull_call_spread", "2026-11-05 10:30", "2026-11-05 11:00", 500.0),   # bet a: -300 + 500 = won
          row("c", "long_put", "2026-11-05 09:30", "2026-11-05 09:50", -100.0),          # bet c: lost
          row("d", "iron_condor", "2026-11-05 11:00"),                                   # bet d: open
          row("e", "bear_call_spread", "2026-11-04 10:00", "2026-11-04 12:00", 70.0))    # bet e (another day): won
    monkeypatch.setattr(tr, "mark", lambda t, chain_fn=None: {"spot": None, "legs": [], "pnl": 40.0, "flags": [], "error": None, "pending": []})
    s = tr.overview(no_prices)["you"]["stats"]
    assert (s["closed"], s["open"], s["bets"], s["bets_open"], s["bet_wins"], s["bet_losses"]) == (4, 1, 4, 1, 2, 1)
    assert s["bet_win_rate"] == pytest.approx(2 / 3 * 100)
    assert s["net"] == pytest.approx(170.0) and s["open_pnl"] == pytest.approx(40.0)       # net: closed trades only


@pytest.mark.unit
def test_a_bet_with_one_trade_still_open_is_open_not_won_or_lost(store):
    store(row("a", "long_call", "2026-11-05 09:20", "2026-11-05 10:00", 900.0), row("b", "long_call", "2026-11-05 10:30"))
    s = tr.overview(no_prices)["you"]["stats"]
    assert (s["bets"], s["bets_open"], s["bet_wins"], s["bet_losses"], s["bet_win_rate"]) == (1, 1, 0, 0, None)
    assert s["net"] == pytest.approx(900.0)


@pytest.mark.unit
def test_the_bet_fields_are_read_time_only(store):
    store(row("a", "long_call", "2026-11-05 09:20"), row("b", "long_call", "2026-11-05 10:30", "2026-11-05 10:40", 5.0))
    tr.overview(no_prices)
    tr._save(tr._load())
    o = tr.overview(no_prices)                                                         # a save during overview too
    assert all(not ({"bet_id", "bet_index", "bet_size", "bet_started"} & set(t)) for t in tr._load())
    assert o["you"]["closed"][0]["bet_started"] == "2026-11-05 09:20"


@pytest.mark.unit
def test_grouping_reads_find_bet():
    import inspect
    assert "find_bet(" in inspect.getsource(tr._group_bets)
    assert "direction_of(" in inspect.getsource(tr._bet_side)

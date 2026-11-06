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


# ---------------------------------------------------------------- adding to a bet: you confirm, the AI adds and logs it

from tests.test_take_honest_entry import take as take_via_server, world  # noqa: E402,F401  (world is a fixture)
from tests.test_trade_record import RESULT  # noqa: E402


def events(world_tmp):
    log = tr.STORE.parent / "events.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


@pytest.mark.unit
def test_your_second_take_in_the_same_direction_asks_first_and_writes_nothing(world):
    first = take_via_server(world, 0)                                               # long call: bullish
    r = take_via_server(world, 1)                                                   # bull call spread: bullish too
    assert first.status_code == 200 and r.status_code == 409
    assert r.json()["detail"]["bet_id"] == first.json()["id"] and "bet" in r.json()["detail"]["message"]
    assert [t["id"] for t in tr._load()] == [first.json()["id"]]                    # no row, not even "not taken"


@pytest.mark.unit
def test_on_ok_the_trade_is_added_to_the_bet_tagged_and_logged(world):
    first = take_via_server(world, 0).json()
    r = take_via_server(world, 1, confirm=True)
    assert r.status_code == 200 and r.json()["added_to_bet"] == first["id"]
    assert f"override: added to bet {first['id']}" in events(world)
    o = tr.overview(lambda *a: (_ for _ in ()).throw(RuntimeError("no prices")))
    assert {t["id"]: t["bet_id"] for t in o["you"]["open"]} == {first["id"]: first["id"], r.json()["id"]: first["id"]}


@pytest.mark.unit
def test_the_opposite_direction_or_a_double_click_does_not_ask(world):
    tr.take(RESULT)                                                                 # bearish, already held
    first = take_via_server(world, 0)
    again = take_via_server(world, 0)                                               # the same trade twice: the same row
    assert first.status_code == again.status_code == 200 and again.json()["id"] == first.json()["id"]


@pytest.mark.unit
def test_the_ais_second_trade_in_the_same_direction_is_recorded_in_the_same_bet(world):
    st.save_run(world["run"] | {"run_id": "run2", "trades": world["run"]["trades"][::-1]})   # #1 is now the spread
    a = tr.record_ai_pick("run1")
    b = tr.record_ai_pick("run2")
    assert b["status"] == "open" and b["added_to_bet"] == a["id"] and "added_to_bet" not in a
    assert f"auto: added to bet {a['id']}" in events(world)


@pytest.mark.unit
def test_the_question_and_the_grouping_use_the_same_find_bet():
    import inspect
    assert "find_bet(" in inspect.getsource(tr.take) and "find_bet(" in inspect.getsource(tr._group_bets)
    assert "_bet_side" not in inspect.getsource(tr.take)                           # no second copy of the rule


# ---------------------------------------------------------------- the page: numbers per bet, the row tag, the calendar, the question

from tests.test_ui_regressions import closed_trade, record, render, stats as trade_stats, text, view  # noqa: E402

BET = {"bets": 1, "bets_open": 1, "bet_wins": 0, "bet_losses": 0, "bet_win_rate": None}


def two_trade_bet():
    """A bullish bet: started 4 Nov with a trade still open, a second trade added on 5 Nov and closed (+₹500)."""
    a = closed_trade(id="a", status="open", taken_at="2026-11-04 14:00", closed_at=None, net_pnl=None, live={"pnl": 120.0},
                     bet_id="a", bet_index=1, bet_size=2, bet_started="2026-11-04 14:00")
    b = closed_trade(id="b", taken_at="2026-11-05 09:15", closed_at="2026-11-05 10:00", net_pnl=500.0, added_to_bet="a",
                     bet_id="a", bet_index=2, bet_size=2, bet_started="2026-11-04 14:00")
    s = trade_stats(500, closed=1, wins=1, open_=1) | BET | {"open_pnl": 120.0}
    return record(you={"open": [a], "closed": [b], "stats": s})


@pytest.mark.unit
def test_the_numbers_show_trades_and_bets_won_lost_by_bet_and_open_apart():
    t = text(view(render("recordHtml(ARGS[0])", two_trade_bet()), "you"))
    assert "2 trades · 1 bet" in t and "1 bet open" in t
    assert "Won / lost (bets) 0 / 0" in t and "no bet closed yet" in t
    assert "Net P&L, closed ₹500 1 closed trade · open: ₹120 (not in net)" in t                 # the open P&L on its own line


@pytest.mark.unit
def test_each_trade_says_its_place_in_the_bet_and_an_added_trade_says_so():
    t = text(view(render("recordHtml(ARGS[0])", two_trade_bet()), "you"))
    assert "bet 1/2 · shuru 04 Nov 14:00" in t and "bet 2/2 · shuru 04 Nov 14:00" in t
    assert t.count("added to existing bet") == 1


@pytest.mark.unit
def test_the_calendar_counts_a_bet_on_its_first_day_and_says_where_the_pnl_shows():
    html = view(render("S.recMonth = { you: '2026-11' }; recordHtml(ARGS[0])", two_trade_bet()), "you")
    cells = {d: text(c) for d, c in __import__("re").findall(r'data-day="(2026-11-0[45])"(.*?)</button>', html, flags=__import__("re").S)}
    assert "1 bet" in cells["2026-11-04"] and "0 new bets" in cells["2026-11-05"]
    assert "P&L shows on the day each trade was taken" in cells["2026-11-05"] and "bet started 04 Nov" in cells["2026-11-05"]


TAKE = """(async () => {
  const sent = [];
  fetch = async (p, o) => { const b = JSON.parse(o.body); sent.push(b);
    return b.confirm ? { ok: true, status: 200, json: async () => ({ id: "t2" }) }
      : { ok: false, status: 409, json: async () => ({ detail: { message: "Is disha (bullish) ka ek NIFTY bet pehle se chal raha hai", bet_id: "t1" } }) }; };
  confirm = (m) => { sent.push("asked: " + m); return ANSWER; };
  S.strat.NIFTY = { result: { run_id: "r1", trades: [] } };
  const t = await takePost("NIFTY", 1);
  return JSON.stringify({ sent, t });
})()"""


@pytest.mark.unit
@pytest.mark.parametrize("answer", [True, False])
def test_a_409_asks_the_question_and_ok_sends_the_take_again_with_confirm(answer):
    out = __import__("json").loads(render(TAKE.replace("ANSWER", str(answer).lower())))
    assert out["sent"][0] == {"run_id": "r1", "candidate": 1}
    assert out["sent"][1] == "asked: Is disha (bullish) ka ek NIFTY bet pehle se chal raha hai"
    if answer:
        assert out["sent"][2] == {"run_id": "r1", "candidate": 1, "confirm": True} and out["t"] == {"id": "t2"}
    else:
        assert len(out["sent"]) == 2 and out["t"] is None                               # cancel: nothing sent, nothing recorded

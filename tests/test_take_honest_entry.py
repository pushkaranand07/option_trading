"""Take records an honest entry (audit step 1): the server prices it from a fresh chain at that moment, from a run of
today, inside the entry zone, with live two-sided quotes, while the market is open. The page sends only the run and
the candidate. Mocked chains and a fixed IST clock; no network."""

import inspect
from datetime import datetime

import pytest
import pytz
from fastapi import HTTPException

from tests.test_strategist import CHAIN, _q
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import option_chain as oc, server, signals, strategist as st, trade_record as tr

IST = pytz.timezone("Asia/Kolkata")
THU = (2026, 11, 5)                                  # a weekday; the calendar below has no holidays
EXPIRY = "27-Nov-2026"


def at(hour, minute, day=THU):
    return IST.localize(datetime(*day, hour, minute))


def chain(spot=22600, **quotes):
    """The test chain at ``spot``; ``quotes`` replaces a quote, e.g. ce22600=_q(...)."""
    rows = []
    for r in CHAIN["rows"]:
        k = int(r["strike"])
        rows.append(r | {"ce": quotes.get(f"ce{k}", r["ce"]), "pe": quotes.get(f"pe{k}", r["pe"])})
    return CHAIN | {"spot": spot, "expiry": EXPIRY, "rows": rows, "summary": {"atm_iv": 14.0, "resistance": 23000, "support": 22000}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(st, "_runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    clock = {"now": at(10, 0)}
    monkeypatch.setattr(signals, "now_ist", lambda: clock["now"])
    live = {"chain": chain()}

    def fetch(symbol, expiry):
        if isinstance(live["chain"], Exception):
            raise live["chain"]
        ch = live["chain"]                               # NSE stamps each chain; a test that sets none gets "now"
        return ch if "timestamp" in ch else ch | {"timestamp": clock["now"].strftime("%d-%b-%Y %H:%M:%S")}

    monkeypatch.setattr(oc, "chain", fetch)
    ctx = {"spot": 22600, "days_to_expiry": 22, "expected_move": {"day_pct": 0.01}, "option_chain": {"summary": chain()["summary"]}}
    cands = st.rank("NIFTY", built=(ctx, chain()), top=50)["candidates"]
    call = next(c for c in cands if c["plan"]["strategy"] == "long_call" and c["priced"]["legs"][0]["strike"] == 22600.0)
    spread = next(c for c in cands if c["plan"]["strategy"] == "bull_call_spread")
    run = {"symbol": "NIFTY", "expiry": EXPIRY, "spot": 22600, "lot": 65, "trades": [call, spread], "asked_at": "2026-11-05 09:58",
           "run_id": "run1", "day": "2026-11-05"}
    st.save_run(run)
    return {"clock": clock, "live": live, "run": run, "call": call}


class Resp:
    def __init__(self, status_code, body):
        self.status_code, self._body, self.text = status_code, body, str(body)

    def json(self):
        return self._body


def _call(fn, *args):
    """Call an endpoint function directly (the suite blocks sockets, which a test HTTP client needs on Windows).
    An async endpoint is driven by hand: it must finish without suspending."""
    try:
        out = fn(*args)
        if inspect.iscoroutine(out):
            try:
                out.send(None)
            except StopIteration as done:
                return Resp(200, done.value)
            raise RuntimeError("the endpoint suspended")
        return Resp(200, out)
    except HTTPException as exc:
        return Resp(exc.status_code, {"detail": exc.detail})


def take(w, candidate=0, run_id="run1", **extra):
    body = {"run_id": run_id, "candidate": candidate, **extra}
    if inspect.iscoroutinefunction(server.trade_take):          # the endpoint before this change read the raw request
        class Request:
            async def json(self):
                return body
        return _call(server.trade_take, Request())
    return _call(server.trade_take, body)


def latest():
    return _call(server.strategy_latest, "NIFTY").json()


@pytest.mark.unit
def test_the_entry_is_priced_from_a_fresh_chain_and_the_page_price_is_ignored(world):
    world["live"]["chain"] = chain(ce22600=_q(104, 103, 105))                  # the ask moved 101 -> 105 since the run
    r = take(world, priced={"legs": [{"action": "BUY", "type": "CE", "strike": 22600.0, "price": 1.0}]})   # a page lying
    assert r.status_code == 200, r.text
    leg = r.json()["legs"][0]
    assert leg["entry"] == 105 and leg["shown_price"] == 101                    # bought at the ask now; the run showed 101
    t = r.json()
    assert t["run_id"] == "run1" and t["candidate"] == 0 and t["spot_at_entry"] == 22600 and t["spot_at_run"] == 22600


@pytest.mark.unit
def test_a_sold_leg_is_priced_at_the_bid(world):
    k = int(next(x for x in world["run"]["trades"][1]["priced"]["legs"] if x["action"] == "SELL")["strike"])
    world["live"]["chain"] = chain(**{f"ce{k}": _q(27, 23, 28)})                 # the bid moved since the run
    r = take(world, candidate=1)
    assert r.status_code == 200, r.text
    sold = next(x for x in r.json()["legs"] if x["action"] == "SELL")
    assert sold["entry"] == 23 and sold["shown_price"] != 23


@pytest.mark.unit
@pytest.mark.parametrize(("hour", "minute"), [(9, 14), (15, 30), (15, 31)])
def test_take_is_refused_outside_the_session(world, hour, minute):
    world["clock"]["now"] = at(hour, minute)
    r = take(world)
    assert r.status_code == 400 and "Market band" in r.json()["detail"]


@pytest.mark.unit
def test_take_works_at_the_open(world):
    world["clock"]["now"] = at(9, 15)
    assert take(world).status_code == 200


@pytest.mark.unit
def test_a_run_from_another_day_cannot_be_taken_and_loads_as_expired(world):
    world["clock"]["now"] = at(10, 0, day=(2026, 11, 6))
    r = take(world)
    assert r.status_code == 400 and "expired" in r.json()["detail"].lower()
    got = latest()
    assert got["run_id"] == "run1" and got.get("expired") is True
    world["clock"]["now"] = at(10, 0)
    assert latest().get("expired") is False


@pytest.mark.unit
def test_a_saved_run_without_an_id_is_expired(world):
    st.save_run({"symbol": "NIFTY", "trades": [world["call"]], "asked_at": "2026-11-04 12:58"})    # saved before this change
    assert latest().get("expired") is True


@pytest.mark.unit
def test_spot_just_inside_the_entry_zone_is_taken_just_outside_is_refused(world):
    hi = world["call"]["plan"]["underlying_entry_high"]
    assert world["run"]["trades"][1]["plan"]["underlying_entry_high"] == hi     # same direction, same zone
    world["live"]["chain"] = chain(spot=hi)                                     # on the edge: inside
    assert take(world).status_code == 200
    world["live"]["chain"] = chain(spot=hi + 0.05)                              # a hair above: outside
    r = take(world, candidate=1)
    assert r.status_code == 400 and "entry zone" in r.json()["detail"]


@pytest.mark.unit
def test_spot_just_below_the_zone_is_refused(world):
    lo = world["call"]["plan"]["underlying_entry_low"]
    world["live"]["chain"] = chain(spot=lo - 0.05)
    r = take(world)
    assert r.status_code == 400 and "entry zone" in r.json()["detail"]


@pytest.mark.unit
def test_a_leg_with_a_zero_bid_is_refused(world):
    world["live"]["chain"] = chain(ce22600=_q(100, 0, 101))
    r = take(world)
    assert r.status_code == 400 and "bid / ask" in r.json()["detail"]
    assert not tr.STORE.exists() or tr.overview(lambda *a: chain())["stats"]["open"] == 0


@pytest.mark.unit
def test_a_failed_chain_fetch_refuses_and_never_uses_the_old_prices(world):
    world["live"]["chain"] = RuntimeError("NSE timed out")
    r = take(world)
    assert r.status_code == 400 and "NSE timed out" in r.json()["detail"]
    rows = tr._load()                                    # since step 3 a refused Take is kept, as not taken and with no entry
    assert [t["status"] for t in rows] == ["not_taken"] and "NSE timed out" in rows[0]["reason"]
    assert all("entry" not in leg for leg in rows[0]["legs"])


@pytest.mark.unit
def test_a_double_take_records_one_trade(world):
    a, b = take(world), take(world)
    assert a.status_code == 200 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert tr.overview(lambda *x: chain())["stats"]["open"] == 1


@pytest.mark.unit
def test_an_unknown_run_or_candidate_is_refused(world):
    r = take(world, run_id="nope")
    assert r.status_code == 400 and "not on file" in r.json()["detail"]
    r = take(world, candidate=7)
    assert r.status_code == 400 and "no trade #8" in r.json()["detail"]


APP = (__import__("pathlib").Path(server.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")


def _js(name):
    start = APP.index(name)
    return APP[start:APP.index("\n}\n", start)]


@pytest.mark.unit
def test_the_page_sends_only_the_run_and_the_candidate():
    for fn in ("async function takeRanked(", "async function takeTrade("):
        body = _js(fn)
        assert "body: takeBody(" in body and "JSON.stringify(c)" not in body and "JSON.stringify(res)" not in body, fn
    assert 'const takeBody = (sym, i) => JSON.stringify({ run_id: S.strat[sym]?.result?.run_id || null, candidate: i });' in APP


@pytest.mark.unit
def test_an_expired_run_is_read_only_on_the_page():
    ai = _js("function aiListHtml(")
    assert "res.expired ?" in ai and "res.market_closed || res.expired" in ai
    assert 'res.expired ? "run expired"' in _js("function renderStrat(") and "res._locked ?" in _js("function stratHtml(")

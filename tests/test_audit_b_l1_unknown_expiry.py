"""L1: an unknown ``expiry`` was silently replaced by another one. At the HTTP layer only, /api/chain, /api/rank and
/api/optionchain now answer 400 with the valid list when the expiry asked for isn't one of the symbol's expiries.
``option_chain.chain`` itself stays lenient (the forward test's build_context relies on that).

/api/chain and /api/rank check against ``option_chain.valid_expiries`` (NSE, from Track D); /api/optionchain is the
Dhan chain, whose expiries are Dhan's own list (``market_data.expiries``, the list its page offers), so it checks that."""

import pytest

from tests.test_audit_b_support import client, loopback  # noqa: F401  (fixtures)
from webapp import market_data as md, option_chain as oc, strategist

NSE_EXPIRIES = ["13-Nov-2026", "27-Nov-2026"]
DHAN_EXPIRIES = ["2026-11-13", "2026-11-27"]


@pytest.fixture
def world(monkeypatch):
    calls = {"chain": [], "rank": [], "dhan": [], "valid": []}
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})
    monkeypatch.setattr(oc, "valid_expiries", lambda s: calls["valid"].append(s) or list(NSE_EXPIRIES), raising=False)
    monkeypatch.setattr(oc, "chain", lambda s, e=None, **k: calls["chain"].append(e) or {"symbol": s, "expiry": e or NSE_EXPIRIES[0]})
    monkeypatch.setattr(strategist, "rank", lambda s, e=None, **k: calls["rank"].append(e) or {"symbol": s, "candidates": []})
    monkeypatch.setattr(md, "expiries", lambda s: list(DHAN_EXPIRIES))
    monkeypatch.setattr(md, "option_chain", lambda s, e=None: calls["dhan"].append(e) or {"symbol": s, "expiry": e, "spot": 0.0, "rows": []})
    return calls


@pytest.mark.unit
@pytest.mark.parametrize(("path", "kind", "valid"), [("/api/chain/NIFTY", "chain", NSE_EXPIRIES), ("/api/rank/NIFTY", "rank", NSE_EXPIRIES),
                                                     ("/api/optionchain/NIFTY", "dhan", DHAN_EXPIRIES)])
def test_an_unknown_expiry_is_400_with_the_valid_list(client, world, path, kind, valid):
    r = client.get(path, params={"expiry": "01-Jan-2030"})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["valid_expiries"] == valid and "01-Jan-2030" in detail["message"]
    assert world[kind] == []                                                 # nothing was fetched for another expiry


@pytest.mark.unit
@pytest.mark.parametrize(("path", "kind", "expiry"), [("/api/chain/NIFTY", "chain", "27-Nov-2026"), ("/api/rank/NIFTY", "rank", "27-Nov-2026"),
                                                      ("/api/optionchain/NIFTY", "dhan", "2026-11-27")])
def test_a_valid_expiry_is_passed_through(client, world, path, kind, expiry):
    r = client.get(path, params={"expiry": expiry})
    assert r.status_code == 200, r.text
    assert world[kind] == [expiry]


@pytest.mark.unit
@pytest.mark.parametrize(("path", "kind"), [("/api/chain/NIFTY", "chain"), ("/api/rank/NIFTY", "rank"), ("/api/optionchain/NIFTY", "dhan")])
def test_no_expiry_means_the_nearest_and_no_check(client, world, path, kind):
    assert client.get(path).status_code == 200
    assert world[kind] == [None] and world["valid"] == []


@pytest.mark.unit
def test_without_track_ds_valid_expiries_the_route_stays_lenient(client, world, monkeypatch):
    monkeypatch.delattr(oc, "valid_expiries", raising=False)
    assert client.get("/api/chain/NIFTY", params={"expiry": "01-Jan-2030"}).status_code == 200
    assert world["chain"] == ["01-Jan-2030"]

"""L4: every exception became a 502 carrying ``str(exc)``, so Python's own text reached the page ("int() argument must
be ... NoneType"). Now: bad input is 400/422 with our message; upstream data errors (DataError, ChainError, requests)
stay 502 with the app's message; anything else is 500 {"detail": "Internal error", "error_id"} with the traceback
logged under that id. The messages the page relies on are unchanged."""

import logging

import pytest
import requests

from tests import test_audit_b_support as support
from tests.test_audit_b_support import HEADER
from webapp import market_data as md, option_chain as oc, quant, strategist, trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures

SECRET = r"boom at C:\Users\someone\secret.py line 7"


def _internal(r, caplog):
    assert r.status_code == 500, r.text
    body = r.json()
    assert set(body) == {"detail", "error_id"} and body["detail"] == "Internal error"
    assert "boom" not in r.text and "secret" not in r.text
    logged = [rec for rec in caplog.records if body["error_id"] in rec.getMessage()]
    assert logged and logged[0].exc_info and "secret.py" in str(logged[0].exc_info[1])      # traceback logged under the id
    return body["error_id"]


@pytest.mark.unit
def test_an_empty_trade_body_gets_our_message_not_pythons(client):
    r = client.post("/api/trades", json={}, headers=HEADER)
    assert r.status_code in (400, 422), r.text
    assert "NoneType" not in r.text and "int()" not in r.text


@pytest.mark.unit
def test_an_unexpected_error_is_500_with_an_id_and_the_traceback_is_logged(client, monkeypatch, caplog):
    def broken(*a, **k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(quant, "risk", broken)
    with caplog.at_level(logging.ERROR):
        first = _internal(client.get("/api/risk/NIFTY"), caplog)
        second = _internal(client.get("/api/risk/NIFTY"), caplog)
    assert first != second and len(first) >= 6


@pytest.mark.unit
def test_an_unexpected_error_in_a_plain_endpoint_is_also_500_with_an_id(client, monkeypatch, caplog):
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})

    def broken(*a, **k):
        raise KeyError(SECRET)

    monkeypatch.setattr(strategist, "latest_run", broken)
    with caplog.at_level(logging.ERROR):
        _internal(client.get("/api/strategy/latest/NIFTY"), caplog)


@pytest.mark.unit
def test_an_unexpected_chain_error_is_no_longer_502_with_its_text(client, monkeypatch, caplog):
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})

    def broken(*a, **k):
        raise TypeError(SECRET)

    monkeypatch.setattr(oc, "chain", broken)
    monkeypatch.setattr(strategist, "rank", broken)
    with caplog.at_level(logging.ERROR):
        _internal(client.get("/api/chain/NIFTY"), caplog)
        _internal(client.get("/api/rank/NIFTY"), caplog)


@pytest.mark.unit
@pytest.mark.parametrize("error", [md.DataError("Yahoo has no data for XYZ."), requests.ConnectionError("NSE did not answer.")])
def test_upstream_data_errors_stay_502_with_the_apps_message(client, monkeypatch, error):
    def fail(*a, **k):
        raise error

    monkeypatch.setattr(quant, "spreads", fail)
    r = client.get("/api/spreads/NIFTY")
    assert r.status_code == 502 and r.json() == {"detail": str(error)}


@pytest.mark.unit
def test_a_chain_error_stays_404_with_its_message(client, monkeypatch):
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})

    def fail(*a, **k):
        raise oc.ChainError("NSE has no option chain for XYZ.")

    monkeypatch.setattr(oc, "chain", fail)
    r = client.get("/api/chain/XYZ")
    assert r.status_code == 404 and r.json() == {"detail": "NSE has no option chain for XYZ."}


@pytest.mark.unit
def test_the_pages_messages_are_kept(client, monkeypatch):
    assert client.get("/api/ai/nope").json() == {"detail": "Unknown job"}
    assert client.get("/api/strategy/nope").json() == {"detail": "Unknown job"}
    r = client.get("/api/morning", params={"date": "09-11-2026"})
    assert r.status_code == 400 and r.json() == {"detail": "date must be YYYY-MM-DD"}

    def unknown(trade_id):
        raise tr.TradeError("Unknown trade.")

    monkeypatch.setattr(tr, "delete", unknown)
    r = client.delete("/api/trades/nope", headers=HEADER)
    assert r.status_code == 404 and r.json() == {"detail": "Unknown trade."}
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": "NIFTY", "has_options": True})
    r = client.get("/api/expiries/NIFTY")
    assert r.status_code == 502 and "needs Dhan" in r.json()["detail"]


@pytest.mark.unit
def test_a_refused_take_keeps_not_taken(client, monkeypatch):
    def refuse(run_id, candidate, confirm=False):
        raise tr.TradeError("This run is not on file: run the analysis again.")

    monkeypatch.setattr(tr, "take_from_run", refuse)
    monkeypatch.setattr(tr, "record_refused", lambda *a, **k: None)
    r = client.post("/api/trades", json={"run_id": "x", "candidate": 0}, headers=HEADER)
    assert r.status_code == 400 and r.json() == {"detail": "Not taken: This run is not on file: run the analysis again."}

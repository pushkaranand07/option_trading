"""Track A's ``trade_record.StoreCorrupt`` (a TradeError raised on writes when the store is corrupt) is a 503 with a
clear message on every route that writes trades, not a 400 'Not taken' / 404, and a refused take is not recorded
(that would be another write to the corrupt store)."""

import pytest

from tests import test_audit_b_support as support
from tests.test_audit_b_support import HEADER
from webapp import trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures

WHY = "trades.json could not be read (line 3): fix or restore it; nothing was written."


@pytest.fixture
def corrupt(monkeypatch):
    class StoreCorrupt(tr.TradeError):
        pass

    def fail(*a, **k):
        raise StoreCorrupt(WHY)

    refused = []
    monkeypatch.setattr(tr, "StoreCorrupt", StoreCorrupt, raising=False)
    for name in ("take_from_run", "close", "delete"):
        monkeypatch.setattr(tr, name, fail)
    monkeypatch.setattr(tr, "record_refused", lambda *a, **k: refused.append(a))
    return refused


@pytest.mark.unit
@pytest.mark.parametrize(("method", "path", "body"), [("post", "/api/trades", {"run_id": "r1", "candidate": 0}),
                                                      ("post", "/api/trades/t1/close", None), ("delete", "/api/trades/t1", None)])
def test_a_corrupt_store_is_503_with_its_message(client, corrupt, method, path, body):
    kw = {"headers": HEADER} | ({"json": body} if body is not None else {})
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 503, r.text
    assert WHY in r.json()["detail"] and "Not taken" not in r.json()["detail"]
    assert corrupt == []                                                     # nothing else written to the store


@pytest.mark.unit
def test_a_refused_take_whose_record_hits_a_corrupt_store_is_503(client, corrupt, monkeypatch):
    def refuse(*a, **k):
        raise tr.TradeError("outside the entry zone: not taken.")

    def record(*a, **k):
        raise tr.StoreCorrupt(WHY)

    monkeypatch.setattr(tr, "take_from_run", refuse)
    monkeypatch.setattr(tr, "record_refused", record)
    r = client.post("/api/trades", json={"run_id": "r1", "candidate": 0}, headers=HEADER)
    assert r.status_code == 503 and WHY in r.json()["detail"]

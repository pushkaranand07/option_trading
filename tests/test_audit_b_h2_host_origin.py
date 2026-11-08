"""H2: DNS rebinding and CSRF. Only Host 127.0.0.1 / localhost is served; every request that can change something
(not GET / HEAD / OPTIONS) needs the header ``X-Pulse-Request: 1`` and, when the browser names an Origin (or a
Referer), it must be http://127.0.0.1:<port> or http://localhost:<port>."""

import pytest

from tests.test_audit_b_support import HEADER, SAME_ORIGIN, client, loopback  # noqa: F401  (fixtures)
from webapp import trade_record as tr


@pytest.fixture
def fake_trades(monkeypatch):
    closed = []
    monkeypatch.setattr(tr, "overview", lambda *a, **k: {"you": {}, "ai": {}})
    monkeypatch.setattr(tr, "close", lambda trade_id: closed.append(trade_id) or {"id": trade_id, "status": "closed"})
    return closed


@pytest.mark.unit
def test_a_foreign_host_is_refused(client, fake_trades):
    r = client.get("/api/trades", headers={"Host": "attacker.example"})
    assert r.status_code == 400, r.text


@pytest.mark.unit
@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8794"])
def test_the_local_host_is_served(client, fake_trades, host):
    assert client.get("/api/trades", headers={"Host": host}).status_code == 200


@pytest.mark.unit
def test_a_cross_site_post_is_refused_even_with_the_header(client, fake_trades):
    r = client.post("/api/trades/t1/close", headers=HEADER | {"Origin": "http://evil.example"})
    assert r.status_code == 403, r.text
    assert fake_trades == []                                                  # the handler never ran


@pytest.mark.unit
def test_a_cross_site_referer_is_refused_when_there_is_no_origin(client, fake_trades):
    r = client.post("/api/trades/t1/close", headers=HEADER | {"Referer": "http://evil.example/page"})
    assert r.status_code == 403 and fake_trades == []


@pytest.mark.unit
@pytest.mark.parametrize("origin", ["http://127.0.0.1.evil.example", "https://127.0.0.1:8000", "http://localhost.evil:80", "null"])
def test_look_alike_origins_are_refused(client, fake_trades, origin):
    assert client.post("/api/trades/t1/close", headers=HEADER | {"Origin": origin}).status_code == 403
    assert fake_trades == []


@pytest.mark.unit
def test_a_post_without_the_header_is_refused(client, fake_trades):
    r = client.post("/api/trades/t1/close", headers=SAME_ORIGIN)
    assert r.status_code == 403, r.text
    assert fake_trades == []


@pytest.mark.unit
def test_a_delete_without_the_header_is_refused(client, monkeypatch):
    deleted = []
    monkeypatch.setattr(tr, "delete", deleted.append)
    assert client.delete("/api/trades/t1").status_code == 403 and deleted == []


@pytest.mark.unit
@pytest.mark.parametrize("origin", [SAME_ORIGIN, {"Origin": "http://localhost:8794"}, {"Referer": "http://127.0.0.1:8000/"}, {}])
def test_a_same_origin_post_with_the_header_reaches_the_handler(client, fake_trades, origin):
    r = client.post("/api/trades/t1/close", headers=HEADER | origin)
    assert r.status_code == 200, r.text
    assert fake_trades == ["t1"]


@pytest.mark.unit
def test_get_needs_no_header(client, fake_trades):
    assert client.get("/api/trades").status_code == 200

"""NSE client: survives NSE's bot protection, throttling and outages (problem P-01)."""

import json

import pytest

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors.nse.client import NSEClient, NSEDataNotPublishedError


class FakeResponse:
    def __init__(self, status=200, body=b"{}", content_type="application/json", headers=None):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = {"content-type": content_type, **(headers or {})}

    def json(self):
        return json.loads(self.content)


class FakeCookies(dict):
    def clear(self):
        super().clear()


class FakeSession:
    """Scripted answers per URL fragment; pages set a cookie when they answer 200."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.headers = {}
        self.cookies = FakeCookies()
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        for fragment, answers in self.script.items():
            if fragment in url:
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(answer, Exception):
                    raise answer
                if "/api/" not in url and answer.status_code == 200:
                    self.cookies["nsit"] = "x"
                return answer
        return FakeResponse(404, b"", "text/html")


def make_client(tmp_path, script, **kw):
    sleeps = []
    clock = iter(range(0, 10_000))
    client = NSEClient(FakeSession(script), cache_dir=tmp_path, sleep=sleeps.append,
                       clock=lambda: next(clock), min_interval=0, **kw)
    return client, sleeps


@pytest.mark.unit
def test_bootstraps_cookies_from_a_page_that_is_not_blocked(tmp_path):
    client, _ = make_client(tmp_path, {
        "/option-chain": [FakeResponse(200, b"<html>", "text/html")],
        "/api/data": [FakeResponse(200, {"ok": 1})],
    })
    assert client.get_json("/api/data").data == {"ok": 1}
    assert any("/option-chain" in c for c in client._session.calls)


@pytest.mark.unit
def test_a_403_triggers_a_fresh_session_and_a_retry(tmp_path):
    client, _ = make_client(tmp_path, {
        "/option-chain": [FakeResponse(200, b"<html>", "text/html")],
        "/api/data": [FakeResponse(403, b"denied", "text/html"), FakeResponse(200, {"ok": 2})],
    })
    assert client.get_json("/api/data").data == {"ok": 2}
    pages = [c for c in client._session.calls if c.endswith("/option-chain")]
    assert len(pages) == 2      # initial bootstrap + re-bootstrap after the 403


@pytest.mark.unit
def test_an_html_page_served_as_200_is_treated_as_a_block(tmp_path):
    client, _ = make_client(tmp_path, {
        "/option-chain": [FakeResponse(200, b"<html>", "text/html")],
        "/api/data": [FakeResponse(200, b"<!DOCTYPE html><p>blocked", "text/html"), FakeResponse(200, {"ok": 3})],
    })
    assert client.get_json("/api/data").data == {"ok": 3}


@pytest.mark.unit
def test_throttling_backs_off_honouring_retry_after(tmp_path):
    client, sleeps = make_client(tmp_path, {
        "/option-chain": [FakeResponse(200, b"<html>", "text/html")],
        "/api/data": [FakeResponse(429, b"", headers={"Retry-After": "7"}), FakeResponse(200, {"ok": 4})],
    })
    assert client.get_json("/api/data").data == {"ok": 4}
    assert 7.0 in sleeps


@pytest.mark.unit
def test_404_means_not_published_not_an_outage(tmp_path):
    client, _ = make_client(tmp_path, {"/content/fo/x.zip": [FakeResponse(404, b"", "text/html")]})
    with pytest.raises(NSEDataNotPublishedError):
        client.get_archive("/content/fo/x.zip")
    assert not client.breaker_open


@pytest.mark.unit
def test_breaker_opens_after_repeated_failures_and_fails_fast(tmp_path):
    client, _ = make_client(tmp_path, {
        "/option-chain": [FakeResponse(200, b"<html>", "text/html")],
        "/api/data": [FakeResponse(503, b"")],
    }, breaker_threshold=2, max_attempts=1, breaker_cooldown=10_000)
    for _ in range(2):
        with pytest.raises(VendorUnavailableError):
            client.get_json("/api/data", ttl=0)
    assert client.breaker_open
    calls_before = len(client._session.calls)
    with pytest.raises(VendorUnavailableError, match="cooldown"):
        client.get_json("/api/data", ttl=0)
    assert len(client._session.calls) == calls_before     # no request while open


@pytest.mark.unit
def test_outage_serves_the_cached_answer_marked_stale(tmp_path):
    ok = {"/option-chain": [FakeResponse(200, b"<html>", "text/html")], "/api/data": [FakeResponse(200, {"v": 1})]}
    client, _ = make_client(tmp_path, ok)
    assert client.get_json("/api/data").stale is False

    down = {"/option-chain": [FakeResponse(503, b"")], "/api/data": [FakeResponse(503, b"")]}
    client2, _ = make_client(tmp_path, down, max_attempts=1)
    fetched = client2.get_json("/api/data", ttl=0)
    assert fetched.stale is True and fetched.data == {"v": 1}
    assert "STALE" in fetched.provenance()


@pytest.mark.unit
def test_archives_are_cached_forever_without_refetching(tmp_path):
    client, _ = make_client(tmp_path, {"/content/a.csv": [FakeResponse(200, b"a,b\n1,2", "text/csv")]})
    first = client.get_archive("/content/a.csv")
    calls = len(client._session.calls)
    second = client.get_archive("/content/a.csv")
    assert first.data == second.data == b"a,b\n1,2"
    assert len(client._session.calls) == calls

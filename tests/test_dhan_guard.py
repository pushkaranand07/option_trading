"""Dhan guard (audit 2026-11, step 1.2a): every Dhan call goes through webapp/dhan_guard.py, which allows only
public market-data endpoints (quotes/LTP/OHLC, intraday and historical charts, option chain, expiry list, the
security master). Any account endpoint (orders, positions, holdings, funds, trade book, ledger, kill switch, super /
forever orders, profile, eDIS) raises DhanAccountAccessBlocked before a request is made, unless
DHAN_ACCOUNT_ACCESS=1. Each call is logged (no secrets) and Dhan is called at most once a second."""

import pytest

from webapp import dhan_guard as g, market_data as md

ACCOUNT = [("POST", "/orders"), ("GET", "/orders"), ("PUT", "/orders/123"), ("DELETE", "/orders/123"), ("GET", "/orders/123"),
           ("GET", "/trades"), ("GET", "/trades/2026-11-01/2026-11-08/0"), ("GET", "/positions"), ("POST", "/positions/convert"),
           ("GET", "/holdings"), ("GET", "/fundlimit"), ("POST", "/margincalculator"), ("GET", "/ledger"), ("POST", "/killswitch"),
           ("POST", "/super/orders"), ("GET", "/forever/orders"), ("POST", "/forever/orders"), ("GET", "/profile"),
           ("POST", "/edis/tpin"), ("GET", "/edis/inquire/ALL"), ("POST", "/marketfeed/../orders"),
           ("GET", "https://api.dhan.co/v2/positions"), ("GET", "https://evil.example/marketfeed/ltp")]
MARKET = [("POST", "/marketfeed/ltp"), ("POST", "/marketfeed/ohlc"), ("POST", "/marketfeed/quote"), ("POST", "/charts/intraday"),
          ("POST", "/charts/historical"), ("POST", "/optionchain"), ("POST", "/optionchain/expirylist"),
          ("GET", "https://images.dhan.co/api-data/api-scrip-master.csv"), ("GET", "https://images.dhan.co/api-data/api-scrip-master-detailed.csv")]


class FakeResponse:
    status_code = 200
    content = b"x"
    text = "{}"

    def json(self):
        return {"data": {}}

    def raise_for_status(self):
        return None


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Requests that actually left the guard (none should for account paths); no sleeping; the log in tmp."""
    calls = []
    monkeypatch.setattr(g.requests, "request", lambda method, url, **kw: calls.append((method, url, kw)) or FakeResponse())
    monkeypatch.setattr(g, "LOG", tmp_path / "dhan_calls.log")
    monkeypatch.setattr(g, "_sleep", lambda s: None)
    monkeypatch.delenv("DHAN_ACCOUNT_ACCESS", raising=False)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize(("method", "path"), ACCOUNT)
def test_every_account_endpoint_is_blocked_before_any_request(sent, method, path):
    with pytest.raises(g.DhanAccountAccessBlocked):
        g.request(method, path, token="secret-token", client_id="1100")
    assert sent == []


@pytest.mark.unit
@pytest.mark.parametrize(("method", "path"), MARKET)
def test_every_market_data_endpoint_is_allowed_and_logged_without_secrets(sent, method, path):
    g.request(method, path, token="secret-token", client_id="1100", json={"x": 1})
    assert len(sent) == 1 and sent[0][0] == method and sent[0][1].endswith(path.split("dhan.co")[-1].replace("/api-data", "/api-data"))
    log = g.LOG.read_text(encoding="utf-8")
    assert path.split("?")[0].rsplit("/", 1)[-1] in log and "secret-token" not in log and "1100" not in log


@pytest.mark.unit
def test_the_escape_hatch_needs_the_explicit_switch(sent, monkeypatch):
    monkeypatch.setenv("DHAN_ACCOUNT_ACCESS", "1")
    g.request("GET", "/positions", token="t", client_id="c")
    assert len(sent) == 1


@pytest.mark.unit
def test_calls_are_spaced_at_least_one_second_apart(sent, monkeypatch):
    waits, clock = [], {"t": 100.0}
    monkeypatch.setattr(g, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(g, "_sleep", lambda s: waits.append(s) or clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(g, "_last", 0.0)
    for _ in range(3):
        g.request("POST", "/marketfeed/ltp", token="t", client_id="c")
    assert len(sent) == 3 and len(waits) == 2 and all(w >= 1.0 for w in waits)


@pytest.mark.unit
def test_market_data_module_calls_dhan_only_through_the_guard(sent, monkeypatch):
    monkeypatch.setattr(md.dhan, "client_id", "1100")
    monkeypatch.setattr(md.dhan, "token", "secret-token")
    md.dhan.post("/optionchain/expirylist", {"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I"})
    assert sent and sent[-1][1] == md.DHAN_BASE + "/optionchain/expirylist"
    with pytest.raises(g.DhanAccountAccessBlocked):
        md.dhan.post("/orders", {"transactionType": "BUY"})
    assert len(sent) == 1
    assert not hasattr(md, "dhan_profile")                     # the dead account call is gone


@pytest.mark.unit
def test_no_module_calls_api_dhan_co_except_through_the_guard():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = []
    for p in [*root.glob("webapp/*.py"), *root.glob("scripts/*.py"), *root.rglob("tradingagents/**/*.py")]:
        if p.name == "dhan_guard.py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"requests\.(get|post|put|delete|request)\([^)]*(DHAN_BASE|SCRIP_MASTER_URL|dhan\.co)", text):
            hits.append(p.name)
    assert hits == []

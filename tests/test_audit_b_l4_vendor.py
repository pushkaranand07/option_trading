"""L4 follow-up: the package's vendor errors (tradingagents.dataflows.errors.VendorError and its subclasses, e.g.
"NSE request failed after retries ...") are upstream data errors with app-written messages: 502 with that message,
not 500 "Internal error"."""

import pytest

from tests import test_audit_b_support as support
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from webapp import market_data as md, option_chain as oc, quant, strategist

client, loopback = support.client, support.loopback          # the shared fixtures

NSE_DOWN = VendorUnavailableError("NSE request failed after retries (HTTP 403): https://www.nseindia.com/api/x")


def _raise(error):
    def fail(*a, **k):
        raise error
    return fail


@pytest.fixture
def nse_down(monkeypatch):
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper()})
    for target, name in ((oc, "chain"), (oc, "contract"), (strategist, "rank"), (quant, "risk"), (quant, "spreads")):
        monkeypatch.setattr(target, name, _raise(NSE_DOWN))
    monkeypatch.delattr(oc, "valid_expiries", raising=False)


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/api/chain/NIFTY", "/api/chain/NOTASYMBOL", "/api/rank/NIFTY", "/api/contract?id=x",
                                  "/api/risk/NIFTY", "/api/spreads/NIFTY"])
def test_a_vendor_error_is_502_with_its_message(client, nse_down, path):
    r = client.get(path)
    assert r.status_code == 502, r.text
    assert r.json() == {"detail": str(NSE_DOWN)}                                  # its message, no error_id


@pytest.mark.unit
def test_no_market_data_is_502_too(client, monkeypatch):
    monkeypatch.setattr(md, "candles", _raise(NoMarketDataError("XYZ", detail="Yahoo returned nothing")))
    r = client.get("/api/candles/XYZ")
    assert r.status_code == 502 and "No market data for 'XYZ'" in r.json()["detail"] and "error_id" not in r.json()

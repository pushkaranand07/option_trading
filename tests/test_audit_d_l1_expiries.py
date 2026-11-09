"""Audit L1 (support for Track B): a list of valid expiries, and an opt-in strict mode that refuses an unknown expiry
instead of silently pricing the nearest one. The default (unknown expiry -> nearest) must stay exactly as it is:
the v3 forward test depends on it. No network: a fake NSE client and a fake Dhan."""

import pytest

from webapp import market_data as md, option_chain as oc

EXPS = ["17-Nov-2026", "24-Nov-2026", "29-Dec-2026"]
RAW = {"records": {"underlyingValue": 25000.0, "timestamp": "09-Nov-2026 10:00:00", "data": [
    {"strikePrice": 24500 + 50 * i, "CE": {"lastPrice": 10, "openInterest": 5}, "PE": {"lastPrice": 10, "openInterest": 5}}
    for i in range(21)]}}


class Client:
    def __init__(self, exps=EXPS, fail=False):
        self.exps, self.fail, self.calls = exps, fail, []

    def get_json(self, path, params=None, ttl=None):
        self.calls.append((path, dict(params or {})))
        if self.fail:
            raise OSError("NSE unreachable")
        data = {"expiryDates": self.exps} if path == oc.CONTRACT_INFO else RAW
        return type("F", (), {"data": data})()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "index_lots", lambda: {})
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())


@pytest.mark.unit
def test_default_unknown_expiry_still_uses_the_nearest():
    for fn in (oc.chain, oc.full_chain):
        got = fn("NIFTY", "01-Jan-2020", lot=65, client=Client())
        assert got["expiry"] == "17-Nov-2026"                 # unchanged default behaviour
        assert fn("NIFTY", None, lot=65, client=Client())["expiry"] == "17-Nov-2026"
        assert fn("NIFTY", "24-Nov-2026", lot=65, client=Client())["expiry"] == "24-Nov-2026"


@pytest.mark.unit
def test_strict_refuses_an_unknown_expiry_and_names_the_valid_ones():
    for fn in (oc.chain, oc.full_chain):
        with pytest.raises(oc.ChainError, match=r"unknown expiry 01-Jan-2020; valid: .*17-Nov-2026"):
            fn("NIFTY", "01-Jan-2020", lot=65, client=Client(), strict=True)
        assert fn("NIFTY", "24-Nov-2026", lot=65, client=Client(), strict=True)["expiry"] == "24-Nov-2026"
        assert fn("NIFTY", None, lot=65, client=Client(), strict=True)["expiry"] == "17-Nov-2026"


@pytest.mark.unit
def test_valid_expiries_is_nses_list_and_never_raises(monkeypatch):
    monkeypatch.setattr(oc, "_client", lambda: Client())
    assert oc.valid_expiries("NIFTY") == EXPS
    monkeypatch.setattr(oc, "_client", lambda: Client(fail=True))
    assert oc.valid_expiries("NIFTY") == []                    # nothing available: empty, not an error
    monkeypatch.setattr(oc, "_client", lambda: Client(exps=[]))
    assert oc.valid_expiries("SENSEX") == []


@pytest.mark.unit
def test_valid_expiries_falls_back_to_dhans_list_when_nse_is_down(monkeypatch):
    calls = []
    monkeypatch.setattr(md, "dhan", type("D", (), {"enabled": True})())

    def dhan_expiries(symbol):
        calls.append(symbol)
        return ["2026-11-17", "2026-11-24"]

    monkeypatch.setattr(md, "expiries", dhan_expiries)
    monkeypatch.setattr(oc, "_client", lambda: Client(fail=True))
    assert oc.valid_expiries("NIFTY") == ["17-Nov-2026", "24-Nov-2026"]       # in NSE's spelling
    monkeypatch.setattr(oc, "_client", lambda: Client())
    assert oc.valid_expiries("NIFTY") == EXPS                                  # NSE's list wins when it has one
    assert calls == ["NIFTY"]                                                  # Dhan's list is cached for the day

    def broken(symbol):
        raise md.DataError("Dhan down")

    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "expiries", broken)
    monkeypatch.setattr(oc, "_client", lambda: Client(fail=True))
    assert oc.valid_expiries("NIFTY") == []


@pytest.mark.unit
def test_dhan_option_chain_strict_is_opt_in(monkeypatch):
    posts = []

    class D:
        enabled = True

        def post(self, path, body):
            posts.append((path, body))
            if path == "/optionchain/expirylist":
                return {"data": ["2026-11-17", "2026-11-24"]}
            return {"data": {"last_price": 25000, "oc": {"25000.0": {"ce": {"last_price": 10}, "pe": {"last_price": 9}}}}}

    monkeypatch.setattr(md, "dhan", D())
    assert md.option_chain("NIFTY", "2026-01-01")["expiry"] == "2026-01-01"    # default: passed through as today
    with pytest.raises(md.DataError, match=r"unknown expiry 2026-01-01; valid: .*2026-11-17"):
        md.option_chain("NIFTY", "2026-01-01", strict=True)
    assert md.option_chain("NIFTY", "2026-11-24", strict=True)["expiry"] == "2026-11-24"
    assert md.option_chain("NIFTY", strict=True)["expiry"] == "2026-11-17"

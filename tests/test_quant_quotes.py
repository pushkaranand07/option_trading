"""Daily option bid/ask snapshot: capture, dedup by NSE's timestamp, parsing, real-vs-model spreads."""

from datetime import date
from types import SimpleNamespace

import pytest

from tradingagents.analytics import quotes


def chain_json(stamp="23-Oct-2026 15:40:00", spot=100.0):
    def leg(typ, k, bid, ask):
        return {"buyPrice1": bid, "sellPrice1": ask, "buyQuantity1": 500, "sellQuantity1": 500, "lastPrice": ask,
                "impliedVolatility": 30, "totalTradedVolume": 10, "openInterest": 100, "expiryDate": "24-11-2026",
                "strikePrice": k, "underlyingValue": spot}
    data = [{"strikePrice": 100, "CE": leg("CE", 100, 4.80, 5.20), "PE": leg("PE", 100, 3.90, 4.10)},
            {"strikePrice": 150, "CE": leg("CE", 150, 0, 0.10)}]           # no bid: dropped
    return {"records": {"timestamp": stamp, "underlyingValue": spot, "data": data}}


class FakeClient:
    def __init__(self, stamp="23-Oct-2026 15:40:00", broken=()):
        self.stamp, self.broken, self.calls = stamp, set(broken), []

    def get_json(self, path, params, ttl=None):
        self.calls.append((path, dict(params)))
        if params["symbol"] in self.broken:
            raise RuntimeError("NSE said no")
        if path == quotes.CONTRACT_INFO:
            return SimpleNamespace(data={"expiryDates": ["24-Nov-2026", "29-Dec-2026", "26-Jan-2027", "23-Feb-2027"]})
        return SimpleNamespace(data=chain_json(self.stamp))


@pytest.mark.unit
def test_capture_saves_by_nse_snapshot_date_and_skips_a_repeat(tmp_path):
    counts = quotes.capture(["RELIANCE", "NIFTY"], FakeClient(), tmp_path, expiries=2)
    assert counts == {"saved": 4, "already": 0, "failed": 0}
    files = sorted(p.name for p in (tmp_path / "option_quotes" / "2026-10-23").iterdir())
    assert files == ["NIFTY_2026-11-24.json", "NIFTY_2026-12-29.json",
                     "RELIANCE_2026-11-24.json", "RELIANCE_2026-12-29.json"]
    # A weekend run gets the same Friday book from NSE: nothing new is written.
    again = quotes.capture(["RELIANCE", "NIFTY"], FakeClient(), tmp_path, expiries=2)
    assert again == {"saved": 0, "already": 4, "failed": 0}


@pytest.mark.unit
def test_index_chains_are_requested_as_indices_and_one_failure_keeps_the_rest(tmp_path):
    client = FakeClient(broken=["TCS"])
    counts = quotes.capture(["TCS", "NIFTY", "INFY"], client, tmp_path, expiries=1)
    assert counts == {"saved": 2, "already": 0, "failed": 1}
    kinds = {p["symbol"]: p["type"] for path, p in client.calls if path == quotes.CHAIN}
    assert kinds == {"NIFTY": "Indices", "INFY": "Equity"}


@pytest.mark.unit
def test_parse_and_compare_with_the_slippage_model(tmp_path):
    quotes.capture(["X"], FakeClient(), tmp_path, expiries=1)
    q = quotes.load(tmp_path)
    assert len(q) == 2                                   # the strike with no bid is dropped
    ce = q[q["option_type"] == "CE"].iloc[0]
    assert (ce["trade_date"], ce["expiry"]) == (date(2026, 10, 23), date(2026, 11, 24))
    assert ce["mid"] == pytest.approx(5.0) and ce["half_spread"] == pytest.approx(0.20)
    v = quotes.versus_model(q)
    # Model: 0.05 + 1% of mid -> CE 0.10 (real 0.20, ratio 2.0), PE 0.09 (real 0.10, ratio ~1.11).
    assert v["real_vs_model"].iloc[0] == pytest.approx((2.0 + 0.10 / 0.09) / 2)

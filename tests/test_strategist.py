"""AI strategist: the code, not the LLM, enforces defined risk, prices at bid / ask and sizes to the user's limit;
and the NSE option chain is shaped correctly (units, PCR, walls near the money, max pain)."""

import pytest

from webapp import option_chain as oc, strategist as st


def _q(ltp, bid, ask, oi=1000):
    return {"ltp": ltp, "bid": bid, "ask": ask, "oi": oi, "iv": 14.0, "chg_oi": 0, "chg": 0, "volume": 0}


CHAIN = {"spot": 22600, "atm": 22600.0, "lot": 65, "expiry": "27-Oct-2026", "summary": {}, "rows": [
    {"strike": 22400.0, "ce": _q(230, 228, 232), "pe": _q(30, 29, 31), "pcr": 1.0},
    {"strike": 22500.0, "ce": _q(160, 158, 162), "pe": _q(55, 54, 56), "pcr": 1.0},
    {"strike": 22600.0, "ce": _q(100, 99, 101), "pe": _q(95, 94, 96), "pcr": 1.0},
    {"strike": 22700.0, "ce": _q(55, 54, 56), "pe": _q(150, 148, 152), "pcr": 1.0},
    {"strike": 22800.0, "ce": _q(25, 24, 26), "pe": _q(220, 218, 222), "pcr": 1.0},
]}


def plan(strategy, legs, **kw):
    base = {"market_read": "x", "bias": "bearish", "strategy": strategy, "buy_or_sell_reasoning": "x",
            "strike_reasoning": "x", "exit_plan": "x", "confidence": "low",
            "legs": [st.Leg(action=a, option_type=t, strike=k) for a, t, k in legs]}
    return st.StrategyPlan(**(base | kw))


@pytest.mark.unit
def test_naked_or_malformed_structures_are_rejected():
    naked = plan("bear_call_spread", [("SELL", "CE", 22700), ("SELL", "CE", 22800)])
    assert any("protective" in p for p in st.check_structure(naked, CHAIN))
    wrong_way = plan("bull_call_spread", [("SELL", "CE", 22600), ("BUY", "CE", 22700)])
    assert st.check_structure(wrong_way, CHAIN)
    off_chain = plan("long_call", [("BUY", "CE", 23000)])
    assert "not on the option chain" in st.check_structure(off_chain, CHAIN)[0]
    condor = plan("iron_condor", [("BUY", "PE", 22400), ("SELL", "PE", 22500), ("SELL", "CE", 22700),
                                  ("BUY", "CE", 22800)])
    assert st.check_structure(condor, CHAIN) == [] and st.check_structure(plan("no_trade", []), CHAIN) == []


@pytest.mark.unit
def test_pricing_buys_at_the_ask_sells_at_the_bid():
    p = st.price(plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)]), CHAIN)
    assert p["net_per_unit"] == pytest.approx(54 - 26)                 # credit 28
    assert p["max_profit_per_lot"] == pytest.approx(28 * 65) and p["max_loss_per_lot"] == pytest.approx(72 * 65)
    assert p["breakevens"] == [pytest.approx(22728)]
    d = st.price(plan("bull_call_spread", [("BUY", "CE", 22600), ("SELL", "CE", 22700)], bias="bullish"), CHAIN)
    assert d["debit"] and d["max_loss_per_lot"] == pytest.approx((101 - 54) * 65)
    assert d["breakevens"] == [pytest.approx(22647)]
    lc = st.price(plan("long_put", [("BUY", "PE", 22600)]), CHAIN)
    assert lc["max_profit_per_lot"] is None and lc["breakevens"] == [pytest.approx(22600 - 96)]


@pytest.mark.unit
def test_sizing_keeps_the_worst_case_plus_charges_inside_the_limit():
    p = st.price(plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)]), CHAIN)   # 4,680 a lot
    s = st.size(p, risk_amount=10_000, allocation=None)
    assert s["lots"] == 2 and s["max_loss"] <= 10_000 and s["charges"] > 0
    assert st.size(p, risk_amount=10_000, allocation=5_000)["lots"] == 1          # the money set aside binds
    tight = st.size(p, risk_amount=4_700, allocation=None)                        # 4,680 + charges > 4,700
    assert tight["lots"] == 0 and "max loss" in tight["reason"]
    assert st.size(p, risk_amount=None, allocation=None)["lots"] is None


@pytest.mark.unit
def test_recommend_flags_poor_reward_and_never_sends_capital(monkeypatch):
    monkeypatch.setattr(st, "build_context", lambda symbol, expiry=None: ({"instrument": symbol}, CHAIN))
    seen = {}

    def fake_llm(ctx, risk_pct):
        seen.update(ctx=ctx, risk_pct=risk_pct)
        return plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)], underlying_entry_low=22620,
                    underlying_entry_high=22660, underlying_target=22450, underlying_stop=22720)

    out = st.recommend("NIFTY", 1.0, risk_amount=12_345, allocation=50_000, llm=fake_llm)
    assert "12345" not in str(seen) and seen["risk_pct"] == 1.0
    assert out["sizing"]["lots"] == 2 and any("break even" in w for w in out["warnings"])
    bad = st.recommend("NIFTY", 1.0, 10_000, None,
                       llm=lambda c, r: plan("bear_call_spread", [("SELL", "CE", 22700), ("SELL", "CE", 22800)]))
    assert bad["rejected"] and bad["priced"] is None


RAW = {"records": {"underlyingValue": 22610, "timestamp": "23-Oct-2026 15:30:00", "data": [
    {"strikePrice": k, "CE": {"openInterest": ce, "lastPrice": 1, "impliedVolatility": 14},
     "PE": {"openInterest": pe, "lastPrice": 1, "impliedVolatility": 16}}
    for k, ce, pe in [(22000, 10, 900), (22500, 50, 300), (22600, 100, 100), (22700, 400, 20), (23500, 2000, 1)]]}}


@pytest.mark.unit
def test_chain_shape_units_pcr_walls_and_max_pain():
    c = oc.shape(RAW, lot=65, strikes_each_side=2)
    assert c["atm"] == 22600 and [r["strike"] for r in c["rows"]] == [22000, 22500, 22600, 22700, 23500]
    assert c["rows"][2]["ce"]["oi"] == 100 * 65 and c["rows"][0]["pcr"] == pytest.approx(90)
    s = c["summary"]
    assert s["resistance"] == 23500 and s["support"] == 22000 and s["atm_iv"] == pytest.approx(15)
    near = oc.shape(RAW, lot=65, strikes_each_side=1)          # walls are taken from the strikes shown
    assert near["summary"]["resistance"] == 22700 and near["summary"]["support"] == 22500
    assert oc.max_pain(c["rows"]) == 22600

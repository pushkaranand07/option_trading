"""AI strategist: the code, not the LLM, enforces defined risk and prices per lot at the bid / ask;
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
def test_charges_cover_every_leg_in_and_out():
    p = st.price(plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)]), CHAIN)
    one = st.charges(p, 1)
    assert one > 4 * 20                                   # four orders (2 legs, in and out), ₹20 brokerage each
    assert st.charges(p, 2) < 2 * one                     # the flat brokerage does not double


@pytest.mark.unit
def test_recommend_prices_per_lot_flags_poor_reward_and_refuses_naked_sells(monkeypatch):
    monkeypatch.setattr(st, "build_context", lambda symbol, expiry=None: ({"instrument": symbol}, CHAIN))

    def fake_llm(ctx):
        return plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)], underlying_entry_low=22620,
                    underlying_entry_high=22660, underlying_target=22450, underlying_stop=22720)

    out = st.recommend("NIFTY", llm=fake_llm)
    assert out["priced"]["max_loss_per_lot"] == pytest.approx(72 * 65) and out["charges_per_lot"] > 0
    assert any("break even" in w for w in out["warnings"])
    bad = st.recommend("NIFTY", llm=lambda c: plan("bear_call_spread", [("SELL", "CE", 22700), ("SELL", "CE", 22800)]))
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


@pytest.mark.unit
def test_trade_levels_give_each_leg_a_target_and_stop_premium_on_the_right_side():
    p = plan("bear_call_spread", [("SELL", "CE", 22700), ("BUY", "CE", 22800)], underlying_entry_low=22580,
             underlying_entry_high=22640, underlying_target=22480, underlying_stop=22720)
    chain = CHAIN | {"summary": {"atm_iv": 14.0}}
    lv = st.trade_levels(p, st.price(p, chain), chain, days_to_expiry=2)
    sold, bought = lv["legs"]
    # NIFTY falling to the target makes both calls cheaper; rising to the stop makes them dearer
    assert sold["premium_at_target"] < sold["price"] < sold["premium_at_stop"]
    assert bought["premium_at_target"] < bought["price"] < bought["premium_at_stop"]
    assert lv["pnl_target_per_lot"] > 0 > lv["pnl_stop_per_lot"]                      # the sold leg dominates
    sp = lv["spread"]
    assert sp["at_target"] < sp["now"] < sp["at_stop"] and not sp["debit"]           # buy back cheaper at target
    assert lv["pnl_target_per_lot"] == pytest.approx((sp["now"] - sp["at_target"]) * 65, abs=1)
    one = st.trade_levels(plan("long_put", [("BUY", "PE", 22600)], underlying_target=22400, underlying_stop=22700),
                          st.price(plan("long_put", [("BUY", "PE", 22600)]), chain), chain, 2)
    leg = one["legs"][0]
    assert leg["premium_at_stop"] < leg["price"] < leg["premium_at_target"] and one["spread"] is None
    assert st.trade_levels(plan("long_put", [("BUY", "PE", 22600)]), st.price(plan("long_put", [("BUY", "PE", 22600)]), chain),
                           chain, 2) is None                                          # no levels from the AI


class _Client:
    def __init__(self, data):
        self.data = data

    def get_json(self, path, params, ttl=0):
        return type("R", (), {"data": self.data})()


@pytest.mark.unit
def test_contract_ticks_high_low_and_identifier_check():
    c = oc.contract("OPTIDXNIFTY27-10-2099CE22700.00", client=_Client(
        {"closePrice": 155.2, "grapthData": [[1000, 210], [2000, 241.05], [3000, 54.9], [4000, 88.8]]}))
    assert (c["high"], c["low"], c["last"], c["prev_close"]) == (241.05, 54.9, 88.8, 155.2) and c["points"][0] == (1, 210.0)
    with pytest.raises(oc.ChainError):
        oc.contract("../etc", client=_Client({}))

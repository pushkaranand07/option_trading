"""Phase 1 of the quant plan: NSE round-trip cost model, checked against hand arithmetic."""

import pytest

from tradingagents.analytics.costs import (
    DELIVERY,
    FUTURES,
    OPTIONS,
    ChargeRates,
    cost_fraction,
    round_trip,
)


@pytest.mark.unit
def test_nifty_option_round_trip_matches_hand_calculation():
    # Buy 75 at Rs 100, sell at Rs 110: premium turnover 7,500 + 8,250 = 15,750.
    b = round_trip(OPTIONS, 75, 100, 110, slippage=None)
    assert b.brokerage == pytest.approx(40.0)
    assert b.stt == pytest.approx(0.0015 * 8250)               # 12.375, sell side
    assert b.exchange == pytest.approx(0.0003553 * 15750)      # 5.596
    assert b.sebi_fee == pytest.approx(15750 * 10 / 1e7)       # 0.01575
    assert b.stamp == pytest.approx(0.00003 * 7500)            # 0.225, buy side
    assert b.gst == pytest.approx(0.18 * (40 + 5.595975 + 0.01575))
    assert b.charges == pytest.approx(66.42, abs=0.01)


@pytest.mark.unit
def test_futures_stt_is_sell_side_only_at_the_2026_rate():
    b = round_trip(FUTURES, 100, 1000, 1000, slippage=None)
    assert b.stt == pytest.approx(0.0005 * 100_000)
    assert b.stamp == pytest.approx(0.00002 * 100_000)


@pytest.mark.unit
def test_delivery_pays_stt_both_sides_and_a_dp_charge():
    b = round_trip(DELIVERY, 10, 1000, 1100, slippage=None)
    assert b.stt == pytest.approx(0.001 * (10_000 + 11_000))
    assert b.dp_charge == 20.0
    assert b.gst == pytest.approx(0.18 * (40 + 0.0000307 * 21_000 + 21_000 * 1e-6 + 20))


@pytest.mark.unit
def test_exercised_option_pays_stt_on_intrinsic_and_has_no_sell_order():
    b = round_trip(OPTIONS, 75, 100, 0, exercised_intrinsic=150, slippage=None)
    assert b.brokerage == 20.0
    assert b.stt == pytest.approx(0.0015 * 75 * 150)


@pytest.mark.unit
def test_slippage_is_added_on_top_of_contract_note_charges():
    b = round_trip(OPTIONS, 75, 100, 110)
    assert b.slippage == pytest.approx(75 * ((0.05 + 1.0) + (0.05 + 1.1)))
    assert b.total == pytest.approx(b.charges + b.slippage)


@pytest.mark.unit
def test_percentage_capped_brokerage_and_cost_fraction():
    rates = ChargeRates(brokerage_pct_cap={DELIVERY: 0.001, "intraday": None, FUTURES: None, OPTIONS: None})
    assert round_trip(DELIVERY, 1, 1000, 1000, rates, None).brokerage == pytest.approx(2.0)  # 0.1% of 1,000 each
    frac = cost_fraction(FUTURES, 25_000, 75)
    assert 0.0005 < frac < 0.003  # a NIFTY future round trip costs roughly 0.1-0.2% with slippage


@pytest.mark.unit
def test_unknown_segment_is_rejected():
    with pytest.raises(ValueError):
        round_trip("crypto", 1, 1, 1)

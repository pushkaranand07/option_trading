"""Phase 8 of the quant plan: fractional-Kelly sizing with hard caps."""

import pytest

from tradingagents.analytics import sizing as sz


@pytest.mark.unit
def test_kelly_matches_the_plans_worked_example():
    assert sz.kelly(0.55, 1.5) == pytest.approx(0.25)


@pytest.mark.unit
def test_quarter_kelly_is_capped_at_one_percent_of_capital():
    advice = sz.size(0.55, 1.5, capital=500_000)
    assert advice.capped and advice.fraction == pytest.approx(0.01)
    assert advice.risk_rupees == pytest.approx(5_000)


@pytest.mark.unit
def test_a_small_edge_is_sized_below_the_cap():
    advice = sz.size(0.52, 1.0, capital=200_000)       # Kelly 0.04 -> quarter 0.01 -> exactly the cap
    assert advice.fraction == pytest.approx(0.01)
    small = sz.size(0.51, 1.0, capital=200_000)         # Kelly 0.02 -> quarter 0.005
    assert not small.capped and small.risk_rupees == pytest.approx(1_000)


@pytest.mark.unit
def test_no_edge_means_no_trade():
    advice = sz.size(0.45, 1.0, capital=100_000)
    assert advice.fraction == 0 and advice.risk_rupees == 0 and "no edge" in advice.reason


@pytest.mark.unit
def test_quantity_rounds_down_to_whole_lots():
    assert sz.quantity(5_000, entry=1000, stop=980, lot=1) == 250
    assert sz.quantity(5_000, entry=100, stop=90, lot=75) == 450          # 6 lots, not 6.67
    with pytest.raises(ValueError):
        sz.quantity(5_000, entry=100, stop=100)

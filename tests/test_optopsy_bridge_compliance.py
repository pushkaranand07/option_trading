"""Options engine inside TradingAgents (P-15), NSE->engine adapter, and report compliance (P-25)."""

import importlib
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import compliance
from tradingagents.integrations.optopsy import bridge as bridge_mod
from tradingagents.integrations.optopsy.adapter import bhavcopy_to_optopsy, bs_price, implied_vol
from tradingagents.integrations.optopsy.bridge import OptopsyBridge, OptopsyUnavailableError
from tradingagents.reporting import write_report_tree

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_engine_is_the_copy_inside_this_repository():
    info = OptopsyBridge().info()
    assert Path(info["location"]).resolve().is_relative_to(REPO / "option_backtester")
    assert (REPO / "option_backtester" / "LICENSE").exists()      # AGPL notice travels with the code


@pytest.mark.unit
def test_engine_exposes_its_strategies_and_signals():
    comps = OptopsyBridge().list_components()
    assert len(comps["strategies"]) == 40
    assert {"iron_condor", "short_put_spread", "long_calls"} <= set(comps["strategies"])
    assert {"rsi_below", "supertrend_buy", "iv_rank_above"} <= set(comps["signals"])


@pytest.mark.unit
def test_a_missing_engine_dependency_is_a_clear_error(monkeypatch):
    real = importlib.import_module

    def broken(name, *a, **k):
        if name == "option_backtester":
            raise ImportError("No module named 'pandas_ta_classic'")
        return real(name, *a, **k)

    monkeypatch.setattr(bridge_mod.importlib, "import_module", broken)
    with pytest.raises(OptopsyUnavailableError, match="pandas-ta-classic"):
        OptopsyBridge()


def two_day_put_chain():
    """A NIFTY put chain quoted on entry day and on expiry day, built through the NSE adapter."""
    rows = []
    for day, spot, t_days in ((date(2026, 9, 15), 23000.0, 7), (date(2026, 9, 22), 23300.0, 0)):
        for strike in range(22300, 23401, 100):
            intrinsic = max(strike - spot, 0.0)
            price = intrinsic + (bs_price(spot, strike, max(t_days, 0.25) / 365, 0.065, 0.14, False) - intrinsic
                                 if t_days else 0.05)
            rows.append({"trade_date": day, "symbol": "NIFTY", "expiry": date(2026, 9, 22),
                         "strike": float(strike), "option_type": "PE", "close": round(max(price, 0.05), 2),
                         "underlying_price": spot, "contracts": 100, "open_interest": 1000})
    return bhavcopy_to_optopsy(pd.DataFrame(rows), "NIFTY")


@pytest.mark.unit
def test_engine_backtests_an_nse_chain_end_to_end():
    chain = two_day_put_chain()
    bridge = OptopsyBridge()
    puts = bridge.run_strategy("short_puts", chain, max_entry_dte=10, exit_dte=0, raw=True)
    assert len(puts) > 0 and (puts["dte_entry"] == 7).all()
    legs = {"leg1_delta": {"target": 0.10, "min": 0.02, "max": 0.20},
            "leg2_delta": {"target": 0.30, "min": 0.20, "max": 0.45}}
    spreads = bridge.run_strategy("short_put_spread", chain, max_entry_dte=10, exit_dte=0, raw=True, **legs)
    assert len(spreads) > 0
    assert (spreads["strike_leg1"] < spreads["strike_leg2"]).all()   # long wing below the short put


@pytest.mark.unit
def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="unknown options strategy"):
        OptopsyBridge().run_strategy("no_such_thing", two_day_put_chain())


@pytest.mark.unit
def test_implied_vol_round_trips_black_scholes():
    price = bs_price(22800, 23000, 30 / 365, 0.065, 0.15, True)
    assert implied_vol(price, 22800, 23000, 30 / 365, 0.065, True) == pytest.approx(0.15, abs=1e-4)
    assert implied_vol(0.01, 22800, 20000, 30 / 365, 0.065, True) is None     # below intrinsic


@pytest.mark.unit
def test_bhavcopy_adapter_builds_optopsy_rows_and_states_its_approximations():
    bhav = pd.DataFrame([
        {"trade_date": date(2026, 10, 21), "symbol": "NIFTY", "expiry": date(2026, 11, 3), "strike": 22800.0,
         "option_type": "CE", "close": 226.4, "underlying_price": 22811.35, "contracts": 35551, "open_interest": 1},
        {"trade_date": date(2026, 10, 21), "symbol": "NIFTY", "expiry": date(2026, 11, 3), "strike": 22800.0,
         "option_type": "PE", "close": 266.1, "underlying_price": 22811.35, "contracts": 57376, "open_interest": 1},
        {"trade_date": date(2026, 10, 21), "symbol": "NIFTY", "expiry": date(2026, 11, 3), "strike": 25000.0,
         "option_type": "CE", "close": 1.0, "underlying_price": 22811.35, "contracts": 0, "open_interest": 1},
    ])
    chain = bhavcopy_to_optopsy(bhav, "NIFTY")
    assert list(chain["option_type"]) == ["call", "put"]
    assert 0.4 < chain.loc[0, "delta"] < 0.7 and -0.6 < chain.loc[1, "delta"] < -0.3
    assert (chain["bid"] == chain["ask"]).all()
    assert any("1 untraded" in a for a in chain.attrs["approximations"])


# ---------------------------------------------------------------- compliance


@pytest.mark.unit
@pytest.mark.parametrize("text", [
    "This trade offers guaranteed returns of 20%.",
    "A sure-shot breakout.",
    "It is risk-free at these levels.",
    "Nifty will certainly hit 25,000.",
    "Buffett would buy this stock today.",
])
def test_red_flag_language_is_found(text):
    assert compliance.review(text)


@pytest.mark.unit
@pytest.mark.parametrize("text", [
    "There are no guaranteed returns in equities.",
    "This is not risk-free.",
    "Risk of loss remains; the stop-loss is 22,550.",
    "Passes 7 of 16 applicable frameworks (rule-based approximation).",
])
def test_ordinary_risk_language_is_not_flagged(text):
    assert compliance.review(text) == []


@pytest.mark.unit
def test_every_complete_report_ends_with_disclaimer_and_flags(tmp_path):
    state = {"market_report": "Sure-shot setup.", "final_trade_decision": "Rating: Hold"}
    out = write_report_tree(state, "^NSEI", tmp_path).read_text(encoding="utf-8")
    assert "## Compliance and risk disclaimer" in out
    assert "“Sure-shot” (certainty claim)" in out
    assert "not investment advice" in out
    assert "Sure-shot setup." in out                                  # the text itself is not rewritten
    html = (tmp_path / "complete_report.html").read_text(encoding="utf-8")
    assert "SEBI" in html

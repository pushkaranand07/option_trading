"""Phase 9 of the quant plan: the agents' quant report uses only what was known, and says what is validated."""

from datetime import date

import pandas as pd
import pytest

from tradingagents.analytics import quant_report as qr
from tradingagents.analytics import trial_log


@pytest.fixture
def store(tmp_path):
    days = pd.bdate_range("2026-10-19", periods=4)          # Mon..Thu
    (tmp_path / "regime").mkdir()
    pd.DataFrame({"trade_date": [d.date() for d in days], "p_calm": [0.9, 0.9, 0.1, 0.1],
                  "p_choppy": [0.1, 0.1, 0.1, 0.1], "p_stress": [0.0, 0.0, 0.8, 0.8],
                  "regime": ["calm", "calm", "stress", "stress"]}).to_parquet(tmp_path / "regime" / "regime.parquet")
    (tmp_path / "vol_forecasts").mkdir()
    cols = {f"{m}_h{h}": [0.20, 0.21, 0.30, 0.40] for m in ("garch", "gjr", "ewma", "hist") for h in (5, 10, 21)}
    pd.DataFrame(cols, index=days).to_parquet(tmp_path / "vol_forecasts" / "RELIANCE.parquet")
    return tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("ticker, symbol", [("RELIANCE.NS", "RELIANCE"), ("reliance", "RELIANCE"),
                                            ("^NSEI", "NIFTY"), ("^NSEBANK", "BANKNIFTY"), ("M&M.NS", "M&M"),
                                            ("ZOMATO.NS", None)])
def test_tickers_map_to_store_symbols(ticker, symbol):
    assert qr.store_symbol(ticker) == symbol


@pytest.mark.unit
def test_values_dated_on_the_analysis_day_are_not_used(store, tmp_path):
    # Analysis on Wed 21-Oct: Wednesday's close (stress, 30%) is not known before Wednesday's open.
    text = qr.quant_signal_text("RELIANCE.NS", date(2026, 10, 21), root=store, trial_path=tmp_path / "t.sqlite")
    assert "CALM" in text and "STRESS" not in text
    assert "GARCH 21.0%" in text and "30.0%" not in text
    later = qr.quant_signal_text("RELIANCE.NS", date(2026, 10, 22), root=store, trial_path=tmp_path / "t.sqlite")
    assert "STRESS since 2026-10-21" in later


@pytest.mark.unit
def test_report_says_no_signal_is_validated_until_one_passes(store, tmp_path):
    log = tmp_path / "t.sqlite"
    trial_log.record(trial_log.Trial("lgbm", {}, n_oos_trades=500, oos_sharpe=0.9, gate_verdict="rejected"), log)
    text = qr.quant_signal_text("RELIANCE.NS", date(2026, 10, 23), root=store, trial_path=log)
    assert "NO quant signal has passed the gates" in text and "lgbm: gates rejected" in text
    trial_log.record(trial_log.Trial("vrp", {}, n_oos_trades=300, oos_sharpe=1.2, gate_verdict="approved"), log)
    text = qr.quant_signal_text("RELIANCE.NS", date(2026, 10, 23), root=store, trial_path=log)
    assert "Approved signals: vrp." in text and "NO quant signal" not in text


@pytest.mark.unit
def test_symbols_outside_the_universe_get_no_numbers(store):
    text = qr.quant_signal_text("ZOMATO.NS", date(2026, 10, 23), root=store)
    assert "outside the research universe" in text and "%" not in text


@pytest.mark.unit
def test_missing_outputs_are_said_plainly(tmp_path):
    text = qr.quant_signal_text("TCS.NS", date(2026, 10, 23), root=tmp_path, trial_path=tmp_path / "t.sqlite")
    assert "Regime: not available" in text and "Volatility forecast: not available" in text

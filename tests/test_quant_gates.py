"""Phase 0 of the quant plan: success gates and the trial log."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import trial_log
from tradingagents.analytics.gates import (
    FAIL,
    NOT_EVALUATED,
    PASS,
    Evidence,
    annual_return,
    check_gates,
    evidence_from_walk_forward,
    max_drawdown,
)
from tradingagents.analytics.validation import walk_forward


def good_evidence(**overrides):
    idx = pd.bdate_range("2020-01-01", periods=750)
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.0012, 0.008, len(idx)), index=idx)
    ev = Evidence(
        oos_returns=returns,
        fold_returns=[0.05, 0.03, -0.01, 0.04, 0.06],
        n_oos_trades=320,
        deflated_sharpe=0.97,
        in_sample_sharpe=1.8,
        oos_sharpe=1.3,
        lookahead_mismatches=0,
        regime_expectancy={"calm": 0.004, "range": 0.002, "stress": -0.003},
        chosen_sharpe=1.3,
        neighbour_sharpes=[1.1, 1.2, 0.9, 1.0],
    )
    for k, v in overrides.items():
        setattr(ev, k, v)
    return ev


def status(report, name):
    return next(r.status for r in report.results if r.name == name)


@pytest.mark.unit
def test_a_strategy_with_every_gate_met_is_approved():
    report = check_gates(good_evidence())
    assert report.verdict == "approved", report.summary()


@pytest.mark.unit
def test_missing_evidence_is_never_a_pass():
    report = check_gates(Evidence())
    assert not report.approved
    assert report.verdict == "incomplete"
    assert all(r.status == NOT_EVALUATED for r in report.results)


@pytest.mark.unit
@pytest.mark.parametrize("override, gate", [
    ({"lookahead_mismatches": 3}, "no look-ahead"),
    ({"n_oos_trades": 40}, "out-of-sample trades"),
    ({"deflated_sharpe": 0.80}, "deflated Sharpe"),
    ({"in_sample_sharpe": 3.0, "oos_sharpe": 1.0}, "OOS / IS Sharpe"),
    ({"in_sample_sharpe": -0.2}, "OOS / IS Sharpe"),
    ({"fold_returns": [0.05, -0.02, -0.01, 0.04]}, "positive folds"),
    ({"neighbour_sharpes": [0.1, 0.2, -0.3]}, "parameter stability"),
])
def test_each_gate_rejects_its_own_failure(override, gate):
    report = check_gates(good_evidence(**override))
    assert status(report, gate) == FAIL
    assert report.verdict == "rejected"


@pytest.mark.unit
def test_regime_gate_needs_two_winning_regimes_or_the_losers_switched_off():
    one_winner = {"calm": 0.004, "range": -0.001, "stress": -0.003}
    assert status(check_gates(good_evidence(regime_expectancy=one_winner)), "regime stability") == FAIL
    switched_off = good_evidence(regime_expectancy=one_winner, regimes_switched_off=frozenset({"range", "stress"}))
    assert status(check_gates(switched_off), "regime stability") == PASS


@pytest.mark.unit
def test_drawdown_gate_fails_a_losing_strategy():
    idx = pd.bdate_range("2020-01-01", periods=500)
    losing = pd.Series(-0.001, index=idx)
    assert status(check_gates(good_evidence(oos_returns=losing)), "drawdown vs return") == FAIL


@pytest.mark.unit
def test_drawdown_and_annual_return_arithmetic():
    r = pd.Series([0.10, -0.50, 0.20])
    assert max_drawdown(r) == pytest.approx(-0.50)
    assert annual_return(pd.Series([0.0] * 252)) == pytest.approx(0.0)
    assert annual_return(pd.Series([0.01] * 252), periods=252) == pytest.approx(1.01 ** 252 - 1)


@pytest.mark.unit
def test_walk_forward_evidence_is_filled_from_the_result():
    idx = pd.bdate_range("2018-01-01", periods=600)
    rng = np.random.default_rng(1)
    data = pd.DataFrame({"Close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))}, index=idx)

    def momentum(df, params):
        ret = df["Close"].pct_change()
        pos = (df["Close"] > df["Close"].rolling(params["n"]).mean()).astype(float).shift(1)
        return (pos * ret).fillna(0.0)

    result = walk_forward(data, momentum, [{"n": 10}, {"n": 30}], train=250, test=100)
    ev = evidence_from_walk_forward(result)
    assert len(ev.fold_returns) == len(result.folds)
    assert ev.n_oos_trades == result.n_trades
    report = check_gates(ev)
    # Random-walk data: whatever else happens, this must not be approved.
    assert not report.approved
    assert status(report, "no look-ahead") == NOT_EVALUATED


@pytest.mark.unit
def test_trial_log_keeps_every_run_and_counts_trials(tmp_path):
    path = tmp_path / "trials.sqlite"
    trial_log.record(trial_log.Trial("fii-reversal", {"threshold": 3000}, n_trials=9, verdict="not_significant"),
                     path)
    trial_log.record(trial_log.Trial("fii-reversal", {"threshold": 4000}, n_trials=9), path)
    trial_log.record(trial_log.Trial("vrp", {"z": 1.0}), path)

    rows = trial_log.load("fii-reversal", path)
    assert [r.params for r in rows] == [{"threshold": 3000}, {"threshold": 4000}]
    assert rows[0].verdict == "not_significant" and rows[0].id == 1
    assert trial_log.trial_count("fii-reversal", path) == 18
    assert trial_log.trial_count(path=path) == 19

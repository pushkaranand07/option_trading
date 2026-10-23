"""Stage 3 of the proof plan: the forward paper-trading ledger."""

from datetime import date, datetime

import pytest

from tradingagents.analytics import paper
from tradingagents.analytics.condor import CondorTrade


def trade(entry, exit_=None, pnl=0.0, credit=10.0, risk=100.0):
    t = CondorTrade(entry, date(2026, 12, 29), {"short_put": 100.0, "short_call": 120.0}, {}, lot=1,
                    credit=credit, max_risk=risk, exit_date=exit_, exit_reason="take_profit" if exit_ else "",
                    pnl=pnl)
    t.symbol = "NIFTY"
    return t


def strategy(start=date(2026, 11, 1)):
    return paper.PaperStrategy("demo", "docs/strategies/demo.md", start, lambda: [], 0.12, 0.45)


@pytest.mark.unit
def test_only_trades_from_the_start_date_are_recorded_and_open_ones_close_later(tmp_path):
    db = tmp_path / "ledger.sqlite"
    before = trade(date(2026, 10, 20), date(2026, 10, 30), pnl=5.0)
    live = trade(date(2026, 11, 3))
    assert paper.update(strategy(), [before, live], db) == {"new": 1, "closed": 0, "integrity": 0}
    rep = paper.report(strategy(), db)
    assert (rep.open_trades, rep.n) == (1, 0)

    closed = trade(date(2026, 11, 3), date(2026, 11, 20), pnl=6.0)
    assert paper.update(strategy(), [before, closed], db)["closed"] == 1
    rep = paper.report(strategy(), db)
    assert (rep.open_trades, rep.n) == (0, 1) and rep.closed == [pytest.approx(0.06)]


@pytest.mark.unit
def test_a_recorded_trade_that_changes_or_vanishes_is_an_integrity_event(tmp_path):
    db = tmp_path / "ledger.sqlite"
    paper.update(strategy(), [trade(date(2026, 11, 3), date(2026, 11, 20), pnl=6.0)], db)
    revised = trade(date(2026, 11, 3), date(2026, 11, 20), pnl=-40.0)        # history rewritten
    assert paper.update(strategy(), [revised], db)["integrity"] == 1
    assert paper.update(strategy(), [], db)["integrity"] == 1                 # and then gone
    rep = paper.report(strategy(), db)
    assert rep.integrity_events == 2 and any("integrity" in k for k in rep.kill)
    assert "KILL" in rep.summary()


@pytest.mark.unit
def test_kill_rules_and_evidence_arithmetic():
    rep = paper.PaperReport("demo", date(2026, 11, 1), 0, [-0.1] * 8, 0, 0.12, 0.45)
    assert rep.losing_streak == 8 and any("8 losing" in k for k in rep.kill)
    # Total -0.8 is still inside the band: floor = 8 x 0.12 - 1.645 x 0.45 x sqrt(8) = -1.13.
    assert not rep.below_band
    assert paper.PaperReport("demo", date(2026, 11, 1), 0, [-0.5] * 8, 0, 0.12, 0.45).below_band
    assert rep.trades_needed == 57                         # (2 x 0.45 / 0.12)^2 = 56.25
    good = paper.PaperReport("demo", date(2026, 11, 1), 0, [0.2, 0.1, 0.15, -0.05] * 15, 0, 0.12, 0.45)
    assert good.kill == [] and good.p_value < 0.05 and "PASS" in good.summary()
    assert any("max risk" in k for k in paper.PaperReport("d", date(2026, 1, 1), 0, [-1.5], 0, 0.1, 0.4).kill)


@pytest.mark.unit
def test_now_is_recorded_as_first_seen(tmp_path):
    db = tmp_path / "ledger.sqlite"
    paper.update(strategy(), [trade(date(2026, 11, 3))], db, now=datetime(2026, 11, 3, 19, 45))
    import sqlite3
    first_seen = sqlite3.connect(db).execute("SELECT first_seen FROM trades").fetchone()[0]
    assert first_seen == "2026-11-03T19:45:00"


@pytest.mark.unit
def test_an_observation_only_strategy_is_never_reported_as_passing():
    good = [0.2, 0.1, 0.15, -0.05] * 15
    rep = paper.PaperReport("demo", date(2026, 11, 1), 0, good, 0, 0.12, 0.45, "observation", "holdout failed")
    text = rep.summary()
    assert "OBSERVATION ONLY" in text and "holdout failed" in text and "PASS" not in text

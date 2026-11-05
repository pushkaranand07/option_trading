"""The Plan tab's trades and labels. The typed word of docs/root_cause_v1.md item 4 and the UNTESTED label were removed by the
user on 2026-11-04 (docs/PA_52, spec v2 ui_until_verdict). Reads the page source; not a browser test."""

import re
from pathlib import Path

import pytest

APP = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start:APP.index("\n}\n", start)]


@pytest.mark.unit
def test_no_typed_word_and_no_untested_label_anywhere():
    for gone in ("ackGate", "S.ack", "ACK_WORD", "ack-untested", "window.prompt(", "UNTESTED"):
        assert gone not in APP, gone


@pytest.mark.unit
def test_the_signal_panel_says_no_edge_evidence_with_no_win_rate_or_60_percent_meter():
    assert 'const conf = live ? `<div class="conf small muted"><b>no edge evidence</b></div>` : "";' in APP
    for gone in ("similar trades", "Need 60%+", "the 60% we require", "conf-row"):
        assert gone not in APP, gone
    assert 'class="meter"' in APP          # the regime display keeps its own meter


def _fn_any(name: str) -> str:
    start = APP.index(name)
    return APP[start:APP.index("\n}\n", start)]


@pytest.mark.unit
def test_the_backtest_table_by_side_line_and_btst_note_show_no_past_win_rate():
    record, btst = _function("renderRecord"), _function("renderBtst")
    assert record.count("no edge evidence") == 2 and "win_rate" not in record and "Win rate" not in record
    assert "no edge evidence" in btst and "win_rate" not in btst.split("History:")[1]


@pytest.mark.unit
def test_recorded_trade_summaries_keep_their_numbers_and_carry_the_line():
    assert "recorded trades, not a test (not registered before entry); ${COST_NOTE}" in APP
    for part in (_fn_any("async function loadJournal("), _fn_any("function recordHtml("), _function("aiRecordHtml")):
        assert "${RECORDED_NOTE}" in part
    assert 'stat("Win rate"' in APP and "win_rate.toFixed(0)" in APP       # the numbers stay


@pytest.mark.unit
def test_recent_trades_show_no_won_lost_count_or_boxes():
    record = _function("renderRecord")
    for gone in (" won, ", "chips", 'class="trades"', "r.last"):
        assert gone not in record, gone


@pytest.mark.unit
def test_the_glossary_has_no_win_rate_entry():
    page = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert "win rate" not in page.lower() and "<b>Avg result</b>" in page


@pytest.mark.unit
def test_the_ai_trades_keep_their_confidence_badge():
    assert "AI confidence ${esc(a.confidence)}" in _function("stratHtml") and "AI confidence ${esc(a.confidence)}" in _function("tradeCard")


@pytest.mark.unit
def test_the_plan_tab_has_one_ai_list_and_no_other_trade_card():
    render, ai = _function("renderStrat"), _function("aiListHtml")
    assert "aiListHtml(sym, res)" in render and "Second opinion" not in APP
    for gone in ("rankHtml", "gamePlanHtml", "rulesHtml", "callHtml", "call-slot", "loadRank"):
        assert gone not in APP, gone
    assert "not by profit size" in ai and "tradeCard(c, i, sym" in ai and "no real order" in ai and "<table" not in ai     # cards, not a wide table
    card = _function("tradeCard")
    assert "c.ai_why" in card and "takeCell(c" in card and "underlying_entry_low" in card and "limit <b>${fmt(l.price)}</b>" in card
    take = _function("takeRanked")
    assert "S.strat[sym]?.result?.trades?.[i]" in take and '"/api/trades"' in take


@pytest.mark.unit
def test_a_run_stays_fixed_until_the_next_run():
    assert "they change only when you run again" in _function("renderStrat")
    latest = APP[APP.index("async function loadLatestRun"):]
    assert '"/api/strategy/latest/"' in latest[:400] and "loadLatestRun(sym)" in APP


@pytest.mark.unit
def test_every_trade_shows_the_money_one_lot_needs():
    assert "lotMoney(c.priced.debit, c.priced.outlay_per_lot)" in _function("tradeCard") and "1 lot <b>${rupee(m.v)}</b>" in _function("tradeCard")
    assert "Money for 1 lot" in _function("stratHtml") and "money in it" in _function("openTradeHtml")
    assert '"≈ margin (Dhan sets exact)"' in _function("lotMoney")


@pytest.mark.unit
def test_each_trade_says_in_hinglish_what_to_buy_or_sell_and_what_a_lot_costs():
    plain = _function("plainTradeHtml")
    assert 'kharid (BUY)' in plain and 'bech (SELL)' in plain and "rupee(l.price * lot)" in plain and "Pehle " in plain
    assert "Kul milake tu" in plain and "Kul milake tujhe" in plain and "profit book kar" in plain and "nikal ja" in plain
    assert "plainTradeHtml(c, sym)" in _function("tradeCard")


@pytest.mark.unit
def test_two_buttons_complete_once_a_day_and_quick_from_its_research():
    render = _function("renderStrat")
    assert 'data-mode="full"' in render and 'data-mode="quick"' in render and "Complete analysis" in render and "Quick analysis" in render
    assert "startStrat(sym, b.dataset.mode)" in render and "loadResearch(sym)" in APP and '"/api/strategy/research/"' in APP
    assert "mode })" in _fn_any("async function startStrat(")

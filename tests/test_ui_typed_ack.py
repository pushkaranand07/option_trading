"""Untested trades carry the UNTESTED label; the typed word of docs/root_cause_v1.md item 4 was removed by the user on 2026-11-04
(docs/PA_52, spec v2 ui_until_verdict). Reads the page source; not a browser test."""

import re
from pathlib import Path

import pytest

APP = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start:APP.index("\n}\n", start)]


@pytest.mark.unit
def test_no_typed_word_anywhere_the_label_stays_on_every_trade_surface():
    for gone in ("ackGate", "S.ack", "ACK_WORD", "ack-untested", "window.prompt("):
        assert gone not in APP, gone
    for name in ("stratHtml", "aiListHtml"):
        assert "${UNTESTED}" in _function(name), name


@pytest.mark.unit
def test_the_intraday_card_has_the_label_and_no_past_win_rate():
    body = _function("callHtml")
    assert body.count("Take this trade ${UNTESTED}") == 2 and body.count("no edge evidence") == 2
    assert not re.search(r"win_rate|similar trades|avg_r", body)


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
    for part in (_fn_any("async function loadJournal("), _fn_any("async function loadRecord("), _function("aiRecordHtml")):
        assert "${RECORDED_NOTE}" in part
    assert 'stat("Win rate"' in APP and "win_rate.toFixed(0)" in APP       # the numbers stay


@pytest.mark.unit
def test_the_no_trade_card_shows_no_server_reason():
    body = _function("callHtml")
    assert "<b>No trade right now.</b> no trade signal today" in body and "blockers" not in body


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
    assert "AI confidence ${esc(a.confidence)}" in _function("stratHtml") and "AI confidence ${esc(c.plan.confidence)}" in _function("aiListHtml")


@pytest.mark.unit
def test_one_ai_list_with_take_buttons_and_the_rule_views_folded_away():
    render, ai = _function("renderStrat"), _function("aiListHtml")
    assert "aiListHtml(sym, res)" in render and "rulesHtml(sym)" in render and "Second opinion" not in APP
    assert '<details class="rules"' in _function("rulesHtml") and "rankHtml(sym)" in _function("rulesHtml")
    assert "not by profit size" in ai and "takeCell(c" in ai and "c.ai_why" in ai and "no real order" in ai
    take = _function("takeRanked")
    assert "btn.dataset.ai ? S.strat[sym]?.result?.trades?.[i]" in take and '"/api/trades"' in take

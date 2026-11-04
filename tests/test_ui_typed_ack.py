"""A typed word before an untested trade's orders, target and stop show (docs/root_cause_v1.md, item 4). Reads the page source; not a browser test."""

import re
from pathlib import Path

import pytest

APP = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start:APP.index("\n}\n", start)]


@pytest.mark.unit
@pytest.mark.parametrize(("name", "key"), [("callHtml", "callKey"), ("stratHtml", "stratKey"), ("rankHtml", "rankKey")])
def test_each_trade_surface_returns_a_gate_before_its_levels(name, key):
    body = _function(name)
    gate = body.index(f"S.ack[{key}(")
    assert "ackGate(" in body[gate:gate + 200]
    for word in ("s.stop_loss", "underlying_target)}", "premium_at_target"):
        if word in body:
            assert gate < body.index(word), word


@pytest.mark.unit
def test_the_take_button_and_action_need_the_acknowledgement():
    body = _function("stratHtml")
    assert body.index("ackGate(") < body.index("take-trade")
    assert "S.ack[stratKey(res, sym)]" in APP[APP.index("async function takeTrade"):APP.index("async function takeTrade") + 200]


@pytest.mark.unit
def test_only_the_exact_word_opens_it():
    handler = APP[APP.index('document.addEventListener("click", (e) => {\n  const b = e.target.closest?.(".ack-untested")'):]
    assert 'window.prompt(' in handler[:400] and 'toUpperCase() !== ACK_WORD) return' in handler[:500] and 'ACK_WORD = "UNTESTED"' in APP


@pytest.mark.unit
def test_the_intraday_card_has_the_label_and_no_past_win_rate():
    body = _function("callHtml")
    assert body.count("Take this trade ${UNTESTED}") == 2 and body.count("no edge evidence") == 2
    assert not re.search(r"win_rate|similar trades|avg_r", body)


@pytest.mark.unit
def test_chart_lines_stay_hidden_until_the_acknowledgement():
    assert 'S.ack[callKey(sym, p)]) {\n      level(p.signal.entry' in APP and 'S.ack[stratKey(r, sym)]) {\n      const who' in APP


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
def test_ranked_plans_show_na_and_ai_plans_keep_their_confidence_badge():
    assert '${res.source === "pulse" ? "n/a" : `AI confidence ${esc(a.confidence)}`}' in _function("stratHtml")


@pytest.mark.unit
def test_ranked_trades_follow_the_ai_answer_and_each_can_be_recorded_behind_the_acknowledgement():
    render, ranked = _function("renderStrat"), _function("rankHtml")
    assert 'st.result ? aiHead + (cand ? "" : detail) + rankHtml(sym)' in render and "takeRanked(sym" in render
    assert ranked.index("S.ack[rankKey(sym)]") < ranked.index("rank-take")
    take = _function("takeRanked")
    assert "S.ack[rankKey(sym)]) return" in take and '"/api/trades"' in take
    assert "it places no real order" in ranked and "Take (dummy, 1 lot)" in ranked

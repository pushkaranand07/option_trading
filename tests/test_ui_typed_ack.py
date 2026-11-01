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

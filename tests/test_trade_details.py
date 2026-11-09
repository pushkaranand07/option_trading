"""Each recorded trade opens a full detail: every leg as BUY (kharida) or SELL (becha) with its contract, quantity,
the run's price, the filled entry and the exit (or the price now), the times, NIFTY at the run, the Take and the exit,
the plan's levels, where it came from and why the AI picked it. The AI's reason is now stored on new trades."""

import csv
import io

import pytest

from tests.test_take_honest_entry import chain, take, world  # noqa: F401  (world is a fixture)
from tests.test_ui_regressions import app_source
from webapp import strategist as st, trade_record as tr

APP = app_source()                              # the page's script: every module under webapp/static/js


def _js(name):
    start = APP.index(name)
    return APP[start:APP.index("\n}\n", start)]


@pytest.fixture
def why(world):
    for i, c in enumerate(world["run"]["trades"]):
        c["ai_why"] = f"reason {i + 1}"
    st.save_run(world["run"])
    return world


@pytest.mark.unit
def test_a_take_stores_the_ais_reason(why):
    assert take(why, candidate=1).json()["ai_why"] == "reason 2"


@pytest.mark.unit
def test_a_not_taken_pick_stores_the_ais_reason(why):
    why["live"]["chain"] = chain(spot=why["call"]["plan"]["underlying_entry_high"] + 30)
    assert tr.record_ai_pick("run1")["ai_why"] == "reason 1"


@pytest.mark.unit
def test_the_csv_carries_the_ais_reason(why):
    take(why)
    head, row = list(csv.reader(io.StringIO(tr.history_csv())))[:2]
    assert head[-1] == "ai_reason" and row[-1] == "reason 1"


@pytest.mark.unit
def test_the_detail_shows_each_leg_in_words_with_its_prices_and_quantity():
    d = _js("function tradeDetailHtml(")
    for part in ('"BUY — kharida"', '"SELL — becha"', "contractName(", "t.lot * (t.lots || 1)", "l.shown_price", "l.entry", "l.exit"):
        assert part in d, part
    for part in ("t.taken_at", "t.closed_at", "t.spot_at_run", "t.spot_at_entry", "t.spot_at_exit", "t.entry_low", "t.ai_why", "t.reason"):
        assert part in d, part


@pytest.mark.unit
def test_every_record_row_can_open_its_detail():
    assert "${tradeDetailHtml(t)}" in APP[APP.index("const detailRow = "):][:250]          # each detail row holds the detail
    for fn, cols in (("function openRowHtml(", 6), ("function histRowHtml(", 7), ("function notTakenRowsHtml(", 5)):
        assert f"detailRow(t, {cols})" in _js(fn), fn                                    # open, closed and not-taken rows
    assert '".rec-more"' in APP and "S.openDetail" in APP


@pytest.mark.unit
def test_each_row_says_what_was_bought_or_sold_at_what_price_and_for_how_much():
    paid = _js("function paidTxt(")
    for part in ('"Kharida"', '"Becha"', "l.entry", "rupee(px * qty)", '"becha"', '"wapas kharida"', "kul ${t.debit ? \"diya\" : \"mila\"}"):
        assert part in paid, part
    for fn in ("function openRowHtml(", "function histRowHtml(", "function notTakenRowsHtml("):
        assert "${paidTxt(t)}" in _js(fn), fn
    assert "<th>Amount (entry × qty)</th>" in _js("function tradeDetailHtml(")

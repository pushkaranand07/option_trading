"""Track E verifier's M1 (audit 2026-11): the degraded notice hid a v2 failure on the assumption the v2 line shows it,
but that line exists only on the Plan tab. Now v2 is left out of the notice only while a v2 line is on the page."""

import pytest

from tests.test_ui_regressions import render, text

V2 = [{"part": "v2", "reason": "could not read the registry (error id ab12cd)"}, {"part": "calendar", "reason": "x"}]


@pytest.mark.unit
def test_a_v2_failure_shows_in_the_notice_when_no_v2_line_is_on_the_page():
    shown = text(render("degradedText(ARGS[0], false)", V2))
    assert "v2" in shown and "error id ab12cd" in shown and "calendar" not in shown


@pytest.mark.unit
def test_with_the_v2_line_on_the_page_the_notice_does_not_repeat_it():
    assert render("String(degradedText(ARGS[0], true))", V2) == "null"

"""Dates and power for the AI forward test's options come from the spec; nothing is picked (docs/ai_test_options_v1.md)."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_option_dates_and_power_come_from_the_spec():
    m = _script("ai_test_options")
    assert m.verdict_date(500, 5) == date(2028, 10, 2)
    assert m.trades_by(date(2027, 11, 1), 5) == 260
    table = {"0.20": {"50": 0.1, "200": 0.5, "500": 0.8}}
    assert m.power_at(table, "0.20", 499) == 0.5 and m.power_at(table, "0.20", 49) is None


@pytest.mark.unit
def test_the_options_doc_picks_nothing_and_warns_about_the_first_question():
    text = (DOCS / "ai_test_options_v1.md").read_text(encoding="utf-8")
    assert "I have not picked one" in text and "first trade" in text and all(x in text for x in ("(a)", "(b)", "(c)", "(d)"))

"""Only slippage moves in the cost sensitivity table (docs/cost_parameters_v1.md)."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_only_slippage_moves_in_the_sensitivity_table():
    m = _script("research_cost_sensitivity")
    kinds = pd.Series(["index", "stock"])
    a, b = m.scenario_costs(kinds, 1.0), m.scenario_costs(kinds, 3.0)
    assert b[0] - a[0] == pytest.approx(2 * 2 * 2 / 1e4) and b[1] - a[1] == pytest.approx(2 * 2 * 5 / 1e4)


@pytest.mark.unit
def test_the_parameter_table_marks_slippage_as_an_assumption_and_keeps_the_label():
    text = (DOCS / "cost_parameters_v1.md").read_text(encoding="utf-8")
    assert "Cost model unverified" in text and text.count("**ASSUMPTION**") >= 4

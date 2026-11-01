"""The model suite's verdict is stated with its conditions everywhere (docs/root_cause_v1.md, item 2)."""

import importlib.util
import re
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
@pytest.mark.parametrize("name", ["data_catalog.md", "models_v1_refit_report.md", "models_v1_report.md", "PA_48-model-suite-v1-refit.md", "PA_47-model-suite-v1.md"])
def test_the_verdict_is_stated_with_its_conditions(name):
    text = (DOCS / name).read_text(encoding="utf-8").lower()
    assert "no edge found under these conditions" in text
    for hit in re.findall(r"no edge found[^.\n]{0,40}", text):
        assert "under these conditions" in hit, hit


@pytest.mark.unit
def test_the_conditions_are_listed_and_the_plan_tab_is_conditioned():
    catalog = (DOCS / "data_catalog.md").read_text(encoding="utf-8")
    for word in ("D-1 timing", "futures only", "1.5x costs", "end-of-day features", "these 6 specs", "1,532 trials"):
        assert word in catalog, word
    app = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
    assert "no edge in the project's tests" not in app and "under the conditions tested" in app


@pytest.mark.unit
def test_the_protocol_cannot_reopen_the_closed_line():
    text = (DOCS / "nse_publication_protocol_v1.md").read_text(encoding="utf-8")
    assert "does not reopen" in text and "20 trading evenings" in text

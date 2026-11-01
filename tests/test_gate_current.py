"""The current-gate summary matches the frozen files, and new addenda need a reason (docs/gate_current.md)."""

import importlib.util
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
def test_gate_current_quotes_every_source_with_its_current_hash():
    m = _script("make_gate_current")
    text = (DOCS / "gate_current.md").read_text(encoding="utf-8")
    assert text.replace("\r\n", "\n") == m.build().replace("\r\n", "\n")
    for name, *_ in m.SOURCES:
        assert m.canonical_hash(DOCS / name) in text, name
    assert "changes no rule" in text


@pytest.mark.unit
def test_the_catalog_requires_a_reason_and_results_seen_for_a_new_addendum():
    catalog = (DOCS / "data_catalog.md").read_text(encoding="utf-8")
    assert "no new addenda without a written reason and the list of results seen so far" in catalog.lower()

"""The public risk document holds no endpoint host, and nothing claims to have been sent (docs/external_risks_v1.md)."""

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
def test_the_public_risk_doc_has_no_endpoint_host_and_says_nothing_was_sent():
    text = (DOCS / "external_risks_v1.md").read_text(encoding="utf-8")
    assert not re.search(r"cognitiveservices|openai\.azure", text)
    assert "Nothing has been sent" in text

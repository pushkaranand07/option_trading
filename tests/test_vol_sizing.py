"""The volatility sizing test is frozen, and its weights follow the spec (docs/vol_sizing_test_v1.json)."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_vol_sizing_spec_is_frozen_and_weights_cap(tmp_path):
    m = _script("research_vol_sizing")
    assert m.read_spec()["edge_claim"].startswith("none") and "2022-12-31" in m.read_spec()["period"]
    w = m.weight(np.array([0.1, 0.3, 0.6, 0.0]))
    assert w[0] == 2.0 and w[1] == pytest.approx(1.0) and w[2] == pytest.approx(0.5) and np.isnan(w[3])
    p = tmp_path / "s.json"
    p.write_text(m.SPEC_FILE.read_text(encoding="utf-8").replace('"version": 1', '"version": 2'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        m.read_spec(p)


@pytest.mark.unit
def test_the_report_makes_no_edge_claim():
    text = (DOCS / "vol_sizing_report_v1.md").read_text(encoding="utf-8")
    assert "no edge claim" in text and "Lower risk is not an edge" in text

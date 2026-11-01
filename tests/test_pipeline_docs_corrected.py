"""The audit's corrections are in the docs (docs/pipeline_audit_v1.md)."""

from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.mark.unit
def test_the_parity_figure_is_corrected_and_the_threshold_stays():
    text = (DOCS / "features_threshold_report.md").read_text(encoding="utf-8")
    assert "0.6444%" in text and "threshold of 25 does not change" in text and "**Result: 25 contracts" in text


@pytest.mark.unit
def test_the_audit_compares_series_and_passes_both_corrected_rows():
    text = (DOCS / "pipeline_audit_v1.md").read_text(encoding="utf-8")
    assert "| U1 series, 2022 | 100 | 100 |" in text and "103 symbols" in text
    rows = [x for x in text.splitlines() if x.startswith(("| U1 series", "| parity flag"))]
    assert len(rows) == 2 and all("**PASS**" in x for x in rows)


@pytest.mark.unit
def test_the_catalog_records_the_har_result_as_unusable():
    assert "HAR result unusable (biased fit); GARCH-beats-HAR claim unproven" in (DOCS / "data_catalog.md").read_text(encoding="utf-8")

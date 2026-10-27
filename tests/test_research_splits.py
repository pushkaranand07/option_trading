"""The frozen split (docs/data/splits_v1.json, docs/PA_31)."""

import json
from datetime import date, timedelta

import pytest

from tradingagents.research import splits


@pytest.mark.unit
def test_file_matches_its_frozen_hash():
    splits.read()


@pytest.mark.unit
def test_any_change_of_content_is_refused(tmp_path):
    content = json.loads(splits.SPLITS_PATH.read_text(encoding="utf-8"))
    content["periods"]["validation"]["end"] = "2025-06-30"
    changed = tmp_path / "splits.json"
    changed.write_text(json.dumps(content, indent=2), encoding="utf-8")
    with pytest.raises(splits.SplitsChanged):
        splits.read(changed)


@pytest.mark.unit
def test_formatting_alone_does_not_change_the_hash(tmp_path):
    content = json.loads(splits.SPLITS_PATH.read_text(encoding="utf-8"))
    reformatted = tmp_path / "splits.json"
    reformatted.write_text(json.dumps(content, indent=1).replace("\n", "\r\n"), encoding="utf-8")
    splits.read(reformatted)


@pytest.mark.unit
def test_periods_are_contiguous_and_only_dev_and_validation_are_open():
    p = splits.periods()
    assert p["development"].start is None and p["development"].end == date(2022, 12, 31)
    assert p["validation"].start == date(2023, 1, 1) and p["validation"].end == date(2024, 12, 31)
    assert p["final_holdout"].start == date(2025, 1, 1)
    assert p["forward_holdout"].start == date(2026, 10, 27) and p["forward_holdout"].end is None
    order = ["development", "validation", "final_holdout", "forward_holdout"]
    for a, b in zip(order, order[1:], strict=False):
        assert p[a].end + timedelta(days=1) == p[b].start
    assert [n for n in order if not p[n].locked] == ["development", "validation"]
    assert p["forward_holdout"].access == splits.PREREGISTERED
    assert splits.last_open_day() == date(2024, 12, 31)


@pytest.mark.unit
def test_contamination_is_labelled_and_the_prior_experiments_are_named():
    content = splits.read()
    assert splits.periods(content)["final_holdout"].label == "contaminated for ideas tested before 2026-10-27"
    seen = " ".join(e["idea"] for e in content["seen_2025_plus"]["experiments"])
    for experiment in ("vrp_condor", "lgbm", "chronos", "results_iron_fly", "Market Map"):
        assert experiment in seen


@pytest.mark.unit
def test_period_of_boundaries():
    assert splits.period_of(date(2022, 12, 31)).name == "development"
    assert splits.period_of(date(2023, 1, 1)).name == "validation"
    assert splits.period_of(date(2025, 1, 1)).name == "final_holdout"
    assert splits.period_of(date(2026, 10, 26)).name == "final_holdout"
    assert splits.period_of(date(2026, 10, 27)).name == "forward_holdout"

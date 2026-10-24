"""Phase 10 groundwork: the after-close refresh runs its steps in order and stops at a failure."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "quant_daily_update", Path(__file__).resolve().parents[1] / "scripts" / "quant_daily_update.py")
daily = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(daily)


@pytest.mark.unit
def test_steps_run_in_order_and_the_download_rechecks_recent_missing_days():
    plan = daily.steps(date(2026, 10, 23))
    assert [name for name, _ in plan] == ["download", "store", "volatility", "regime", "tracker", "market_map", "paper"]
    download = plan[0][1]
    assert "--retry-missing" in download and download[download.index("--start") + 1] == "2026-10-13"
    assert plan[1][1][-1] == "2026"


@pytest.mark.unit
def test_a_failing_step_stops_the_run():
    calls = []

    def runner(args):
        calls.append(args[0])
        return 1 if "build_store" in args[0] else 0

    records = daily.run_steps(daily.steps(date(2026, 10, 23)), runner)
    assert [r["step"] for r in records] == ["download", "store"]
    assert records[-1]["exit_code"] == 1
    assert not any("vol_forecasts" in c for c in calls)

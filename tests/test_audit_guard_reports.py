"""Audit-fix guard (2026-11): no test can write the user's real reports/ folder. The session fixture in conftest.py
points every web-app data path at a temporary directory; this checks it, including through a real lifespan
(TestClient), whose start-up refresh and monitor would otherwise use the real trades.json."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL = (ROOT / "reports").resolve()


def _outside_real(path) -> bool:
    return REAL not in Path(path).resolve().parents and Path(path).resolve() != REAL


@pytest.mark.unit
def test_every_web_app_data_path_points_away_from_the_real_reports_folder():
    from webapp import ai_test, dhan_guard, morning, quant, strategist, trade_record

    for path in (trade_record.STORE, ai_test.REGISTRY, ai_test.CHAINS, quant.JOURNAL_DIR, morning.PLAN_DIR,
                 strategist._runs_dir(), dhan_guard.LOG):
        assert _outside_real(path), path

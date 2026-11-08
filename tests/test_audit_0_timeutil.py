"""Track 0 (audit L6): today_ist() is India's date even when the PC's clock says another day."""

from datetime import UTC, datetime

import pytest

from webapp import signals, timeutil


@pytest.mark.unit
def test_today_ist_is_indias_date_not_the_local_date(monkeypatch):
    # 20:00 UTC on 8 Nov is 01:30 IST on 9 Nov: a UTC or US machine's date.today() would say the 8th.
    utc = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)
    monkeypatch.setattr(signals, "now_ist", lambda: utc.astimezone(signals.IST))
    monkeypatch.setattr(timeutil, "now_ist", lambda: utc.astimezone(signals.IST))
    assert str(timeutil.today_ist()) == "2026-11-09"
    assert timeutil.now_ist().utcoffset().total_seconds() == 5.5 * 3600
    assert timeutil.IST is signals.IST

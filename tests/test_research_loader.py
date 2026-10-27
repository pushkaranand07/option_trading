"""The locked research loader: point-in-time checks and holdout locks (docs/PA_31)."""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.analytics import trial_log
from tradingagents.research import loader
from tradingagents.research.loader import HoldoutLocked, PointInTimeError, Unlock


def _store(tmp_path: Path, rows: list[tuple[date, date]]) -> Path:
    """A store with one fo_summary row per (trade_date, known_from), one file per year."""
    df = pd.DataFrame([{"trade_date": t, "known_from": k, "symbol": "NIFTY", "fut_close": 100.0 + i}
                       for i, (t, k) in enumerate(rows)])
    root = tmp_path / "store"
    (root / "fo_summary").mkdir(parents=True)
    for year, g in df.groupby(df["trade_date"].map(lambda d: d.year)):
        g.to_parquet(root / "fo_summary" / f"{year}.parquet", index=False)
    return root


def _days(start: date, end: date) -> list[tuple[date, date]]:
    out, d = [], start
    while d <= end:
        out.append((d, d + timedelta(days=1)))
        d += timedelta(days=1)
    return out


@pytest.fixture
def store(tmp_path):
    return _store(tmp_path, _days(date(2024, 12, 20), date(2025, 1, 10)) + _days(date(2026, 10, 20), date(2026, 10, 30)))


@pytest.fixture
def log(tmp_path):
    return tmp_path / "trials.sqlite"


@pytest.mark.unit
def test_default_stops_at_the_last_open_day_by_known_from(store, log):
    df = loader.load("fo_summary", root=store, log_path=log)
    assert pd.to_datetime(df["known_from"]).max().date() == date(2024, 12, 31)
    # traded on 2024-12-31 but public on 2025-01-01: a holdout row
    assert date(2024, 12, 31) not in set(df["trade_date"])
    assert trial_log.load_events(path=log) == []


@pytest.mark.unit
def test_final_holdout_is_refused_without_an_unlock_and_nothing_is_logged(store, log):
    with pytest.raises(HoldoutLocked, match="final_holdout"):
        loader.load("fo_summary", end=date(2025, 1, 5), root=store, log_path=log)
    assert trial_log.load_events(path=log) == []


@pytest.mark.unit
def test_unlock_needs_a_reason(store, log):
    with pytest.raises(HoldoutLocked, match="reason"):
        loader.load("fo_summary", end=date(2025, 1, 5), unlocks=[Unlock("final_holdout", "  ")],
                    root=store, log_path=log)


@pytest.mark.unit
def test_final_unlock_is_logged_then_returns_rows(store, log):
    df = loader.load("fo_summary", start=date(2025, 1, 1), end=date(2025, 1, 5),
                     unlocks=[Unlock("final_holdout", "final test of spec X")], root=store, log_path=log)
    assert pd.to_datetime(df["known_from"]).min().date() == date(2025, 1, 1)
    events = trial_log.load_events("holdout_unlock", path=log)
    assert len(events) == 1
    assert events[0]["detail"]["period"] == "final_holdout"
    assert events[0]["detail"]["label"] == "contaminated for ideas tested before 2026-10-27"
    assert trial_log.trial_count(path=log) == 0        # an unlock is not a trial


@pytest.mark.unit
def test_no_rows_if_the_unlock_cannot_be_logged(store, log, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(trial_log, "log_event", broken)
    read = []
    monkeypatch.setattr(loader, "_read", lambda *a, **k: read.append(1))
    with pytest.raises(OSError):
        loader.load("fo_summary", end=date(2025, 1, 5), unlocks=[Unlock("final_holdout", "x")],
                    root=store, log_path=log)
    assert read == []


@pytest.mark.unit
def test_final_unlock_does_not_open_the_forward_holdout(store, log):
    with pytest.raises(HoldoutLocked, match="forward_holdout"):
        loader.load("fo_summary", start=date(2026, 10, 20), end=date(2026, 10, 30),
                    unlocks=[Unlock("final_holdout", "x")], root=store, log_path=log)


@pytest.mark.unit
def test_forward_holdout_needs_a_committed_preregistration(store, log, tmp_path, monkeypatch):
    window = {"start": date(2026, 10, 27), "end": date(2026, 10, 30), "root": store, "log_path": log}
    with pytest.raises(HoldoutLocked, match="pre-registered"):
        loader.load("fo_summary", unlocks=[Unlock("forward_holdout", "final test")], **window)
    spec = tmp_path / "spec.md"
    spec.write_text("frozen rules", encoding="utf-8")
    monkeypatch.setattr(loader, "_committed", lambda p: False)
    with pytest.raises(HoldoutLocked, match="committed"):
        loader.load("fo_summary", unlocks=[Unlock("forward_holdout", "final test", spec)], **window)
    assert trial_log.load_events(path=log) == []
    monkeypatch.setattr(loader, "_committed", lambda p: True)
    df = loader.load("fo_summary", unlocks=[Unlock("forward_holdout", "final test", spec)], **window)
    assert len(df) == 4
    (event,) = trial_log.load_events("holdout_unlock", path=log)
    assert event["detail"]["preregistration_sha256"]


@pytest.mark.unit
def test_committed_check_uses_git_for_a_tracked_clean_file():
    assert loader._committed(loader.REPO_ROOT / "pyproject.toml") in (True, False)   # runs git, no exception


@pytest.mark.unit
@pytest.mark.parametrize("known_offset, message", [(0, "on or before"), (-1, "on or before"), (None, "without")])
def test_point_in_time_violations_fail_the_whole_load(tmp_path, log, known_offset, message):
    t = date(2024, 6, 3)
    bad = None if known_offset is None else t + timedelta(days=known_offset)
    root = _store(tmp_path, [(date(2024, 6, 1), date(2024, 6, 3)), (t, bad)])
    with pytest.raises(PointInTimeError, match=message):
        loader.load("fo_summary", root=root, log_path=log)


@pytest.mark.unit
def test_datasets_without_known_from_are_refused(tmp_path, log):
    with pytest.raises(PointInTimeError, match="known_from"):
        loader.load("vol_forecasts", root=tmp_path, log_path=log)
    df = pd.DataFrame({"trade_date": [date(2024, 1, 2)], "symbol": ["NIFTY"], "iv30": [0.12]})
    (tmp_path / "iv").mkdir()
    df.to_parquet(tmp_path / "iv" / "iv30.parquet", index=False)
    with pytest.raises(PointInTimeError, match="known_from"):
        loader.load("iv30", root=tmp_path, log_path=log)


@pytest.mark.unit
def test_start_is_by_known_from_and_reads_back_far_enough(tmp_path, log):
    # traded before a long gap, public on the first day of the range
    root = _store(tmp_path, [(date(2024, 3, 1), date(2024, 3, 25)), (date(2024, 3, 25), date(2024, 3, 26))])
    df = loader.load("fo_summary", start=date(2024, 3, 25), end=date(2024, 3, 31), root=root, log_path=log)
    assert list(df["trade_date"]) == [date(2024, 3, 1), date(2024, 3, 25)]


@pytest.mark.unit
def test_holdout_counts_give_counts_only_and_need_no_unlock(store, log):
    counts = loader.holdout_counts("fo_summary", root=store)
    assert list(counts.columns) == ["period", "known_from", "rows"]
    assert set(counts["period"]) == {"final_holdout", "forward_holdout"}
    assert counts["known_from"].min() == date(2025, 1, 1)
    assert counts["rows"].sum() == 11 + 11      # trade dates 2024-12-31..2025-01-10 and 2026-10-20..30
    assert trial_log.load_events(path=log) == []

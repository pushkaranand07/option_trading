"""The NSE holiday list is saved through a temp file of its own (2026-11-11 server log: "could not save the NSE holiday
list: [WinError 32] ... holidays_last_good.tmp -> holidays_last_good.json"). Every writer used the one fixed name
holidays_last_good.tmp, so two saves at once (threads asking for the calendar together at start-up) collided, and on
Windows a temp file still held open by another writer could not be moved into place. Now each save writes its own
uniquely named temp file (tradingagents.dataflows.files.replace_file) and the list is saved."""

import json
import threading
from datetime import date

import pytest

from tradingagents.dataflows.vendors.nse import calendar as cal

HOLIDAYS = {date(2026, 11, 24): "Guru Nanak Jayanti", date(2026, 12, 25): "Christmas"}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    path = tmp_path / "nse" / "holidays_last_good.json"
    monkeypatch.setattr(cal, "SAVED_HOLIDAYS", str(path))
    return path


@pytest.mark.unit
def test_a_temp_file_held_by_another_writer_does_not_stop_the_save(saved, caplog):
    saved.parent.mkdir(parents=True)
    with open(saved.with_suffix(".tmp"), "w", encoding="utf-8"):        # the old fixed temp name, open elsewhere
        cal._save_holidays(HOLIDAYS)
    assert "could not save" not in caplog.text
    assert cal._load_saved_holidays() == HOLIDAYS


@pytest.mark.unit
def test_saves_at_the_same_time_all_succeed_and_leave_no_temp_files(saved, caplog):
    go = threading.Barrier(8)

    def save():
        go.wait()
        cal._save_holidays(HOLIDAYS)

    threads = [threading.Thread(target=save) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert json.loads(saved.read_text(encoding="utf-8"))["holidays"] == {"24-Nov-2026": "Guru Nanak Jayanti", "25-Dec-2026": "Christmas"}
    assert [p.name for p in saved.parent.iterdir()] == [saved.name]
    assert "could not save" not in caplog.text

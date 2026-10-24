"""Phase 1 of the quant plan: resumable NSE archive backfill and the research universe."""

from datetime import date

import pytest

from tradingagents.analytics import universe
from tradingagents.analytics.backfill import backfill, candidate_urls, load_manifest
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors.nse.client import Fetched, NSEDataNotPublishedError


class FakeClient:
    """Publishes every file except on holidays and weekends (unless a weekend is a special session)."""

    def __init__(self, holidays=(), fail_after=None, weekend_sessions=()):
        weekends = {date.fromordinal(o) for o in range(date(2025, 1, 1).toordinal(), date(2027, 1, 1).toordinal())
                    if date.fromordinal(o).weekday() >= 5} - set(weekend_sessions)
        self.holidays, self.fail_after, self.calls = set(holidays) | weekends, fail_after, []

    def get_archive(self, url):
        self.calls.append(url)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise VendorUnavailableError("nse", "down")
        if any(f"{d:%d%m%Y}" in url or f"{d:%Y%m%d}" in url or f"{d:%d%b%Y}".upper() in url
               for d in self.holidays):
            raise NSEDataNotPublishedError("archive", detail=url)
        return Fetched(b"data:" + url.encode(), url, None)


@pytest.mark.unit
def test_fo_format_is_tried_in_the_order_nse_published_it():
    assert "BhavCopy_NSE_FO" in candidate_urls("fo", date(2025, 1, 2))[0]
    assert "historical/DERIVATIVES" in candidate_urls("fo", date(2019, 1, 2))[0]


@pytest.mark.unit
def test_backfill_saves_files_marks_holidays_and_probes_weekends_once(tmp_path):
    client = FakeClient(holidays=[date(2026, 1, 26)])
    stats = backfill(client, date(2026, 1, 23), date(2026, 1, 27), root=tmp_path)  # Fri, Sat, Sun, Mon, Tue
    manifest = load_manifest(tmp_path)
    assert {d for d, _ in manifest} == {date(2026, 1, d) for d in (23, 24, 25, 26, 27)}
    assert manifest[(date(2026, 1, 26), "mto")].status == "missing"
    assert manifest[(date(2026, 1, 27), "participant")].status == "ok"
    # A normal weekend costs one request (the index-close file) and records nothing else.
    assert manifest[(date(2026, 1, 24), "indices")].status == "missing"
    assert (date(2026, 1, 24), "fo") not in manifest
    assert (stats.fetched, stats.missing) == (8, 6)
    assert (tmp_path / "mto" / "2026" / "MTO_27012026.DAT").read_bytes().startswith(b"data:")


@pytest.mark.unit
def test_backfill_resumes_without_refetching(tmp_path):
    backfill(FakeClient(), date(2026, 1, 5), date(2026, 1, 6), root=tmp_path)
    again = FakeClient()
    stats = backfill(again, date(2026, 1, 5), date(2026, 1, 7), root=tmp_path)
    assert stats.skipped == 8 and stats.fetched == 4
    assert all("07012026" in u or "20260107" in u or "07JAN2026" in u for u in again.calls)


@pytest.mark.unit
def test_backfill_stops_cleanly_when_nse_goes_down(tmp_path):
    stats = backfill(FakeClient(fail_after=4), date(2026, 1, 5), date(2026, 1, 9), root=tmp_path)
    assert stats.stopped_early
    manifest = load_manifest(tmp_path)
    # Nothing is wrongly marked missing because of the outage.
    assert all(row.status == "ok" for row in manifest.values())
    assert len(manifest) == 4   # stopped on the 5th fetch


@pytest.mark.unit
def test_universe_has_29_unique_stocks_each_with_a_sector_and_ticker():
    assert len(universe.STOCKS) == 29 == len(set(universe.STOCKS))
    assert set(universe.SECTOR_OF) == set(universe.STOCKS)
    assert all(s in universe.YAHOO_TICKERS for s in universe.SYMBOLS)


@pytest.mark.unit
def test_a_weekend_special_session_is_downloaded_in_full(tmp_path):
    budget_sunday = date(2026, 2, 1)
    client = FakeClient(weekend_sessions=[budget_sunday])
    backfill(client, date(2026, 1, 31), date(2026, 2, 1), root=tmp_path)            # Sat (closed), Sun (Budget)
    manifest = load_manifest(tmp_path)
    assert all(manifest[(budget_sunday, k)].status == "ok" for k in ("fo", "participant", "mto", "indices"))
    assert [k for d, k in manifest if d == date(2026, 1, 31)] == ["indices"]
    assert len(client.calls) == 5
    # Re-running asks NSE for nothing: the closed Saturday is remembered as missing.
    again = FakeClient(weekend_sessions=[budget_sunday])
    assert backfill(again, date(2026, 1, 31), date(2026, 2, 1), root=tmp_path).fetched == 0 and again.calls == []

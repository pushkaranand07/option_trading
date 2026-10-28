"""Point-in-time rules on the real store (docs/PA_31). Opt-in, because the suite never reads the user's cache:

    $env:RESEARCH_STORE_DIR = "$HOME\\.tradingagents\\cache\\quant\\store"; pytest tests/test_research_store_pit.py

Reads only trade_date and known_from. Fails if any row lacks known_from or is public on or before its own
session. The fuller audit against NSE's official calendar is scripts/research_check_pit.py (needs network).
"""

import os
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.analytics import datastore as ds
from tradingagents.research import loader

ROOT = Path(os.environ.get("RESEARCH_STORE_DIR", "-"))
pytestmark = pytest.mark.skipif(not (ROOT / "fo_summary").is_dir(), reason="set RESEARCH_STORE_DIR")


@pytest.mark.parametrize("dataset", loader.DATASETS)
def test_every_row_has_a_known_from_after_its_session(dataset):
    if dataset in loader.BASE and not (ROOT / dataset).is_dir():
        pytest.skip(f"{dataset} not built on this machine")
    files = (sorted((ROOT / dataset).glob("*.parquet")) if dataset in ds.DATASETS + loader.BASE
             else [ROOT.joinpath(*loader.DERIVED[dataset])])
    df = pd.concat((pd.read_parquet(f, columns=["trade_date", "known_from"]) for f in files), ignore_index=True)
    loader.check_point_in_time(df, dataset)


def test_no_price_bar_or_known_from_on_a_day_without_an_nse_session():
    """Sessions: the days the store holds F&O data for, plus the sessions whose F&O file is an archive hole.
    Bars after the last F&O day (today's, before tonight's files) are left to the calendar check in the builder."""
    from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES

    fo = pd.concat(pd.read_parquet(f, columns=["trade_date"]) for f in sorted((ROOT / "fo_summary").glob("*.parquet")))
    sessions = set(pd.to_datetime(fo["trade_date"]).dt.date) | {d for d, k in ARCHIVE_HOLES.items() if "fo" in k}
    first, last = min(sessions), max(sessions)
    p = pd.read_parquet(ROOT.joinpath(*loader.DERIVED["prices"]), columns=["trade_date", "known_from"])
    traded, known = pd.to_datetime(p["trade_date"]).dt.date, pd.to_datetime(p["known_from"]).dt.date
    window = (traded >= first) & (traded <= last)
    off = sorted(set(traded[window & ~traded.isin(sessions)]))
    assert not off, f"price bars on days with no NSE session: {off}"
    bad = sorted(set(known[window & (known <= last) & ~known.isin(sessions)]))
    assert not bad, f"known_from on days with no NSE session: {bad}"


def test_the_loader_never_returns_an_unverified_lot_size(tmp_path):
    """Every UNVERIFIED lot in the stored base comes back empty in lot_size (value in lot_size_unverified)."""
    if not (ROOT / "base_fo_summary").is_dir():
        pytest.skip("base_fo_summary not built on this machine")
    from datetime import date

    files = sorted((ROOT / "base_fo_summary").glob("*.parquet"))
    stored = pd.concat(pd.read_parquet(f, columns=["trade_date", "lot_status", "known_from"]) for f in files)
    open_end = pd.Timestamp(date(2024, 12, 31))
    unverified = stored[(stored["lot_status"] == "UNVERIFIED")]
    assert (pd.to_datetime(unverified["known_from"]) <= open_end).all(), "an UNVERIFIED lot inside a holdout"
    got = loader.load("base_fo_summary", start=date(2010, 1, 1), root=ROOT, log_path=tmp_path / "trials.sqlite")
    got_unverified = got[got["lot_status"] == "UNVERIFIED"]
    assert len(got_unverified) == len(unverified)
    assert got_unverified["lot_size"].isna().all()

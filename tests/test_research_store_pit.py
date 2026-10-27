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
    files = (sorted((ROOT / dataset).glob("*.parquet")) if dataset in ds.DATASETS
             else [ROOT.joinpath(*loader.DERIVED[dataset])])
    df = pd.concat((pd.read_parquet(f, columns=["trade_date", "known_from"]) for f in files), ignore_index=True)
    loader.check_point_in_time(df, dataset)

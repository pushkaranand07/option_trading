"""Re-audit S1 (High, audit 2026-11): the candles symbol was never checked, and the last-good cache built a file path
from it and loaded it with pandas.read_pickle. GET /api/candles/..%5C..%5Cx?tf=1D (no header needed, so any web page
can make the browser send it) loaded an attacker's pickle from outside the cache folder, and loading a pickle can run
code. Now instrument() accepts only plain symbols, and the cache never reads or writes outside its own folder."""

import pickle
from pathlib import Path

import pytest

from webapp import market_data as md


class _Payload:
    """A pickle that, if loaded, writes a marker file: proof that read_pickle ran attacker data."""

    def __init__(self, marker: Path):
        self.marker = marker

    def __reduce__(self):
        return (Path.write_text, (self.marker, "code ran via read_pickle"))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    good = tmp_path / "cache" / "webapp_candles"
    good.mkdir(parents=True)
    monkeypatch.setattr(md, "LAST_GOOD_DIR", good)
    monkeypatch.setattr(md, "_good", {})
    marker = tmp_path / "PICKLE_EXECUTED.txt"
    (tmp_path / "evil_1D.pkl").write_bytes(pickle.dumps(_Payload(marker)))    # outside the cache folder
    return tmp_path, marker


@pytest.mark.unit
@pytest.mark.parametrize("symbol", ["../../evil", "..\\..\\evil", "..%5C..%5Cevil"])
def test_the_cache_never_loads_a_file_outside_its_folder(cache, symbol):
    _, marker = cache
    assert md._last_good(symbol.replace("%5C", "\\"), "1D") is None
    assert not marker.exists(), "an attacker's pickle was loaded"


@pytest.mark.unit
@pytest.mark.parametrize("symbol", ["../../evil", "..\\evil", "C:\\evil", "/etc/x", "a/b", "NIFTY 50", "", "X" * 40, "RELIANCE.NS"])
def test_instrument_refuses_a_symbol_that_is_not_plain(symbol):
    with pytest.raises(md.DataError):
        md.instrument(symbol)


@pytest.mark.unit
@pytest.mark.parametrize("symbol", ["NIFTY", "banknifty", "RELIANCE", "M&M", "BAJAJ-AUTO", "NAM_INDIA"])
def test_real_symbols_still_work(symbol, monkeypatch):
    monkeypatch.setattr(md, "equities", lambda: {})
    monkeypatch.setattr(md, "index_lots", lambda: {})
    assert md.instrument(symbol)["symbol"] == symbol.upper()


@pytest.mark.unit
def test_the_cache_does_not_write_outside_its_folder(cache):
    import pandas as pd

    tmp, _ = cache
    md._good_saved.clear()
    md._remember("../outside", "1D", pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-11-09"])))
    assert not (tmp / "cache" / "outside_1D.pkl").exists() and not list(tmp.glob("outside*"))

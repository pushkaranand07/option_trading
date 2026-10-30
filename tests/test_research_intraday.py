"""Intraday bars are public at their end, carry their source, and are never spliced (docs/PA_38).

No intraday dataset exists yet: any later test that depends on intraday data is "sample size limited by data depth".
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from tradingagents.research import intraday as ix

IST = pytz.timezone("Asia/Kolkata")


def at(h, m):
    return IST.localize(datetime(2024, 11, 4, h, m))


@pytest.mark.unit
@pytest.mark.parametrize("start, interval, want", [
    (at(9, 15), timedelta(minutes=1), at(9, 16)),       # first 1m bar: public at 09:16, not 09:15
    (at(15, 29), timedelta(minutes=1), at(15, 30)),     # last 1m bar
    (at(15, 25), timedelta(minutes=5), at(15, 30)),
    (at(15, 15), timedelta(minutes=60), at(15, 30)),    # last hourly bar is cut at the close
    (at(9, 0), timedelta(minutes=30), at(9, 30)),       # a 30m bar aligned to 09:00 still ends at 09:30
])
def test_known_from_is_the_bar_end_never_its_start(start, interval, want):
    got = ix.bar_known_from(start, interval)
    assert got == want and got > start


@pytest.mark.unit
def test_stamping_uses_bar_end_and_records_the_source():
    idx = pd.DatetimeIndex([at(9, 15), at(9, 16)])
    out = ix.stamp(pd.DataFrame({"close": [1.0, 2.0]}, index=idx), timedelta(minutes=1), "source-a")
    assert list(out["known_from"]) == [at(9, 16), at(9, 17)]
    assert (pd.Series(out["known_from"].to_list(), index=out.index) > out.index.to_series()).all()
    assert set(out["source"]) == {"source-a"}
    with pytest.raises(ValueError):
        ix.stamp(out, timedelta(minutes=1), "")


@pytest.mark.unit
def test_two_sources_are_never_spliced_into_one_series():
    a = pd.DataFrame({"close": [1.0], "source": ["source-a"]})
    b = pd.DataFrame({"close": [1.0], "source": ["source-b"]})
    ix.check_single_source(a)
    with pytest.raises(ValueError, match="mixes sources"):
        ix.check_single_source(pd.concat([a, b]))
    with pytest.raises(ValueError, match="without a source"):
        ix.check_single_source(pd.DataFrame({"close": [1.0]}))

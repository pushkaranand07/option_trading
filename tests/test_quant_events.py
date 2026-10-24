"""Results-day iron butterfly: event dates, timing windows, and trade accounting."""

import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import events as ev


def bs(f, k, t, vol, call):
    if t <= 0:
        return max(f - k, 0.0) if call else max(k - f, 0.0)
    d1 = (math.log(f / k) + vol * vol * t / 2) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return f * n(d1) - k * n(d2) if call else k * n(-d2) - f * n(-d1)


def chain(spots: dict, vols: dict, expiry=date(2026, 3, 31), strikes=range(70, 135, 5)):
    rows = []
    for d, s in spots.items():
        t = (expiry - d).days / 365
        for k in strikes:
            for typ in ("CE", "PE"):
                p = round(max(bs(s, k, t, vols[d], typ == "CE"), 0.05), 2)
                rows.append({"trade_date": d, "symbol": "X", "expiry": expiry, "strike": float(k),
                             "option_type": typ, "close": p, "settle": p, "contracts": 100})
    return pd.DataFrame(rows)


DAYS = [date(2026, 3, d) for d in (2, 3, 4, 5, 6, 9, 10, 11)]


@pytest.mark.unit
def test_results_dates_are_deduplicated_with_the_earliest_intimation():
    rows = [
        {"bm_date": "05-Mar-2026", "bm_purpose": "Financial Results", "bm_desc": "", "bm_timestamp": "10-Feb-2026 18:00:00"},
        {"bm_date": "05-Mar-2026", "bm_purpose": "Board Meeting Intimation",
         "bm_desc": "to approve the Financial results", "bm_timestamp": "01-Feb-2026 09:00:00"},
        {"bm_date": "20-Mar-2026", "bm_purpose": "Fund Raising", "bm_desc": "", "bm_timestamp": "01-Mar-2026 09:00:00"},
    ]
    df = ev.results_events(rows)
    assert list(df["date"]) == [date(2026, 3, 5)]
    assert df["announced"].iloc[0] == datetime(2026, 2, 1, 9, 0)


@pytest.mark.unit
def test_windows_straddle_the_event_and_need_advance_notice():
    events = pd.DataFrame({"date": [date(2026, 3, 5), date(2026, 3, 7), date(2026, 3, 10)],
                           "announced": [datetime(2026, 2, 1), datetime(2026, 2, 1), datetime(2026, 3, 9, 20)]})
    w = ev.event_windows(DAYS, events)
    # Thursday meeting: in Wed, out Fri. Saturday meeting: in Fri, out Mon. Announced the evening
    # before entry (9-Mar for a 9-Mar entry) is not known in advance: skipped.
    assert w == [(date(2026, 3, 5), date(2026, 3, 4), date(2026, 3, 6)),
                 (date(2026, 3, 7), date(2026, 3, 6), date(2026, 3, 9))]


@pytest.mark.unit
def test_iv_crush_pays_and_a_big_move_loses_at_most_the_defined_risk():
    vols_crush = {d: (0.60 if d <= date(2026, 3, 4) else 0.25) for d in DAYS}
    calm = ev.window_trade(ev._prepare(chain(dict.fromkeys(DAYS, 100.0), vols_crush)), "X", 50,
                           date(2026, 3, 4), date(2026, 3, 6))
    assert calm is not None and calm.pnl > 0
    assert calm.strikes["short_put"] == calm.strikes["short_call"] == 100.0
    straddle = calm.entry_prices["short_put"] + calm.entry_prices["short_call"]
    assert calm.strikes["long_call"] - 100 >= straddle * 0.97 and 100 - calm.strikes["long_put"] >= straddle * 0.97

    jump = {d: (100.0 if d <= date(2026, 3, 4) else 130.0) for d in DAYS}
    hit = ev.window_trade(ev._prepare(chain(jump, vols_crush)), "X", 50, date(2026, 3, 4), date(2026, 3, 6))
    assert hit.pnl < 0
    # Before charges the loss is the defined risk plus exit slippage on the far (worthless) side.
    per_unit = hit.pnl / hit.lot + hit.charges / hit.lot
    assert -hit.max_risk - 0.25 <= per_unit < -0.9 * hit.max_risk


@pytest.mark.unit
def test_no_trade_when_the_only_expiry_falls_inside_the_window():
    c = chain(dict.fromkeys(DAYS, 100.0), dict.fromkeys(DAYS, 0.3), expiry=date(2026, 3, 6))
    assert ev.window_trade(ev._prepare(c), "X", 50, date(2026, 3, 4), date(2026, 3, 6)) is None


@pytest.mark.unit
def test_quiet_entries_skip_sessions_near_results():
    q = ev.quiet_entries(DAYS, [date(2026, 3, 5)], buffer=1)
    assert q == [0, 1, 5, 6, 7]                       # 4-, 5-, 6-Mar are within one session of 5-Mar
    assert np.all(np.diff(q) > 0)

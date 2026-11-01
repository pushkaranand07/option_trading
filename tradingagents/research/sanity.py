"""Automated sanity checks for the feature tables: units, look-ahead, stale values (docs/pipeline_audit_v1.md).

Ranges come from what the quantity is, not from results: an annualised volatility has a median between 5% and 150%, a share lies in 0 to 1.
Each check returns the problems it found. A planted bug must produce one (tests/test_pipeline_sanity.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# name prefix or exact name -> (lowest allowed value, highest allowed value, lowest median, highest median); None means no limit
VOL = (0.0, 10.0, 0.05, 1.5)
RANGES = {
    "garch_h": VOL, "rv_": (0.0, 20.0, 0.05, 1.5), "parkinson_20": VOL, "garman_klass_20": VOL, "atm_iv_front": (0.0, 5.0, 0.05, 1.5), "atm_iv_next": (0.0, 5.0, 0.05, 1.5),
    "ret_1": (-0.7, 0.7, -0.01, 0.01), "ret_5": (-3.0, 3.0, -0.05, 0.05), "gap_1": (-0.7, 0.7, -0.02, 0.02), "range_1": (0.0, 1.0, 0.0, 0.2), "close_loc_1": (0.0, 1.0, 0.2, 0.8),
    "oi_near_share": (0.0, 1.0, None, None), "oi_rel_252": (0.0, 1.0, None, None), "atm_iv_rel_252": (0.0, 1.0, None, None), "deliv_pct": (0.0, 100.0, 5.0, 90.0), "vix": (5.0, 120.0, 8.0, 40.0),
    "breadth_up": (0.0, 1.0, 0.2, 0.8), "rank_": (0.0, 1.0, 0.4, 0.6), "day_of_week": (0, 6, None, None), "days_to_expiry": (0, 120, None, None), "pcr_": (0.0, None, 0.05, 5.0),
    "fii_": (-1.0, 1.0, None, None), "dii_": (-1.0, 1.0, None, None), "client_": (-1.0, 1.0, None, None), "pro_": (-1.0, 1.0, None, None),
}
EXACT_ONLY = {"ret_1", "ret_5", "vix"}
# legitimately repeat from one session to the next
STEP_LIKE = ("day_of_week", "days_", "expiry_week", "board_", "results_", "nifty_above", "disc_flag", "oi_reset_flag", "sessions_since", "n_liquid", "rank_")
STALE_LIMIT = 0.50


def range_for(name: str) -> tuple | None:
    if name in RANGES and name in EXACT_ONLY:
        return RANGES[name]
    return next((v for k, v in RANGES.items() if k not in EXACT_ONLY and name.startswith(k)), None)


def check_ranges(table: pd.DataFrame) -> list[str]:
    """Values or medians outside what the quantity can be: this is how a unit error shows."""
    problems = []
    for c in table.columns:
        rule = range_for(c)
        if rule is None:
            continue
        v = pd.to_numeric(table[c], errors="coerce").dropna()
        if not len(v):
            continue
        low, high, med_low, med_high = rule
        if low is not None and v.min() < low:
            problems.append(f"{c}: minimum {v.min():.4g} below {low}")
        if high is not None and v.max() > high:
            problems.append(f"{c}: maximum {v.max():.4g} above {high}")
        med = float(v.median())
        if med_low is not None and med < med_low:
            problems.append(f"{c}: median {med:.4g} below {med_low}")
        if med_high is not None and med > med_high:
            problems.append(f"{c}: median {med:.4g} above {med_high}")
    return problems


def check_lookahead(full: pd.DataFrame, cut: pd.DataFrame, keys: list[str], columns: list[str]) -> list[str]:
    """Values for one date from all data against values rebuilt from data cut before it: any difference is look-ahead."""
    x = full.merge(cut, on=keys, how="outer", suffixes=("", "__cut"), indicator=True)
    problems = [f"{int((x['_merge'] != 'both').sum())} rows on one side only"] if (x["_merge"] != "both").any() else []
    both = x[x["_merge"] == "both"]
    for c in columns:
        a, b = both[c].to_numpy(dtype=float), both[f"{c}__cut"].to_numpy(dtype=float)
        same = (np.isnan(a) & np.isnan(b)) | np.isclose(a, b, rtol=1e-9, atol=1e-12)
        if not same.all():
            problems.append(f"{c}: {int((~same).sum())} values differ")
    return problems


def check_stale(table: pd.DataFrame, by: str | None, order: str, columns: list[str], limit: float = STALE_LIMIT) -> list[str]:
    """Columns whose value equals the row before more often than ``limit``: a value carried forward. Step-like columns are skipped."""
    problems = []
    t = table.sort_values(([by] if by else []) + [order])
    for c in columns:
        if c.startswith(STEP_LIKE):
            continue
        s = pd.to_numeric(t[c], errors="coerce")
        prev = s.groupby(t[by]).shift(1) if by else s.shift(1)
        both = s.notna() & prev.notna()
        if both.sum() >= 20:
            share = float((s[both] == prev[both]).mean())
            if share > limit:
                problems.append(f"{c}: {share:.0%} of values equal the previous session")
    return problems

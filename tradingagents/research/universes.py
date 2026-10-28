"""Point-in-time universe membership on the stored base (docs/data/universes_v1.json, docs/PA_37).

Pure functions over a ``base_fo_summary`` frame from the research loader; no store paths. The rules are fixed in the
addendum, which references the frozen split file's hash and the symbol map's hash and was written before any ranking
ran. Membership on session ``D`` is decided from rows whose ``known_from`` is ``D``, so it is reproducible from data
truncated at the session before ``D``.

:func:`sealed_top_n` ranks a year whose inputs lie in the locked holdout: its only result is the member set; turnover,
ranks and rank gaps never leave it, not even in an error.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.research import splits

ROOT = Path(__file__).resolve().parents[2]
ADDENDUM = ROOT / "docs" / "data" / "universes_v1.json"
SYMBOL_MAP = ROOT / "docs" / "data" / "symbol_map_v1.csv"
TOP_N = 100


class AddendumMismatch(RuntimeError):
    """The universe addendum no longer matches the split file or the symbol map it references."""


class SealedRankingError(RuntimeError):
    """A sealed ranking failed; by design the error carries no input values."""


def _lf_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def addendum() -> dict:
    """The rules, after checking the hashes they reference."""
    rules = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    if rules["addendum_to"]["sha256"] != splits.SPLITS_SHA256:
        raise AddendumMismatch("universes_v1.json references another split file")
    if rules["symbol_map"]["sha256_lf"] != _lf_hash(SYMBOL_MAP):
        raise AddendumMismatch("symbol_map_v1.csv changed after the addendum was written")
    return rules


def series_ids(symbol_map: pd.DataFrame, symbols: Iterable[str]) -> dict[str, str]:
    """symbol -> series id: mapped links only, chained as listed; the id is the chain's last symbol."""
    links = {o: n for o, n, s in zip(symbol_map["old"], symbol_map["new"], symbol_map["status"], strict=True)
             if s == "mapped"}
    out = {}
    for sym in set(symbols) | set(links) | set(links.values()):
        cur, seen = sym, {sym}
        while cur in links:
            cur = links[cur]
            if cur in seen:
                raise ValueError(f"symbol map has a cycle through {sym}")
            seen.add(cur)
        out[sym] = cur
    return out


def with_series(summary: pd.DataFrame, ids: dict[str, str]) -> pd.DataFrame:
    s = summary.copy()
    s["series"] = s["symbol"].map(ids).fillna(s["symbol"])
    s["known_from"] = pd.to_datetime(s["known_from"]).dt.date
    s["trade_date"] = pd.to_datetime(s["trade_date"]).dt.date
    return s


def _turnover(summary: pd.DataFrame, year: int) -> pd.Series:
    rows = summary[(pd.to_datetime(summary["trade_date"]).dt.year == year - 1) & (summary["kind"] == "stock")]
    if (pd.to_datetime(rows["trade_date"]).dt.year >= year).any():      # the modelled year never enters
        raise AssertionError("modelled-year row in ranking input")
    return (rows["fut_turnover"].fillna(0) + rows["opt_turnover"].fillna(0)).groupby(rows["series"]).sum()


def _top(turnover: pd.Series, n: int) -> list[str]:
    order = sorted(turnover.items(), key=lambda kv: (-kv[1], kv[0]))   # turnover desc, then series id asc
    return [s for s, _ in order[:n]]


def sealed_top_n(summary: pd.DataFrame, year: int, n: int = TOP_N) -> frozenset[str]:
    """The top-``n`` stock series for ``year`` by ``year - 1`` turnover, as a set and nothing else."""
    failed, result = False, None
    try:
        result = frozenset(_top(_turnover(summary, year), n))
    except Exception:      # noqa: BLE001 - every failure is reported the same way, with no values
        failed = True
    if failed:             # raised outside the except block, so no original exception is attached
        raise SealedRankingError(f"ranking for {year} failed; details are sealed")
    return result


def open_ranking(summary: pd.DataFrame, year: int) -> pd.DataFrame:
    """Turnover and rank for ``year``'s ranking, only when its inputs are outside the locked holdout."""
    if date(year - 1, 12, 31) >= splits.periods()["final_holdout"].start:
        raise PermissionError(f"ranking inputs for {year} are in the locked holdout: use sealed_top_n")
    t = _turnover(summary, year)
    order = _top(t, len(t))
    return pd.DataFrame({"series": order, "turnover": [t[s] for s in order], "rank": range(1, len(order) + 1)})


def members_by_year(summary: pd.DataFrame, years: Iterable[int], n: int = TOP_N) -> dict[int, frozenset[str]]:
    return {y: sealed_top_n(summary, y, n) for y in years}


def membership(summary: pd.DataFrame, universe: str, top: dict[int, frozenset[str]] | None = None,
               through: date | None = None) -> pd.DataFrame:
    """One row per (session D, series) that is a member on D: columns date, series, symbol, kind."""
    rows = summary[summary["kind"].isin(["index", "stock"])]
    if through is not None:
        rows = rows[rows["known_from"] <= through]
    rows = rows.assign(date=rows["known_from"], year=pd.to_datetime(rows["known_from"]).dt.year)
    if universe == "U1":
        rows = rows[rows["year"] >= 2011]
        keep = rows["kind"] == "index"
        for y, members in (top or {}).items():
            keep |= (rows["year"] == y) & (rows["kind"] == "stock") & rows["series"].isin(members)
        rows = rows[keep]
    elif universe != "U2":
        raise ValueError(f"unknown universe {universe!r}")
    return (rows[["date", "series", "symbol", "kind"]].drop_duplicates(["date", "series"])
            .sort_values(["date", "series"]).reset_index(drop=True))


def members_on(summary: pd.DataFrame, day: date, universe: str, n: int = TOP_N) -> frozenset[str]:
    """Members on ``day`` using only rows public by ``day`` (known_from <= day)."""
    known = summary[summary["known_from"] <= day]
    top = {day.year: sealed_top_n(known, day.year, n)} if universe == "U1" and day.year >= 2011 else {}
    m = membership(known, universe, top)
    return frozenset(m.loc[m["date"] == day, "series"])


def spells(member_rows: pd.DataFrame, sessions: list[date]) -> pd.DataFrame:
    """Membership dates: runs of consecutive sessions per series (start, end, sessions)."""
    pos = {d: i for i, d in enumerate(sorted(sessions))}
    m = member_rows.assign(i=member_rows["date"].map(pos)).sort_values(["series", "i"])
    run = (m["i"].diff() != 1) | (m["series"] != m["series"].shift())
    m["run"] = run.cumsum()
    return (m.groupby("run").agg(series=("series", "first"), start=("date", "min"), end=("date", "max"),
                                 sessions=("date", "size")).reset_index(drop=True))

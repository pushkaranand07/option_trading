"""Index volume that means something, and index bars that are actually there.

Yahoo's ``^NSEI`` / ``^NSEBANK`` volume is not the index's traded volume: on
22-Oct-2026 it read 391,600 and 285,800 for two sessions and 0 for the latest,
while one constituent (RELIANCE) alone traded ~15 million shares. ``^INDIAVIX``
volume is always 0. Volume patterns read from those columns (spikes, dry-ups,
breakout-on-volume, OBV) are noise. Yahoo also drops index bars: ``^NSEI`` had
no 21-Oct-2026 bar though NSE traded that day.

Fix:

- ``assess_volume`` judges a volume column unreliable (zeros, a zero latest bar,
  or far below what the constituents trade) and says why.
- ``constituent_turnover_proxy`` sums ₹ traded value (close × volume) over the
  index's members *as of each date* (point-in-time, so it carries no
  survivorship bias) and reports per-date coverage.
- ``sanitize_index_ohlcv`` blanks the unreliable volume, adds the proxy in a
  clearly named column (``volume_proxy_turnover_cr``) with ``volume_source``,
  and lists sessions the series is missing per the NSE calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import yfinance as yf

from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar

INDEX_TICKERS = frozenset({"^NSEI", "^NSEBANK", "^INDIAVIX", "^CNXIT", "^CNXFIN", "^NSMIDCP", "^CRSLDX"})

# Below this share of zero bars, and with a non-zero latest bar, a volume
# column is at least internally consistent.
MAX_ZERO_SHARE = 0.05
# Index "volume" this many times smaller than the constituents' summed volume
# cannot be the index's traded volume.
MIN_RATIO_TO_CONSTITUENTS = 0.05


def is_nse_index(ticker: str) -> bool:
    return ticker.strip().upper() in INDEX_TICKERS


@dataclass
class VolumeAssessment:
    reliable: bool
    reasons: list[str] = field(default_factory=list)


def assess_volume(volume: pd.Series, constituent_volume: pd.Series | None = None) -> VolumeAssessment:
    reasons = []
    vol = pd.to_numeric(volume, errors="coerce")
    if vol.empty or vol.isna().all():
        return VolumeAssessment(False, ["no volume values"])
    zero_share = float((vol.fillna(0) == 0).mean())
    if zero_share > MAX_ZERO_SHARE:
        reasons.append(f"{zero_share:.0%} of bars have zero volume")
    if vol.iloc[-1] == 0 or pd.isna(vol.iloc[-1]):
        reasons.append("latest bar has zero/missing volume")
    if constituent_volume is not None:
        aligned = constituent_volume.reindex(vol.index)
        ratio = (vol / aligned).replace([float("inf")], pd.NA).dropna()
        if not ratio.empty and float(ratio.median()) < MIN_RATIO_TO_CONSTITUENTS:
            reasons.append(f"median index volume is {float(ratio.median()):.3%} of its constituents' "
                           "summed volume — not the index's traded volume")
    return VolumeAssessment(not reasons, reasons)


def _download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    try:
        data = yf.download(tickers, start=start.isoformat(), end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
                           auto_adjust=False, progress=False, group_by="column", threads=True)
    except Exception as exc:   # yfinance raises a zoo of types; all mean "no answer"
        raise VendorUnavailableError(f"Yahoo download failed for {len(tickers)} constituents: {exc}") from exc
    if data is None or data.empty:
        raise VendorUnavailableError("Yahoo returned no constituent data")
    data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
    return data


def constituent_turnover_proxy(
    index: str,
    start: date,
    end: date,
    store=None,
    download=_download,
) -> pd.DataFrame:
    """Per session: ₹ crore traded across the members on that date, summed volume, and coverage."""
    from tradingagents.dataflows.vendors.nse.indices import ConstituentStore

    store = store or ConstituentStore()
    memberships = {}
    tickers: set[str] = set()
    for day in pd.bdate_range(start, end):
        m = store.members_as_of(index, day.date())
        memberships[day.normalize()] = m
        tickers |= set(m.yahoo_tickers())
    data = download(sorted(tickers), start, end)
    close, volume = data["Close"], data["Volume"]
    rows = []
    for day in close.index:
        m = memberships.get(day) or store.members_as_of(index, day.date())
        cols = [t for t in m.yahoo_tickers() if t in close.columns]
        traded = (close.loc[day, cols] * volume.loc[day, cols]).dropna()
        rows.append({
            "date": day,
            "turnover_cr": float(traded.sum()) / 1e7,
            "constituent_volume": float(volume.loc[day, cols].sum(skipna=True)),
            "coverage": len(traded) / max(len(m.symbols), 1),
            "survivorship_safe": m.survivorship_safe,
        })
    return pd.DataFrame(rows).set_index("date")


@dataclass
class SanitizedIndex:
    frame: pd.DataFrame
    assessment: VolumeAssessment
    missing_sessions: list[date]
    unexpected_bars: list[date]
    notes: list[str]

    def to_text(self) -> str:
        lines = []
        if not self.assessment.reliable:
            lines.append("Vendor volume for this index is UNRELIABLE and was removed: "
                         + "; ".join(self.assessment.reasons) + ".")
            lines.append("Use `volume_proxy_turnover_cr` (₹ crore traded across point-in-time "
                         "constituents) for volume analysis; it is a proxy, label it as such.")
        if self.missing_sessions:
            lines.append("Vendor series is MISSING NSE sessions: "
                         + ", ".join(f"{d:%d-%b-%Y}" for d in self.missing_sessions)
                         + ". Do not treat the gap as a price move.")
        if self.unexpected_bars:
            lines.append("Bars on non-session dates (check vendor): "
                         + ", ".join(f"{d:%d-%b-%Y}" for d in self.unexpected_bars))
        return "\n".join(lines + self.notes)


def sanitize_index_ohlcv(
    df: pd.DataFrame,
    index: str,
    calendar: NSECalendar,
    proxy: pd.DataFrame | None = None,
) -> SanitizedIndex:
    """Replace unreliable index volume with a labelled proxy and report calendar gaps.

    ``df`` is indexed by date with a ``Volume`` column. ``proxy`` is the output
    of ``constituent_turnover_proxy`` (omit it to only blank and flag).
    """
    frame = df.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if dates.tz is not None:
        dates = dates.tz_localize(None)     # keep the IST wall-clock date
    frame.index = dates.normalize()
    constituent_volume = proxy["constituent_volume"] if proxy is not None else None
    assessment = assess_volume(frame["Volume"], constituent_volume)
    notes = []
    if not assessment.reliable:
        frame["Volume"] = pd.NA
        frame["volume_source"] = "unavailable"
    else:
        frame["volume_source"] = "vendor"
    if proxy is not None:
        frame["volume_proxy_turnover_cr"] = proxy["turnover_cr"].reindex(frame.index)
        frame["proxy_coverage"] = proxy["coverage"].reindex(frame.index)
        if not assessment.reliable:
            frame["volume_source"] = "constituent_turnover_proxy"
        if not bool(proxy["survivorship_safe"].all()):
            notes.append("Proxy membership is not survivorship-safe for part of the window "
                         "(see constituent change log).")
    have = {ts.date() for ts in frame.index}
    start, end = min(have), max(have)
    return SanitizedIndex(frame, assessment, calendar.missing_sessions(have, start, end),
                          calendar.unexpected_bars(have), notes)

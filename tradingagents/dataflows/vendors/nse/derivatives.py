"""F&O contract facts from NSE's own files: bhavcopies, lot sizes, expiries.

Lot sizes are revised periodically (the NIFTY lot was 50 in Jan-2024 and is 65
in Oct-2026, per the bhavcopies themselves), weekly expiries have been cut back, and
the expiry weekday has moved — and still shifts around holidays (the NIFTY
series listed on 22-Oct-2026 expire on Tuesdays except 09-Nov and 23-Nov, two
Mondays before holidays). Any constant for these is wrong for some period.

So nothing is hardcoded. The F&O bhavcopy is the source of truth:

- ``fo_bhavcopy(day)`` loads the day's file in either format NSE has used —
  the UDiFF file (from 08-Jul-2024, carries ``NewBrdLotQty``) and the legacy
  ``foDDMONYYYYbhav.csv`` (no lot size column) — into one schema.
- ``LotSizeHistory`` stores observed lot sizes as dated runs. Legacy files have
  no lot column, so their lot is derived from turnover / (contracts × price)
  over the day's futures and labelled ``derived``.
- Lookups between two observations with different lots say the change date is
  uncertain instead of guessing.
- Expiries come from the contracts that actually traded (history) or from
  NSE's contract-info API (live).
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.files import replace_file
from tradingagents.dataflows.vendors.nse.client import NSEDataNotPublishedError

UDIFF_SINCE = date(2024, 7, 8)

UNIFIED_COLUMNS = [
    "trade_date", "instrument", "symbol", "expiry", "strike", "option_type",
    "open", "high", "low", "close", "settle", "underlying_price",
    "open_interest", "oi_change", "contracts", "turnover", "lot_size", "format",
]

_UDIFF_INSTRUMENT = {"IDO": "OPTIDX", "IDF": "FUTIDX", "STO": "OPTSTK", "STF": "FUTSTK"}

# Yahoo / common names -> NSE F&O symbols.
FNO_SYMBOLS = {
    "^NSEI": "NIFTY", "NIFTY50": "NIFTY", "NIFTY 50": "NIFTY",
    "^NSEBANK": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY",
    "NIFTY_FIN_SERVICE.NS": "FINNIFTY", "^CNXFIN": "FINNIFTY",
    "NIFTY_MID_SELECT.NS": "MIDCPNIFTY",
}


def fno_symbol(ticker: str) -> str:
    """The NSE F&O symbol for a Yahoo-style ticker (``RELIANCE.NS`` -> ``RELIANCE``)."""
    upper = ticker.strip().upper()
    if upper in FNO_SYMBOLS:
        return FNO_SYMBOLS[upper]
    for suffix in (".NS", ".BO"):
        if upper.endswith(suffix):
            return upper[: -len(suffix)]
    return upper


def udiff_url(day: date) -> str:
    return f"/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def legacy_url(day: date) -> str:
    mon = day.strftime("%b").upper()
    return f"/content/historical/DERIVATIVES/{day:%Y}/{mon}/fo{day:%d}{mon}{day:%Y}bhav.csv.zip"


def _unzip_csv(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return pd.read_csv(archive.open(archive.namelist()[0]))


def normalize_udiff(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["TradDt"]).dt.date,
        "instrument": raw["FinInstrmTp"].map(_UDIFF_INSTRUMENT).fillna(raw["FinInstrmTp"]),
        "symbol": raw["TckrSymb"].astype(str).str.strip(),
        "expiry": pd.to_datetime(raw["XpryDt"]).dt.date,
        "strike": pd.to_numeric(raw["StrkPric"], errors="coerce"),
        "option_type": raw["OptnTp"].where(raw["OptnTp"].isin(["CE", "PE"])),
        "open": raw["OpnPric"], "high": raw["HghPric"], "low": raw["LwPric"],
        "close": raw["ClsPric"], "settle": raw["SttlmPric"],
        "underlying_price": raw["UndrlygPric"],
        "open_interest": raw["OpnIntrst"], "oi_change": raw["ChngInOpnIntrst"],
        # Contracts, not units: turnover / (volume × lot) comes out at strike + premium.
        "contracts": raw["TtlTradgVol"],
        "turnover": raw["TtlTrfVal"],
        "lot_size": raw["NewBrdLotQty"],
    })
    df["format"] = "udiff"
    return df[UNIFIED_COLUMNS]


def normalize_legacy(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.rename(columns=lambda c: str(c).strip())
    option_type = raw["OPTION_TYP"].where(raw["OPTION_TYP"].isin(["CE", "PE"]))
    df = pd.DataFrame({
        "trade_date": pd.to_datetime(raw["TIMESTAMP"], format="%d-%b-%Y").dt.date,
        "instrument": raw["INSTRUMENT"].str.strip(),
        "symbol": raw["SYMBOL"].astype(str).str.strip(),
        "expiry": pd.to_datetime(raw["EXPIRY_DT"], format="%d-%b-%Y").dt.date,
        "strike": pd.to_numeric(raw["STRIKE_PR"], errors="coerce"),
        "option_type": option_type,
        "open": raw["OPEN"], "high": raw["HIGH"], "low": raw["LOW"],
        "close": raw["CLOSE"], "settle": raw["SETTLE_PR"],
        "underlying_price": pd.NA,
        "open_interest": raw["OPEN_INT"], "oi_change": raw["CHG_IN_OI"],
        "contracts": raw["CONTRACTS"],
        "turnover": raw["VAL_INLAKH"] * 1e5,
        "lot_size": pd.NA,
    })
    df["format"] = "legacy"
    return df[UNIFIED_COLUMNS]


def fo_bhavcopy(day: date, client=None) -> pd.DataFrame:
    """The day's F&O bhavcopy in the unified schema, whichever format NSE published it in."""
    from tradingagents.dataflows.vendors.nse.client import default_client

    client = client or default_client()
    attempts = [(udiff_url, normalize_udiff), (legacy_url, normalize_legacy)]
    if day < UDIFF_SINCE:
        attempts.reverse()
    for url_for, normalize in attempts:
        try:
            fetched = client.get_archive(url_for(day))
        except NSEDataNotPublishedError:
            continue
        df = normalize(_unzip_csv(fetched.data))
        df.attrs["source"] = fetched.provenance()
        return df
    raise NoMarketDataError("F&O bhavcopy", detail=f"no file for {day:%d-%b-%Y} (holiday or not yet published)")


def derive_legacy_lot_sizes(df: pd.DataFrame) -> dict[str, int]:
    """Lot per symbol from a legacy file: turnover / (contracts × close), over its futures.

    Turnover is at traded prices and the close is one price, so each contract's
    estimate is a little off; the median across the symbol's futures, rounded,
    lands on the lot unless the day moved several percent.
    """
    futures = df[df["instrument"].isin(["FUTIDX", "FUTSTK"]) & (df["contracts"] > 0) & (df["close"] > 0)]
    estimate = futures["turnover"] / (futures["contracts"] * futures["close"])
    return {sym: int(round(val)) for sym, val in estimate.groupby(futures["symbol"]).median().items()}


@dataclass(frozen=True)
class LotSize:
    symbol: str
    on: date
    lot_size: int
    confidence: str          # "observed" | "between_same" | "extrapolated"
    source: str              # "bhavcopy" | "derived"
    note: str = ""


class LotSizeHistory:
    """Observed lot sizes as runs of (first_seen, last_seen, lot, source), per symbol."""

    EXTRAPOLATE_DAYS = 31     # beyond the last observation, trust it this long and no longer

    def __init__(self, path: Path | None = None):
        self.path = path or Path(get_config()["data_cache_dir"]) / "nse" / "lot_size_history.json"
        self.runs: dict[str, list[list]] = {}
        if self.path.exists():
            self.runs = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.runs, indent=1, sort_keys=True)
        replace_file(self.path, lambda tmp: Path(tmp).write_text(text, encoding="utf-8"))

    def record(self, symbol: str, day: date, lot: int, source: str = "bhavcopy") -> None:
        runs = self.runs.setdefault(symbol, [])
        iso = day.isoformat()
        for run in runs:
            if run[0] <= iso <= run[1]:
                if run[2] != lot and source == "bhavcopy":
                    run[2], run[3] = lot, source     # an exact file overrides a derived estimate
                return
        runs.append([iso, iso, lot, source])
        runs.sort(key=lambda r: r[0])
        merged = [runs[0]]
        for run in runs[1:]:
            last = merged[-1]
            if run[2] == last[2]:
                last[1] = max(last[1], run[1])
                if run[3] == "bhavcopy":
                    last[3] = "bhavcopy"
            else:
                merged.append(run)
        self.runs[symbol] = merged

    def update_from_bhavcopy(self, df: pd.DataFrame) -> int:
        """Record every symbol's lot from a unified bhavcopy; returns how many were recorded."""
        if df.empty:
            return 0
        day = df["trade_date"].iloc[0]
        if df["format"].iloc[0] == "udiff":
            lots = df.dropna(subset=["lot_size"]).groupby("symbol")["lot_size"].agg(lambda s: int(s.mode().iloc[0]))
            items, source = lots.items(), "bhavcopy"
        else:
            items, source = derive_legacy_lot_sizes(df).items(), "derived"
        count = 0
        for symbol, lot in items:
            self.record(symbol, day, int(lot), source)
            count += 1
        return count

    def lot_size(self, symbol: str, day: date) -> LotSize:
        runs = self.runs.get(symbol)
        if not runs:
            raise NoMarketDataError(symbol, detail="no lot size observed; ingest an F&O bhavcopy first")
        iso = day.isoformat()
        for i, (first, last, lot, source) in enumerate(runs):
            if first <= iso <= last:
                return LotSize(symbol, day, lot, "observed", source)
            if iso < first:
                if i == 0:
                    raise NoMarketDataError(
                        symbol, detail=f"{day} is before the first observed lot ({first}); ingest older bhavcopies")
                prev = runs[i - 1]
                raise NoMarketDataError(
                    symbol, detail=f"lot changed from {prev[2]} to {lot} between {prev[1]} and {first}; "
                    f"{day} falls in that gap — ingest the bhavcopy for {day} to settle it")
        first, last, lot, source = runs[-1]
        if (day - date.fromisoformat(last)).days <= self.EXTRAPOLATE_DAYS:
            return LotSize(symbol, day, lot, "extrapolated", source,
                           f"last observed {last}; revisions are announced in advance — re-check")
        raise NoMarketDataError(symbol, detail=f"last observed lot is from {last}; refresh from a recent bhavcopy")


def expiries_from_bhavcopy(df: pd.DataFrame, symbol: str) -> list[date]:
    """Expiries of the symbol's options that traded in this file, ascending."""
    opts = df[(df["symbol"] == symbol) & df["option_type"].notna()]
    return sorted(set(opts["expiry"]))


def live_contract_info(symbol: str, client=None) -> dict:
    """Live expiries and strikes from NSE (``/api/option-chain-contract-info``)."""
    from tradingagents.dataflows.vendors.nse.client import default_client

    client = client or default_client()
    fetched = client.get_json("/api/option-chain-contract-info", {"symbol": symbol}, ttl=3600)
    expiries = [datetime.strptime(x, "%d-%b-%Y").date() for x in fetched.data.get("expiryDates", [])]
    return {"symbol": symbol, "expiries": sorted(expiries),
            "strikes": fetched.data.get("strikePrice", []), "source": fetched.provenance()}


def describe_expiries(expiries: list[date]) -> str:
    """Expiries with their weekdays, so a shifted (holiday) expiry is visible."""
    return ", ".join(f"{d:%d-%b-%Y} ({d:%a})" for d in expiries)


def latest_bhavcopy(on_or_before: date, client=None, max_back: int = 7) -> pd.DataFrame:
    """The most recent bhavcopy on or before a date (skips holidays and unpublished days)."""
    day = on_or_before
    for _ in range(max_back):
        try:
            return fo_bhavcopy(day, client)
        except NoMarketDataError:
            day -= timedelta(days=1)
    raise NoMarketDataError("F&O bhavcopy", detail=f"none found in the {max_back} days to {on_or_before}")


def delivery_url(day: date) -> str:
    return f"/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"


def delivery_data(day: date, client=None) -> pd.DataFrame:
    """Per-stock traded and delivered quantity / delivery % for one session (EQ series)."""
    from tradingagents.dataflows.vendors.nse.client import default_client

    client = client or default_client()
    try:
        fetched = client.get_archive(delivery_url(day))
    except NSEDataNotPublishedError as exc:
        raise NoMarketDataError("delivery data", detail=f"no file for {day:%d-%b-%Y}") from exc
    df = pd.read_csv(io.BytesIO(fetched.data))
    df.columns = [c.strip() for c in df.columns]
    for col in ("SYMBOL", "SERIES"):
        df[col] = df[col].astype(str).str.strip()
    df = df[df["SERIES"] == "EQ"].copy()
    df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
    df["DELIV_QTY"] = pd.to_numeric(df["DELIV_QTY"], errors="coerce")
    df.attrs["source"] = fetched.provenance()
    return df


def legacy_equity_url(day: date) -> str:
    mon = day.strftime("%b").upper()
    return f"/content/historical/EQUITIES/{day:%Y}/{mon}/cm{day:%d}{mon}{day:%Y}bhav.csv.zip"


def equity_bhavcopy(day: date, client=None) -> pd.DataFrame:
    """Unadjusted EQ-series OHLC and volume for one session: ``symbol, open, high, low, close, volume``.

    Uses the full bhavcopy (with delivery) where NSE has it, the legacy CM
    bhavcopy otherwise. Prices are as traded that day, not split-adjusted.
    """
    from tradingagents.dataflows.vendors.nse.client import default_client

    client = client or default_client()
    try:
        full = delivery_data(day, client)
        return pd.DataFrame({
            "symbol": full["SYMBOL"].to_numpy(),
            "open": pd.to_numeric(full["OPEN_PRICE"], errors="coerce").to_numpy(),
            "high": pd.to_numeric(full["HIGH_PRICE"], errors="coerce").to_numpy(),
            "low": pd.to_numeric(full["LOW_PRICE"], errors="coerce").to_numpy(),
            "close": pd.to_numeric(full["CLOSE_PRICE"], errors="coerce").to_numpy(),
            "volume": pd.to_numeric(full["TTL_TRD_QNTY"], errors="coerce").to_numpy(),
        })
    except NoMarketDataError:
        pass
    try:
        fetched = client.get_archive(legacy_equity_url(day))
    except NSEDataNotPublishedError as exc:
        raise NoMarketDataError("equity bhavcopy", detail=f"no file for {day:%d-%b-%Y}") from exc
    raw = _unzip_csv(fetched.data).rename(columns=lambda c: str(c).strip())
    raw = raw[raw["SERIES"].astype(str).str.strip() == "EQ"]
    return pd.DataFrame({
        "symbol": raw["SYMBOL"].astype(str).str.strip().to_numpy(),
        "open": raw["OPEN"].to_numpy(dtype=float), "high": raw["HIGH"].to_numpy(dtype=float),
        "low": raw["LOW"].to_numpy(dtype=float), "close": raw["CLOSE"].to_numpy(dtype=float),
        "volume": raw["TOTTRDQTY"].to_numpy(dtype=float),
    })

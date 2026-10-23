"""Index constituents as of a date — the guard against survivorship bias.

Backtesting "Nifty 50 stocks" over 2015–2026 with today's member list tests the
winners only: the companies that were dropped (and their losses) are missing,
and stocks are "held" before they ever joined. The universe on date *t* must be
the members on date *t*.

NSE publishes the *current* list as a CSV (``ind_nifty50list.csv``) but no free,
machine-readable membership history; changes are announced in press-release
PDFs. So:

- Every fetch of the current list is stored as a dated snapshot. Snapshots
  accumulate, so the store becomes point-in-time on its own over time.
- Past membership is reconstructed backwards from the earliest snapshot with a
  change log (``index_changes.json``: date, added, removed), filled from NSE's
  announcements. The log ships empty: nothing is invented.
- Every answer says how it was obtained and whether it is survivorship-safe.
  A date before the change log's coverage is answered with the nearest list,
  flagged ``survivorship_safe=False``, so a backtest report can say so.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.files import replace_file

CONSTITUENT_FILES = {
    "NIFTY 50": "ind_nifty50list.csv",
    "NIFTY BANK": "ind_niftybanklist.csv",
    "NIFTY NEXT 50": "ind_niftynext50list.csv",
    "NIFTY 100": "ind_nifty100list.csv",
    "NIFTY 500": "ind_nifty500list.csv",
}
INDEX_ALIASES = {"^NSEI": "NIFTY 50", "^NSEBANK": "NIFTY BANK", "NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}


def index_name(ticker_or_name: str) -> str:
    key = ticker_or_name.strip().upper()
    return INDEX_ALIASES.get(key, key)


def fetch_constituents(index: str, client=None) -> tuple[list[str], str]:
    """Today's members of ``index`` from NSE's archive CSV, and the provenance line."""
    from tradingagents.dataflows.vendors.nse.client import default_client

    name = index_name(index)
    filename = CONSTITUENT_FILES.get(name)
    if filename is None:
        raise NoMarketDataError(index, detail=f"no constituent file known; known: {sorted(CONSTITUENT_FILES)}")
    client = client or default_client()
    fetched = client.get_archive(f"/content/indices/{filename}", ttl=86400)
    df = pd.read_csv(io.BytesIO(fetched.data))
    symbols = sorted(df["Symbol"].astype(str).str.strip())
    return symbols, fetched.provenance()


@dataclass(frozen=True)
class Membership:
    index: str
    as_of: date
    symbols: tuple[str, ...]
    method: str               # "snapshot" | "reconstructed" | "nearest_snapshot"
    survivorship_safe: bool
    note: str

    def yahoo_tickers(self) -> list[str]:
        return [f"{s}.NS" for s in self.symbols]


class ConstituentStore:
    """Dated snapshots of index membership plus a change log for reconstruction."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(get_config()["data_cache_dir"]) / "nse"
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.root / "index_snapshots.json"
        self.changes_path = self.root / "index_changes.json"
        self.snapshots: dict[str, dict[str, list[str]]] = _load(self.snapshot_path, {})
        # {"NIFTY 50": {"complete_since": "2023-01-01", "events": [{"date", "added", "removed"}]}}
        self.changes: dict[str, dict] = _load(self.changes_path, {})

    def record_snapshot(self, index: str, day: date, symbols: list[str]) -> None:
        name = index_name(index)
        self.snapshots.setdefault(name, {})[day.isoformat()] = sorted(symbols)
        _save(self.snapshot_path, self.snapshots)

    def add_change(self, index: str, day: date, added: list[str], removed: list[str]) -> None:
        """Record an announced reconstitution effective on ``day``."""
        log = self.changes.setdefault(index_name(index), {"complete_since": None, "events": []})
        log["events"] = [e for e in log["events"] if e["date"] != day.isoformat()]
        log["events"].append({"date": day.isoformat(), "added": sorted(added), "removed": sorted(removed)})
        log["events"].sort(key=lambda e: e["date"])
        _save(self.changes_path, self.changes)

    def set_complete_since(self, index: str, day: date) -> None:
        """Declare the change log complete from ``day`` onward (enables survivorship-safe answers)."""
        self.changes.setdefault(index_name(index), {"complete_since": None, "events": []})["complete_since"] = day.isoformat()
        _save(self.changes_path, self.changes)

    def refresh(self, index: str, today: date, client=None) -> list[str]:
        symbols, _ = fetch_constituents(index, client)
        self.record_snapshot(index, today, symbols)
        return symbols

    def members_as_of(self, index: str, day: date) -> Membership:
        name = index_name(index)
        snaps = self.snapshots.get(name, {})
        if not snaps:
            raise NoMarketDataError(name, detail="no constituent snapshot stored; call refresh() first")
        iso = day.isoformat()
        dates = sorted(snaps)
        if iso in snaps:
            return Membership(name, day, tuple(snaps[iso]), "snapshot", True, f"snapshot taken {iso}")

        earlier = [d for d in dates if d <= iso]
        later = [d for d in dates if d > iso]
        log = self.changes.get(name, {"complete_since": None, "events": []})
        complete_since = log.get("complete_since")

        # Between two snapshots that agree, nothing changed in between.
        if earlier and later and snaps[earlier[-1]] == snaps[later[0]]:
            return Membership(name, day, tuple(snaps[earlier[-1]]), "snapshot", True,
                              f"unchanged between snapshots {earlier[-1]} and {later[0]}")

        # Reconstruct backwards from the next snapshot by undoing later changes.
        if later:
            anchor = later[0]
            members = set(snaps[anchor])
            for event in sorted(log["events"], key=lambda e: e["date"], reverse=True):
                if iso < event["date"] <= anchor:
                    members -= set(event["added"])
                    members |= set(event["removed"])
            safe = bool(complete_since and complete_since <= iso)
            note = (f"reconstructed from the {anchor} snapshot and the change log"
                    + ("" if safe else f"; change log not declared complete back to {iso} — "
                       "membership may include later joiners and miss dropped stocks (survivorship bias)"))
            return Membership(name, day, tuple(sorted(members)), "reconstructed", safe, note)

        # Only earlier snapshots: the latest one, unless a logged change came after it.
        last = earlier[-1]
        members = set(snaps[last])
        for event in log["events"]:
            if last < event["date"] <= iso:
                members -= set(event["removed"])
                members |= set(event["added"])
        safe = bool(complete_since and complete_since <= last)
        return Membership(name, day, tuple(sorted(members)), "nearest_snapshot", safe,
                          f"latest snapshot {last} rolled forward with logged changes")


def survivorship_warning(membership: Membership) -> str:
    if membership.survivorship_safe:
        return ""
    return (f"SURVIVORSHIP WARNING ({membership.index} as of {membership.as_of}): {membership.note}. "
            "Backtest results on this universe are likely overstated.")


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, data) -> None:
    text = json.dumps(data, indent=1, sort_keys=True)
    replace_file(path, lambda tmp: Path(tmp).write_text(text, encoding="utf-8"))

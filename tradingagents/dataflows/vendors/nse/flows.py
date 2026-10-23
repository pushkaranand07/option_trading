"""FII/DII cash-market flows, with their publication status.

NSE's ``/api/fiidiiTradeReact`` returns one day only — the latest published —
and NSE offers no free history endpoint. Two consequences handled here:

1. During market hours the API still returns *yesterday's* figures. Every
   answer is classified (``calendar.classify_availability``) so an agent is told
   "today's figures are not published yet" instead of reading yesterday's as
   today's.
2. History is built locally: each fetch is appended to ``fii_dii_history.csv``
   in the cache, so after a few weeks of runs the tool can answer for past
   dates and for trailing sums. A date we never captured is reported missing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors.nse.calendar import (
    Availability,
    DataAvailability,
    NSECalendar,
    classify_availability,
    now_ist,
)

FLOWS_API = "/api/fiidiiTradeReact"
HISTORY_FIELDS = ("date", "category", "buy_cr", "sell_cr", "net_cr", "source", "fetched_at")


@dataclass(frozen=True)
class FlowRow:
    category: str          # "FII/FPI" or "DII"
    buy_cr: float          # ₹ crore
    sell_cr: float
    net_cr: float


@dataclass
class FlowsReport:
    requested: date
    published: date | None
    availability: DataAvailability
    rows: list[FlowRow] = field(default_factory=list)
    source: str = ""

    def to_text(self) -> str:
        lines = [f"## FII/DII cash-market flows (requested {self.requested:%d-%b-%Y})",
                 f"Status: {self.availability.status.value} — {self.availability.message}"]
        if self.rows:
            lines.append(f"Figures below are for {self.published:%d-%b-%Y} (₹ crore, provisional):")
            lines.append("| Category | Buy | Sell | Net |")
            lines.append("|---|---:|---:|---:|")
            lines += [f"| {r.category} | {r.buy_cr:,.2f} | {r.sell_cr:,.2f} | {r.net_cr:+,.2f} |"
                      for r in self.rows]
        else:
            lines.append("No FII/DII figures are available. Do not estimate them.")
        lines.append(f"({self.source})")
        return "\n".join(lines)


def parse_flows(payload: list[dict]) -> tuple[date | None, list[FlowRow]]:
    rows, published = [], None
    for item in payload or []:
        try:
            day = datetime.strptime(item["date"], "%d-%b-%Y").date()
            rows.append(FlowRow(item["category"].strip(), float(item["buyValue"]),
                                float(item["sellValue"]), float(item["netValue"])))
        except (KeyError, ValueError, TypeError):
            continue
        published = max(published, day) if published else day
    return published, rows


def _history_path() -> Path:
    path = Path(get_config()["data_cache_dir"]) / "nse"
    path.mkdir(parents=True, exist_ok=True)
    return path / "fii_dii_history.csv"


def record_history(published: date, rows: list[FlowRow], source: str, path: Path | None = None) -> None:
    """Append a day's figures once; a re-fetch of the same day is not duplicated."""
    path = path or _history_path()
    existing = load_history(path)
    if published in existing:
        return
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        if new_file:
            writer.writeheader()
        stamp = datetime.now().isoformat(timespec="seconds")
        for row in rows:
            writer.writerow({"date": published.isoformat(), "category": row.category,
                             "buy_cr": row.buy_cr, "sell_cr": row.sell_cr, "net_cr": row.net_cr,
                             "source": source, "fetched_at": stamp})


def load_history(path: Path | None = None) -> dict[date, list[FlowRow]]:
    path = path or _history_path()
    history: dict[date, list[FlowRow]] = {}
    if not path.exists():
        return history
    with path.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            try:
                day = date.fromisoformat(item["date"])
                history.setdefault(day, []).append(FlowRow(
                    item["category"], float(item["buy_cr"]), float(item["sell_cr"]), float(item["net_cr"])))
            except (KeyError, ValueError):
                continue
    return history


def get_fii_dii(
    requested: date,
    *,
    client=None,
    calendar: NSECalendar | None = None,
    now: datetime | None = None,
    history_path: Path | None = None,
) -> FlowsReport:
    """FII/DII figures for ``requested``, or the latest available with an honest status."""
    from tradingagents.dataflows.vendors.nse.client import default_client

    client = client or default_client()
    calendar = calendar or NSECalendar.from_nse(client)
    now = now or now_ist()
    history = load_history(history_path)
    target = calendar.latest_session(requested)

    # A past session we already captured needs no network call.
    if target in history and target < now.date():
        availability = classify_availability("fii_dii", requested, target, now, calendar)
        return FlowsReport(requested, target, availability, history[target], "source: local FII/DII history")

    fetched = client.get_json(FLOWS_API, ttl=600)
    published, rows = parse_flows(fetched.data)
    if published and rows:
        record_history(published, rows, fetched.source, history_path)
        history[published] = rows

    if published and published > target:
        # Asked about the past; NSE only serves today. Use history if we have it.
        held = history.get(target)
        if held:
            availability = classify_availability("fii_dii", requested, target, now, calendar)
        else:
            availability = DataAvailability(
                "fii_dii", requested, None, Availability.LATE,
                f"NSE serves only the latest day ({published:%d-%b-%Y}); {target:%d-%b-%Y} was never "
                "captured in local history. Treat it as missing.")
        return FlowsReport(requested, target if held else None, availability, held or [],
                           "source: local FII/DII history")

    availability = classify_availability("fii_dii", requested, published, now, calendar)
    return FlowsReport(requested, published, availability, rows, fetched.provenance())

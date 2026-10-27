"""The frozen development / validation / holdout split (docs/data/splits_v1.json).

The file is frozen by its hash: :data:`SPLITS_SHA256` is the SHA-256 of its canonical JSON (sorted keys, no
whitespace), so line endings and formatting do not matter but any change of content does. Changing a split
means a new file (``splits_v2.json``) and a new hash, never an edit of v1.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SPLITS_PATH = Path(__file__).resolve().parents[2] / "docs" / "data" / "splits_v1.json"
SPLITS_SHA256 = "c647d53089fc05ccb7ee73931b20d2c23493c76f282ec7bb2dc2aa704793642a"

OPEN = "open"
LOCKED = "locked"
PREREGISTERED = "locked_preregistered"


class SplitsChanged(RuntimeError):
    """The split file no longer matches its frozen hash."""


@dataclass(frozen=True)
class Period:
    name: str
    start: date | None          # None: from the earliest data
    end: date | None            # None: open-ended (the forward holdout)
    access: str
    label: str = ""

    @property
    def locked(self) -> bool:
        return self.access != OPEN

    def overlaps(self, start: date | None, end: date | None) -> bool:
        return (self.end is None or start is None or start <= self.end) and \
               (self.start is None or end is None or end >= self.start)


def canonical_hash(content: dict) -> str:
    text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read(path: Path = SPLITS_PATH, expected: str = SPLITS_SHA256) -> dict:
    content = json.loads(Path(path).read_text(encoding="utf-8"))
    actual = canonical_hash(content)
    if actual != expected:
        raise SplitsChanged(f"{path} hash {actual} != frozen {expected}; a new split needs a new file")
    return content


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def periods(content: dict | None = None) -> dict[str, Period]:
    content = content or read()
    return {name: Period(name, _day(p["start"]), _day(p["end"]), p["access"], p.get("label", ""))
            for name, p in content["periods"].items()}


def period_of(day: date, content: dict | None = None) -> Period:
    for p in periods(content).values():
        if p.overlaps(day, day):
            return p
    raise ValueError(f"{day} is in no period")


def last_open_day(content: dict | None = None) -> date:
    return max(p.end for p in periods(content).values() if not p.locked and p.end is not None)

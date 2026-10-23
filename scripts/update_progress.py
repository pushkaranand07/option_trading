"""Recalculate the progress bars in docs/PROGRESS_TRACKER.md.

    python scripts/update_progress.py

Each phase's bar comes from its checkboxes; the overall bar from all of them;
the download bar from the NSE backfill manifest (days done out of weekdays
from 2018-01-01 to yesterday). Only the text between the progress markers and
the "Last updated" line are rewritten.
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TRACKER = Path(__file__).resolve().parents[1] / "docs" / "PROGRESS_TRACKER.md"
WIDTH = 25


def bar(done: int, total: int) -> str:
    share = done / total if total else 0.0
    filled = round(share * WIDTH)
    return f"`{'█' * filled}{'░' * (WIDTH - filled)}` {share:.0%}"


def download_share() -> tuple[int, int] | None:
    try:
        from tradingagents.analytics.backfill import KINDS, load_manifest, raw_root, weekdays
        from tradingagents.analytics.universe import HISTORY_START
    except Exception:
        return None
    manifest = load_manifest(raw_root())
    if not manifest:
        return None
    total = sum(1 for _ in weekdays(HISTORY_START, date.today() - timedelta(days=1))) * len(KINDS)
    return min(len(manifest), total), total


def render(text: str) -> str:
    sections = re.split(r"(?m)^(?=## )", text)
    all_done = all_total = 0
    out = []
    for section in sections:
        boxes = re.findall(r"(?m)^- \[([ xX])\]", section)
        if section.startswith("## Phase") and boxes:
            done = sum(b.lower() == "x" for b in boxes)
            all_done, all_total = all_done + done, all_total + len(boxes)
            section = re.sub(r"<!-- progress:phase -->.*?<!-- /progress:phase -->",
                             f"<!-- progress:phase -->\n{bar(done, len(boxes))} ({done}/{len(boxes)})\n"
                             "<!-- /progress:phase -->", section, flags=re.S)
        out.append(section)
    text = "".join(out)
    text = re.sub(r"<!-- progress:overall -->.*?<!-- /progress:overall -->",
                  f"<!-- progress:overall -->\n**Overall:** {bar(all_done, all_total)} "
                  f"({all_done}/{all_total} tasks)\n<!-- /progress:overall -->", text, flags=re.S)
    dl = download_share()
    if dl:
        text = re.sub(r"<!-- progress:download -->.*?<!-- /progress:download -->",
                      f"<!-- progress:download -->\n**NSE history download:** {bar(*dl)} "
                      f"({dl[0]:,}/{dl[1]:,} files)\n<!-- /progress:download -->", text, flags=re.S)
    return re.sub(r"(?m)^_Last updated: .*_$", f"_Last updated: {datetime.now():%Y-%m-%d %H:%M}_", text)


def main() -> int:
    text = TRACKER.read_text(encoding="utf-8")
    TRACKER.write_text(render(text), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252, which lacks the bar blocks
    print(re.search(r"\*\*Overall:\*\*.*", TRACKER.read_text(encoding="utf-8")).group(0))
    return 0


if __name__ == "__main__":
    sys.exit(main())

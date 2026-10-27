"""Record the frozen split in the trial log (docs/PA_31). Safe to re-run: a hash already recorded is skipped.

    python scripts/research_freeze_splits.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.research import splits  # noqa: E402


def main() -> int:
    content = splits.read()
    done = [e for e in trial_log.load_events("split_freeze") if e["detail"].get("sha256") == splits.SPLITS_SHA256]
    if done:
        print(f"Already recorded (event {done[0]['id']}, {done[0]['run_at']}).")
        return 0
    detail = {
        "file": splits.SPLITS_PATH.relative_to(splits.SPLITS_PATH.parents[2]).as_posix(),
        "sha256": splits.SPLITS_SHA256,
        "periods": {n: {"start": p.start, "end": p.end, "access": p.access, "label": p.label}
                    for n, p in splits.periods(content).items()},
        "seen_2025_plus": [e["idea"] for e in content["seen_2025_plus"]["experiments"]],
    }
    event = trial_log.log_event("split_freeze", detail)
    print(f"Recorded split_freeze event {event}: final_holdout labelled "
          f"'{detail['periods']['final_holdout']['label']}', {len(detail['seen_2025_plus'])} prior experiments listed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

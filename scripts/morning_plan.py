"""Build today's morning plan for NIFTY and BANKNIFTY (scheduled at 8:30 AM on weekdays).

    python scripts/morning_plan.py                 # rules + AI view (2 GPT-5 analyses, ~20 min)
    python scripts/morning_plan.py --no-ai         # rules only, seconds
    pythonw scripts/morning_plan.py --log <file>   # as Task Scheduler runs it (windowless)

Saved to reports/morning/<date>.json and shown in the web app's Plan tab. On a holiday it records that the market
is closed and skips the AI analysis.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")        # a scheduled run has no shell environment: the LLM settings come from here

from webapp import morning  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-ai", action="store_true", help="skip the AI agents (rules and data only)")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--log", type=Path, help="append all output here (for windowless pythonw runs)")
    args = parser.parse_args()
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = args.log.open("a", encoding="utf-8", buffering=1)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"--- morning plan {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    plan = morning.build(args.date, with_ai=not args.no_ai)
    s = plan["session"]
    if not s["trading"]:
        print(f"{s['date']}: market closed ({s['holiday'] or s['weekday']}); next session {s['next_session']}")
        return 0
    for sym, entry in plan["indices"].items():
        ai = entry.get("ai") or {}
        c = entry["context"]
        em = c.get("expected_move") or {}
        print(f"{sym}: trend {c.get('trend', {}).get('label', '?')}, regime {(c.get('regime') or {}).get('name', '?')}, "
              f"day range ±{em.get('day_pct', 0):.2%}, AI {ai.get('rating') or ai.get('error') or 'not run'}", flush=True)
    print(f"saved {morning.path_for(date.fromisoformat(s['date']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

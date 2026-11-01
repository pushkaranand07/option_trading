"""Settle the AI strategist's forward test and report what the spec allows (docs/ai_strategist_test_v1_1.json, docs/PA_50, PA_51).

    python scripts/ai_test_settle.py --mode interim|stop --registry <file> --chains <folder> --settlements <json> --sessions <json> --spec-hash <hash>

Not cleared for real rows: REAL_RUN_APPROVED stays False until the user says otherwise, in a reviewed commit. Until then the real registry
is refused, and so is any copy of it, because every non-synthetic row is refused. Settlement and session files map or list ISO dates.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.research import ai_settle  # noqa: E402

REAL_RUN_APPROVED = False
REAL_REGISTRY = ROOT / "reports" / "ai_test" / "registry.jsonl"


def run(registry_path: Path, chains: Path, settlements: dict[date, float], sessions: set[date], spec_hash: str, mode: str = "interim", today: date | None = None, stop: date = date(2027, 11, 1)) -> dict:
    if Path(registry_path).resolve() == REAL_REGISTRY.resolve() and not REAL_RUN_APPROVED:
        raise ai_settle.RealRowsRefused("the real registry is refused until the user approves this script for real rows")
    if mode == "interim":
        return ai_settle.interim_counts(registry_path, spec_hash, sessions, approved=REAL_RUN_APPROVED)
    from tradingagents.analytics import trial_log

    done = ai_settle.settle(registry_path, chains, settlements, sessions, spec_hash, approved=REAL_RUN_APPROVED)
    return {"counts": done["counts"], "report": ai_settle.at_stop(done["settled"], spec_hash, today or date.today(), stop, [t.idea for t in trial_log.load()])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--chains", type=Path, required=True)
    parser.add_argument("--settlements", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--spec-hash", required=True)
    parser.add_argument("--mode", choices=["interim", "stop"], default="interim")
    args = parser.parse_args()
    prices = {date.fromisoformat(k): float(v) for k, v in json.loads(args.settlements.read_text(encoding="utf-8")).items()}
    sessions = {date.fromisoformat(x) for x in json.loads(args.sessions.read_text(encoding="utf-8"))}
    try:
        print(json.dumps(run(args.registry, args.chains, prices, sessions, args.spec_hash, args.mode), indent=1))
    except ai_settle.RealRowsRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

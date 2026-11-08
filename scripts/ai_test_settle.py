"""Settle the AI strategist's forward test, version 3, and report what the spec allows (docs/ai_strategist_test_v3.json, docs/PA_50-53).

    python scripts/ai_test_settle.py --mode interim|stop --settlements <json> --sessions <json> [--registry <file> --chains <folder> --spec-hash <hash>]

The registry, chains and spec hash default to version 3's. Rows before its first counted session (webapp.ai_test.FIRST_SESSION,
from the spec's "starts" rule) are left out. It prints JSON and writes no file.

Real rows: the interim count (questions, entries, voids, missed days; no price, no return) is cleared for the real registry
(REAL_INTERIM_APPROVED, the user's decision of 2026-11-05). The stop stays locked: REAL_RUN_APPROVED is False until the user says
otherwise, in a reviewed commit, and the spec forbids any performance figure before the stop date. Settlement and session files map or
list ISO dates.
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
from webapp import ai_test  # noqa: E402

REAL_RUN_APPROVED = False
REAL_INTERIM_APPROVED = True
REAL_REGISTRY = ai_test.REGISTRY          # version 3's; 2's (reports/ai_test/v2) and 1.1's (reports/ai_test/registry.jsonl) are closed and never settled


def run(registry_path: Path, chains: Path, settlements: dict[date, float], sessions: set[date], spec_hash: str, mode: str = "interim", today: date | None = None, stop: date | None = None) -> dict:
    real = Path(registry_path).resolve() == REAL_REGISTRY.resolve()
    starts = ai_test.FIRST_SESSION
    if mode == "interim":
        if real and not REAL_INTERIM_APPROVED:
            raise ai_settle.RealRowsRefused("the interim count on the real registry is not approved")
        return ai_settle.interim_counts(registry_path, spec_hash, sessions, approved=real and REAL_INTERIM_APPROVED, starts=starts)
    if real and not REAL_RUN_APPROVED:
        raise ai_settle.RealRowsRefused("the real registry is refused for settlement until the user approves this script for real rows")
    from tradingagents.analytics import trial_log

    stop = stop or date.fromisoformat(ai_test.read_spec()["stop"]["date"])
    done = ai_settle.settle(registry_path, chains, settlements, sessions, spec_hash, approved=REAL_RUN_APPROVED, starts=starts)
    return {"counts": done["counts"], "report": ai_settle.at_stop(done["settled"], spec_hash, today or date.today(), stop, [t.idea for t in trial_log.load()])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=ai_test.REGISTRY)
    parser.add_argument("--chains", type=Path, default=ai_test.CHAINS)
    parser.add_argument("--settlements", type=Path, required=True)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--spec-hash", default=ai_test.SPEC_SHA256)
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

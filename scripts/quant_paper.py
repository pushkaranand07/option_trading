"""Forward paper trading (PROOF_PLAN.md, Stage 3): update the ledger and report.

    python scripts/quant_paper.py            # update every strategy, print the reports
    python scripts/quant_paper.py --report   # reports only

Run after the store is refreshed (the daily job does both). Each strategy's frozen
simulation is re-run on all data to date; trades entered on/after its paper start
date are recorded; a recorded trade that later changes is an integrity event.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import paper  # noqa: E402
from tradingagents.analytics.paper_strategies import STRATEGIES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="only print the reports")
    args = parser.parse_args()
    killed = False
    for s in STRATEGIES:
        if not args.report:
            counts = paper.update(s, s.simulate())
            print(f"{s.name}: {counts['new']} new, {counts['closed']} closed, "
                  f"{counts['integrity']} integrity events", flush=True)
        rep = paper.report(s)
        print(rep.summary())
        killed |= bool(rep.kill)
    return 1 if killed else 0


if __name__ == "__main__":
    sys.exit(main())

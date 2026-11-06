"""Rating stability test (docs/rating_stability_test.md): N multi-agent runs of ^NSEI on the same closed-market input.
It counts how many runs' rating directions differ from the majority and reads the result by the rule fixed in that doc.

    python scripts/research_rating_stability.py --pilot            # one run first: its tokens, then stop
    python scripts/research_rating_stability.py --runs 5           # the batch, in parallel

Refuses while the NSE session is open. Each run reads its own copy of one memory-log snapshot, with settlement off,
so every run gets the same lessons. Nothing the app or the forward test reads is written: the v2 registry, the research
files and the morning plan are hashed before and after, and the script fails if any of them changed. Output goes to
reports/rating_stability/<date-time>/ (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TICKER = "^NSEI"
DIRECTIONS = {"buy": "bullish", "overweight": "bullish", "hold": "neutral", "underweight": "bearish", "sell": "bearish",
              "review": "review"}
GUARDED = [ROOT / "reports" / "ai_test" / "v2", ROOT / "reports" / "ai_runs", ROOT / "reports" / "morning"]
SUMMARY_KEYS = ("market_report", "sentiment_report", "news_report", "fundamentals_report", "investment_plan",
                "trader_investment_plan", "final_trade_decision")


def direction(rating: str) -> str:
    """A rating's direction; an unknown rating is an error."""
    try:
        return DIRECTIONS[str(rating).strip().lower()]
    except KeyError:
        raise ValueError(f"rating {rating!r} has no direction") from None


def verdict(dirs: list[str]) -> dict:
    """Flips = runs outside the most common direction. Read by the 5-run rule fixed before any run."""
    if len(dirs) != 5:
        raise ValueError(f"no rule fixed for {len(dirs)} runs: add it to docs/rating_stability_test.md first")
    majority = max(set(dirs), key=dirs.count)
    flips = len(dirs) - dirs.count(majority)
    return {"flips": flips, "reading": "noise" if flips >= 2 else "noisy" if flips == 1 else "inconclusive", "majority": majority}


def _market_open() -> bool:
    from webapp import signals

    return signals.market_open()


def _fingerprint() -> dict[str, str]:
    """Hash of every file under the guarded folders: the forward test's registry, the research and the morning plan."""
    out = {}
    for folder in GUARDED:
        for f in sorted(folder.rglob("*")) if folder.exists() else []:
            if f.is_file():
                out[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def run_config(snapshot: Path, dest: Path, i: int) -> dict:
    """The app's config for one run, with its own copy of the memory snapshot and its own results folder."""
    from tradingagents.default_config import build_default_config

    run_dir = dest / f"run_{i:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    memory = run_dir / "memory.md"
    shutil.copyfile(snapshot, memory)
    cfg = build_default_config()
    cfg.update(memory_log_path=str(memory), results_dir=str(run_dir / "logs"), checkpoint_enabled=False)
    return cfg


def one_run(snapshot: Path, dest: Path, i: int, day: str) -> dict:
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    from tradingagents.agents.rating import run_rating
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    cb = UsageMetadataCallbackHandler()
    started = datetime.now().isoformat(timespec="seconds")
    graph = TradingAgentsGraph(config=run_config(snapshot, dest, i), callbacks=[cb])
    graph.settle_all_pending = lambda wait=True: SimpleNamespace(failed=[])      # the same lessons in every run
    state, _ = graph.propagate(TICKER, day)
    rating = run_rating(state)
    row = {"run": i, "started": started, "finished": datetime.now().isoformat(timespec="seconds"), "rating": rating,
           "direction": direction(rating), "usage": cb.usage_metadata,
           "summary": {k: (state.get(k) or "")[:1500] for k in SUMMARY_KEYS},
           "research_manager": ((state.get("investment_debate_state") or {}).get("judge_decision") or "")[:1500],
           "risk_judge": ((state.get("risk_debate_state") or {}).get("judge_decision") or "")[:1500]}
    (dest / f"run_{i:02d}" / "result.json").write_text(json.dumps(row, indent=1, default=str), encoding="utf-8")
    return row


def tokens(rows: list[dict]) -> dict:
    total = {"input": 0, "output": 0, "cached_input": 0, "reasoning": 0}
    for r in rows:
        for usage in (r.get("usage") or {}).values():
            total["input"] += usage.get("input_tokens", 0)
            total["output"] += usage.get("output_tokens", 0)
            total["cached_input"] += (usage.get("input_token_details") or {}).get("cache_read", 0)
            total["reasoning"] += (usage.get("output_token_details") or {}).get("reasoning", 0)
    return total


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--pilot", action="store_true", help="one run only, to measure its tokens")
    p.add_argument("--dest", type=Path, default=None)
    p.add_argument("--first", type=int, default=1, help="number of the first run (a batch after the pilot starts at 2)")
    args = p.parse_args(argv)
    if _market_open():
        raise SystemExit("The NSE market is open: this test runs only after the close (same input in every run).")
    from dotenv import load_dotenv

    from tradingagents.default_config import build_default_config

    load_dotenv(ROOT / ".env")
    dest = args.dest or ROOT / "reports" / "rating_stability" / datetime.now().strftime("%Y-%m-%d")
    dest.mkdir(parents=True, exist_ok=True)
    snapshot = dest / "memory_snapshot.md"
    if not snapshot.exists():                            # one snapshot for the pilot and the batch alike
        real = Path(build_default_config()["memory_log_path"]).expanduser()
        shutil.copyfile(real, snapshot) if real.exists() else snapshot.write_text("", encoding="utf-8")
    before = _fingerprint()
    n = 1 if args.pilot else args.runs
    day = str(date.today())
    with ThreadPoolExecutor(n) as pool:                  # together: the news differs as little as possible
        rows = list(pool.map(lambda i: one_run(snapshot, dest, i, day), range(args.first, args.first + n)))
    if _fingerprint() != before:
        raise SystemExit("A file the app or the forward test reads changed during the runs: see the guarded folders.")
    for r in rows:
        print(f"run {r['run']:02d} {r['started']} -> {r['finished']}  {r['rating']:<12} {r['direction']}")
    print("tokens:", tokens(rows))
    print("guarded files unchanged:", len(before))
    return 0


if __name__ == "__main__":
    sys.exit(main())

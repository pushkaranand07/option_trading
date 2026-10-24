"""Phase 9 exit check: replay full agent analyses and check the quant numbers they quote.

    python scripts/quant_replay.py                 # run the 10 analyses (resumes: finished ones are kept)
    python scripts/quant_replay.py --check-only    # re-check saved runs, no LLM calls

Each run is a full TradingAgents analysis (the LLM set in .env), 2 debate rounds and
2 risk rounds, with its own empty memory log so no run can see another's decision.
Saved under reports/replay/ (gitignored). The check is ``replay_check.py``; its rules
were fixed before the first run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import replay_check as rc  # noqa: E402
from tradingagents.analytics.quant_report import quant_signal_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "replay"
# Calm, choppy and event days across 2022-2026, indices and stocks (chosen before any run).
RUNS = [("^NSEI", "2023-08-10"), ("^NSEI", "2024-06-05"), ("^NSEBANK", "2025-04-08"), ("RELIANCE.NS", "2026-03-24"),
        ("HDFCBANK.NS", "2022-06-14"), ("INFY.NS", "2026-07-24"), ("TCS.NS", "2026-10-23"), ("SBIN.NS", "2024-11-25"),
        ("TATASTEEL.NS", "2022-02-25"), ("ADANIENT.NS", "2023-01-30")]
TEXT_FIELDS = ("market_report", "sentiment_report", "news_report", "fundamentals_report", "investment_plan",
               "trader_investment_plan", "final_trade_decision")


def slug(symbol: str, day: str) -> str:
    return f"{symbol.replace('^', '').replace('.', '_')}_{day}"


def run_one(symbol: str, day: str) -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = 2
    config["max_risk_discuss_rounds"] = 2
    config["results_dir"] = str(OUT / "logs")
    memory = OUT / "memory" / f"{slug(symbol, day)}.md"
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.unlink(missing_ok=True)                      # a fresh, empty memory for every run
    config["memory_log_path"] = str(memory)
    state, rating = TradingAgentsGraph(debug=False, config=config).propagate(symbol, day)
    saved = {k: state.get(k, "") for k in TEXT_FIELDS}
    for k in ("investment_debate_state", "risk_debate_state"):
        d = state.get(k) or {}
        saved[k] = {"history": d.get("history", ""), "judge_decision": d.get("judge_decision", "")}
    saved["rating"] = rating
    return saved


def texts_of(saved: dict) -> list[str]:
    out = [saved.get(k) or "" for k in TEXT_FIELDS]
    for k in ("investment_debate_state", "risk_debate_state"):
        d = saved.get(k) or {}
        out += [d.get("history", ""), d.get("judge_decision", "")]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    results, lines = [], ["# Phase 9 replay check", ""]
    for symbol, day in RUNS:
        path = OUT / f"{slug(symbol, day)}.json"
        if not path.exists():
            if args.check_only:
                print(f"{symbol} {day}: not run yet")
                continue
            started = time.monotonic()
            print(f"{symbol} {day}: running ...", flush=True)
            saved = run_one(symbol, day)
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  done in {(time.monotonic() - started) / 60:.1f} min, rating {saved['rating']}", flush=True)
        saved = json.loads(path.read_text(encoding="utf-8"))
        res = rc.check(texts_of(saved), quant_signal_text(symbol, day))
        results.append(res)
        verdict = "PASS" if res.passed else "FLAGS"
        print(f"{symbol} {day}: {verdict} — {res.sentences} quant sentences, {len(res.unsupported)} unsupported "
              f"numbers, {len(res.claims)} validation claims, rating {saved.get('rating')}", flush=True)
        lines += [f"## {symbol} {day} — {verdict} (rating {saved.get('rating')})",
                  f"{res.sentences} sentences quoting quant numbers.", ""]
        lines += [f"- unsupported **{n}**: {s}" for n, s in res.unsupported]
        lines += [f"- validation claim: {s}" for s in res.claims]
        lines.append("")

    if results:
        n_bad = sum(not r.passed for r in results)
        total = (f"{len(results)} runs, {sum(r.sentences for r in results)} quant sentences, "
                 f"{sum(len(r.unsupported) for r in results)} unsupported numbers, "
                 f"{sum(len(r.claims) for r in results)} validation claims -> "
                 f"{'PASS' if n_bad == 0 and len(results) == len(RUNS) else 'NOT PASSED (read the flags)'}")
        print(f"\n{total}")
        lines.insert(2, total + "\n")
        (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"Flags with their sentences: {OUT / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Item 3: what each option for the AI forward test does to the verdict date and power. Writes docs/ai_test_options_v1.md.

    python scripts/ai_test_options.py

Arithmetic from the frozen spec's power table only: no LLM, no market data, no trade read. Weekdays count as sessions; 2027 and later holidays
are not stored, so every date is a lower bound. The share of answers that become trades is unmeasured, so it is shown as scenarios.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

START = date(2026, 11, 2)
RATES = (5, 4, 3, 2)
TRADE_SHARES = (1.0, 0.7, 0.5)
EDGES = ("0.10", "0.15", "0.20", "0.30")
STOPS = (date(2027, 11, 1), date(2028, 11, 1))


def verdict_date(count: int, per_week: float, start: date = START) -> date:
    """When ``count`` trades have been entered at ``per_week``; settling adds up to the expiry after that."""
    return start + timedelta(weeks=math.ceil(count / per_week))


def trades_by(stop: date, per_week: float, start: date = START) -> int:
    return int((stop - start).days / 7 * per_week)


def power_at(table: dict, edge: str, n: int) -> float | None:
    """The power table's value at the largest listed count at or below n; None below 50."""
    counts = [int(k) for k in table[edge] if int(k) <= n]
    return table[edge][str(max(counts))] if counts else None


def fmt(p: float | None) -> str:
    return "n/a" if p is None else f"{p:.2f}"


def build(spec: dict, system_prompt: str) -> str:
    table = spec["power"]["pass_rate_by_edge"]
    verdict = spec["forward_test"]["verdict_count"]
    t = ["# AI forward test: options", "", "> **Status:** Computed 2026-11-01 from the frozen spec. **No trade has counted yet. Your decision; nothing has been changed.**",
         "> **Scope:** dates and power only. Arithmetic, with no LLM call and no market data.", "",
         f"**Asking a NIFTY question on the Plan tab between 09:30 and 15:00 now counts as the first trade**, under the current spec, and the choice below would then no longer be free. Dates are lower bounds: weekdays count as sessions, 2027 and later holidays are not stored, and settling adds up to one expiry. Start assumed {START}.", "",
         "## How long 500 trades takes", "", "The spec allows at most 5 questions a week. Your real rate and the share of answers that become trades are **UNVERIFIED**: only 2 AI trades exist, from one date.", "",
         "| Questions a week | Trades per answer | Trades a week | Weeks to " + str(verdict) + " | Earliest date |", "|---|---|---|---|---|"]
    for r in RATES:
        for s in TRADE_SHARES:
            w = r * s
            t.append(f"| {r} | {s:.0%} | {w:.1f} | {math.ceil(verdict / w)} | {verdict_date(verdict, w)} |")
    t += ["", "## Power at each trade count", "", "Share of simulated runs passing, from the spec. Edge is the extra net return per trade as a share of max risk.", "", "| Trades | " + " | ".join(f"{float(e):.0%} edge" for e in EDGES) + " |", "|---|" + "---|" * len(EDGES)]
    for n in ("50", "100", "200", "300", "500", "1000"):
        t.append(f"| {n} | " + " | ".join(fmt(table[e].get(n)) for e in EDGES) + " |")
    t += ["", "## What a stop date would allow", "", "Trades reached by each stop date, and the power at that count. Power uses the largest listed count at or below it.", "", "| Stop date | Questions a week | Trades per answer | Trades by then | Power at 20% edge | Power at 30% edge |", "|---|---|---|---|---|---|"]
    for stop in STOPS:
        for r, s in ((5, 1.0), (5, 0.7), (3, 0.7), (2, 0.5)):
            n = trades_by(stop, r * s)
            t.append(f"| {stop} | {r} | {s:.0%} | {n} | {fmt(power_at(table, '0.20', n))} | {fmt(power_at(table, '0.30', n))} |")
    named = {w: bool(re.search(w, system_prompt, re.I)) for w in ("trend", "OI walls", "FII", "implied vol", "PCR")}
    t += ["", "## Risks behind the options", "",
          "- **Provider change:** the spec pins the model's name, API settings and prompt, not the served version. The app does not record the version in each response, so a change behind the same name goes undetected. Whether Azure changes this deployment by itself is UNVERIFIED.",
          f"- **Prompt inputs:** the system prompt names: {', '.join(k for k, v in named.items() if v)}. The word PCR is {'in' if named['PCR'] else 'not in'} the system prompt, though the option-chain data the model receives includes it. The score was removed because similar inputs showed no edge under the tested conditions. Whether an LLM adds anything on top is what this test would measure.",
          "", "## Options", "",
          "| Option | What changes | Verdict date | Power | Main cost |", "|---|---|---|---|---|",
          f"| **(a) Keep as is** | Nothing | Earliest {verdict_date(verdict, 5)}; {verdict_date(verdict, 3 * 0.7)} at 3 questions a week and 70% | 85% at a 20% edge, if it finishes | Needs about 2 to 5 years of daily questions and the same model throughout |",
          "| **(b) Change the prompt or model, restart the hash** | New prompt, for example without the inputs already found wanting. Free before the first trade | Same as (a) | Same as (a) | Does not shorten anything; the prompt becomes another untested design choice |",
          f"| **(c) Stop date and interim look rules** | A fixed end date. Verdict on the trades reached by then | The stop date, for example {STOPS[0]} | At {STOPS[0]}, about 182 trades at 5 and 70%: {fmt(power_at(table, '0.20', 182))} at 20%, {fmt(power_at(table, '0.30', 182))} at 30% | Detects only very large edges. Any interim pass-or-fail look needs its own simulation first: not simulated here |",
          "| **(d) Retire the test** | Remove the hook; AI suggestions stay UNTESTED permanently | None | None | No evidence on the AI, ever. Saves the daily effort and LLM cost |", "",
          "I have not picked one. **Whichever you choose, the stop date and the action at that date must go in the spec before the first counted trade.** The action needs your words: for example, \"retire the test and keep the UNTESTED label\" or \"report what was reached, with no pass\".", ""]
    return "\n".join(t)


def main() -> int:
    from webapp import ai_test, strategist

    (ROOT / "docs" / "ai_test_options_v1.md").write_text(build(ai_test.read_spec(), strategist.SYSTEM), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

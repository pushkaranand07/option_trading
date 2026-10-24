"""Phase 9 exit check: do the agents quote the quant numbers faithfully?

Rules, fixed before any replay was run:

1. Every number in a sentence about volatility, expected move, implied vol or regime
   (``QUANT_WORDS``) must appear in the quant tool's output for that date: a percentage
   must match one of the tool's percentages, any other number any of its numbers;
   within 0.1 (or 1% for large numbers), or, when the agent wrote a whole number, equal
   after rounding. Dates and session counts match because the tool's text has them.
   A number that matches nothing is an **unsupported number**.
2. No sentence may present a quant signal or model as validated / approved / proven
   unless it is negated ("not validated", "no signal has passed"). Such a sentence is a
   **validation claim**.

Pass: zero unsupported numbers and zero validation claims across all replayed runs.
Every flag is printed with its sentence so it can be read, not just counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

QUANT_WORDS = re.compile(r"garch|gjr|ewma|implied vol|\biv\b|expected move|regime|hmm|volatility forecast|"
                         r"historical vol|realised vol|realized vol|\bvol(atility)? percentile", re.I)
CLAIM_WORDS = re.compile(r"\b(validated|approved|proven|passed (the |its )?(gates|validation|backtest))\b", re.I)
SUBJECT_WORDS = re.compile(r"quant|signal|model|garch|regime|strategy|condor|forecast", re.I)
NEGATION = re.compile(r"\b(not|no|never|none|nothing|unvalidated|without|neither|nor|isn't|hasn't|haven't|"
                      r"wasn't|aren't|doesn't|cannot|can't|lack|fails?|failed|rejected|yet to)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])[-+−±]?\d[\d,]*(?:\.\d+)?(?P<pct>\s?%)?")


@dataclass
class CheckResult:
    sentences: int = 0
    unsupported: list[tuple[str, str]] = field(default_factory=list)     # (number, sentence)
    claims: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.unsupported and not self.claims


@dataclass(frozen=True)
class Num:
    token: str
    value: float
    pct: bool
    whole: bool          # written without decimals


def numbers(text: str) -> list[Num]:
    out = []
    for m in NUMBER.finditer(text):
        raw = m.group(0)
        digits = raw.replace("%", "").strip().replace(",", "").replace("−", "-").lstrip("+±-")
        try:
            value = float(digits)
        except ValueError:
            continue
        out.append(Num(raw.strip(), value, bool(m.group("pct")), "." not in digits))
    return out


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    # Split on sentence ends and table / bullet boundaries, keeping decimals intact.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(*#|-])|\s\|\s|\s[-*•]\s", text) if s.strip()]


def _supported(n: Num, truth: list[Num]) -> bool:
    for t in truth:
        if n.pct and not t.pct:
            continue
        x, v = n.value, t.value
        if abs(x - v) <= 0.1 or (v and abs(x - v) / v <= 0.01) or (n.whole and round(x) == round(v)):
            return True
    return False


def check(texts: list[str], quant_text: str) -> CheckResult:
    truth = numbers(quant_text)
    res = CheckResult()
    for text in texts:
        for s in sentences(text):
            if QUANT_WORDS.search(s):
                res.sentences += 1
                for n in numbers(s):
                    if not _supported(n, truth):
                        res.unsupported.append((n.token, s))
            if CLAIM_WORDS.search(s) and SUBJECT_WORDS.search(s) and not NEGATION.search(s):
                res.claims.append(s)
    return res

"""Settlement and baselines for the AI strategist's forward test, following docs/ai_strategist_test_v1_1.json exactly (docs/PA_50, PA_51).

Pure: rows, settlement prices and saved chains go in, numbers come out. Hold to expiry; each leg settles at intrinsic on NSE's final
settlement price. Net P&L after charges as a percentage of max risk. Nothing is reported below 50 settled trades. Pass or fail is decided
once, on the first 500. Rows not marked synthetic are refused unless real rows have been approved. Cost model unverified.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from tradingagents.analytics import costs
from tradingagents.research import registry

SYNTHETIC = "SYNTHETIC"
REPORT_MINIMUM, VERDICT_COUNT = 50, 500
RANDOM_DRAWS, BOOTSTRAP = 1000, 2000
WARNING = "50 settled trades are too few to prove an edge. No pass or fail before 500"
LABEL = "paper entries at quoted prices; hold to expiry; tests direction and structure, not target or stop; cost model unverified"


class RealRowsRefused(PermissionError):
    """Real rows reached the settlement before the user approved it."""


def intrinsic(kind: str, strike: float, settlement: float) -> float:
    return max(settlement - strike, 0.0) if kind == "CE" else max(strike - settlement, 0.0)


def leg_charges(legs: list[dict], lot: int) -> float:
    """As strategist.charges: each leg in and out at about the same premium."""
    total = 0.0
    for leg in legs:
        side_in, side_out = ("buy", "sell") if leg["action"] == "BUY" else ("sell", "buy")
        total += costs.fill_charges(costs.OPTIONS, lot, leg["price"], side_in) + costs.fill_charges(costs.OPTIONS, lot, leg["price"], side_out)
    return total


def max_risk(legs: list[dict], lot: int) -> float:
    """Debit paid, or the widest spread less the credit, as strategist.price."""
    net = sum(x["price"] if x["action"] == "SELL" else -x["price"] for x in legs)
    if net < 0:
        return -net * lot
    width = 0.0
    for kind in ("CE", "PE"):
        ks = sorted(x["strike"] for x in legs if x["type"] == kind)
        if len(ks) == 2:
            width = max(width, ks[1] - ks[0])
    return (width - net) * lot


def net_percent(legs: list[dict], settlement: float, lot: int, charges: float, risk: float) -> float | None:
    """Net P&L after charges as a percentage of max risk."""
    if not risk or risk <= 0:
        return None
    points = sum((1 if x["action"] == "BUY" else -1) * (intrinsic(x["type"], x["strike"], settlement) - x["price"]) for x in legs)
    return (points * lot - charges) / risk * 100.0


def _quote(chain: dict, kind: str, strike: float, action: str) -> float | None:
    row = next((r for r in chain["rows"] if r["strike"] == strike), None)
    q = row and row.get(kind.lower())
    if not q or not q.get("bid") or not q.get("ask"):
        return None
    return q["ask"] if action == "BUY" else q["bid"]


def _nearest(chain: dict, x: float) -> float:
    return min((r["strike"] for r in chain["rows"]), key=lambda k: abs(k - x))


def _requote(chain: dict, legs: list[dict]) -> list[dict] | None:
    out = []
    for x in legs:
        p = _quote(chain, x["type"], x["strike"], x["action"])
        if p is None:
            return None
        out.append({**x, "price": p})
    return out


def random_variants(structure: str, legs: list[dict], chain: dict) -> list[list[dict]]:
    """The two outcomes of the random direction, priced from the saved entry chain. An iron condor's centre moves up or down by 1% of
    spot, keeping its wings. Any other structure: the same trade and its mirror at the same strike distances from spot."""
    spot = chain["spot"]
    if structure == "iron_condor":
        raw = [[{**x, "strike": _nearest(chain, x["strike"] + s * 0.01 * spot)} for x in legs] for s in (1, -1)]
    else:
        raw = [[dict(x) for x in legs], [{**x, "type": "PE" if x["type"] == "CE" else "CE", "strike": _nearest(chain, 2 * spot - x["strike"])} for x in legs]]
    return [v for v in (_requote(chain, r) for r in raw) if v is not None]


def _load_chain(folder: Path, sha: str) -> dict:
    text = (Path(folder) / f"{sha}.json").read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != sha:
        raise ValueError(f"saved chain {sha[:12]} does not match its hash")
    return json.loads(text)


def _expiry(text: str) -> date:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unknown expiry format: {text}")


def _registrations(rows: list[dict], spec_hash: str, starts: date | None) -> list[dict]:
    """One test version's answers: its spec hash, from its first counted session on (rows before it never count)."""
    return [r for r in rows if r["type"] == "strategist" and r["spec_hash"] == spec_hash and (starts is None or date.fromisoformat(r["date"]) >= starts)]


def settle(path: Path, chains: Path, settlements: dict[date, float], sessions: set[date], spec_hash: str, approved: bool = False,
           starts: date | None = None) -> dict:
    """Every row of one test version settled where its expiry has a settlement price. A broken hash chain raises."""
    registry.verify(path)
    all_rows = registry.read(path)
    regs = _registrations(all_rows, spec_hash, starts)
    if not approved and any(r["symbol"] != SYNTHETIC for r in regs):
        raise RealRowsRefused("real rows are refused until the user approves running on them")
    entries = {r["registration"]: r for r in all_rows if r["type"] == "strategist_entry"}
    missed = [r for r in all_rows if r["type"] == "missed" and r["spec_hash"] == spec_hash]
    real_missed = [r["date"] for r in missed if date.fromisoformat(r["date"]) in sessions]
    counts = {"registered": len(regs), "no_trade": 0, "rejected": 0, "trade": 0, "void": 0, "open": 0, "no_entry": 0, "missed": len(real_missed), "missed_on_non_sessions_dropped": len(missed) - len(real_missed), "no_random_baseline": 0, "no_rule_pick": 0}
    settled = []
    for r in sorted(regs, key=lambda x: x["date"]):
        counts[r["outcome"]] += 1
        if r["outcome"] != "trade":
            continue
        e = entries.get(r["hash"])
        if e is None:
            counts["no_entry"] += 1
            continue
        if e["status"] != "entered":
            counts["void"] += 1
            continue
        expiry = _expiry(r["expiry"])
        price = settlements.get(expiry)
        if price is None:
            counts["open"] += 1
            continue
        lot = e["lot"]
        chain = _load_chain(chains, e["chain_sha256"])
        draws = []
        for v in random_variants(r["structure"], e["legs"], chain):
            n = net_percent(v, price, lot, leg_charges(v, lot), max_risk(v, lot))
            if n is not None:
                draws.append(n)
        if not draws:
            counts["no_random_baseline"] += 1
        pick = e.get("rule_pick")
        rule = net_percent(pick["legs"], price, lot, pick["charges"], pick["max_risk"]) if pick else None
        if rule is None:
            counts["no_rule_pick"] += 1
        settled.append({"date": r["date"], "expiry": expiry.isoformat(), "pct": net_percent(e["legs"], price, lot, e["charges"], e["max_risk"]), "random": draws, "rule": rule})
    return {"counts": counts, "settled": settled}


def evaluate(settled: list[dict], spec_hash: str) -> dict:
    """The report the spec allows at this count: nothing below 50; numbers and a warning from 50; pass or fail once, on the first 500."""
    n = len(settled)
    if n < REPORT_MINIMUM:
        return {"status": "below minimum: nothing is reported", "settled": n, "report_minimum": REPORT_MINIMUM}
    use = settled[:VERDICT_COUNT]
    rng = np.random.default_rng(int(spec_hash[:16], 16))
    pct = np.array([x["pct"] for x in use], dtype=float)
    mean = float(pct.mean())
    weeks, inv = np.unique([x["expiry"] for x in use], return_inverse=True)
    s, c = np.bincount(inv, pct), np.bincount(inv)
    picks = rng.integers(0, len(weeks), size=(BOOTSTRAP, len(weeks)))
    lower = float(np.percentile(s[picks].sum(axis=1) / c[picks].sum(axis=1), 2.5))
    with_draws = [x["random"] for x in use if x["random"]]
    means = np.zeros(RANDOM_DRAWS)
    for options in with_draws:
        means += np.array(options)[rng.integers(0, len(options), size=RANDOM_DRAWS)]
    means = means / max(len(with_draws), 1)
    top = float(np.percentile(means, 97.5))
    rules = [x["rule"] for x in use if x["rule"] is not None]
    rule_mean = float(np.mean(rules)) if rules else None
    out = {"settled": n, "used": len(use), "label": LABEL, "mean_net_pct_of_max_risk": mean, "lower_bound_pct": lower, "expiry_weeks": len(weeks), "random_97_5_pct": top, "random_median_pct": float(np.median(means)), "rule_pick_mean_pct": rule_mean, "no_trade_pct": 0.0}
    if n < VERDICT_COUNT:
        return out | {"status": "reported, no verdict", "warning": WARNING}
    checks = {"mean_above_zero": mean > 0, "lower_bound_above_zero": lower > 0, "above_random_97_5": mean > top, "above_rule_pick": rule_mean is not None and mean > rule_mean}
    return out | {"status": "verdict", "checks": checks, "verdict": "pass" if all(checks.values()) else "fail", "meaning_if_fail": "no large edge found; a smaller edge is not ruled out", "no_second_look": True}


def interim_counts(path: Path, spec_hash: str, sessions: set[date], approved: bool = False, starts: date | None = None) -> dict:
    """The one interim check: counts and missed days only. It reads no price and computes no return."""
    registry.verify(path)
    rows = registry.read(path)
    regs = _registrations(rows, spec_hash, starts)
    if not approved and any(r["symbol"] != SYNTHETIC for r in regs):
        raise RealRowsRefused("real rows are refused until the user approves running on them")
    keys = {r["hash"] for r in regs}
    entries = [r for r in rows if r["type"] == "strategist_entry" and r["registration"] in keys]
    missed = [r["date"] for r in rows if r["type"] == "missed" and r["spec_hash"] == spec_hash and date.fromisoformat(r["date"]) in sessions]
    return {"questions": len(regs), "trades": sum(r["outcome"] == "trade" for r in regs), "no_trade": sum(r["outcome"] == "no_trade" for r in regs), "rejected": sum(r["outcome"] == "rejected" for r in regs),
            "entered": sum(e["status"] == "entered" for e in entries), "void": sum(e["status"] == "void" for e in entries), "missed_days": sorted(missed)}


def at_stop(settled: list[dict], spec_hash: str, today: date, stop: date, trials: list[str]) -> dict:
    """The pre-registered action at the stop date. It refuses to run before it, and shows the trial list with any written decision."""
    if today < stop:
        raise ValueError(f"no performance figure is read before the stop date, {stop}")
    report = evaluate(settled, spec_hash)
    if len(settled) < REPORT_MINIMUM:
        return report | {"action": "the user decides in writing: extend or retire", "trial_list": trials}
    if report["status"] == "verdict":
        return report | {"action": "the verdict stands"}
    if report["lower_bound_pct"] > 0:
        return report | {"action": "the user decides in writing: extend or retire", "trial_list": trials}
    return report | {"action": "retire the test", "statement": "no large edge detected"}

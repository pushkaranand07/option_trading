"""Position sizing from a calibrated edge: fractional Kelly with hard caps (plan, Phase 8).

    Kelly fraction  f* = p - (1 - p) / b      (p = win probability, b = avg win / avg loss)

Full Kelly assumes ``p`` and ``b`` are known exactly; they are estimates, and
over-betting an estimated edge is how accounts blow up. So the size is
``kelly_fraction`` (default 1/4) of ``f*``, then capped at ``max_risk`` of capital
at risk per trade (default 1%, the plan's early-live limit). No edge (f* <= 0)
means no trade.

The capital is the user's to set; nothing here assumes it. The result is the
rupees *at risk* (entry to stop), which the user turns into a quantity with
their own stop distance on Dhan.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SizeAdvice:
    kelly: float            # full Kelly fraction of capital at risk
    fraction: float         # after the Kelly multiplier and the cap
    risk_rupees: float      # capital x fraction
    capped: bool
    reason: str


def kelly(p: float, b: float) -> float:
    if not (0.0 < p < 1.0) or b <= 0:
        raise ValueError("need 0 < p < 1 and b > 0")
    return p - (1.0 - p) / b


def size(p: float, b: float, capital: float, kelly_fraction: float = 0.25, max_risk: float = 0.01) -> SizeAdvice:
    """Rupees to put at risk on one trade, from a calibrated win probability and payoff ratio."""
    if capital <= 0:
        raise ValueError("capital must be positive")
    full = kelly(p, b)
    if full <= 0:
        return SizeAdvice(full, 0.0, 0.0, False, f"no edge: Kelly {full:+.3f} at p={p:.2f}, b={b:.2f}")
    frac = kelly_fraction * full
    capped = frac > max_risk
    frac = min(frac, max_risk)
    why = (f"{kelly_fraction:g} x Kelly {full:.3f} = {kelly_fraction * full:.2%}"
           + (f", capped at {max_risk:.2%}" if capped else ""))
    return SizeAdvice(full, frac, capital * frac, capped, why)


def quantity(risk_rupees: float, entry: float, stop: float, lot: int = 1) -> int:
    """Units (rounded down to whole lots) so that entry-to-stop loses at most ``risk_rupees``."""
    per_unit = abs(entry - stop)
    if per_unit <= 0 or lot <= 0:
        raise ValueError("stop must differ from entry and lot must be positive")
    return int(risk_rupees // (per_unit * lot)) * lot

"""The trading rules the page shows and applies, in one place, served to it by ``GET /api/rules``.

Until 2026-11 the page hard-coded them (app.js). Where the server already had a value it is reused, not copied:
the exit time and the first entry are ``planner.EXIT_BY`` / ``planner.ENTRY_FROM`` (the rule the record replays), and
the credit spreads are ``trade_record.CREDIT`` (the ones whose sold leg carries the Dhan Super order).

Nothing here changes a trade: every paper trade is one lot, the budget card is a display-only filter (it offers only
a single BUY costing at most the budget for one lot; the AI's ranking and the forward test are untouched), and no real
order is placed. The budget is a default: the user can set their own in their browser (localStorage ``pulse.budget``).
The page's static/js/rules.js keeps a copy of these values to use if this request fails;
tests/test_audit_p3_appjs_rules.py checks the two agree.
"""

from __future__ import annotations

from datetime import time

from webapp import planner, trade_record

BUDGET_DEFAULT = 15_000          # rupees, the simple card's budget unless the user set their own in the browser
LOTS = 1                         # every paper trade, yours or the AI's, is one lot
PAPER_ONLY = True                # Take records a dummy trade; no order ever goes to a broker
STOCK_RISK_RUPEES = 1_000        # a stock plan sizes shares so the stop loses about this much
BUDGET_PICK = {"legs": 1, "action": "BUY", "debit": True}       # what the budget card may offer: one bought option
MONEY_LABELS = {"debit": "you pay", "credit": "max loss · Dhan margin is much higher"}


def hhmm(t: time) -> str:
    """09:45, 15:15: a time as the page writes it in 24-hour form."""
    return t.strftime("%H:%M")


def budget_pick(trades: list[dict], budget: float = BUDGET_DEFAULT) -> dict | None:
    """The best-ranked trade (the list is in rank order) that is one bought option whose one lot costs at most
    ``budget`` (its outlay per lot, the premium paid); None when there is no such trade. A trade with a SELL leg needs
    Dhan margin far above a small budget, so it is never picked."""
    for c in trades:
        legs = (c.get("levels") or {}).get("legs") or []
        priced = c.get("priced") or {}
        if (len(legs) == BUDGET_PICK["legs"] and legs[0].get("action") == BUDGET_PICK["action"]
                and bool(priced.get("debit")) == BUDGET_PICK["debit"] and priced.get("outlay_per_lot") is not None
                and priced["outlay_per_lot"] <= budget):
            return c
    return None


def lot_money(debit: bool, per_lot: float) -> dict:
    """What one lot ties up and how to label it. A bought option or debit spread costs its net premium (exact). For a
    credit spread only its worst case is known; the margin Dhan blocks is NOT that number (SPAN + exposure, usually
    far above it), so the label says so and the page never calls it margin."""
    return {"v": per_lot, "label": MONEY_LABELS["debit" if debit else "credit"]}


def trade_money(t: dict) -> float:
    """The money a recorded trade put in: the premium paid for a debit trade (net entry × lot × lots, the entry being
    negative when paid), the worst case for a credit one (max loss per lot × lots)."""
    return -t["net_entry"] * t["lot"] * t["lots"] if t.get("debit") else t["max_loss_per_lot"] * t["lots"]


def rules() -> dict:
    """Everything above as the page reads it (JSON)."""
    return {
        "budget_default": BUDGET_DEFAULT,
        "lots": LOTS,
        "paper_only": PAPER_ONLY,
        "exit_by": hhmm(planner.EXIT_BY),
        "entry_from": hhmm(planner.ENTRY_FROM),
        "stock_risk_rupees": STOCK_RISK_RUPEES,
        "credit_strategies": list(trade_record.CREDIT),
        "budget_pick": dict(BUDGET_PICK),
        "money_labels": dict(MONEY_LABELS),
    }

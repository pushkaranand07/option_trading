"""P3: the trading rules live on the server (webapp/rules.py, GET /api/rules) and the page reads them from there.
The values themselves are unchanged: 1 lot, paper only, the ₹15,000 budget card (a display-only filter: one bought
option costing at most the budget for one lot), exit by 15:15."""

import json
from datetime import time

import pytest

from tests import test_audit_b_support as _support
from tests.test_ui_regressions import ROOT, pytestmark as _needs_node, render
from webapp import planner, rules, trade_record

client, loopback = _support.client, _support.loopback          # fixtures: a TestClient allowed loopback sockets only


def leg(action="BUY", type_="CE"):
    return {"action": action, "type": type_, "strike": 24000, "price": 100.0}


def trade(rank, legs, debit=True, outlay=9000.0):
    return {"rank": rank, "levels": {"legs": legs}, "priced": {"debit": debit, "outlay_per_lot": outlay, "lot": 75}}


SINGLE_BUY = trade(3, [leg()], outlay=9000.0)
POOL = [trade(1, [leg(), leg("SELL")], outlay=5000.0),                 # a debit spread: has a SELL leg
        trade(2, [leg("SELL")], debit=False, outlay=40000.0),          # a naked SELL: never
        trade(3, [leg("BUY", "PE")], outlay=16000.0),                 # one BUY, over the budget
        SINGLE_BUY,
        trade(5, [leg()], outlay=1000.0)]                             # cheaper, but ranked lower


# ---------------------------------------------------------------- the rules themselves (pure)

@pytest.mark.unit
def test_the_trading_rules_are_unchanged():
    r = rules.rules()
    assert r["budget_default"] == 15000 and r["lots"] == 1 and r["paper_only"] is True and r["exit_by"] == "15:15"
    assert r["budget_pick"] == {"legs": 1, "action": "BUY", "debit": True}


@pytest.mark.unit
def test_the_rules_reuse_the_servers_own_values(monkeypatch):
    monkeypatch.setattr(planner, "EXIT_BY", time(15, 0))
    monkeypatch.setattr(planner, "ENTRY_FROM", time(10, 0))
    monkeypatch.setattr(trade_record, "CREDIT", ("bull_put_spread",))
    r = rules.rules()
    assert (r["exit_by"], r["entry_from"], r["credit_strategies"]) == ("15:00", "10:00", ["bull_put_spread"])


@pytest.mark.unit
def test_the_budget_card_picks_the_best_ranked_single_buy_within_the_budget():
    assert rules.budget_pick(POOL) is SINGLE_BUY
    assert rules.budget_pick(POOL, 20000)["rank"] == 3 and rules.budget_pick(POOL, 20000)["priced"]["outlay_per_lot"] == 16000
    assert rules.budget_pick(POOL, 9000) is SINGLE_BUY                      # costing exactly the budget is allowed
    assert rules.budget_pick(POOL, 8999)["rank"] == 5
    assert rules.budget_pick(POOL, 999) is None and rules.budget_pick([]) is None


@pytest.mark.unit
def test_a_trade_with_a_sell_leg_or_a_credit_is_never_the_budget_pick():
    assert rules.budget_pick([trade(1, [leg(), leg("SELL")], outlay=100.0)]) is None
    assert rules.budget_pick([trade(1, [leg("SELL")], debit=False, outlay=100.0)]) is None
    assert rules.budget_pick([trade(1, [leg()], debit=False, outlay=100.0)]) is None
    assert rules.budget_pick([{"rank": 1, "levels": {"legs": [leg()]}, "priced": {"debit": True, "outlay_per_lot": None}}]) is None


@pytest.mark.unit
def test_money_for_one_lot_is_never_called_margin_for_a_credit_trade():
    assert rules.lot_money(True, 9000) == {"v": 9000, "label": "you pay"}
    assert rules.lot_money(False, 4200) == {"v": 4200, "label": "max loss · Dhan margin is much higher"}


@pytest.mark.unit
def test_the_money_a_recorded_trade_put_in():
    assert rules.trade_money({"debit": True, "net_entry": -120.0, "lot": 75, "lots": 1}) == 9000
    assert rules.trade_money({"debit": False, "net_entry": 30.0, "lot": 75, "lots": 1, "max_loss_per_lot": 5250.0}) == 5250


# ---------------------------------------------------------------- GET /api/rules

@pytest.mark.unit
def test_the_rules_endpoint_serves_the_rules(client):
    r = client.get("/api/rules")
    assert r.status_code == 200 and r.json() == rules.rules()
    assert client.post("/api/rules", headers={"X-Pulse-Request": "1"}).status_code == 405      # read-only


# ---------------------------------------------------------------- the page reads them

@pytest.mark.unit
@_needs_node
def test_the_pages_fallback_rules_are_the_servers():
    assert json.loads(render("JSON.stringify(RULES)")) == rules.rules()


@pytest.mark.unit
@_needs_node
@pytest.mark.parametrize("budget", [15000, 20000, 9000, 8999, 999])
def test_the_page_picks_the_same_trade_as_the_server(budget):
    shown = render("JSON.stringify((budgetPick(ARGS[0], ARGS[1]) || {}).rank ?? null)", POOL, budget)
    pick = rules.budget_pick(POOL, budget)
    assert json.loads(shown) == (pick["rank"] if pick else None)


# /api/rules answers ARGS[0] with status ARGS[2]; then the budget card for ARGS[1], a run whose only trade is a
# ₹18,000 single BUY (₹240 × 75).
LOADED = """
var WARN = []; console.warn = (...a) => WARN.push(a.map(String).join(' '));
fetch = async (p) => (p === '/api/rules' ? { ok: ARGS[2] < 400, status: ARGS[2], json: async () => ARGS[0] }
  : { ok: false, status: 404, json: async () => ({}) });
loadRules().then(() => JSON.stringify({ card: budgetCardHtml('NIFTY', ARGS[1]), WARN, budget: budget() }))"""


def _run(price=240.0):
    legs = [{"action": "BUY", "type": "CE", "strike": 24000, "price": price, "premium_at_target": price * 1.5,
             "premium_at_stop": price * 0.7, "pnl_target_per_lot": 9000, "pnl_stop_per_lot": -5400}]
    plan = {"underlying_entry_low": 23950, "underlying_entry_high": 24010, "underlying_target": 24200, "underlying_stop": 23900}
    c = {"rank": 1, "expiry": "13-Nov-2026", "levels": {"legs": legs}, "plan": plan,
         "priced": {"debit": True, "outlay_per_lot": price * 75, "lot": 75}}
    return {"trades": [c], "expiry": "13-Nov-2026"}


@pytest.mark.unit
@_needs_node
def test_the_budget_card_follows_the_rules_the_server_sends():
    served = rules.rules() | {"budget_default": 20000, "exit_by": "15:00"}
    out = json.loads(render(LOADED, served, _run(), 200))
    assert out["budget"] == 20000 and out["WARN"] == []
    assert "For your ₹20,000" in out["card"] and "Exit by 3:00 PM no matter what" in out["card"] and "BUY" in out["card"]


@pytest.mark.unit
@_needs_node
def test_without_the_rules_endpoint_the_page_says_so_and_keeps_the_built_in_rules():
    out = json.loads(render(LOADED, {"detail": "down"}, _run(), 500))
    assert out["budget"] == 15000 and "No trade today" in out["card"]                          # ₹18,000 > ₹15,000
    assert len(out["WARN"]) == 1 and "/api/rules" in out["WARN"][0] and "built-in" in out["WARN"][0]


@pytest.mark.unit
@_needs_node
def test_a_budget_set_in_this_browser_still_wins():
    out = json.loads(render("localStorage.getItem = (k) => (k === 'pulse.budget' ? '20000' : null);" + LOADED,
                            rules.rules(), _run(), 200))
    assert out["budget"] == 20000 and "For your ₹20,000" in out["card"] and "you pay ₹18,000.00" in out["card"]


@pytest.mark.unit
def test_the_page_loads_the_rules_when_it_starts():
    main = (ROOT / "webapp" / "static" / "js" / "main.js").read_text(encoding="utf-8")
    init = main[main.index("(async function init()"):]
    assert "loadRules()" in init[:init.index("poller.start()")]

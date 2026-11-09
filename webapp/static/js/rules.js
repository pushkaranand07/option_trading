// Trading rules the page applies, read from the server (GET /api/rules, webapp/rules.py) when the page starts.
import { api } from "./api.js";
import { store } from "./util.js";

// Used until /api/rules answers, and kept if it fails (said in the console). The same values as webapp/rules.py;
// tests/test_audit_p3_appjs_rules.py checks that they agree.
export const RULES = {
  budget_default: 15000,                  // rupees; this browser's own budget (localStorage pulse.budget) wins
  lots: 1,                                // every paper trade is one lot
  paper_only: true,                       // Take records a dummy trade; no real order
  exit_by: "15:15",                       // planner.EXIT_BY
  entry_from: "09:45",                    // planner.ENTRY_FROM
  stock_risk_rupees: 1000,                // a stock plan sizes shares so the stop loses about this much
  credit_strategies: ["bear_call_spread", "bull_put_spread"],     // trade_record.CREDIT
  budget_pick: { legs: 1, action: "BUY", debit: true },
  money_labels: { debit: "you pay", credit: "max loss · Dhan margin is much higher" },
};

export async function loadRules() {
  try { Object.assign(RULES, await api("/api/rules")); } catch (e) { console.warn(`/api/rules failed (${e.message}); using the built-in trading rules`); }
}

// "15:15" -> "3:15 PM" (or "3:15" without the suffix), the way the page writes a time in a sentence.
export const clock12 = (hhmm, suffix = true) => {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")}${suffix ? (h < 12 ? " AM" : " PM") : ""}`;
};

// Every AI suggestion, recorded automatically and settled by rule (target / stop / expiry).
export const tradeMoney = (t) => (t.debit ? -t.net_entry * t.lot * t.lots : t.max_loss_per_lot * t.lots);

// What one lot ties up: a bought option or debit spread costs its net premium (exact). For a credit spread we only
// know its worst case; the margin Dhan blocks is NOT that number. It is set by Dhan (SPAN + exposure, more on expiry
// day), usually far above it, and a naked SELL blocks about ₹1 lakh+. Never shown as margin.
export function lotMoney(debit, perLot) {
  return { v: perLot, label: RULES.money_labels[debit ? "debit" : "credit"] };
}

// ---------- the user's budget: one lot, only single BUY options it can pay for (display only) ----------
// The AI still ranks all its trades and the forward test still counts its #1 unchanged; this only decides what the
// simple card offers. A trade with a SELL leg needs Dhan margin far above a small budget, so it is never offered.
export const budget = () => Number(store("budget")) || RULES.budget_default;
export function budgetPick(trades, limit = budget()) {   // the AI's best-ranked trade that is one bought option costing ≤ limit for 1 lot
  const p = RULES.budget_pick;
  return trades.find((c) => c.levels?.legs?.length === p.legs && c.levels.legs[0].action === p.action
    && !!c.priced?.debit === p.debit && c.priced?.outlay_per_lot != null && c.priced.outlay_per_lot <= limit) || null;
}

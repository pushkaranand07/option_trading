// Trading rules the page applies: money for one lot and the budget card's pick.
import { store } from "./util.js";

// Every AI suggestion, recorded automatically and settled by rule (target / stop / expiry).
export const tradeMoney = (t) => (t.debit ? -t.net_entry * t.lot * t.lots : t.max_loss_per_lot * t.lots);

// What one lot ties up: a bought option or debit spread costs its net premium (exact). For a credit spread we only
// know its worst case; the margin Dhan blocks is NOT that number. It is set by Dhan (SPAN + exposure, more on expiry
// day), usually far above it, and a naked SELL blocks about ₹1 lakh+. Never shown as margin.
export function lotMoney(debit, perLot) {
  return debit ? { v: perLot, label: "you pay" } : { v: perLot, label: "max loss · Dhan margin is much higher" };
}

// ---------- the user's budget: one lot, only single BUY options it can pay for (display only) ----------
// The AI still ranks all its trades and the forward test still counts its #1 unchanged; this only decides what the
// simple card offers. A trade with a SELL leg needs Dhan margin far above a small budget, so it is never offered.
export const BUDGET = Number(store("budget")) || 15000;
export function budgetPick(trades) {   // the AI's best-ranked trade that is one bought option costing ≤ BUDGET for 1 lot
  return trades.find((c) => c.levels?.legs?.length === 1 && c.levels.legs[0].action === "BUY"
    && c.priced?.debit && c.priced.outlay_per_lot <= BUDGET) || null;
}

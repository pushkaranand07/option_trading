// The Scanner tab: which instrument to buy an option in today, across the indices and the header's F&O stocks
// (POST /api/scan, webapp/scanner.py). The code screens every name by today's tape and an affordable option, builds the
// top few trades the way the Plan tab prices them, and one AI call orders them. Display only: nothing is recorded.
import { api } from "./api.js";
import { contractName, esc, fmt, fmt0, rupee } from "./format.js";
import { selectSymbol } from "./instrument.js";
import { budget } from "./rules.js";
import { S } from "./state.js";
import { refreshStrat } from "./strat.js";
import { showTab } from "./tabs.js";
import { $, istNow, store } from "./util.js";

const SCAN_STAGE = { screen: "Step 1 of 3: checking every index and stock — today's trend and an option you can afford",
  build: "Step 2 of 3: pricing the best few trades", ai: "Step 3 of 3: the AI is ordering them (about a minute)" };

export async function loadScanner() {
  if (!S.scan) {
    try { const r = await api("/api/scan/latest"); S.scan = r.scanned ? { result: r } : {}; } catch { S.scan = {}; }
    const job = store("scanJob"); if (job && !S.scan.running) pollScan(job);
  }
  renderScanner();
}

export async function startScan() {
  S.scan = { ...S.scan, running: true, stage: "screen", error: null }; renderScanner();
  try {
    const { job } = await api("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ budget: budget() }) });
    store("scanJob", job); pollScan(job);
  } catch (e) { S.scan = { ...S.scan, running: false, error: e.message }; renderScanner(); }
}

export async function pollScan(job) {
  try {
    const j = await api("/api/scan/" + job);
    if (j.status === "running") { S.scan = { ...S.scan, running: true, stage: j.stage, started: j.started }; renderScanner(); setTimeout(() => pollScan(job), 3000); return; }
    S.scan = j.status === "done" ? { result: j.result } : { ...S.scan, running: false, error: j.error };
  } catch { S.scan = { ...S.scan, running: false }; }       // the server restarted: the last saved scan stays
  store("scanJob", ""); renderScanner();
}

// One pick: what to buy, for how much, when to take profit or cut it, and why.
export function scanPickHtml(p) {
  const r = p.row, t = r.trade, a = t.plan, l = t.levels.legs[0], lot = t.priced.lot, up = r.tape === "up";
  const ok = l.premium_at_target > l.price && l.premium_at_stop < l.price;
  return `<div class="scan-pick">
    <div class="ai-top"><b class="rk">#${p.rank}</b> <b>${esc(r.symbol)}</b> <span class="badge ${up ? "up" : "down"}">${up ? "trend up · buy a CALL" : "trend down · buy a PUT"}</span>
      ${p.confidence ? `<span class="small muted">AI confidence ${esc(p.confidence)}</span>` : ""}
      <button class="btn small-btn scan-open" data-sym="${esc(r.symbol)}">Open in Plan tab</button></div>
    <div class="budget-order"><span class="leg-tag buy">BUY</span> <b>${esc(contractName(r.symbol, t.expiry, l))}</b> <span class="muted">(1 lot = ${lot} qty)</span></div>
    <div class="levels">
      <div class="lv"><span>Buy at</span><b>₹${fmt(l.price)} or less</b><small>1 lot ${rupee(l.price * lot)} · at the scan</small></div>
      ${ok ? `<div class="lv"><span>Take profit: sell at</span><b class="up">₹${fmt(l.premium_at_target)}</b><small>about +₹${fmt0(l.pnl_target_per_lot)}</small></div>
      <div class="lv"><span>Stop loss: sell at</span><b class="down">₹${fmt(l.premium_at_stop)}</b><small>about −₹${fmt0(-l.pnl_stop_per_lot)}</small></div>`
      : `<div class="lv"><span>Exit</span><b>by hand</b><small>at ${esc(r.symbol)} ${fmt0(a.underlying_target)} (profit) or ${fmt0(a.underlying_stop)} (stop)</small></div>`}
    </div>
    <div class="small">Buy only while ${esc(r.symbol)} is between <b>${fmt0(a.underlying_entry_low)}–${fmt0(a.underlying_entry_high)}</b> (it was ${fmt(r.price)} at ${esc(r.tape_as_of || "—")}).
      Today ${r.move_pct > 0 ? "+" : ""}${fmt(r.move_pct)}% from the open (${fmt(Math.abs(r.move_z))}× a normal day's move) · daily trend ${esc(r.trend)}.</div>
    ${p.why ? `<div class="ai-why">${esc(p.why)}</div>` : ""}</div>`;
}

export function scanTableHtml(rows) {
  const tape = (x) => (x === "up" ? `<b class="up">UP</b>` : x === "down" ? `<b class="down">DOWN</b>` : x ? "mixed" : "—");
  return `<div class="x-scroll"><table class="t scan-t"><thead><tr><th class="left">Instrument</th><th>Tape</th><th>Today</th><th>vs normal day</th><th>Daily trend</th>
      <th class="left">Option you could buy (1 lot)</th><th class="left">Why not a pick</th></tr></thead><tbody>${rows.map((r) => {
      const o = r.option;
      return `<tr><td class="left"><button class="linkish scan-open" data-sym="${esc(r.symbol)}">${esc(r.symbol)}</button></td><td>${tape(r.tape)}</td>
        <td class="num">${r.move_pct != null ? `${r.move_pct > 0 ? "+" : ""}${fmt(r.move_pct)}%` : "—"}</td><td class="num">${r.move_z != null ? fmt(Math.abs(r.move_z)) + "×" : "—"}</td>
        <td>${esc(r.trend || "—")}</td>
        <td class="left small">${o ? `${fmt0(o.strike).replace(/,/g, "")} ${o.type === "CE" ? "CALL" : "PUT"} @ ₹${fmt(o.ask)} = <b>${rupee(o.cost)}</b> · spread ${fmt(o.spread_pct)}%` : "—"}</td>
        <td class="left small muted">${esc(r.why || (r.score > 0 ? "" : "—"))}</td></tr>`; }).join("")}</tbody></table></div>`;
}

export function scannerHtml(sc) {
  const res = sc.result;
  const head = `<section class="card"><div class="card-head"><h2>Aaj kis mein option lein?</h2></div><div class="body">
    <div class="strat-ask"><button class="btn primary scan-go" ${sc.running ? "disabled" : ""}>Scan now</button>
      <span class="small muted">${sc.running ? `<span class="spinner"></span> ${esc(SCAN_STAGE[sc.stage] || "Starting…")}${sc.started ? ` — started ${esc(sc.started)}` : ""}`
        : `NIFTY, BANKNIFTY, FINNIFTY, MIDCAP SELECT and ${S.foStocks.length || 20} F&amp;O stocks · budget ₹${fmt0(budget())}, 1 lot, single BUY only · about 1½ minutes`}</span></div>
    <div class="small muted">Step 1 (code): today's tape for each (price vs VWAP, EMA 9 vs 21, price vs today's open) and the nearest option one lot of fits your budget.
      Step 2 (code): the top ${5} priced like the Plan tab, with target and stop. Step 3 (AI): orders them and leaves weak ones out. Nothing is recorded; no score here is a proven edge.</div>
    ${sc.error ? `<div class="notice">${esc(sc.error)}</div>` : ""}</div></section>`;
  if (!res) return head;
  const notes = (res.market_closed ? `<div class="notice">Scan market band hone pe hua: prices last close ke hain. 9:15 ke baad dobara scan karo.</div>` : "")
    + (res.ai_error ? `<div class="notice">The AI step failed (${esc(res.ai_error)}): the picks are in the code's order, without reasons.</div>` : "");
  const picks = res.picks?.length ? res.picks.map(scanPickHtml).join("")
    : `<div class="call stop"><b>No pick right now.</b> ${esc(res.market_read || "")}</div>`;
  return head + `<section class="card"><div class="card-head"><h2>Picks · scan at ${esc(res.asked_at.slice(-5))}</h2><span class="small muted">budget ₹${fmt0(res.budget)}</span></div>
    <div class="body">${notes}${res.picks?.length && res.market_read ? `<p>${esc(res.market_read)}</p>` : ""}${picks}
      ${res.left_out ? `<div class="small muted">Left out: ${esc(res.left_out)}</div>` : ""}
      <div class="small muted">Prices are from the scan time and move. Open a pick in the Plan tab for its live chain, then run a Quick analysis there (a stock needs a Complete analysis first). Exit intraday trades by 3:15 PM.</div></div></section>`
    + `<section class="card"><div class="card-head"><h2>Everything scanned (${res.scanned.length})</h2></div><div class="body">${scanTableHtml(res.scanned)}</div></section>`;
}

export function renderScanner() {
  const el = $("#scannerBody"); if (!el) return;
  el.innerHTML = scannerHtml(S.scan || {});
  $(".scan-go", el).onclick = startScan;
  el.querySelectorAll(".scan-open").forEach((b) => (b.onclick = () => openInPlan(b.dataset.sym)));
}

// "Open in Plan tab": the Plan tab shows this pick's trade (card, chart lines, BUY tag on the chain, ticket), not an
// empty page. A name from the table that was not a pick just opens its Plan tab.
export function scanTrade(res, sym) {
  const p = (res?.picks || []).find((x) => x.symbol === sym && x.row?.trade);
  if (!p) return null;
  const old = res.asked_at.slice(0, 10) !== istNow().date;
  return { ...p.row.trade, symbol: sym, rank: p.rank, ai_why: p.why, plan: { ...p.row.trade.plan, confidence: p.confidence || p.row.trade.plan.confidence },
    _label: `Scanner pick #${p.rank} · scan at ${res.asked_at.slice(-5)}`, _scanAt: res.asked_at, _scanOld: old,
    _locked: old ? "scan kisi aur din ka hai" : "scanner ka trade record nahi hota; Quick analysis chala ke uska trade Take kar" };
}
export function openInPlan(sym) {
  const t = scanTrade(S.scan?.result, sym);
  if (t) { S.scanPick[sym] = t; S.view[sym] = "scan"; S.ticket[sym] = null; }
  selectSymbol(sym); showTab("plan");
  refreshStrat(sym);                    // the same instrument already open: show the pick now
}

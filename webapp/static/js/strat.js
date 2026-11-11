// The Plan tab's AI strategist: runs, the ranked trades' card, the leg ticket and Take.
import { api } from "./api.js";
import { v2LineHtml } from "./banners.js";
import { chartOff, chartProblem } from "./chart.js";
import { COST_NOTE, cap, cls, contractName, esc, fmt, fmt0, lakh, money, pnl, rupee, sign } from "./format.js";
import { renderNseChain } from "./nsechain.js";
import { drawPlanChartLines } from "./planchart.js";
import { NAMES, S } from "./state.js";
import { loaded } from "./tabs.js";
import { aiListHtml, legLevelsOk, legRole, stratHtml, takeKey, withLive } from "./tradeview.js";
import { $, cssVar, istNow, store } from "./util.js";

export const stratJobs = JSON.parse(store("stratJobs") || "{}");

// Two buttons (user's choice): the Complete analysis runs the research once a day (10-15 min, best before the open) and
// saves it; a Quick analysis reuses it with the live chart, today's moves and the chain (1-2 min), as often as wanted.
export const STAGE = { full: { agents: "Step 1 of 2: the research agents are reading the news, yesterday's market and sentiment, and debating bull vs bear (10-15 min)",
    ranking: "Step 2 of 2: the AI is ranking the live trades by the whole analysis" },
  quick: { agents: "Using today's research…", ranking: "The AI is reading the live chart, today's moves and the option chain and ranking the trades (1-2 min)" } };
export async function loadResearch(sym) {
  try { S.research[sym] = await api("/api/strategy/research/" + encodeURIComponent(sym)); } catch { S.research[sym] = {}; }
  renderStrat(sym);
}
export function renderStrat(sym) {
  const slot = $(`.plan-card[data-sym="${sym}"] .strat-slot`); if (!slot) return;
  const st = S.strat[sym] || {}, res = liveResult(sym), lv = res?._live;
  const rs = S.research[sym] || {}, have = !!rs.source, busy = st.running ? "disabled" : "";
  const liveNote = lv ? ` Prices and each trade's status are <b>live</b>: NSE ${esc(lv.as_of)}, ${esc(NAMES[sym] || sym)} ${fmt0(lv.spot)}${lv.spot_at_run != null ? ` (${fmt0(lv.spot_at_run)} at the run)` : ""}. No AI call; the AI's read is still the run's.`
    : S.stratLive[sym]?.live === false && S.stratLive[sym].why && !res?.expired && !res?.market_closed ? ` Prices are the run's, not live: ${esc(S.stratLive[sym].why)}` : "";
  const researchLine = have ? `Today's research: <b>${esc(rs.source)}</b> at ${esc(rs.at)}${rs.rating ? `, the agents' call <b>${esc(rs.rating)}</b>` : ""}. A Quick analysis uses it with the live market.`
    : `No research yet today. Run the <b>Complete analysis</b> once (best before 9:15); after that, Quick analysis takes 1-2 minutes.`;
  const ask = `<div class="strat-ask strat-modes">
      <button class="btn ${have ? "" : "primary"} strat-go" data-mode="full" ${busy}>Complete analysis</button>
      <button class="btn ${have ? "primary" : ""} strat-go" data-mode="quick" ${busy || (have ? "" : "disabled")}>Quick analysis</button>
      <span class="small muted">${st.running ? `<span class="spinner"></span> ${esc(STAGE[st.mode]?.[st.stage] || "Starting…")} — started ${esc(st.started || "")}` : researchLine}</span></div>
    <div class="small muted">Complete: news, yesterday's market, sentiment and the bull / bear debate, then the 8 trades (10-15 min, once a day). Quick: today's research plus the live chart, today's moves and the option chain, then the 8 trades (1-2 min).
      ${res && !st.running ? `The 8 trades below and their order are fixed from the run at <b>${esc(res.asked_at.slice(-5))}</b>; they change only when you run again.` : ""}${res ? liveNote : ""}</div>
    <div class="small v2-line">${v2LineHtml()}</div>`;
  const v = S.view[sym], cand = typeof v === "number" ? res?.trades?.[v] : null, scan = S.scanPick[sym];
  slot.innerHTML = ask + (st.error ? `<div class="notice">${esc(st.error)}</div>` : "")
    + (scan ? scanBannerHtml(sym, scan, v === "scan") : "")
    + (v === "scan" && scan ? stratHtml(scan, sym) : "")
    + (res ? aiListHtml(sym, res) : "")
    + (cand ? stratHtml(Object.assign(cand, { _locked: res.expired ? "run expired" : res.market_closed ? "market band" : null }), sym) : "");
  slot.querySelectorAll(".ai-trade").forEach((r) => (r.onclick = () => { S.view[sym] = S.view[sym] === +r.dataset.ai ? null : +r.dataset.ai; S.ticket[sym] = null; refreshStrat(sym); }));
  slot.querySelectorAll(".strat-go").forEach((b) => (b.onclick = () => startStrat(sym, b.dataset.mode)));
  if ($(".scan-show", slot)) $(".scan-show", slot).onclick = () => { S.view[sym] = S.view[sym] === "scan" ? null : "scan"; S.ticket[sym] = null; refreshStrat(sym); };
  if ($(".scan-drop", slot)) $(".scan-drop", slot).onclick = () => { delete S.scanPick[sym]; if (S.view[sym] === "scan") S.view[sym] = null; S.ticket[sym] = null; refreshStrat(sym); };
  slot.querySelectorAll("[data-leg]").forEach((b) => (b.onclick = () => openTicket(sym, +b.dataset.leg)));
  if ($(".take-trade", slot)) $(".take-trade", slot).onclick = () => takeTrade(sym);
  slot.querySelectorAll(".rank-take").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); takeRanked(sym, +b.dataset.take, b); }));
  if (S.ticket[sym]) renderTicket(sym);
}

export async function startStrat(sym, mode = "quick") {
  const prev = S.strat[sym]?.result;                       // the last trades stay on screen while the new run works
  S.strat[sym] = { running: true, mode, started: istNow().hhmm.slice(0, 5), result: prev }; renderStrat(sym);
  try {
    const { job } = await api("/api/strategy", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, expiry: S.nseExp[sym] || null, mode }) });
    stratJobs[sym] = job; store("stratJobs", JSON.stringify(stratJobs));
    pollStrat(sym, job);
  } catch (e) { S.strat[sym] = { error: e.message, result: prev }; renderStrat(sym); }
}

export async function pollStrat(sym, job) {
  try {
    const j = await api("/api/strategy/" + job);
    const prev = S.strat[sym]?.result;
    if (j.status === "running") { S.strat[sym] = { running: true, mode: j.mode || "full", started: j.started, stage: j.stage, result: prev }; renderStrat(sym); setTimeout(() => pollStrat(sym, job), 3000); return; }
    S.strat[sym] = j.status === "done" && j.result?.trades ? { result: j.result } : j.status === "done" ? { result: prev } : { error: j.error, result: prev };
    if (j.result?.mode === "full") loadResearch(sym);
    S.ticket[sym] = null; S.view[sym] = S.strat[sym].result?.trades?.length ? 0 : null;
    delete stratJobs[sym]; store("stratJobs", JSON.stringify(stratJobs));
  } catch { delete stratJobs[sym]; store("stratJobs", JSON.stringify(stratJobs)); S.strat[sym] = {}; }   // server restarted
  renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym);
  loadLiveTrades(sym);                  // the run took about a minute: put NSE's prices of now on it straight away
}

// The run's trades at NSE's prices now (no AI call): asked for with every chain poll during the session, when a run
// ends and when a saved run loads. A run that is expired or was made with the market closed stays as it is. A failed
// request keeps the last answer, which withLive drops once it is two minutes old.
export async function loadLiveTrades(sym) {
  const res = S.strat[sym]?.result;
  if (!res?.run_id || !res.trades?.length || res.expired || res.market_closed) return;
  try { S.stratLive[sym] = { ...(await api("/api/strategy/live/" + encodeURIComponent(sym))), _got: Date.now() }; } catch { return; }
  renderStrat(sym);
}
export const liveResult = (sym) => withLive(S.strat[sym]?.result, S.stratLive[sym]);
Object.entries(stratJobs).forEach(([sym, job]) => pollStrat(sym, job));   // a result survives a page reload

// The last run, saved on the server: its trades stay the same until the next run (reloads, restarts).
export async function loadLatestRun(sym) {
  if (S.strat[sym]?.result || S.strat[sym]?.running || stratJobs[sym]) return;
  try {
    const res = await api("/api/strategy/latest/" + encodeURIComponent(sym));
    if (!res.trades || S.strat[sym]?.result || S.strat[sym]?.running) return;
    S.strat[sym] = { result: res };
    if (S.view[sym] !== "scan") S.view[sym] = res.trades.length ? 0 : null;      // a pick opened from the Scanner stays shown
    refreshStrat(sym);
    loadLiveTrades(sym);
  } catch { /* no saved run */ }
}

export async function openTicket(sym, i) {
  const res = curRes(sym); if (!res) return;
  S.ticket[sym] = S.ticket[sym]?.i === i ? null : { i, data: null };          // a second tap closes it
  renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym);
  const leg = (res.levels?.legs || res.priced.legs)[i];
  if (!S.ticket[sym] || !leg.id) return;
  try { S.ticket[sym].data = await api("/api/contract?id=" + encodeURIComponent(leg.id)); } catch (e) { S.ticket[sym].data = { error: e.message }; }
  if (S.ticket[sym]?.i === i) renderTicket(sym);
  $(`.plan-card[data-sym="${sym}"] .plan-oc tr.focus`)?.scrollIntoView({ block: "nearest" });
}

export let ticketChart = null;
export function renderTicket(sym) {
  const slot = $(`.plan-card[data-sym="${sym}"] .ticket-slot`), t = S.ticket[sym], res = curRes(sym);
  if (ticketChart) { ticketChart.remove(); ticketChart = null; }
  if (!slot) return;
  if (!t || !res) { slot.innerHTML = ""; return; }
  const l = (res.levels?.legs || res.priced.legs)[t.i], d = t.data, lot = res.lot, buy = l.action === "BUY";
  const role = legRole(res.plan.strategy, res.levels?.legs || res.priced.legs, l), dhan = role === "super" && legLevelsOk(l, l.premium_at_target, l.premium_at_stop);
  const nm = NAMES[sym] || sym;
  const chgPct = l.ltp && l.chg != null ? (l.chg / (l.ltp - l.chg)) * 100 : null;
  const totB = l.total_buy_qty || 0, totS = l.total_sell_qty || 0, bidPct = totB + totS ? (totB / (totB + totS)) * 100 : null;
  slot.innerHTML = `<div class="ticket">
    <div class="ticket-head"><div><div class="ask">${buy ? "Buy" : "Sell"} · tap the card again to close</div><h3>${esc(contractName(sym, res.expiry, l))}</h3>
      <div class="ticket-ltp"><b>${fmt(l.ltp)}</b> <span class="${cls(l.chg)}">${sign(l.chg)}${fmt(l.chg)}${chgPct != null ? ` (${sign(chgPct)}${chgPct.toFixed(2)}%)` : ""}</span></div></div>
      <div class="ticket-ohlc">${[["High", d?.high], ["Low", d?.low], ["Prev. close", d?.prev_close]].map(([k, v]) => `<div><span>${k}</span><b>${v != null ? fmt(v) : "—"}</b></div>`).join("")}</div></div>
    <div class="ticket-chart">${!d ? `<div class="loading"><span class="spinner"></span>Loading the option's price from NSE…</div>` : d.error ? `<div class="notice">${esc(d.error)}</div>` : ""}</div>
    <div class="ticket-grid">
      <div class="ticket-box"><h4 class="mini-h">How to place it in Dhan</h4>
        <table class="facts small-facts">
          <tr><th>Side</th><td><span class="leg-tag ${buy ? "buy" : "sell"}">${l.action}</span></td></tr>
          <tr><th>Lot</th><td>1 lot = <b>${lot}</b> qty (you choose how many lots)</td></tr>
          <tr><th>P&L figures</th><td class="small muted">${cap(COST_NOTE)}</td></tr>
          <tr><th>Order type</th><td>${dhan ? "<b>Super</b> order (limit + target + stop loss in one)" : role === "hedge" ? "<b>Limit</b> order — protection, place it first" : "<b>Limit</b> order — close both legs together by hand"}</td></tr>
          <tr><th>Limit price</th><td><b>${rupee(l.price)}</b> <span class="muted small">(${buy ? "the best ask" : "the best bid"} now)</span></td></tr>
          ${dhan ? `<tr><th>Target</th><td><b class="up">${rupee(l.premium_at_target)}</b> ${l.pnl_target_per_lot != null ? `<span class="small">(${pnl(l.pnl_target_per_lot)} a lot)</span>` : ""}</td></tr>
          <tr><th>Stop loss</th><td><b class="down">${rupee(l.premium_at_stop)}</b> ${l.pnl_stop_per_lot != null ? `<span class="small">(${pnl(l.pnl_stop_per_lot)} a lot)</span>` : ""}</td></tr>`
          : `<tr><th>Target / stop</th><td>${role === "hedge" ? "<b>none</b> — sell it right after the SELL leg's target or stop fills" : `<b>none in Dhan</b> — close by hand when ${esc(nm)} reaches its target or stop`}</td></tr>
          <tr><th>Expected price</th><td class="small">at ${esc(nm)} target <b class="ref">${rupee(l.premium_at_target)}</b> · at ${esc(nm)} stop <b class="ref">${rupee(l.premium_at_stop)}</b></td></tr>`}
          <tr><th>${buy ? "Money needed" : "Margin"}</th><td>${buy ? `<b>${money(l.price * lot)}</b> a lot (premium × qty)` : `set by Dhan; with the bought leg placed first it is close to the spread's worst case, <b>${money(res.priced.max_loss_per_lot)}</b> a lot`}</td></tr>
        </table></div>
      <div class="ticket-box"><h4 class="mini-h">Market depth (best price)</h4>
        <table class="depth"><thead><tr><th>Qty</th><th>Bid</th><th>Ask</th><th>Qty</th></tr></thead>
          <tbody><tr><td>${l.bid_qty != null ? fmt0(l.bid_qty) : "—"}</td><td class="up">${fmt(l.bid)}</td><td class="down">${fmt(l.ask)}</td><td>${l.ask_qty != null ? fmt0(l.ask_qty) : "—"}</td></tr></tbody></table>
        <div class="depth-tot small"><span>Total buy <b>${fmt0(totB)}</b></span><span>Total sell <b>${fmt0(totS)}</b></span></div>
        ${bidPct != null ? `<div class="bidbar"><div style="width:${bidPct}%">${bidPct.toFixed(0)}% bids</div><div>${(100 - bidPct).toFixed(0)}% offers</div></div>` : ""}
        <div class="small muted">Spread ${fmt(l.ask - l.bid)} (${l.ask && l.bid ? (((l.ask - l.bid) / ((l.ask + l.bid) / 2)) * 100).toFixed(1) : "—"}%). NSE publishes only the best level; Dhan shows 5.</div>
        <div class="small muted">IV ${l.iv ? l.iv.toFixed(1) + "%" : "—"} · OI ${lakh(l.oi)}</div></div>
    </div></div>`;
  if (!d || d.error || !d.points?.length) return;
  const el = $(".ticket-chart", slot);
  if (chartProblem()) return void chartOff(el, true);
  ticketChart = LightweightCharts.createChart(el, { autoSize: true, layout: { background: { type: "solid", color: "transparent" }, textColor: cssVar("--muted"),
      fontFamily: "Inter, system-ui, sans-serif" }, grid: { vertLines: { color: cssVar("--grid") }, horzLines: { color: cssVar("--grid") } },
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false }, crosshair: { mode: 0 } });
  const s = ticketChart.addAreaSeries({ lineColor: cssVar("--ema9"), topColor: "rgba(47,111,237,.18)", bottomColor: "rgba(47,111,237,0)", lineWidth: 2, priceLineVisible: false });
  let last = 0; s.setData(d.points.filter(([tm]) => (tm > last ? ((last = tm), true) : false)).map(([tm, p]) => ({ time: tm, value: p })));
  const mk = (price, color, title, style = 2) => price && s.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
  mk(l.price, cssVar("--text"), buy ? "Buy at" : "Sell at", 0);
  if (dhan) { mk(l.premium_at_target, cssVar("--up"), "Target"); mk(l.premium_at_stop, cssVar("--down"), "Stop loss"); }
  else { mk(l.premium_at_target, cssVar("--muted"), `at ${nm} target`); mk(l.premium_at_stop, cssVar("--muted"), `at ${nm} stop`); }
  ticketChart.timeScale().fitContent();
}

// ---------- Trade Record: dummy trades taken from the AI strategist ----------
// One lot each. Marked live from the NSE chain at the price each leg could be closed at; when the index reaches the
// target or stop the trade closes itself at those prices (the stop if both). Stored on this computer (reports/trade_record).
// A Take sends only the run and the trade's place in it: the server prices the entry from a fresh chain now and
// refuses (with the reason shown here) a run from another day, a closed market, NIFTY outside the entry zone or a
// leg with no live bid / ask. A Take that would join a bet already running in the same direction comes back 409:
// the page asks, and only an OK sends it again with confirm (the server writes nothing until then).
export const takeBody = (sym, i, extra = {}) => JSON.stringify({ run_id: S.strat[sym]?.result?.run_id || null, candidate: i, ...extra });
export async function takePost(sym, i) {
  const post = (extra) => api("/api/trades", { method: "POST", headers: { "Content-Type": "application/json" }, body: takeBody(sym, i, extra) });
  try { return await post(); } catch (e) {
    if (e.status !== 409) throw e;
    return confirm(e.message) ? post({ confirm: true }) : null;                 // cancel: nothing recorded
  }
}
export async function takeRanked(sym, i, btn) {
  const c = S.strat[sym]?.result?.trades?.[i];
  if (!c) return;
  btn.disabled = true;
  try {
    if (!(await takePost(sym, i))) { btn.disabled = false; return; }
    S.takenRank[takeKey(c)] = true; renderStrat(sym); loaded.record = false;
  } catch (e) { alert(e.message); btn.disabled = false; }
}

export async function takeTrade(sym) {
  const res = curRes(sym); if (!res) return;
  const btn = $(`.plan-card[data-sym="${sym}"] .take-trade`); if (btn) btn.disabled = true;
  try {
    const t = await takePost(sym, S.view[sym]);
    if (!t) { if (btn) btn.disabled = false; return; }
    const run = S.strat[sym].result.trades[S.view[sym]];             // the run's own trade: res may be its live copy
    run._taken = t.id; S.takenRank[takeKey(res)] = true; renderStrat(sym); loaded.record = false;
  } catch (e) { alert(e.message); if (btn) btn.disabled = false; }
}

// ---------- the AI's ranked trades: which one the detail card shows ----------
export function curRes(sym) {          // the trade shown in the detail card: one of the AI's ranked trades
  const v = S.view[sym];
  if (v === "scan") return S.scanPick[sym] || null;                                 // opened from the Scanner tab
  return typeof v === "number" ? liveResult(sym)?.trades?.[v] || null : null;      // at live prices when there are any
}
// The Scanner's pick for this instrument: where it came from, its price then and NSE's ask now (the chain on this tab,
// refreshed every 15 s), and buttons to show or hide its card.
export function scanBannerHtml(sym, t, on) {
  const l = t.levels.legs[0], q = S.nse[sym]?.expiry === t.expiry ? S.nse[sym].rows.find((r) => r.strike === l.strike)?.[l.type.toLowerCase()] : null;
  const now = q?.ask ? ` · NSE abhi <b>₹${fmt(q.ask)}</b> (${q.ask > l.price ? "+" : ""}${fmt(q.ask - l.price)})` : "";
  return `<div class="scan-banner ${on ? "on" : ""}"><span class="badge flat">From the Scanner</span>
    <span><b>${esc(t._label)}</b>: ${l.action} ${esc(contractName(sym, t.expiry, l))} @ ₹${fmt(l.price)} at the scan${now}</span>
    ${t._scanOld ? `<span class="small warn-c">⚠ This scan is from another day: its prices are not today's.</span>` : ""}
    <span class="scan-banner-btns"><button class="btn small-btn scan-show">${on ? "Hide card" : "Show card"}</button><button class="btn small-btn scan-drop" title="Remove">✕</button></span></div>`;
}
export function refreshStrat(sym) { renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym); }

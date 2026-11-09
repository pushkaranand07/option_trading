// The Plan tab's NSE option chain.
import { api } from "./api.js";
import { cls, esc, fmt, fmt0, lakh, sign } from "./format.js";
import { phase, planEntries } from "./plan.js";
import { drawPlanChartLines } from "./planchart.js";
import { NAMES, S, nameOf } from "./state.js";
import { curRes, renderStrat } from "./strat.js";
import { $, PREVIEW_AT, istNow, store } from "./util.js";

// ---------- Plan tab: NSE option chain and the AI strategist ----------
// The chain comes from NSE (OI in units, as trading apps show it). The AI proposes one defined-risk strategy or
// none; the server checks it and prices it at the bid / ask, per lot.
// Every 15 s, only on the Plan tab during the live session (outside it the chain does not move).
export function pollNseChains() {     // returns the loads, so the scheduler sees them pending and never overlaps a run
  if (S.tab === "plan" && S.morning && phase(S.morning.session).key === "live") return Promise.all((planEntries() || []).map(([sym]) => loadNseChain(sym)));
}

export async function loadNseChain(sym, expiry) {
  const slot = $(`.plan-card[data-sym="${sym}"] .chain-slot`); if (!slot) return;
  if (expiry) S.nseExp[sym] = expiry;
  if (!S.nse[sym]) slot.innerHTML = `<div class="loading"><span class="spinner"></span>Loading the option chain from NSE…</div>`;
  try {
    const c = await api(`/api/chain/${encodeURIComponent(sym)}${S.nseExp[sym] ? "?expiry=" + encodeURIComponent(S.nseExp[sym]) : ""}`);
    S.nse[sym] = c; S.nseExp[sym] = c.expiry;
    renderNseChain(sym); drawPlanChartLines(sym); if (!S.strat[sym]?.running) renderStrat(sym);
  } catch (e) {
    slot.innerHTML = `<div class="call idle small">${esc(e.message.includes("not known") || e.message.includes("no option") ? `${nameOf(sym)} has no options on NSE.` : "Option chain unavailable: " + e.message)}</div>`;
  }
}

export function legsAt(sym) {          // strike|type -> "BUY" / "SELL" from the AI's proposal, to mark them in the chain
  const r = curRes(sym), out = {};
  if (r && !r.rejected && r.expiry === S.nse[sym]?.expiry) (r.plan.legs || []).forEach((l) => (out[l.strike + l.option_type] = l.action));
  return out;
}

export function focusLeg(sym) {         // the leg whose ticket is open, if it is on the chain shown
  const t = S.ticket[sym], r = curRes(sym);
  return t && r?.priced && r.expiry === S.nse[sym]?.expiry ? r.priced.legs[t.i] : null;
}

// How old NSE's snapshot is, e.g. " (52 s ago)"; NSE stamps "26-Oct-2026 11:44:29" in IST.
export function nseAge(ts) {
  const m = /(\d{2}):(\d{2}):(\d{2})$/.exec(ts || ""); if (!m || PREVIEW_AT) return "";
  const now = istNow(), secs = now.mins * 60 + new Date().getSeconds() - (+m[1] * 3600 + +m[2] * 60 + +m[3]);
  return secs >= 0 && secs < 3600 ? ` (${secs < 90 ? secs + " s" : Math.round(secs / 60) + " min"} ago)` : "";
}

export function renderNseChain(sym) {
  const c = S.nse[sym], slot = $(`.plan-card[data-sym="${sym}"] .chain-slot`); if (!c || !slot) return;
  const v = S.nseView, mark = legsAt(sym), sm = c.summary, focus = focusLeg(sym);
  const metric = { oi: ["OI", (q) => q?.oi, (q) => q?.chg_oi], volume: ["Volume", (q) => q?.volume, () => null], iv: ["IV", (q) => q?.iv, () => null] }[v];
  const top = (side) => new Set(c.rows.filter((r) => r[side]).sort((a, b) => (metric[1](b[side]) || 0) - (metric[1](a[side]) || 0)).slice(0, 3).map((r) => r.strike));
  const topCe = top("ce"), topPe = top("pe");
  const maxV = Math.max(1, ...c.rows.flatMap((r) => [metric[1](r.ce) || 0, metric[1](r.pe) || 0]));
  const val = (q) => (v === "iv" ? (q?.iv ? q.iv.toFixed(1) : "—") : lakh(metric[1](q)));
  const chg = (x) => (x == null ? "" : `<small class="${cls(x)}">${x > 0 ? "+" : ""}${lakh(x)}</small>`);
  const prem = (q) => (q ? `<b>${fmt(q.ltp)}</b><small class="${cls(q.chg)}">${sign(q.chg)}${fmt(q.chg)}</small>` : "—");
  const tag = (k) => (mark[k] ? `<span class="leg-tag ${mark[k] === "BUY" ? "buy" : "sell"}">${mark[k]}</span>` : "");
  let spotDone = false;
  const rows = c.rows.map((r) => {
    let line = "";
    if (!spotDone && r.strike > c.spot) { spotDone = true; line = `<tr class="spot-row"><td colspan="5"><span>${esc(NAMES[sym] || sym)} ${fmt(c.spot)}</span></td></tr>`; }
    const ci = r.strike < c.spot ? "itm" : "", pi = r.strike > c.spot ? "itm" : "";
    const ceK = r.strike + "CE", peK = r.strike + "PE";
    return line + `<tr class="${r.strike === c.atm ? "atm" : ""}${mark[ceK] || mark[peK] ? " picked" : ""}${focus && focus.strike === r.strike ? " focus focus-" + focus.type : ""}">
      <td class="${ci} ${topCe.has(r.strike) ? "hot" : ""}"><div class="bar ce-bar" style="width:${(metric[1](r.ce) || 0) / maxV * 100}%"></div><span class="v">${val(r.ce)}${chg(metric[2](r.ce))}</span></td>
      <td class="${ci} prem">${tag(ceK)}${prem(r.ce)}</td>
      <td class="strike">${fmt0(r.strike)}<small>PCR ${r.pcr != null ? r.pcr.toFixed(2) : "—"}</small></td>
      <td class="${pi} prem">${prem(r.pe)}${tag(peK)}</td>
      <td class="${pi} ${topPe.has(r.strike) ? "hot" : ""}"><div class="bar pe-bar" style="width:${(metric[1](r.pe) || 0) / maxV * 100}%"></div><span class="v">${val(r.pe)}${chg(metric[2](r.pe))}</span></td></tr>`;
  }).join("");
  const note = $(`.plan-card[data-sym="${sym}"] .chain-note`);
  if (note) note.textContent = `NSE data as of ${c.timestamp || c.fetched}${nseAge(c.timestamp)} · NSE updates about every 45 s · lot ${c.lot}`;
  slot.innerHTML = `<div class="seg-row">${c.expiries.slice(0, 6).map((x) => `<button class="seg ${x === c.expiry ? "on" : ""}" data-exp="${esc(x)}">${esc(x.slice(0, 6))}</button>`).join("")}</div>
    <div class="oc-stats">${[["PCR", sm.pcr?.toFixed(2)], ["Call wall", fmt0(sm.resistance)], ["Put wall", fmt0(sm.support)], ["Max pain", fmt0(sm.max_pain)], ["ATM IV", sm.atm_iv ? sm.atm_iv.toFixed(1) + "%" : "—"]]
      .map(([k, x]) => `<div class="stat"><span>${k}</span><b class="num">${x ?? "—"}</b></div>`).join("")}</div>
    <div class="seg-row">${[["oi", "Open interest"], ["volume", "Volume"], ["iv", "Implied vol"]].map(([k, t]) => `<button class="seg ${k === v ? "on" : ""}" data-view="${k}">${t}</button>`).join("")}
      <span class="small muted">Top 3 per side in bold · BUY / SELL tags are the AI's strikes</span></div>
    <div class="oc-scroll plan-oc"><table class="oc"><thead><tr><th class="calls">Calls ${metric[0]}</th><th class="calls">Call LTP</th><th class="strike">Strike</th><th class="puts">Put LTP</th><th class="puts">Puts ${metric[0]}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="small muted">Biggest call OI above the price acts as a ceiling (call wall), biggest put OI below as a floor (put wall). Shaded cells are in the money. ${c.fetched ? `Fetched ${esc(c.fetched)}.` : ""}
      <button class="btn small-btn chain-refresh">Refresh</button></p>`;
  slot.querySelectorAll("[data-exp]").forEach((b) => (b.onclick = () => loadNseChain(sym, b.dataset.exp)));
  slot.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => { S.nseView = b.dataset.view; store("nseView", S.nseView); renderNseChain(sym); }));
  $(".chain-refresh", slot).onclick = () => loadNseChain(sym);
  const sc = $(".plan-oc", slot), atm = $("tr.spot-row", sc) || $("tr.atm", sc);
  if (atm && slot.dataset.centered !== c.expiry) { sc.scrollTop = atm.offsetTop - sc.clientHeight / 2; slot.dataset.centered = c.expiry; }
}

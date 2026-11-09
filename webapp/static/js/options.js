// The Options tab: the live Dhan option chain and the measured trading costs.
import { api } from "./api.js";
import { cls, esc, fmt, fmt0, fmtInt, freshLine, pc } from "./format.js";
import { S, isIndex } from "./state.js";
import { $ } from "./util.js";

// ---------- option chain ----------
$("#expirySel").onchange = (e) => { S.expiry = e.target.value; loadChain(); };
export async function loadOptions() {
  const notice = $("#ocNotice");
  $("#ocTable tbody").innerHTML = ""; $("#ocStats").innerHTML = "";
  const hideChain = (msg) => { notice.hidden = false; notice.textContent = msg; $(".oc-scroll", $("#ocTable").closest(".pad")).hidden = true; $("#expirySel").closest("label").hidden = true; };
  $(".oc-scroll", $("#ocTable").closest(".pad")).hidden = false; $("#expirySel").closest("label").hidden = false;
  if (!isIndex(S.sym)) { hideChain("The live option chain is shown for indices. Pick NIFTY, BANKNIFTY or another index above — the trading costs below work for stocks too."); return; }
  if (S.status?.dhan === false) { S.expiry = null; hideChain(NEEDS_DHAN); return; }     // no request that can only fail
  try {
    const exps = await api("/api/expiries/" + S.sym);
    S.expiry = S.expiry && exps.includes(S.expiry) ? S.expiry : exps[0];
    $("#expirySel").innerHTML = exps.map((x) => `<option ${x === S.expiry ? "selected" : ""}>${x}</option>`).join("");
    notice.hidden = true; loadChain();
  } catch (e) { hideChain(e.message.includes("Dhan") ? NEEDS_DHAN : e.message); }
}
export const NEEDS_DHAN = "The live option chain needs a Dhan connection (DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env). The trading costs below work without it.";
export let chainBusy = false, chainCentered = null;
export async function loadChain() {
  if (chainBusy || !S.expiry || S.status?.dhan === false) return; chainBusy = true;
  const sym = S.sym, exp = S.expiry;
  try {
    const c = await api(`/api/optionchain/${sym}?expiry=${exp}`);
    if (sym === S.sym && exp === S.expiry) renderChain(c);
  } catch (e) { $("#ocNotice").hidden = false; $("#ocNotice").textContent = e.message; } finally { chainBusy = false; }
}
export function renderChain(c) {
  const v = c.view || {};
  $("#ocStats").innerHTML = [["Spot", fmt(c.spot)], ["ATM", fmt0(v.atm)], ["PCR", v.pcr], ["Max pain", fmt0(v.max_pain)],
    ["Support", fmt0(v.support)], ["Resistance", fmt0(v.resistance)], ["ATM IV", v.atm_iv ?? "—"], ["Lot", c.lot]]
    .map(([k, x]) => `<div class="stat"><span>${k}</span><b class="num">${x}</b></div>`).join("");
  const maxOi = Math.max(1, ...c.rows.flatMap((r) => [r.ce?.oi || 0, r.pe?.oi || 0]));
  $("#ocTable tbody").innerHTML = c.rows.map((r) => {
    const ce = r.ce || {}, pe = r.pe || {}, ci = r.strike < c.spot ? "itm" : "", pi = r.strike > c.spot ? "itm" : "";
    return `<tr class="${r.strike === v.atm ? "atm" : ""}">
      <td class="${ci}"><div class="bar ce-bar" style="width:${(ce.oi || 0) / maxOi * 100}%"></div><span class="v">${fmtInt(ce.oi)}</span></td>
      <td class="${ci} ${cls(ce.chg_oi)}">${fmtInt(ce.chg_oi)}</td><td class="${ci}">${ce.iv || "—"}</td><td class="${ci}"><b>${fmt(ce.ltp)}</b></td>
      <td class="strike">${fmt0(r.strike)}</td>
      <td class="${pi}"><b>${fmt(pe.ltp)}</b></td><td class="${pi}">${pe.iv || "—"}</td><td class="${pi} ${cls(pe.chg_oi)}">${fmtInt(pe.chg_oi)}</td>
      <td class="${pi}"><div class="bar pe-bar" style="width:${(pe.oi || 0) / maxOi * 100}%"></div><span class="v">${fmtInt(pe.oi)}</span></td></tr>`;
  }).join("");
  if (chainCentered !== c.symbol + c.expiry) { chainCentered = c.symbol + c.expiry; $("#ocTable tr.atm")?.scrollIntoView({ block: "nearest" }); }
}

// ---------- options: measured costs ----------
export async function loadCosts() {
  const sym = S.sym;
  $("#costCard").innerHTML = `<div class="loading"><span class="spinner"></span>Loading trading costs…</div>`;
  let r;
  try { r = await api("/api/spreads/" + encodeURIComponent(sym)); }
  catch (e) { $("#costCard").innerHTML = `<div class="pad notice">${esc(e.message)}</div>`; return; }
  if (sym !== S.sym) return;
  if (!r.available) { $("#costCard").innerHTML = `<div class="card-head"><h2>What it costs to trade</h2></div><div class="body"><p class="muted">${esc(r.message || "No quotes yet.")}</p></div>`; return; }
  const tabsHtml = r.expiries.map((e, i) => `<button data-i="${i}" class="${i ? "" : "active"}">${esc(e.expiry)}</button>`).join("");
  $("#costCard").innerHTML = `<div class="card-head"><h2>What it costs to trade (bid–ask spread)</h2><div class="seg" id="costSeg">${tabsHtml}</div></div><div class="pad">${freshLine(r.freshness)}</div><div class="body" id="costBody"></div>`;
  const show = (i) => {
    const e = r.expiries[i];
    const cell = (x) => (x ? `<td class="num">${fmt(x.bid)} / ${fmt(x.ask)}</td><td class="num ${x.spread_pct > 0.05 ? "down" : x.spread_pct > 0.02 ? "warn-c" : ""}">${pc(x.spread_pct)}</td>` : "<td>—</td><td>—</td>");
    const rows = e.rows.map((x) => `<tr class="${x.strike === e.atm ? "atm" : ""}">${cell(x.ce)}<td class="strike">${fmt0(x.strike)}</td>${cell(x.pe)}</tr>`).join("");
    const level = e.real_vs_model <= 1 ? "normal" : e.real_vs_model <= 2 ? "a bit costly" : "costly";
    $("#costBody").innerHTML = `<p>Typical spread here: <b>${pc(e.median_spread_pct)}</b> of the premium — <b>${level}</b>
        (${e.real_vs_model.toFixed(2)}× our cost model; under 1 is cheaper than we assume).</p>
      <div class="oc-scroll"><table class="oc"><thead><tr><th>Call bid / ask</th><th>Spread</th><th class="strike">Strike</th><th>Put bid / ask</th><th>Spread</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">You pay roughly <b>half the spread</b> each time you buy or sell. A 4-leg trade opened and closed pays it 8 times —
      that is why the results-day butterfly lost money even though its idea was right. Closing quotes of ${esc(r.snapshot)}; updated every evening.</p>`;
    document.querySelectorAll("#costSeg button").forEach((b) => b.classList.toggle("active", +b.dataset.i === i));
  };
  $("#costSeg").onclick = (ev) => { const b = ev.target.closest("button"); if (b) show(+b.dataset.i); };
  show(0);
}

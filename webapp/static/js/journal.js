// The My Trades tab: the user's own Dhan tradebook.
import { api } from "./api.js";
import { RECORDED_NOTE, cap, card, cls, esc, money, pc } from "./format.js";
import { S } from "./state.js";
import { $ } from "./util.js";

// ---------- my trades (journal) ----------
export async function loadJournalFiles(select) {
  const files = await api("/api/journal/files").catch(() => []);
  $("#jrFile").innerHTML = files.map((f) => `<option ${f.name === select ? "selected" : ""}>${esc(f.name)}</option>`).join("");
  if (!files.length) {
    $("#jrBody").innerHTML = card("No tradebook yet", `<ol class="steps">
      <li><span>In Dhan, open <b>Reports</b> and download your <b>tradebook</b> for the last 6–12 months (Excel or CSV).</span></li>
      <li><span>Click <b>Add a tradebook…</b> above and choose the file.</span></li>
      <li><span>Optional: add a <b>Reason</b> column with one word per trade (PCR, breakout, news, VWAP) to see which reasons make money.</span></li></ol>`);
    return;
  }
  loadJournal();
}
$("#jrFile").onchange = () => loadJournal();
$("#jrHorizon").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.jrHorizon = b.dataset.h;
  document.querySelectorAll("#jrHorizon button").forEach((x) => x.classList.toggle("active", x === b));
  loadJournal();
};
// The tradebook's raw bytes; the server accepts only octet-stream, CSV or .xlsx bodies (415 otherwise).
export async function uploadJournal(f) {
  const r = await api("/api/journal/upload?name=" + encodeURIComponent(f.name),
    { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: await f.arrayBuffer() });
  await loadJournalFiles(r.name);
}
$("#jrUpload").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const n = $("#jrNotice"); n.hidden = true;
  try { await uploadJournal(f); } catch (err) { n.hidden = false; n.textContent = err.message; }
  e.target.value = "";
};
export const COLS = [["trades", "Trades", (x) => x], ["win_rate", "Won", (x) => pc(x, 0)], ["avg_win", "Avg win", money],
  ["avg_loss", "Avg loss", money], ["net_per_trade", "Per trade", money], ["total_net", "Total", money],
  ["charges_share_of_gross_profit", "Charges ÷ profit", (x) => pc(x, 0)]];
export function jrTable(rows) {
  if (!rows.length) return `<p class="muted small">No trades in this group.</p>`;
  return `<div class="oc-scroll"><table class="t"><thead><tr><th></th>${COLS.map((c) => `<th>${c[1]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
    `<tr><td><b>${esc(r.group === "all" ? "All trades" : cap(r.group))}</b></td>${COLS.map(([k, , f]) => `<td class="num ${k.includes("net") ? cls(r[k]) : ""}">${f(r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
export async function loadJournal() {
  const name = $("#jrFile").value; if (!name) return;
  const n = $("#jrNotice"); n.hidden = true;
  $("#jrBody").innerHTML = `<div class="loading"><span class="spinner"></span>Reading your trades…</div>`;
  let r;
  try { r = await api(`/api/journal?name=${encodeURIComponent(name)}&horizon=${S.jrHorizon}`); }
  catch (e) { $("#jrBody").innerHTML = ""; n.hidden = false; n.textContent = e.message; return; }
  const o = r.sections["Overall"][0];
  const few = r.round_trips < 30 ? `<div class="notice">Only ${r.round_trips} completed trades: treat this as a first look, not proof. 30–50 trades start to mean something.</div>` : "";
  let html = card("Summary", `${RECORDED_NOTE}<p>${r.trades} orders from ${esc(r.from)} to ${esc(r.to)} → <b>${r.round_trips} completed trades</b>${r.still_open ? `, ${r.still_open} still open (not counted)` : ""}. Charges ${esc(r.charges)}.</p>
    ${o ? `<div class="stats"><div class="stat"><span>Won</span><b class="num">${pc(o.win_rate, 0)}</b></div><div class="stat"><span>Average per trade</span><b class="num ${cls(o.net_per_trade)}">${money(o.net_per_trade)}</b></div>
    <div class="stat"><span>Total</span><b class="num ${cls(o.total_net)}">${money(o.total_net)}</b></div><div class="stat"><span>Charges paid</span><b class="num">${money(o.charges)}</b></div></div>` : ""}${few}`);
  if (r.horizon === "all") html += card("By how long you held", jrTable(r.sections["By holding period"]));
  for (const [title, key] of [["Buying vs selling", "By style"], ["By instrument", "By instrument"], ["By stock / index", "By underlying"],
    ["By time you entered", "By hour of entry"], ["By day of week", "By day of week"], ["By your reason", "By your reason"]]) {
    if (r.sections[key]?.length) html += card(title, jrTable(r.sections[key]));
  }
  $("#jrBody").innerHTML = html;
}

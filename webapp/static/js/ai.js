// The AI Analysis tab.
import { api } from "./api.js";
import { esc, mdHtml } from "./format.js";
import { S, nameOf } from "./state.js";
import { $, store } from "./util.js";

// ---------- AI ----------
export const aiJobs = JSON.parse(store("aiJobs") || "{}");
export function renderAI() {
  const btn = $("#aiBtn"), notice = $("#aiNotice");
  btn.textContent = `Run AI analysis on ${nameOf(S.sym)}`;
  notice.hidden = S.status.azure !== false; notice.textContent = S.status.azure_problem || "";
  btn.disabled = S.status.azure === false;
  $("#aiProgress").innerHTML = ""; $("#aiResult").innerHTML = "";
  if (aiJobs[S.sym]) pollAI(aiJobs[S.sym], S.sym);
}
$("#aiBtn").onclick = async () => {
  const analysts = [...document.querySelectorAll("#analysts input:checked")].map((i) => i.value);
  if (!analysts.length) return;
  $("#aiBtn").disabled = true;
  try {
    const { job } = await api("/api/ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: S.sym, analysts }) });
    aiJobs[S.sym] = job; store("aiJobs", JSON.stringify(aiJobs)); pollAI(job, S.sym);
  } catch (e) { $("#aiNotice").hidden = false; $("#aiNotice").textContent = e.message; $("#aiBtn").disabled = false; }
};
// A rating's verdict box tone (style.css .verdict.v-*: each fill with a text colour of at least 4.5:1 in both themes).
export const RATING_TONES = { Buy: "up", Overweight: "up", Hold: "warn", Underweight: "down", Sell: "down" };
export async function pollAI(jobId, sym) {
  if (S.aiJob === jobId) return; S.aiJob = jobId;
  while (S.aiJob === jobId) {
    let job;
    try { job = await api("/api/ai/" + jobId); }
    catch { delete aiJobs[sym]; store("aiJobs", JSON.stringify(aiJobs)); S.aiJob = null; $("#aiBtn").disabled = false; return; }
    if (sym !== S.sym) { S.aiJob = null; return; }
    $("#aiProgress").innerHTML = `<ul class="ai-steps">${job.steps.map((s) => `<li>✅ ${esc(s)}</li>`).join("")}
      ${job.status === "running" ? `<li><span class="spinner"></span>Agents working since ${job.started}…</li>` : ""}</ul>`;
    if (job.status === "running") { $("#aiBtn").disabled = true; await new Promise((r) => setTimeout(r, 3000)); continue; }
    $("#aiBtn").disabled = false; S.aiJob = null;
    if (job.status === "error") { $("#aiResult").innerHTML = `<div class="notice" style="margin:0">${esc(job.error)}</div>`; return; }
    const names = Object.keys(job.reports);
    $("#aiResult").innerHTML = `<div class="verdict v-${RATING_TONES[job.rating] || "muted"}"><h2>${esc(job.rating)}</h2><div>${esc(nameOf(job.symbol))} · finished ${job.finished}</div></div>
      <div class="report-tabs">${names.map((n, i) => `<button data-i="${i}" class="${i ? "" : "active"}">${esc(n)}</button>`).join("")}</div><div class="report" id="reportBody"></div>`;
    const show = (i) => {
      $("#reportBody").innerHTML = mdHtml(job.reports[names[i]] || "");
      document.querySelectorAll(".report-tabs button").forEach((b) => b.classList.toggle("active", +b.dataset.i === i));
    };
    $(".report-tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) show(+b.dataset.i); };
    show(0); return;
  }
}

// The Research tab.
import { api } from "./api.js";
import { card, esc, fmt0, freshLine } from "./format.js";
import { $ } from "./util.js";

// ---------- research ----------
export async function loadResearchTab() {
  let r;
  try { r = await api("/api/research"); }
  catch (e) { $("#researchBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  const inUse = r.in_use.map((x) => `<div class="tool"><div class="tick">✓</div><div><b>${esc(x.name)}</b>
    <div class="small">${esc(x.evidence)}</div><div class="small muted">Use it for: ${esc(x.use)}</div></div></div>`).join("");
  const nicer = (s) => s.replace(/_/g, " ");
  const label = (t) => (t.passed ? ["Passed", "up"] : /predictive|kept/.test(t.verdict) ? ["Insight only", "flat"] : ["Rejected", "down"]);
  const rows = r.tested.map((t) => { const [lb, tone] = label(t);
    return `<tr><td><b>${esc(t.name)}</b>${t.what ? `<div class="small muted">${esc(t.what)}</div>` : ""}</td>
    <td><span class="badge ${tone}">${lb}</span></td><td class="left small">${esc(t.result || t.verdict)}</td>
    <td class="num small">${t.trades != null ? fmt0(t.trades) + " " + esc(t.unit) : "—"}</td></tr>`; }).join("");
  const paper = r.paper.map((p) => `<div class="body"><b>${esc(nicer(p.name))}</b> — ${p.status === "observation" ? "<span class='badge flat'>observation only</span>" : "<span class='badge up'>candidate</span>"}
    <div class="small">Started ${esc(p.start)} · ${p.closed ?? 0} closed, ${p.open ?? 0} open trades</div>
    ${p.note ? `<div class="small muted">${esc(p.note)}</div>` : ""}</div>`).join("") || `<div class="body muted">No paper strategies.</div>`;
  const d = r.daily_job;
  const steps = d?.steps ? d.steps.map((s) => `<span class="step ${s.exit_code === 0 ? "ok" : "bad"}">${esc(s.step)}</span>`).join("") : "";
  const when = (s) => (s ? new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
  const daily = d ? `<p>Last run ${esc(when(d.finished || d.started))}: <b class="${d.ok ? "up" : "down"}">${d.ok ? "all steps OK" : "a step failed"}</b></p><div class="steps-row">${steps}</div>`
    : `<p class="muted">No run recorded yet.</p>`;
  $("#researchBody").innerHTML = freshLine(r.freshness) +
    card("What works — in use now", `<div class="tools">${inUse}</div>`) +
    card(r.approved.length ? `Approved signals: ${esc(r.approved.join(", "))}` : "Trading signals: none has passed yet",
      `<p>${r.approved.length ? "" : "No buy/sell idea has survived all the tests (unseen years, real costs, better than random entry). That is the system protecting you, not a failure."}</p>
       <div class="x-scroll"><table class="t research"><thead><tr><th>Idea tested</th><th>Verdict</th><th class="left">What happened</th><th>Tested on</th></tr></thead><tbody>${rows}</tbody></table></div>`) +
    `<div class="two">${card("Paper trading (no money)", paper)}${card("Nightly update (weekdays 7:30 PM)", daily)}</div>`;
}

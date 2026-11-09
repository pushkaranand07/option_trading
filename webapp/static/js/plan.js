// The Plan tab: the session bar, the morning view and the plan cards.
import { api } from "./api.js";
import { esc, fmt, fmt0, mdHtml, pc, pct } from "./format.js";
import { loadNseChain } from "./nsechain.js";
import { drawPlanChartLines, loadPlanCharts, planCharts } from "./planchart.js";
import { REGIME_TEXT } from "./risk.js";
import { NAMES, S, nameOf } from "./state.js";
import { loadLatestRun, loadResearch, renderStrat } from "./strat.js";
import { $, PREVIEW_AT, dur, istNow, toMins } from "./util.js";

// ---------- plan (morning plan + live call) ----------
export function phase(sess) {
  const now = istNow();
  if (!sess || sess.date !== now.date) return { key: "stale", text: "Plan is not for today — refresh it." };
  if (!sess.trading && sess.muhurat && S.status?.muhurat) return muhuratPhase(sess, S.status.muhurat, now.mins);
  if (!sess.trading) return { key: "closed", text: `Market closed today${sess.holiday ? ` (${sess.holiday.replace("*", "")})` : ""}. Next session: ${sess.next_session}.` };
  const m = now.mins, open = toMins(sess.open), first = toMins(sess.first_signal), close = toMins(sess.close);
  if (m < toMins(sess.pre_open)) return { key: "pre", text: `Before the market. Opens at ${sess.open} — in ${dur(open - m)}. Read the morning view below.` };
  if (m < open) return { key: "preopen", text: `Pre-open auction. Trading starts at ${sess.open} — in ${dur(open - m)}.` };
  if (m < first) return { key: "wait", text: `Market open. The rule waits for the first half hour — trade signal from ${sess.first_signal} (in ${dur(first - m)}).` };
  if (m < close) return { key: "live", text: `Market open — closes at ${sess.close} (in ${dur(close - m)}). Exit intraday trades by 15:15.` };
  return { key: "after", text: `Market closed for today at ${sess.close}. Next session: ${sess.next_session}.` };
}

// Muhurat day: the one-hour session's own times. The rule, the AI plan and dummy trades follow regular sessions only.
export function muhuratPhase(sess, mu, m) {
  const name = sess.holiday ? sess.holiday.replace("*", "") : "Diwali";
  const pre = toMins(mu.pre_open), open = toMins(mu.open), close = toMins(mu.close);
  const off = "The app's rule, AI plan and dummy trades follow regular sessions only.";
  if (m < pre) return { key: "pre", text: `Muhurat trading today (${name}): pre-open ${mu.pre_open}, trading ${mu.open}–${mu.close} IST — in ${dur(open - m)}. ${off}` };
  if (m < open) return { key: "preopen", text: `Muhurat pre-open auction. Trading starts at ${mu.open} — in ${dur(open - m)}.` };
  if (m < close) return { key: "live", text: `Muhurat session open — closes at ${mu.close} (in ${dur(close - m)}). ${off}` };
  return { key: "after", text: `Muhurat session closed at ${mu.close}. Next session: ${sess.next_session}.` };
}

export function renderSession() {
  const s = S.morning?.session; if (!s) return;
  const ph = phase(s);
  const steps = [["Pre-open", s.pre_open], ["Open", s.open], ["Signal from", s.first_signal], ["Exit intraday by", "15:15"],
    ["Close", s.close + (s.index_derivatives_close !== s.close ? ` (index F&O ${s.index_derivatives_close})` : "")]];
  $("#sessionBar").innerHTML = `<div class="body"><div class="session-top"><div><div class="ask">${esc(s.weekday)} ${esc(s.date)}</div>
      <div class="phase ${ph.key}">${esc(ph.text)}</div></div><div class="clock num">${istNow().hhmm} IST</div></div>
    ${s.trading ? `<div class="timeline">${steps.map(([k, v]) => `<div><span>${k}</span><b class="num">${esc(v)}</b></div>`).join("")}</div>` : ""}</div>`;
}

export function planEntries() {
  const m = S.morning; if (!m) return null;
  if (m.indices[S.sym]) return [[S.sym, m.indices[S.sym]]];
  const x = S.extraCtx[S.sym];
  if (x === "pending") return null;
  if (x) return [[S.sym, { ...x, extra: true }]];
  S.extraCtx[S.sym] = "pending";
  api("/api/morning/context/" + encodeURIComponent(S.sym)).then((r) => { S.extraCtx[S.sym] = r; renderPlanCards(); loadLive(); })
    .catch((e) => { S.extraCtx[S.sym] = { context: { error: e.message }, ai: null }; renderPlanCards(); });
  return null;
}

export function plainPcr(x) { return x > 1.2 ? "many more puts than calls open (heavy hedging)" : x < 0.8 ? "more calls than puts open" : "calls and puts roughly balanced"; }
export function morningHtml(sym, e) {
  const c = e.context, ai = e.ai, em = c.expected_move, t = c.trend, g = c.regime;
  if (c.error) return `<div class="notice">Could not build the view for ${esc(nameOf(sym))}: ${esc(c.error)}</div>`;
  const aiBlock = e.extra ? `<p class="small muted">The 8:30 AM AI view covers NIFTY 50 and NIFTY BANK. For ${esc(nameOf(sym))}, run it on the AI Analysis tab.</p>`
    : !ai ? `<p class="small muted">AI view not built yet (runs at 8:30 AM on trading days).</p>`
    : ai.error ? `<div class="notice">AI view failed: ${esc(ai.error)}</div>`
    : `<div class="ai-line"><span class="badge ${/Buy|Overweight/.test(ai.rating) ? "up" : /Sell|Underweight/.test(ai.rating) ? "down" : "warn"}">${esc(ai.rating)}</span>
        <span class="small muted">AI agents' view from news, sentiment and the bull/bear debate (${ai.minutes} min)</span></div>
       <details class="ai-more"><summary>Read the AI's reasoning</summary><div class="report">${mdHtml(ai.decision || "")}</div>
         ${ai.news ? `<h3>News</h3><div class="report">${mdHtml(ai.news)}</div>` : ""}</details>`;
  const rows = [
    t && ["Trend", `<b>${esc(t.label)}</b> — ${esc(t.explain)}`],
    em && [S.morning.session.trading ? "Expected range today" : "Expected range next session", `<b>${fmt0(em.day_low)} – ${fmt0(em.day_high)}</b> (±${pc(em.day_pct)} from the last close ${fmt(em.close)}; about 2 days in 3 stay inside)`],
    c.last_session?.close && ["Last session", `${esc(c.last_session.date)}: open ${fmt(c.last_session.open)}, high ${fmt(c.last_session.high)}, low ${fmt(c.last_session.low)}, close <b>${fmt(c.last_session.close)}</b> (${pct(c.last_session.change_pct)})`],
    g && ["Market mood", `<b>${esc(REGIME_TEXT[g.name]?.[0] || g.name)}</b> — ${esc(REGIME_TEXT[g.name]?.[2] || "")}`],
    c.pcr && ["Put-call ratio", `<b>${c.pcr.value.toFixed(2)}</b>${c.pcr.prev ? ` (day before ${c.pcr.prev.toFixed(2)})` : ""} — ${plainPcr(c.pcr.value)}`],
    c.fii_long_share && ["Foreign investors (FII)", `<b>${pc(c.fii_long_share.value, 0)}</b> of their index futures are long${c.fii_long_share.week_ago != null ? ` (a week ago ${pc(c.fii_long_share.week_ago, 0)})` : ""} — ${c.fii_long_share.value < 0.35 ? "they are betting mostly on a fall" : c.fii_long_share.value > 0.65 ? "they are betting mostly on a rise" : "mixed"}`],
    c.iv && ["Options", `implied vol ${pc(c.iv.iv30)}${c.iv.minus_garch21 != null ? `, ${c.iv.minus_garch21 > 0.03 ? "expensive" : c.iv.minus_garch21 < -0.03 ? "cheap" : "fairly priced"} vs the forecast` : ""}`],
  ].filter(Boolean);
  return `${aiBlock}<table class="facts">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
}

export function renderPlanCards() {
  const m = S.morning; if (!m) return;
  const entries = planEntries();
  if (!entries) { $("#planBody").dataset.key = ""; $("#planBody").innerHTML = `<div class="loading"><span class="spinner"></span>Building the plan for ${esc(nameOf(S.sym))}…</div>`; return; }
  // The card is built once per plan and instrument (its chart lives in it); later updates only refill the slots.
  const key = m.built_at + "|" + S.sym + "|" + (entries[0][1].extra ? "x" : "");
  if ($("#planBody").dataset.key !== key) {
    $("#planBody").dataset.key = key;
    $("#planBody").innerHTML = entries.map(([sym, e]) => `<section class="card plan-card" data-sym="${esc(sym)}">
      <div class="card-head"><h2>${esc(NAMES[sym] || nameOf(sym))}</h2>${e.context.trend ? `<span class="badge ${e.context.trend.tone}">${esc(e.context.trend.label)}</span>` : ""}</div>
      <div class="body"><h3 class="sub-h">Price chart <span class="small muted chart-note"></span></h3>
        <div class="pc-bar"></div><div class="pc-info small"><span class="pc-readout"></span><span class="pc-hint"></span></div>
        <div class="pc-wrap"><div class="plan-chart"></div></div>
        <h3 class="sub-h">AI strategy</h3><div class="strat-slot"></div>
        <h3 class="sub-h">Option chain <span class="small muted chain-note"></span></h3><div class="chain-slot"></div>
        <h3 class="sub-h">Morning view</h3><div class="morning-slot"></div></div></section>`).join("");
    planCharts.clear();
    loadPlanCharts();
    for (const [sym] of entries) { renderStrat(sym); loadNseChain(sym); loadLatestRun(sym); loadResearch(sym); }
  }
  for (const [sym, e] of entries) {
    const card = $(`.plan-card[data-sym="${sym}"]`);
    $(".morning-slot", card).innerHTML = morningHtml(sym, e);
    drawPlanChartLines(sym);
  }
  const job = m.ai_job || {};
  $("#planStamp").innerHTML = `Plan built ${esc(m.built_at)}${job.running ? ` · AI view running since ${esc(job.started)}…` : ""}.
    <button class="btn small-btn" id="planRefresh">Refresh data</button>
    ${m.session.trading && !PREVIEW_AT ? `<button class="btn small-btn" id="planAi" ${job.running ? "disabled" : ""}>Run AI view now (~20 min)</button>` : ""}`;
  $("#planRefresh").onclick = async () => { $("#planRefresh").disabled = true; S.morning = await api("/api/morning/refresh", { method: "POST" }).catch(() => S.morning); renderPlan(); };
  if ($("#planAi")) $("#planAi").onclick = async () => { try { await api("/api/morning/ai", { method: "POST" }); } catch (e) { alert(e.message); } loadMorning(); };
}

export function renderPlan() { renderSession(); renderPlanCards(); }

export async function loadMorning() {
  try { S.morning = await api("/api/morning" + (PREVIEW_AT ? "?date=" + PREVIEW_AT.slice(0, 10) : "")); } catch (e) { $("#planBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  renderPlan(); loadLive();
}
export async function loadLive() {
  if (S.morning && phase(S.morning.session).key !== "stale") loadPlanCharts();
  if (!S.morning || !["wait", "live"].includes(phase(S.morning.session).key)) return;
  for (const [sym] of planEntries() || []) {
    try { S.live[sym] = await api("/api/plan/" + encodeURIComponent(sym)); } catch { /* keep the last one */ }
  }
  renderPlanCards();
}

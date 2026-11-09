// The Today tab: the rule's call, the market trend, the track record, BTST and the last sessions.
import { api } from "./api.js";
import { drawPlanLines } from "./chart.js";
import { cls, esc, fmt, fmt0, pct, rupee, sign, srcLabel } from "./format.js";
import { S, nameOf } from "./state.js";
import { $ } from "./util.js";

// ---------- the plan ----------
export async function loadPlan() {
  const sym = S.sym;
  try {
    const p = await api("/api/plan/" + encodeURIComponent(sym));
    if (sym !== S.sym) return;
    S.plan = p;
    renderHero(p); renderMood(p); renderRecord(p); renderBtst(p); renderHistory(p); drawPlanLines();
  } catch (e) {
    if (sym === S.sym && !S.plan) $("#hero").innerHTML = `<div class="notice" style="margin:0">Could not build a plan for ${esc(sym)}: ${esc(e.message)}</div>`;
  }
}

export function checksList(c) { return `<ul class="checks">${(c || []).map((x) => `<li class="${x.ok ? "ok" : ""}">${esc(x.text)}</li>`).join("")}</ul>`; }

export function renderHero(p) {
  const v = p.verdict, s = p.signal, leg = p.option, idx = p.kind === "INDEX";
  const live = s.side !== "WAIT";
  const up = s.side === "BUY";
  const actionCls = v.safe ? (up ? "go-up" : "go-down") : live ? "stop" : "idle";
  const name = nameOf(p.symbol);

  let what;
  if (v.safe && idx) what = `Buy ${esc(name)} ${fmt0(leg.strike)} ${leg.kind}${leg.expiry ? ` · expiry ${esc(leg.expiry)}` : " · nearest weekly expiry"}`;
  else if (v.safe) what = up ? `Buy ${esc(p.symbol)} shares for today (intraday)` : `Short-sell ${esc(p.symbol)} for today, buy back by 3:15 PM`;
  else if (live) what = `A ${esc(v.setup)} setup is showing, but it hasn't been reliable enough to take.`;
  else what = "No clean setup right now. Sitting out is the safe choice.";

  const when = p.market_open ? "" : `<div class="small warn-c">Market is closed. This reads the last session; check again after 9:45 AM.</div>`;

  const conf = live ? `<div class="conf small muted"><b>no edge evidence</b></div>` : "";

  let right;
  if (live && v.safe) {
    const lvl = idx ? `${esc(name)} level` : "share price";
    let extra = "";
    if (idx && leg) {
      extra = leg.premium
        ? `<div class="lv wide"><div><span>Option premium now</span><b>${rupee(leg.premium)}</b></div>
            <div><span>Exit if premium falls to</span><b class="down">${rupee(leg.stop_loss)}</b><small>−${leg.loss_pct}%</small></div>
            <div><span>Book profit at</span><b class="up">${rupee(leg.target)}</b><small>+${leg.gain_pct}%</small></div>
            <div><span>1 lot (${leg.lot})</span><b>${rupee(leg.cost_per_lot)}</b><small>risk ${rupee(leg.max_loss_per_lot)} · gain ${rupee(leg.profit_per_lot)}</small></div></div>`
        : `<div class="lv wide"><div><span>Option premium</span><b>See your broker app</b>
            <small>Expect it to move about ₹${fmt(leg.move_target)} to the target and ₹${fmt(leg.move_sl)} to the stop. Lot size ${leg.lot}. Add Dhan for exact premiums.</small></div></div>`;
    } else if (!idx) {
      const risk = Math.abs(s.entry - s.stop_loss);
      extra = `<div class="lv wide"><div><span>If you are willing to lose ₹1,000</span><b>${Math.max(1, Math.floor(1000 / risk))} shares</b>
        <small>risk ₹${fmt(risk)} per share · reward ₹${fmt(Math.abs(s.target - s.entry))} per share</small></div></div>`;
    }
    right = `<div class="levels">
      <div class="lv"><span>Entry</span><b>${fmt(s.entry)}</b><small>${lvl}</small></div>
      <div class="lv"><span>Stop loss</span><b class="down">${fmt(s.stop_loss)}</b><small>${lvl}</small></div>
      <div class="lv"><span>Target</span><b class="up">${fmt(s.target)}</b><small>${lvl}</small></div>${extra}</div>`;
  } else {
    right = `<div><div class="ask" style="margin-bottom:8px">What we checked (${s.agree ?? 0} of ${s.of ?? 5} agree)</div>${checksList(s.checks)}</div>`;
  }

  let below = "";
  if (live && v.safe) {
    const dir = up ? "below" : "above";
    const tgtDir = up ? "rises to" : "falls to";
    const steps = idx ? [
      `Buy <b>1 lot of ${esc(name)} ${fmt0(leg.strike)} ${leg.kind}</b> while ${esc(name)} is near <b>${fmt(s.entry)}</b>${leg.premium ? ` (premium about ${rupee(leg.premium)})` : ""}.`,
      `Set your stop loss right away: exit if ${esc(name)} goes ${dir} <b>${fmt(s.stop_loss)}</b>${leg.stop_loss ? ` or the premium drops to <b>${rupee(leg.stop_loss)}</b>` : ""}.`,
      `Book profit when ${esc(name)} ${tgtDir} <b>${fmt(s.target)}</b>${leg.target ? ` (premium about <b>${rupee(leg.target)}</b>)` : ""}.`,
      "If neither happens, exit by <b>3:15 PM</b>. Don't hold options overnight on this plan.",
      "One trade a day. If the stop loss hits, you're done for today.",
    ] : [
      `${up ? "Buy" : "Short-sell"} near <b>${fmt(s.entry)}</b> as an <b>intraday (MIS)</b> order.`,
      `Set your stop loss right away at <b>${fmt(s.stop_loss)}</b>.`,
      `Book profit at <b>${fmt(s.target)}</b>.`,
      "If neither happens, exit by <b>3:15 PM</b>.",
      "One trade a day. If the stop loss hits, you're done for today.",
    ];
    below = `<ol class="steps">${steps.map((x) => `<li><span>${x}</span></li>`).join("")}</ol>
      <div class="sub"><h3>Why this trade</h3>${checksList(s.checks)}</div>`;
  } else if (v.blockers.length) {
    below = `<div class="why-not"><h3>Why we're not taking it</h3><ul>${v.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul></div>`;
    if (live) below += `<div class="ghost">For learning only, the setup's levels were: entry ${fmt(s.entry)}, stop loss ${fmt(s.stop_loss)}, target ${fmt(s.target)}.</div>`;
  }

  const src = srcLabel(p.source);
  $("#hero").innerHTML = `<div class="hero-top">
      <div><div class="ask">What should I do with ${esc(name)}?</div>
        <div class="action ${actionCls}">${esc(v.action)}</div>
        <div class="what">${what}</div>${when}${conf}</div>
      ${right}</div>${below}
    <div class="stamp">Last candle ${esc(p.as_of.slice(11, 16))} · ${src} · refreshes every 15 seconds</div>`;
}

export function renderMood(p) {
  const m = p.mood;
  const rets = Object.entries(m.returns).map(([k, x]) => `<div><span>${k}</span><b class="${cls(x)}">${pct(x)}</b></div>`).join("");
  $("#mood").innerHTML = `<div class="card-head"><h2>Market trend</h2><span class="badge ${m.tone}">${esc(m.label)}</span></div>
    <div class="body"><p style="margin:0">${esc(m.explain)}</p>
      <div class="rets">${rets}</div>
      <div class="small"><b>Where it sits in its 1-year range</b></div>
      <div class="range"><div class="range-bar"><i style="left:${m.pos_52w}%"></i></div>
        <div class="range-ends"><span>Low ${fmt(m.low_52w)}</span><span>${m.pos_52w}% of the way up</span><span>High ${fmt(m.high_52w)}</span></div></div>
      <p class="note">It usually moves about <b>±${fmt(m.daily_move)}</b> (${m.daily_move_pct}%) in a day. Averages: 20-day ${fmt(m.averages["20-day"])}, 50-day ${fmt(m.averages["50-day"])}${m.averages["200-day"] ? `, 200-day ${fmt(m.averages["200-day"])}` : ""}.</p></div>`;
}

export function renderRecord(p) {
  const r = p.record;
  const rows = Object.entries(r.by_target).map(([t, x]) => `<tr class="${+t === r.chosen ? "pick" : ""}">
    <td>${t}× risk${+t === r.chosen ? " ✓" : ""}</td><td>${x.trades}</td><td class="small muted">no edge evidence</td>
    <td class="${cls(x.avg_r)}">${x.avg_r != null ? sign(x.avg_r) + x.avg_r : "—"}</td></tr>`).join("");
  const side = (k, label) => { const x = r.by_side[k]; return x.trades ? `${label}: no edge evidence (${x.trades} trades)` : `${label}: none`; };
  $("#record").innerHTML = `<div class="card-head"><h2>Track record of this setup</h2></div>
    <div class="body"><p class="small muted" style="margin-top:0">We replayed this exact rule over the last ${r.days} trading days: one trade a day, entry after 9:45 AM, exit by 3:15 PM, ${r.cost_pct}% costs included.</p>
      <table class="t"><thead><tr><th>Profit target</th><th>Trades</th><th>Edge evidence</th><th>Avg result</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="small" style="margin:10px 0 0">${side("BUY", "Buy setups")} · ${side("SELL", "Sell setups")}</p>
      <p class="note">"Avg result" is the average gain per trade as a share of what you risked: +0.10 means you made 10% of your risk per trade on average.</p></div>`;
}

export function renderBtst(p) {
  const b = p.btst, rec = b.record || {};
  const badge = b.side === "BUY" ? (b.safe ? `<span class="badge up">BTST BUY</span>` : `<span class="badge" style="background:var(--warn-soft);color:var(--warn)">SETUP, NOT SAFE</span>`) : `<span class="badge flat">NO BTST TODAY</span>`;
  const levels = b.side === "BUY" ? `<div class="levels" style="margin:12px 0"><div class="lv"><span>Buy near close</span><b>${fmt(b.entry)}</b></div>
      <div class="lv"><span>Stop loss</span><b class="down">${fmt(b.stop_loss)}</b></div><div class="lv"><span>Target next day</span><b class="up">${fmt(b.target)}</b></div></div>` : "";
  $("#btst").innerHTML = `<div class="card-head"><h2>BTST: buy today, sell tomorrow</h2>${badge}</div>
    <div class="body"><p style="margin-top:0">${b.side === "BUY"
      ? "Today's candle looks strong enough to carry into tomorrow morning."
      : "Today's candle isn't strong enough to hold overnight."} Judge it after <b>3:00 PM</b>, when the day's candle is nearly final.</p>
      ${levels}${checksList(b.checks)}
      <p class="note">History: this BTST rule fired ${rec.trades || 0} times in the last 2 years: no edge evidence (avg ${rec.avg_r != null ? sign(rec.avg_r) + rec.avg_r : "—"}× risk).</p></div>`;
}

export function renderHistory(p) {
  const rows = p.mood.recent.map((d) => `<tr><td>${esc(d.date)}</td><td>${fmt(d.open)}</td><td>${fmt(d.high)}</td><td>${fmt(d.low)}</td><td><b>${fmt(d.close)}</b></td><td class="${cls(d.change_pct)}">${pct(d.change_pct)}</td></tr>`).join("");
  $("#history").innerHTML = `<div class="card-head"><h2>Last 10 sessions</h2><span class="small muted">Switch the chart to Daily for the full history</span></div>
    <div class="body" style="overflow-x:auto"><table class="t"><thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

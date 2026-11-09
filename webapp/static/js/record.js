// The Trade Record tab: My picks and AI #1, each with its numbers, calendar and trades.
import { api } from "./api.js";
import { ftName } from "./banners.js";
import { COST_NOTE, MONTHS, cls, contractName, esc, fmt, fmt0, money, rupee } from "./format.js";
import { lotMoney, tradeMoney } from "./rules.js";
import { NAMES, S } from "./state.js";
import { STRAT_NAMES, ladder } from "./tradeview.js";
import { $, store } from "./util.js";

// Where a trade came from, or "source unknown" for one recorded before provenance (never guessed).
export function provTxt(t) {
  if (!("run_id" in t)) return `<span class="small muted">source unknown (recorded before provenance)</span>`;
  const mode = { quick: "Quick", full: "Complete" }[t.mode] || t.mode || "?";
  return `<span class="small muted">run ${esc((t.run_asked_at || "").slice(-5))} · ${esc(mode)} · AI #${esc(t.ai_rank ?? "?")} · research ${esc(t.research_source || "?")}${t.in_entry_zone === false ? " · outside the entry zone" : ""}</span>`;
}
// One trade in full: each leg in words (BUY — kharida / SELL — becha) with its contract, quantity, the run's price,
// the filled entry and the exit or the price now; the times, NIFTY at the run, the Take and the exit; the plan; where
// it came from and why the AI picked it. A field the trade never recorded says "unknown".
export function paidTxt(t) {
  const qty = t.lot ? t.lot * (t.lots || 1) : null;
  return t.legs.map((l) => {
    const buy = l.action === "BUY", k = `${fmt0(l.strike).replace(/,/g, "")} ${l.type}`;
    if (l.entry == null) return `${buy ? "Kharidna tha" : "Bechna tha"} ${k} @ ₹${fmt(l.shown_price)}`;
    const amt = (px) => (qty ? ` × ${qty} = <b>${rupee(px * qty)}</b>` : "");
    const out = l.exit != null ? `<br><span class="muted">→</span> ${buy ? "becha" : "wapas kharida"} @ ₹${fmt(l.exit)}${amt(l.exit)}` : "";
    return `<b class="${buy ? "up" : "down"}">${buy ? "Kharida" : "Becha"}</b> ${k} @ ₹${fmt(l.entry)}${amt(l.entry)}${out}`;
  }).join("<br>") + (t.net_entry != null && t.status !== "not_taken" ? `<br><span class="muted">kul ${t.debit ? "diya" : "mila"} ${rupee(Math.abs(t.net_entry) * (qty || 0))} (1 lot)</span>` : "");
}
export function tradeDetailHtml(t) {
  const name = NAMES[t.symbol] || t.symbol, v = t.live || {}, qty = t.lot ? t.lot * (t.lots || 1) : null, taken = t.status !== "not_taken";
  const unk = `<span class="muted">unknown</span>`, val = (x, f = fmt) => (x == null ? unk : f(x)), known = "run_id" in t;
  const legs = t.legs.map((l, i) => {
    const now = v.legs?.[i]?.now, out = l.exit ?? (t.status === "open" ? now : null);
    const p = taken && l.entry != null && out != null && qty ? (out - l.entry) * (l.action === "BUY" ? 1 : -1) * qty : null;
    return `<tr><td><b class="${l.action === "BUY" ? "up" : "down"}">${l.action === "BUY" ? "BUY — kharida" : "SELL — becha"}</b></td>
      <td>${esc(contractName(t.symbol, t.expiry, l))}</td><td class="num">${qty ?? unk}</td>
      <td class="num">${"shown_price" in l ? val(l.shown_price) : unk}</td>
      <td class="num"><b>${taken ? val(l.entry) : `<span class="muted">not taken</span>`}</b></td>
      <td class="num">${taken && l.entry != null && qty ? `${rupee(l.entry * qty)} <span class="muted">${l.action === "BUY" ? "diya" : "mila"}</span>` : "—"}</td>
      <td class="num">${l.exit != null ? fmt(l.exit) : t.status === "open" && now != null ? `${fmt(now)} <span class="muted">now</span>` : "—"}</td>
      <td class="num">${l.target != null || l.stop != null ? `${val(l.target)} / ${val(l.stop)}` : "—"}</td>
      <td class="num ${cls(p)}">${p != null ? money(p) : "—"}</td></tr>`;
  }).join("");
  const facts = [
    ["Taken", `${esc(t.taken_at)}${known ? ` · from the run at ${esc((t.run_asked_at || "").slice(-5))}` : ""}`],
    [`${esc(name)} then`, `${known ? `at the run ${val(t.spot_at_run)} · ` : ""}at the Take ${val(t.status === "not_taken" ? t.spot_at_take : t.spot_at_entry)}${t.in_entry_zone === false ? " (outside the entry zone)" : ""}`],
    ["Plan", t.range ? `range ${fmt0(t.range[0])}–${fmt0(t.range[1])}: earns while ${esc(name)} stays inside`
      : `enter while ${esc(name)} is in ${t.entry_low != null ? `${fmt0(t.entry_low)}–${fmt0(t.entry_high)}` : unk} · target ${val(t.index_target, fmt0)} · stop ${val(t.index_stop, fmt0)}`],
    ["Closed", t.status === "closed" ? `${esc(t.closed_at)} · ${esc(name)} ${val(t.spot_at_exit)} · ${esc(t.reason)}`
      : t.status === "open" ? `still open${v.spot != null ? ` · ${esc(name)} now ${fmt(v.spot)}` : ""}` : `not taken: ${esc(t.reason)}`],
    ["From", known ? `${esc({ quick: "Quick", full: "Complete" }[t.mode] || t.mode || "?")} analysis · AI rank #${esc(t.ai_rank ?? "?")} · research ${esc(t.research_source || "?")} · AI confidence ${esc(t.ai_confidence || "?")}`
      : "unknown (recorded before provenance)"],
    ["Why the AI picked it", t.ai_why ? esc(t.ai_why) : unk],
    ["Quotes at the Take", "quote_age_s" in t ? `${esc(t.quote_age_s ?? "?")} s old${t.attempts > 1 ? ` · ${t.attempts} attempts, the last at ${esc(t.last_attempt_at)}` : ""}` : unk],
  ];
  if (taken && t.net_entry != null) facts.push(["Money, 1 lot", `${rupee(tradeMoney(t))} (${lotMoney(t.debit).label})${t.status === "closed"
    ? ` · gross ${money(t.gross_pnl)} · charges ${money(t.charges)} · net <b class="${cls(t.net_pnl)}">${money(t.net_pnl)}</b>` : ""}`]);
  if (t.alerts?.length) facts.push(["Alerts", t.alerts.map((a) => `${esc(FLAG_TEXT[a.kind]?.[0] || a.kind)} at ${esc(a.at)} (${esc(name)} ${fmt0(a.spot)})`).join(" · ")]);
  const lad = t.status === "open" && v.spot != null && t.index_target != null
    ? ladder({ underlying_target: t.index_target, underlying_stop: t.index_stop, underlying_entry_low: t.entry_low, underlying_entry_high: t.entry_high }, v.spot, t.index_target < t.index_stop) : "";
  return `<div class="trade-detail">${lad}<table class="facts small-facts">${facts.map(([k, x]) => `<tr><th>${k}</th><td>${x}</td></tr>`).join("")}</table>
    <table class="t legs"><thead><tr><th>Order</th><th>Contract</th><th>Qty</th><th>Price in the run</th><th>Entry (filled)</th><th>Amount (entry × qty)</th><th>Exit</th><th>Target / stop (premium)</th><th>P&L</th></tr></thead><tbody>${legs}</tbody></table></div>`;
}
export const moreBtn = (t) => `<button class="btn small-btn rec-more" data-id="${t.id}">${S.openDetail.has(t.id) ? "Hide" : "Details"}</button>`;
export const detailRow = (t, cols) => `<tr class="rec-detail" data-for="${t.id}" ${S.openDetail.has(t.id) ? "" : "hidden"}><td colspan="${cols}">${tradeDetailHtml(t)}</td></tr>`;

// The v2 link of an AI #1 row; v2's own entry only on days v2 counts (before it started there is nothing to compare).
export const v2Txt = (t) => (t.v2 ? `<span class="small ${t.v2.counted ? "up" : "muted"}">${esc(t.v2.note)}${t.v2.entry && !t.v2.note.startsWith("before v") ? ` · ${ftName()} entry ${esc(t.v2.entry)}` : ""}</span>` : "");

export const FLAG_TEXT = { target: ["Target reached", "up"], stop: ["Stop reached", "down"], expired: ["Expired", "warn"], exit_pending: ["Exit pending", "warn"] };
// A range trade (iron condor) has a profit zone between its sold strikes, not one target and one stop.
export const levelsTxt = (t) => (t.range ? `range ${fmt0(t.range[0])}–${fmt0(t.range[1])}` : `${fmt0(t.index_target)} / ${fmt0(t.index_stop)}`);
export const legShort = (l) => `${l.action === "BUY" ? "B" : "S"} ${fmt0(l.strike).replace(/,/g, "")} ${l.type}`;

// ---------- Trade Record: one page, two views (My picks / AI #1), each with its own numbers ----------
// The warnings appear once, at the top, as text. Each view: four numbers, then Open, History and Not taken, one line a
// trade; Details opens the full record of a trade. "My picks" is [data-view="you"], "AI #1" is [data-view="ai"].
export const when = (x) => {                     // "2026-11-05 09:41" -> "05 Nov 09:41"
  if (!x) return "—";
  const [d, t] = String(x).split(" "), [, m, dd] = d.split("-"), mon = MONTHS[+m - 1] || "";
  return `${dd} ${mon.charAt(0)}${mon.slice(1).toLowerCase()}${t ? " " + t : ""}`;
};
export const OPEN_HEAD = `<thead><tr><th>Taken</th><th>Trade</th><th>Bought / sold</th><th class="num">NIFTY entry → now</th><th class="num">P&L now</th><th></th></tr></thead>`;
export const HIST_HEAD = `<thead><tr><th>Taken → closed</th><th>Trade</th><th>Bought / sold</th><th class="num">NIFTY in → out</th><th>Why closed</th><th class="num">Net P&L</th><th></th></tr></thead>`;
export const NOT_TAKEN_HEAD = `<thead><tr><th>Tried</th><th>Trade</th><th>Would have bought / sold</th><th>Why not taken</th><th></th></tr></thead>`;
export const delBtn = (t) => `<button class="btn small-btn rec-del" data-id="${t.id}" title="Remove from the record (a trade taken by mistake)">✕</button>`;
// A trade's place in its bet (a bet: the same source, index and direction; see trade_record.find_bet).
export const betTxt = (t) => (t.bet_size > 1 ? `<div class="row-flag muted">bet ${t.bet_index}/${t.bet_size} · shuru ${when(t.bet_started)}</div>` : "")
  + (t.added_to_bet ? `<div class="row-flag warn-c">added to existing bet</div>` : "");
export const tradeCell = (t, extra = "") => `<td><b>${esc(STRAT_NAMES[t.strategy] || t.strategy)}</b><div class="small muted">${esc(NAMES[t.symbol] || t.symbol)} · ${esc(t.expiry)}${t.source === "ai" && t.ai_confidence ? ` · AI ${esc(t.ai_confidence)}` : ""}</div>${betTxt(t)}${t.v2 ? `<div class="row-flag">${v2Txt(t)}</div>` : ""}${t.outside_session ? `<div class="row-flag warn-c">entered while market closed: not counted</div>` : ""}${extra}</td>`;

export function openRowHtml(t) {
  const v = t.live || {}, name = NAMES[t.symbol] || t.symbol;
  const flags = [...new Set([...(t.alerts || []).map((a) => a.kind), ...(v.flags || [])])].filter((f) => f !== "exit_pending").map((f) => {
    const a = (t.alerts || []).find((x) => x.kind === f), [txt, c] = FLAG_TEXT[f] || [f, "warn"];
    return `<div class="row-flag ${c === "up" ? "up" : c === "down" ? "down" : "warn-c"}"><b>${txt}</b> ${f === "expired" ? "— close it to settle at the expiry value"
      : `${a ? `at ${esc(a.at)}` : "now"} — closes itself at the next live price`}</div>`;
  }).join("");
  const pending = v.pending?.length ? v.pending : (t.alerts || []).find((a) => a.kind === "exit_pending")?.legs || [];
  const notes = (pending.length ? `<div class="row-flag warn-c"><b>Exit pending</b>: ${pending.map((p) => `${esc(p)} quote missing`).join(", ")} — it closes at the first price for every leg</div>` : "")
    + (t.note ? `<div class="row-flag warn-c">${esc(t.note)}</div>` : "") + (v.error ? `<div class="row-flag down">${esc(v.error)}</div>` : "");
  return `<tr><td class="when">${when(t.taken_at)}</td>${tradeCell(t, flags + notes)}
    <td class="small paid">${paidTxt(t)}</td>
    <td class="num">${fmt0(t.spot_at_entry)} → <b>${fmt0(v.spot)}</b><div class="small muted">${t.range ? `range ${fmt0(t.range[0])}–${fmt0(t.range[1])}`
      : `target <span class="up">${fmt0(t.index_target)}</span> · stop <span class="down">${fmt0(t.index_stop)}</span>`}</div></td>
    <td class="num"><b class="${cls(v.pnl)}">${v.pnl != null ? money(v.pnl) : "—"}</b>${v.as_of ? `<div class="small muted">NSE ${esc(v.as_of.slice(-8))}</div>` : ""}</td>
    <td class="acts">${t.source !== "ai" ? `<button class="btn primary small-btn rec-close" data-id="${t.id}">Close</button>` : ""}${moreBtn(t)}${delBtn(t)}</td></tr>${detailRow(t, 6)}`;
}

export function histRowHtml(t) {
  return `<tr><td class="when">${when(t.taken_at)}<br>→ ${when(t.closed_at)}</td>${tradeCell(t)}
    <td class="small paid">${paidTxt(t)}</td>
    <td class="num">${fmt0(t.spot_at_entry)} → ${fmt0(t.spot_at_exit)}</td><td class="small">${esc(t.reason)}</td>
    <td class="num"><b class="${cls(t.net_pnl)}">${money(t.net_pnl)}</b><div class="small muted">gross ${money(t.gross_pnl)} · charges ${money(t.charges)}</div></td>
    <td class="acts">${moreBtn(t)}${delBtn(t)}</td></tr>${detailRow(t, 7)}`;
}

// Not-taken rows (the AI's refused pick, or your refused Take): listed with the reason, never counted.
export function notTakenRowsHtml(list) {
  return (list || []).map((t) => `<tr class="not-taken"><td class="when">${when(t.taken_at)}</td>${tradeCell(t)}
      <td class="small paid">${paidTxt(t)}</td>
      <td class="small"><b>not taken</b>${t.attempts > 1 ? ` · ${t.attempts} attempts` : ""}<div class="muted">${esc(t.reason)}</div>${t.later_taken
        ? `<div class="up">later taken at ${esc(t.later_taken.at)} · trade ${esc(t.later_taken.id)}</div>` : ""}</td>
      <td class="acts">${moreBtn(t)}${delBtn(t)}</td></tr>${detailRow(t, 5)}`).join("");
}

// Day by day: a month calendar, one month at a time, with buttons to the month before and after. Each trading day shows
// the net P&L of its closed trades, what went in (the money for the trades taken that day: premium paid, or a credit
// spread's margin), how many, and the P&L now of those still open; a day with trades opens its trades. Trades count on
// the day they were taken; not-taken rows never count. Saturdays and Sundays are shown, dimmed (no session).
export const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
export const monthKey = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
export const shiftMonth = (ym, k) => { const [y, m] = ym.split("-").map(Number); return monthKey(new Date(y, m - 1 + k, 1)); };
export const monthName = (ym) => { const [y, m] = ym.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleString("en-IN", { month: "long", year: "numeric" }); };
export function calendarHtml(v, who) {
  const days = {};
  for (const t of [...v.open, ...v.closed]) {
    const d = (t.taken_at || "").slice(0, 10);
    if (!d || t.outside_session) continue;                                // entered while the market was closed: not counted
    const x = (days[d] ||= { n: 0, inv: 0, net: 0, closed: 0, open: 0, openPnl: 0, bets: 0, earlier: new Set() });
    x.n += 1;
    if (!t.bet_index || t.bet_index === 1) x.bets += 1;                     // a bet counts on the day of its first trade
    else if ((t.bet_started || "").slice(0, 10) !== d) x.earlier.add(when((t.bet_started || "").slice(0, 10)));
    if (t.net_entry != null && t.lot) x.inv += tradeMoney(t);
    if (t.status === "closed") { x.closed += 1; x.net += t.net_pnl || 0; } else { x.open += 1; x.openPnl += t.live?.pnl || 0; }
  }
  const ym = S.recMonth[who] || monthKey(), [y, m] = ym.split("-").map(Number), last = new Date(y, m, 0).getDate();
  const now = new Date(), today = `${monthKey(now)}-${String(now.getDate()).padStart(2, "0")}`;
  const cells = [], total = { n: 0, inv: 0, net: 0, bets: 0 };
  for (let i = 0; i < (new Date(y, m - 1, 1).getDay() + 6) % 7; i++) cells.push(`<div class="cal-day blank"></div>`);
  for (let d = 1; d <= last; d++) {
    const day = `${ym}-${String(d).padStart(2, "0")}`, x = days[day], wknd = (new Date(y, m - 1, d).getDay() + 6) % 7 > 4;
    const mark = `${wknd ? " wknd" : ""}${day === today ? " today" : ""}`;
    if (!x) { cells.push(`<div class="cal-day${mark}"><span class="cal-n">${d}</span></div>`); continue; }
    total.n += x.n; total.inv += x.inv; total.net += x.net; total.bets += x.bets;
    const tip = `Show the trades of this day. P&L shows on the day each trade was taken; a bet counts on the day of its first trade.`
      + (x.earlier.size ? ` Here: trades of a bet started ${[...x.earlier].join(", ")}.` : "");
    cells.push(`<button class="cal-day has ${x.closed ? cls(x.net) : ""}${mark} ${S.recDay[who] === day ? "pick" : ""}" data-day="${day}" data-view-of="${who}"
        title="${esc(tip)}"><span class="cal-n">${d}</span>
      <b class="${cls(x.net)}">${x.closed ? money(x.net) : "—"}</b><small>${rupee(x.inv)} in · ${plural(x.n, "trade")} · ${x.bets ? plural(x.bets, "bet") : "0 new bets"}</small>
      ${x.open ? `<small class="${cls(x.openPnl)}">${money(x.openPnl)} open</small>` : ""}</button>`);
  }
  const nav = (k, label) => `<button class="btn small-btn" data-month-nav="${k}" data-view-of="${who}">${label}</button>`;
  return `<section class="card rec-sec"><div class="card-head"><h2>Day by day</h2>
      <div class="cal-nav">${nav(-1, `‹ ${monthName(shiftMonth(ym, -1))}`)}<b>${monthName(ym)}</b>${nav(1, `${monthName(shiftMonth(ym, 1))} ›`)}${ym !== monthKey() ? nav(0, "Today") : ""}</div></div>
    <p class="cal-total">${total.n ? `${monthName(ym)}: ${rupee(total.inv)} in · net ${money(total.net)} on closed trades · ${plural(total.n, "trade")} · ${plural(total.bets, "bet")}` : `No trades in ${monthName(ym)}.`}</p>
    <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => `<div class="cal-wd">${w}</div>`).join("")}${cells.join("")}</div></section>`;
}

export function viewHtml(who, all) {
  const s = all.stats, ai = who === "ai", day = S.recDay[who];
  const onDay = (list) => (list || []).filter((t) => !day || (t.taken_at || "").startsWith(day));
  const v = { ...all, open: onDay(all.open), closed: onDay(all.closed), not_taken: onDay(all.not_taken) };
  const dayBar = day ? `<div class="rec-day">Showing the trades of <b>${when(day)}</b> · <button class="btn small-btn rec-day-clear" data-view-of="${who}">Show all ✕</button></div>` : "";
  const inOpen = all.open.reduce((a, t) => a + (t.net_entry != null ? tradeMoney(t) : 0), 0);
  const kpi = (label, val, c, sub) => `<div class="kpi"><span>${label}</span><b class="${c || ""}">${val}</b><small>${sub}</small></div>`;
  const kpis = `<div class="kpis">
    ${kpi("Net P&L, closed", money(s.net), cls(s.net), `${plural(s.closed, "closed trade")} · open: ${money(s.open_pnl)} (not in net)`)}
    ${kpi("Trades · bets", `${plural(s.open + s.closed, "trade")} · ${plural(s.bets, "bet")}`, "", `${plural(s.bets_open, "bet")} open · same view, one bet`)}
    ${kpi("Open now", s.open ? `${s.open} · ${money(s.open_pnl)}` : "0", s.open ? cls(s.open_pnl) : "", s.open ? `${rupee(inOpen)} in them` : "nothing open")}
    ${kpi("Won / lost (bets)", `${s.bet_wins} / ${s.bet_losses}`, "", s.bet_win_rate != null ? `${s.bet_win_rate.toFixed(0)}% of closed bets won` : "no bet closed yet")}
    ${kpi("Best / worst", s.closed ? `${money(s.best)} / ${money(s.worst)}` : "—", "", ai ? "the AI's #1 of each run, recorded by itself" : "trades you took")}</div>`;
  const v2 = ai && all.v2_stats ? `<p class="rec-v2">${ftName()} counted ${v.v2_stats.closed + v.v2_stats.open} of these (its own entry, held to expiry in ${ftName()}); settled P&L here ${money(v.v2_stats.net)}.</p>` : "";
  const closedNow = all.open.some((t) => t.live?.market_closed)
    ? `<p class="rec-v2 warn-c">Market band hai: these are the last prices (NSE stops near 15:40). P&L, targets and stops resume at 9:15; nothing opens or closes while the market is closed.</p>` : "";
  const table = (head, rows) => `<div class="tbl"><table class="t rec-t">${head}<tbody>${rows}</tbody></table></div>`;
  const sec = (title, n, body, note = "") => `<section class="card rec-sec"><div class="card-head"><h2>${title}<span class="count">${n}</span></h2>${note}</div>${body}</section>`;
  return kpis + v2 + closedNow + calendarHtml(all, who) + dayBar
    + sec("Open", v.open.length, v.open.length ? table(OPEN_HEAD, v.open.map(openRowHtml).join(""))
      : `<p class="empty">${day ? `No open trades from ${when(day)}.` : `Nothing open.${ai ? "" : " Take a trade on the Plan tab to see it here."}`}</p>`)
    + sec("History", v.closed.length, v.closed.length ? table(HIST_HEAD, v.closed.map(histRowHtml).join("")) : `<p class="empty">${day ? `No closed trades from ${when(day)}.` : "Closed trades appear here with their profit or loss."}</p>`)
    + (v.not_taken?.length ? sec(ai ? "Not taken" : "Refused Takes", v.not_taken.length, table(NOT_TAKEN_HEAD, notTakenRowsHtml(v.not_taken)),
      `<span class="small muted">listed with the reason, never counted</span>`) : "");
}

// The whole Trade Record from /api/trades, as HTML (a pure function, so tests/test_ui_regressions.py can check it).
export function recordHtml(d) {
  const views = [["you", "My picks", d.you], ["ai", "AI #1", d.ai]];
  return `<div class="rec-top">
      <p class="rec-note">Paper trades, 1 lot each — no real order is placed · recorded trades, not a test (not registered before entry) · P&L after charges, ${COST_NOTE} · a handful of trades proves nothing either way</p>
      <div class="seg" role="tablist">${views.map(([k, label, v]) => `<button class="seg-btn ${S.recView === k ? "on" : ""}" data-view-btn="${k}" role="tab">${label}<span class="count">${v.stats.open + v.stats.closed}</span></button>`).join("")}</div>
      <a class="btn small-btn" href="/api/trades.csv" download>Download CSV</a></div>`
    + views.map(([k, , v]) => `<div class="rec-view" data-view="${k}" ${S.recView === k ? "" : "hidden"}>${viewHtml(k, v)}</div>`).join("");
}

export async function loadRecord() {
  const el = $("#recordBody");
  let d;
  try { d = await api("/api/trades"); } catch (e) { el.innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  S.recData = d;
  paintRecord(el);
}

export function paintRecord(el) {
  el.innerHTML = recordHtml(S.recData);
  el.querySelectorAll(".rec-close").forEach((b) => (b.onclick = async () => {
    if (!confirm("Close this dummy trade at the current prices?")) return;
    b.disabled = true;
    try { await api(`/api/trades/${b.dataset.id}/close`, { method: "POST" }); } catch (e) { alert(e.message); }
    loadRecord();
  }));
  el.querySelectorAll(".rec-del").forEach((b) => (b.onclick = async () => {
    if (!confirm("Remove this trade from the record? (Use this for a trade taken by mistake.)")) return;
    try { await api(`/api/trades/${b.dataset.id}`, { method: "DELETE" }); } catch (e) { alert(e.message); }
    loadRecord();
  }));
  el.querySelectorAll(".rec-more").forEach((b) => (b.onclick = () => {
    const id = b.dataset.id, on = !S.openDetail.has(id);
    on ? S.openDetail.add(id) : S.openDetail.delete(id);
    const row = el.querySelector(`tr.rec-detail[data-for="${id}"]`);
    if (row) row.hidden = !on;
    b.textContent = on ? "Hide" : "Details";
  }));
  el.querySelectorAll("[data-day]").forEach((b) => (b.onclick = () => {
    const who = b.dataset.viewOf;
    S.recDay[who] = S.recDay[who] === b.dataset.day ? null : b.dataset.day;      // a second click shows everything again
    paintRecord(el);
    el.querySelector(`[data-view="${who}"] .rec-day`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }));
  el.querySelectorAll("[data-month-nav]").forEach((b) => (b.onclick = () => {
    const who = b.dataset.viewOf, k = +b.dataset.monthNav;
    S.recMonth[who] = k ? shiftMonth(S.recMonth[who] || monthKey(), k) : monthKey();     // 0: back to this month
    paintRecord(el);
  }));
  el.querySelectorAll(".rec-day-clear").forEach((b) => (b.onclick = () => { S.recDay[b.dataset.viewOf] = null; paintRecord(el); }));
  el.querySelectorAll("[data-view-btn]").forEach((b) => (b.onclick = () => {
    S.recView = b.dataset.viewBtn; store("recView", S.recView);
    el.querySelectorAll(".rec-view").forEach((x) => (x.hidden = x.dataset.view !== S.recView));
    el.querySelectorAll("[data-view-btn]").forEach((x) => x.classList.toggle("on", x === b));
  }));
}

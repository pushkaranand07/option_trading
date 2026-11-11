// HTML builders for the AI's trades: the budget card, the ranked list and the trade card.
import { COST_NOTE, cap, contractName, esc, fmt, fmt0, money, pnl, rupee } from "./format.js";
import { RULES, budget, budgetPick, clock12, lotMoney } from "./rules.js";
import { NAMES, S } from "./state.js";

export const STRAT_NAMES = { no_trade: "No trade", long_call: "Buy a call", long_put: "Buy a put", bull_call_spread: "Bull call spread",
  bear_put_spread: "Bear put spread", bull_put_spread: "Bull put spread", bear_call_spread: "Bear call spread", iron_condor: "Iron condor" };

// How each leg goes into Dhan, so every number labelled Target / Stop loss can be typed into a Super order
// (Dhan: a BUY needs target > entry > stop, a SELL needs target < entry < stop).
//  super    — single option, or the SELL leg of a credit spread: Super order with target + stop loss
//  hedge    — the BUY leg of a credit spread: plain Limit, no target / stop; close it right after the SELL leg exits
//  together — debit spread / iron condor legs: Limit orders, closed together by hand at the index levels
//             (a stop on the bought leg alone could leave the sold leg naked)
export function legRole(strategy, legs, l) {
  if (legs.length === 1) return "super";
  if (RULES.credit_strategies.includes(strategy)) return l.action === "SELL" ? "super" : "hedge";
  return "together";
}
export function legLevelsOk(l, tgt, stop) {          // the Super-order rule; anything else is not enterable in Dhan
  return tgt != null && stop != null && (l.action === "BUY" ? tgt > l.price && stop < l.price : tgt < l.price && stop > l.price);
}
export const ROLE_NOTE = {
  super: (l) => l.action === "BUY" ? "Super order: target above the entry, stop loss below." : "Super order on the sold leg: target below the entry, stop loss above (you gain when its price falls).",
  hedge: () => "Protection only — a plain Limit order, no target or stop loss. Place it first; sell it right after the SELL leg's target or stop fills.",
  together: () => "Limit order, no target / stop loss in Dhan. Close both legs by hand when NIFTY reaches its target or stop (grey = expected price then).",
};

// The AI's trade, explained the way a broker app shows an order: each leg is a contract with its own entry,
// target and stop-loss premium (what to type into Dhan); clicking a leg opens its ticket (premium chart, depth,
// how to place it) and marks it on the chain and the index chart.
export function evidenceHtml(e) {
  if (!e) return "";
  return `<details class="evidence"><summary>Inputs looked at</summary>
    <ul class="plain">${e.checks.map((c) => `<li><b>${esc(c.name)}</b> — ${esc(c.why)}</li>`).join("")}</ul>
    <div class="small muted">Inputs only, not evidence: they showed no edge under the conditions tested (daily data, futures, one day old).</div></details>`;
}

export function stratHtml(res, sym) {
  const a = res.plan, pr = res.priced, lv = res.levels;
  const biasCls = { bullish: "up", bearish: "down", neutral: "flat", unclear: "warn" }[a.bias];
  const head = `<div class="strat-head"><div><div class="ask">AI's trade #${res.rank} · expiry ${esc(res.expiry)}</div>
      <div class="what"><b>${esc(STRAT_NAMES[a.strategy])}</b> ${a.strategy !== "no_trade" ? `— ${esc(res.strategy_text)}` : ""}</div></div>
    <div><span class="badge ${biasCls}">${esc(a.bias)}</span> <span class="badge flat">AI confidence ${esc(a.confidence)}</span></div></div>
    ${evidenceHtml(res.evidence)}
    ${res.retried ? `<div class="small muted">The AI's first answer was refused (${esc(res.retried.join("; "))}); this is its corrected answer.</div>` : ""}
    ${res.ai_record ? `<div class="small muted">Saved to the AI track record on the <a href="#record">Trade Record</a> tab, which settles it at its target, stop or expiry.</div>` : ""}`;
  const read = res.ai_why ? `<p><b>Why the AI ranks it #${res.rank}:</b> ${esc(res.ai_why)}</p>` : `<p>${esc(a.market_read)}</p>`;
  if (res.rejected) return `<div class="call stop">${head}<b>The proposal was refused by the safety checks:</b><ul>${res.rejected.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="small">Pulse only shows defined-risk trades (no naked option selling). Ask again, or skip.</div></div>${read}`;
  const name = NAMES[sym] || sym, down = a.underlying_target != null && a.underlying_stop != null && a.underlying_target < a.underlying_stop;
  const story = a.strategy === "no_trade" ? "" : `<div class="story">
      <div class="story-line"><b>${down ? `You make money if ${esc(name)} falls` : a.bias === "neutral" ? `You make money if ${esc(name)} stays in a range` : `You make money if ${esc(name)} rises`}.</b>
        These are <b>${esc(name)} levels</b> — watch the index, not the option price:</div>
      ${ladder(a, res.spot, down)}
      <ol class="steps">
        <li><b>Enter</b> when ${esc(name)} is between <b>${fmt0(a.underlying_entry_low)}</b> and <b>${fmt0(a.underlying_entry_high)}</b> (now ${fmt0(res.spot)}).</li>
        <li><b>Book profit</b> if ${esc(name)} ${down ? "falls" : "rises"} to <b class="up">${fmt0(a.underlying_target)}</b>${lv ? ` — about ${pnl(lv.pnl_target_per_lot)} a lot` : ""}.</li>
        <li><b>Exit with a small loss</b> if ${esc(name)} ${down ? "rises" : "falls"} to <b class="down">${fmt0(a.underlying_stop)}</b>${lv ? ` — about ${pnl(lv.pnl_stop_per_lot)} a lot` : ""}.</li>
      </ol></div>`;
  const allLegs = lv?.legs || pr?.legs || [];
  const legs = !pr ? "" : `<h4 class="mini-h">The order${pr.legs.length > 1 ? "s" : ""} in Dhan — tap one for details</h4><div class="leg-cards">${allLegs.map((l, i) => {
      const role = legRole(a.strategy, allLegs, l), dhan = role === "super" && legLevelsOk(l, l.premium_at_target, l.premium_at_stop);
      const box = (label, v, c) => dhan ? `<div><span>${label}</span><b class="${c}">${v != null ? rupee(v) : "—"}</b></div>`
        : `<div><span>${label === "Target" ? `At ${esc(NAMES[sym] || sym)} target` : `At ${esc(NAMES[sym] || sym)} stop`}</span><b class="ref">${v != null ? rupee(v) : "—"}</b></div>`;
      return `<button class="leg-card ${l.action === "BUY" ? "buy" : "sell"} ${S.ticket[sym]?.i === i ? "on" : ""}" data-leg="${i}">
        <div class="leg-top"><span class="leg-tag ${l.action === "BUY" ? "buy" : "sell"}">${l.action}</span> <b>${esc(contractName(sym, res.expiry, l))}</b>
          <span class="role-tag ${role}">${role === "super" ? "Super order" : role === "hedge" ? "Protection" : "Close together"}</span></div>
        <div class="leg-nums"><div><span>${l.action === "BUY" ? "Buy at" : "Sell at"}</span><b>${rupee(l.price)}</b></div>
          ${role === "hedge" ? `<div><span>Target</span><b class="muted">none</b></div><div><span>Stop loss</span><b class="muted">none</b></div>`
            : box("Target", l.premium_at_target, "up") + box("Stop loss", l.premium_at_stop, "down")}</div>
        <div class="small muted">${ROLE_NOTE[role](l)}</div>
      </button>`;
    }).join("")}</div>`;
  const sp = lv?.spread;
  const together = !sp ? "" : `<div class="together small"><b>Manage the ${pr.legs.length} orders as one trade.</b>
      ${sp.debit ? `You pay <b>${rupee(sp.now)}</b> for the spread.` : `You receive <b>${rupee(sp.now)}</b> for the spread.`}
      Place the <b>BUY</b> leg first, then the SELL leg (Dhan gives a margin benefit for a hedged position).
      ${RULES.credit_strategies.includes(a.strategy)
        ? `Put the <b>Super order</b> (target + stop loss) on the <b>SELL</b> leg only. When it fills at its target or stop, <b>sell the BUY leg</b> straight away. Never put a stop loss on the BUY leg: if it fired alone, the sold leg would be left unprotected.`
        : `Dhan's Super order cannot manage this spread safely, so use plain Limit orders and close <b>both</b> legs by hand when ${esc(name)} reaches its target or stop (the spread is then worth about <b class="up">${rupee(sp.at_target)}</b> or <b class="down">${rupee(sp.at_stop)}</b>). Buy back the <b>SELL</b> leg first, then sell the BUY leg.`}</div>`;
  const econ = pr ? `<div class="levels">
      <div class="lv"><span>Money for 1 lot</span><b>${rupee(pr.outlay_per_lot)}</b><small>${lotMoney(pr.debit, pr.outlay_per_lot).label} · ${pr.lot} qty</small></div>
      <div class="lv"><span>${pr.debit ? "You pay" : "You receive"}</span><b>${rupee(Math.abs(pr.net_per_unit))}</b><small>per unit · ${money(Math.abs(pr.net_per_unit) * pr.lot)} a lot</small></div>
      <div class="lv"><span>Worst case at expiry</span><b class="down">${money(pr.max_loss_per_lot)}</b><small>a lot, if you never exit</small></div>
      <div class="lv"><span>Best case at expiry</span><b class="up">${pr.max_profit_per_lot == null ? "open-ended" : money(pr.max_profit_per_lot)}</b><small>a lot${pr.reward_to_risk != null ? ` · ${pr.reward_to_risk.toFixed(2)}× the risk` : ""}</small></div>
      <div class="lv wide"><div><span>Break-even at expiry</span><b>${pr.breakevens.map(fmt0).join(" / ")}</b></div><div><span>Lot size</span><b>${pr.lot}</b></div>
        <div><span>Charges a lot, in and out (${COST_NOTE})</span><b>${res.charges_per_lot != null ? "≈ " + money(res.charges_per_lot) : "—"}</b></div></div></div>` : "";
  const kl = (a.key_levels || []).map((l) => `<li><b class="num">${fmt0(l.price)}</b> ${esc(l.label)}</li>`).join("");
  return `<div class="call ${a.strategy === "no_trade" ? "idle" : a.bias === "bearish" ? "go-down" : a.bias === "bullish" ? "go-up" : "idle"}">${head}
      ${((ls) => (ls ? `<div class="rec-flag ${ls.tone} live-flag"><b>${ls.tag}.</b> ${ls.text}</div>` : ""))(liveStatus(res, sym))}
      ${story}${legs}<div class="ticket-slot"></div>${together}${econ}
      ${pr ? `<div class="take-row">${res._taken ? `<span class="badge up">Recorded ✓</span> <span class="small">Follow it on the <a href="#record">Trade Record</a> tab.</span>`
        : res._locked ? `<span class="small muted">Take band: ${esc(res._locked)}.</span>`
        : `<button class="btn primary take-trade">Take this trade (dummy, 1 lot)</button> <span class="small muted">Records it on the Trade Record tab at the live price when you press it (the price shown here is ${res._status && res._status !== "unquoted" ? "NSE's latest and can still move" : "from the run"}) and tracks its profit and loss. No real order.</span>`}</div>` : ""}
      ${lv ? `<div class="small muted">Target and stop premiums are estimates for ${esc(name)} reaching those levels today (Black-Scholes from each option's live price and implied vol). Nearer expiry the options move more.</div>` : ""}
      ${(res.warnings || []).map((w) => `<div class="small warn-c">⚠ ${esc(w)}</div>`).join("")}</div>
    ${read}
    <table class="facts">
      <tr><th>Buy or sell options?</th><td>${esc(a.buy_or_sell_reasoning)}</td></tr>
      <tr><th>Why these strikes</th><td>${esc(a.strike_reasoning)}</td></tr>
      <tr><th>Exit plan</th><td>${esc(a.exit_plan)}</td></tr>
      ${kl ? `<tr><th>Key levels</th><td><ul class="plain">${kl}</ul></td></tr>` : ""}
      ${a.risks?.length ? `<tr><th>Risks</th><td><ul class="plain">${a.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></td></tr>` : ""}
    </table>
    <p class="small muted">Chosen by the AI from Pulse's candidates, built by Pulse's rules from the live option chain and priced by Pulse at the live bid / ask. Not advice.</p>`;
}

// NIFTY levels from low to high, so "target below, stop above" (or the reverse) is visible at a glance.
export function ladder(a, spot, down) {
  const pts = [[a.underlying_target, "Target", "up"], [a.underlying_stop, "Stop", "down"], [spot, "Now", "now"],
    [a.underlying_entry_low, "Entry from", "entry"], [a.underlying_entry_high, "Entry to", "entry"]].filter((p) => p[0] != null);
  const lo = Math.min(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[0])), span = hi - lo || 1;
  const x = (v) => 4 + ((v - lo) / span) * 92;
  return `<div class="ladder"><div class="ladder-track">
      <div class="zone entry" style="left:${x(a.underlying_entry_low)}%;width:${x(a.underlying_entry_high) - x(a.underlying_entry_low)}%"></div>
      <div class="zone ${down ? "loss" : "win"}" style="left:${x(Math.max(a.underlying_entry_high, a.underlying_entry_low))}%;right:${100 - x(hi)}%"></div>
      <div class="zone ${down ? "win" : "loss"}" style="left:${x(lo)}%;width:${x(Math.min(a.underlying_entry_low, a.underlying_entry_high)) - x(lo)}%"></div>
      ${pts.filter((p) => p[2] !== "entry").map(([v, t, c]) => `<div class="mark ${c}" style="left:${x(v)}%"><b>${fmt0(v)}</b><span>${t}</span></div>`).join("")}</div>
    <div class="ladder-ends small muted"><span>lower ${down ? "← profit" : "← loss"}</span><span>${down ? "loss →" : "profit →"} higher</span></div></div>`;
}

// ---------- live prices over a fixed run (GET /api/strategy/live, webapp/live.py) ----------
// The run's trades, order, legs and index levels never change. While the market is open the server prices the same
// legs again from NSE's chain (no AI call), and says where the index is against each trade's own levels. withLive
// lays that over the run for display; a live answer for another run, or one older than LIVE_MAX_AGE, is ignored and
// the run's own prices show.
export const LIVE_MAX_AGE = 120000;      // ms: the same 120 s after which a Take refuses NSE's quotes as too old
export function withLive(res, live, now = Date.now()) {
  if (!res?.trades || !live?.live || live.run_id !== res.run_id || now - (live._got ?? now) > LIVE_MAX_AGE) return res;
  return { ...res, spot: live.spot, _live: live, trades: res.trades.map((c, i) => {
    const t = live.trades[i]; if (!t) return c;
    const fresh = t.priced ? { priced: t.priced, levels: t.levels, charges_per_lot: t.charges_per_lot } : {};
    return { ...c, ...fresh, spot: live.spot, _status: t.status, _run_prices: c.priced.legs.map((l) => l.price) };
  }) };
}

// What the trade's status means, in the words the page uses for a warning: [colour, short tag, the sentence].
export function liveStatus(c, sym) {
  if (!c._status) return null;
  const a = c.plan, name = esc(NAMES[sym] || sym), now = `${name} abhi <b>${fmt0(c.spot)}</b>`;
  const zone = `${fmt0(a.underlying_entry_low)}–${fmt0(a.underlying_entry_high)}`, again = "Quick analysis dobara chala.";
  const [tone, tag, text] = {
    enter: ["up", "Zone mein", `${now}: entry zone ${zone} ke andar hai. Le sakta hai; price live hai.`],
    ran: ["warn", "Nikal gaya", `${now}: entry zone ${zone} se aage nikal gaya. Peeche mat bhaag: wapas zone mein aaye tab le, ya ${again}`],
    against: ["warn", "Ulta gaya", `${now}: entry zone ${zone} se ulta gaya, stop ${fmt0(a.underlying_stop)} ki taraf. Abhi mat le.`],
    stop: ["down", "Stop toot gaya", `${now}: is trade ka stop ${fmt0(a.underlying_stop)} toot chuka. Yeh idea ab galat hai, mat le. ${again}`],
    target: ["flat", "Target ho gaya", `${now}: target ${fmt0(a.underlying_target)} aa chuka. Move nikal gaya, ab mat le. ${again}`],
    unquoted: ["warn", "Live quote nahi", `${now}, par is option ka live bid / ask nahi hai: neeche ke prices run ke hain.`],
  }[c._status] || [];
  return tag ? { tone, tag, text } : null;
}

const text1 = (html) => html.replace(/<[^>]+>/g, "");

export const takeKey = (c) => `${c.symbol}|${c.expiry}|${c.priced.legs.map((l) => `${l.action}${l.strike}${l.type}`).join("|")}`;

// The trade in plain Hinglish (user's choice): which option to buy or sell, at what price, what one lot of each costs
// or brings in, the total, when to enter and how to exit. Bought legs first, because that is the order to place them.
export function plainTradeHtml(c, sym) {
  const a = c.plan, pr = c.priced, lot = pr.lot, name = NAMES[sym] || sym, lv = c.levels;
  const legs = [...lv.legs].sort((x, y) => (x.action === y.action ? 0 : x.action === "BUY" ? -1 : 1));
  const kind = (l) => (l.type === "CE" ? "CALL" : "PUT");
  const lines = legs.map((l, i) => `<li>${i === 0 && legs.length > 1 ? "Pehle " : legs.length > 1 ? "Phir " : ""}<b>${esc(fmt0(l.strike).replace(/,/g, ""))} wala ${kind(l)} ${l.action === "BUY" ? "kharid (BUY)" : "bech (SELL)"}</b>
      @ ₹${fmt(l.price)} → 1 lot (${lot}) ${l.action === "BUY" ? "ka" : "bechne pe"} <b>${rupee(l.price * lot)}</b> ${l.action === "BUY" ? "dega" : "milega"}</li>`).join("");
  const total = pr.debit
    ? `Kul milake tu <b>${rupee(pr.outlay_per_lot)} dega</b> (1 lot). Yahi tera max nuksaan hai.${pr.max_profit_per_lot != null ? ` Max fayda <b class="up">${rupee(pr.max_profit_per_lot)}</b>.` : ""}`
    : `Kul milake tujhe <b>${rupee(pr.net_per_unit * lot)} milega</b> (1 lot). Max nuksaan <b class="down">${rupee(pr.outlay_per_lot)}</b>, max fayda <b class="up">${rupee(pr.max_profit_per_lot)}</b>.
       Par margin Dhan isse kaafi zyada rokega (BUY wala pehle fill na ho to ₹1 lakh+): Dhan mein check kar.`;
  const exit = legs.length === 1
    ? `Dhan mein Super order laga: target <b class="up">₹${fmt(legs[0].premium_at_target)}</b>, stop loss <b class="down">₹${fmt(legs[0].premium_at_stop)}</b>.`
    : RULES.credit_strategies.includes(a.strategy)
      ? `Super order (target + stop) sirf SELL wale pe laga; woh nikle to BUY wala turant bech de.`
      : `Dhan ka Super order spread pe nahi chalta: dono saath haath se band kar. Pehle SELL wala wapas kharid, phir BUY wala bech.`;
  return `<div class="plain-trade"><b>Dekh bhai:</b><ol>${lines}</ol>
    <div>${total}</div>
    <div>Lena tab jab ${esc(name)} <b>${fmt0(a.underlying_entry_low)}–${fmt0(a.underlying_entry_high)}</b> ke beech ho.
      ${esc(name)} <b class="up">${fmt0(a.underlying_target)}</b> pahunche to profit book kar (~<b class="up">+₹${fmt0(lv.pnl_target_per_lot)}</b>);
      <b class="down">${fmt0(a.underlying_stop)}</b> aaye to nikal ja (~<b class="down">−₹${fmt0(-lv.pnl_stop_per_lot)}</b>). ${exit}
      Expiry wale din ${clock12(RULES.exit_by, false)} se pehle band kar.</div></div>`;
}

// One trade as a compact card that fits the page width: the summary line, each Dhan order with its entry,
// target and stop, the NIFTY levels with the per-lot result, and the AI's reason (two lines; all of it when selected).
export function tradeCard(c, i, sym, on, closed = false) {
  const lv = c.levels, a = c.plan, name = NAMES[sym] || sym;
  const legs = lv.legs.map((l) => {
    const role = legRole(a.strategy, lv.legs, l), dhan = role === "super" && legLevelsOk(l, l.premium_at_target, l.premium_at_stop);
    const lvl = role === "hedge" ? `<span class="muted">protection, no target / stop</span>`
      : dhan ? `target <b class="up">${fmt(l.premium_at_target)}</b> · stop loss <b class="down">${fmt(l.premium_at_stop)}</b>`
      : `<span class="ref">at ${esc(name)} target ${fmt(l.premium_at_target)} · at stop ${fmt(l.premium_at_stop)}</span>`;
    return `<div class="ai-leg"><span class="leg-tag ${l.action === "BUY" ? "buy" : "sell"}">${l.action}</span> <b>${esc(contractName(sym, c.expiry, l))}</b>
      <span>limit <b>${fmt(l.price)}</b></span> <span>${lvl}</span></div>`;
  }).join("");
  const m = lotMoney(c.priced.debit, c.priced.outlay_per_lot), ls = liveStatus(c, sym);
  return `<div class="ai-trade ${on ? "on" : ""}" data-ai="${i}">
    <div class="ai-top"><b class="rk">#${c.rank}</b> <b>${esc(STRAT_NAMES[a.strategy])}</b>
      <span class="badge ${a.bias === "bearish" ? "down" : "up"}">${esc(a.bias)}</span>${ls ? `<span class="badge ${ls.tone}" title="${esc(text1(ls.text))}">${ls.tag}</span>` : ""}<span class="small muted">AI confidence ${esc(a.confidence)}</span>
      <span class="ai-take"><span class="small">1 lot <b>${rupee(m.v)}</b> <span class="muted">${m.label}</span></span> ${closed ? `<span class="small muted">market band</span>` : takeCell(c, `data-take="${i}"`)}</span></div>
    ${plainTradeHtml(c, sym)}
    <div class="ai-legs">${legs}</div>
    <div class="ai-nums"><span>${esc(name)} entry <b>${fmt0(a.underlying_entry_low)}–${fmt0(a.underlying_entry_high)}</b></span>
      <span>target <b class="up">${fmt0(a.underlying_target)}</b></span><span>stop <b class="down">${fmt0(a.underlying_stop)}</b></span>
      <span>a lot <b class="up">+₹${fmt0(lv.pnl_target_per_lot)}</b> / <b class="down">−₹${fmt0(-lv.pnl_stop_per_lot)}</b></span></div>
    <div class="ai-why">${esc(c.ai_why)}</div></div>`;
}
export const takeCell = (c, attrs) => S.takenRank[takeKey(c)] ? `<span class="badge up">Recorded ✓</span>` : `<button class="btn small-btn rank-take" ${attrs}>Take (dummy, 1 lot)</button>`;

// The AI's ranked trades: the research's read of the market, then up to 8 trades best first, each with the AI's reason.
export function aiListHtml(sym, res) {
  const name = NAMES[sym] || sym, v = S.view[sym], ag = res.agents || {};
  const research = ag.error ? `<div class="notice">The research agents failed (${esc(ag.error)}), so this ranking used the live data only, with no news.</div>`
    : `<div class="small muted">${res.mode === "quick" ? "Quick analysis" : "Complete analysis"} · research: ${esc(ag.source && ag.source !== "fresh" ? `${ag.source} at ${ag.at}` : "run fresh")} (${esc(ag.minutes ?? "—")} min)${ag.rating ? `, the agents' call <b>${esc(ag.rating)}</b>` : ""}. Then the AI ranked ${res.considered} live candidates.</div>`;
  const tp = res.tape?.direction, tapeLine = !tp ? "" : `<div class="small"><b>Aaj ka tape (${esc(res.tape.as_of || "—")}):</b> ${
    tp === "up" ? `<b class="up">UP</b> (VWAP, EMA 9/21 aur open teeno ke upar), isliye AI ko sirf <b>bullish</b> trades diye gaye.`
    : tp === "down" ? `<b class="down">DOWN</b> (VWAP, EMA 9/21 aur open teeno ke neeche), isliye AI ko sirf <b>bearish</b> trades diye gaye.`
    : `<b>MIXED</b>${res.tape.why ? ` (${esc(res.tape.why)})` : ""}: dono direction ke trades diye gaye.`}</div>`;
  const read = `${tapeLine}<p>${esc(res.market_read)}</p>${res.news_read ? `<p><b>News and agents:</b> ${esc(res.news_read)}</p>` : ""}
    ${res.risks?.length ? `<details class="evidence"><summary>Risks the AI sees</summary><ul class="plain">${res.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}`;
  const closedNote = (res.expired ? `<div class="notice">Yeh run expired hai (kisi aur din ka): sirf dekhne ke liye. Uske prices aaj ke nahi, isliye Take band hai. Analysis dobara chala.</div>` : "")
    + (res.market_closed ? `<div class="notice">Yeh run market band hone pe hua: prices last close ke hain, in pe asli order nahi lagta. Take band hai, aur AI record mein nahi gaya. 9:15 ke baad Quick analysis chala.</div>` : "");
  if (!res.trades.length) return budgetCardHtml(sym, res) + closedNote + `<div class="call stop"><b>No trade.</b> The AI found no candidate the evidence supports.${research}</div>${read}`;
  const cards = res.trades.map((c, i) => tradeCard(c, i, sym, v === i, res.market_closed || res.expired)).join("");
  return `${budgetCardHtml(sym, res)}
    <div class="rank-head"><div><h4 class="mini-h">The AI's ${res.trades.length} strongest trades · run at ${esc(res.asked_at)} · expiry ${esc(res.expiry)}</h4>${research}
      <div class="small muted">The full list, for the forward test and for reading. Trades with a SELL leg need far more than ₹${fmt0(budget())}.</div></div></div>
    ${closedNote}${read}
    <div class="ai-trades">${cards}</div>
    <div class="small muted">Strongest first, by the whole analysis, not by profit size. Pulse priced each at the live bid / ask of the run and set its entry zone, target and stop by a fixed rule.
      Entry: place each Limit order at its price while ${esc(name)} is inside the entry zone. Tap a trade for its full card and ticket. Target / stop loss are Dhan Super-order prices; <span class="ref">grey</span> = expected price when ${esc(name)} hits its level, closed by hand.
      Premiums at target and stop are estimates for today. One lot each; charges in the card. ${cap(COST_NOTE)}. #1 is the forward test's trade. Take records it on the Trade Record tab; no real order.</div>`;
}

export function budgetCardHtml(sym, res) {
  const head = `<div class="ai-head"><b>For your ₹${fmt0(budget())} · 1 lot</b></div>`;
  if (S.status?.muhurat) return `<div class="budget-card">${head}<div class="call stop"><b>No trade today.</b> Muhurat day: you don't trade it. The data is still saved.</div></div>`;
  const c = budgetPick(res.trades || []);
  if (!c) return `<div class="budget-card">${head}<div class="call stop"><b>No trade today.</b> None of the AI's trades is a single BUY that costs ₹${fmt0(budget())} or less for 1 lot. Don't force one.</div></div>`;
  const l = c.levels.legs[0], lot = c.priced.lot, a = c.plan, name = NAMES[sym] || sym, pay = l.price * lot;
  const ok = legLevelsOk(l, l.premium_at_target, l.premium_at_stop);
  const exits = ok
    ? `<div class="lv"><span>Take profit: sell at</span><b class="up">₹${fmt(l.premium_at_target)}</b><small>you make about +₹${fmt0(l.pnl_target_per_lot)}</small></div>
       <div class="lv"><span>Stop loss: sell at</span><b class="down">₹${fmt(l.premium_at_stop)}</b><small>you lose about −₹${fmt0(-l.pnl_stop_per_lot)}</small></div>`
    : `<div class="lv"><span>Exit</span><b>by hand</b><small>sell when ${esc(name)} reaches ${fmt0(a.underlying_target)} (profit) or ${fmt0(a.underlying_stop)} (stop)</small></div>`;
  const stale = res.market_closed || res.expired
    ? `<div class="notice">These are last-close prices, not live. Run Quick analysis after 9:15 AM before buying.</div>` : "";
  const ls = liveStatus(c, sym), was = c._run_prices?.[0];
  const liveLine = ls ? `<div class="rec-flag ${ls.tone} live-flag"><b>${ls.tag}.</b> ${ls.text}</div>` : "";
  const moved = was != null && was !== l.price ? ` · run ke time ₹${fmt(was)} tha` : "";
  return `<div class="budget-card">${head}${stale}${liveLine}
    <div class="budget-order"><span class="leg-tag buy">BUY</span> <b>${esc(contractName(sym, c.expiry || res.expiry, l))}</b> <span class="muted">(1 lot = ${lot} qty)</span></div>
    <div class="levels">
      <div class="lv"><span>Buy at${ls ? " (live)" : ""}</span><b>₹${fmt(l.price)} or less</b><small>you pay ${rupee(pay)} · ₹${fmt0(budget() - pay)} stays free${moved}</small></div>
      ${exits}
    </div>
    <div class="small">Buy only while ${esc(name)} is between <b>${fmt0(a.underlying_entry_low)}–${fmt0(a.underlying_entry_high)}</b>.
      ${ok ? "In Dhan: Super order with this target and stop loss." : ""} <b>Exit by ${clock12(RULES.exit_by)} no matter what.</b> Worst case you lose the ${rupee(pay)} you paid.</div>
    <div class="small muted">AI's #${c.rank} of ${res.trades.length}. Not a proven edge; ${COST_NOTE}.</div></div>`;
}

// The Risk tab: regime, expected move, volatility and option richness.
import { api } from "./api.js";
import { card, esc, fmt, fmt0, freshLine, pc } from "./format.js";
import { S } from "./state.js";
import { $ } from "./util.js";

// ---------- risk & volatility ----------
export const REGIME_TEXT = {
  calm: ["Calm", "up", "Moves are smaller than usual. Option sellers face less risk; tight stops get hit less often."],
  choppy: ["Choppy", "warn", "Moves are bigger than usual. Use wider stops and smaller size."],
  stress: ["Stress", "down", "Rare, violent markets. Defined-risk trades only, and small size."],
};

export async function loadRisk() {
  const sym = S.sym;
  $("#riskBody").innerHTML = `<div class="loading"><span class="spinner"></span>Loading…</div>`;
  let r;
  try { r = await api("/api/risk/" + encodeURIComponent(sym)); }
  catch (e) { $("#riskBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  if (sym !== S.sym) return;
  let html = freshLine(r.freshness);
  const g = r.regime;
  if (g) {
    const [label, tone, meaning] = REGIME_TEXT[g.name] || [g.name, "flat", ""];
    const bars = ["calm", "choppy", "stress"].map((k) => `<div class="prob"><span>${REGIME_TEXT[k][0]}</span>
      <div class="meter"><i style="width:${Math.round(g.p[k] * 100)}%;background:var(--${REGIME_TEXT[k][1] === "warn" ? "warn" : REGIME_TEXT[k][1]})"></i></div>
      <b class="num">${Math.round(g.p[k] * 100)}%</b></div>`).join("");
    html += card("How calm is the market?", `<p class="big">${label}</p><p>${meaning}</p>
      <p class="small muted">Whole-market reading (NIFTY), ${label.toLowerCase()} since ${esc(g.since)}, as of the close of ${esc(g.as_of)}.</p>${bars}
      <p class="note">The regime tells you how <b>big</b> moves tend to be next, not which <b>way</b>: next-month volatility was 11.5% in calm markets vs 15.1% in choppy ones (2021–26).</p>`,
      `<span class="badge ${tone}">${label}</span>`);
  }
  if (!r.in_universe) {
    html += `<div class="notice">Volatility forecasts exist for the research universe only: the 29 large F&amp;O stocks, NIFTY and BANKNIFTY.
      ${esc(sym)} is not in it. Pick NIFTY, BANKNIFTY or a large stock such as RELIANCE, HDFCBANK, INFY.</div>`;
    $("#riskBody").innerHTML = html; return;
  }
  const m = r.expected_move;
  if (m) {
    const rows = [5, 10, 21].map((h) => {
      const x = m["h" + h], lo = m.close ? m.close - x.rupees : null, hi = m.close ? m.close + x.rupees : null;
      return `<tr><td>Next ${h} trading days${h === 5 ? " (a week)" : h === 21 ? " (a month)" : " (two weeks)"}</td>
        <td class="num"><b>±${pc(x.pct)}</b></td><td class="num">${x.rupees != null ? "±₹" + fmt0(x.rupees) : "—"}</td>
        <td class="num">${lo != null ? `${fmt0(lo)} – ${fmt0(hi)}` : "—"}</td></tr>`;
    }).join("");
    html += card("How far could it move?", `<table class="t"><thead><tr><th>Period</th><th>Move</th><th>In ₹</th><th>Likely range</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="note">About <b>2 times in 3</b> the price stays inside this range (one standard deviation from the GARCH forecast, last close ₹${fmt(m.close)}).
      Use it for <b>stop distance</b> (a stop inside the 5-day move gets hit by normal noise), <b>option strike width</b> and <b>position size</b>.</p>`,
      `<span class="small muted">GARCH, made after the close of ${esc(r.vol?.as_of || "")}</span>`);
  }
  const v = r.vol;
  if (v) {
    const row = (h) => `<tr><td>Next ${h} days</td><td class="num"><b>${pc(v["h" + h].garch)}</b></td><td class="num">${pc(v["h" + h].ewma)}</td></tr>`;
    html += card("Volatility forecast (yearly terms)", `<table class="t"><thead><tr><th>Period</th><th>GARCH (validated)</th><th>Simple average</th></tr></thead>
      <tbody>${row(5)}${row(10)}${row(21)}</tbody></table>
      <p class="note">Last 20 days actually moved at ${pc(v.historical_20d)} a year. GARCH beat that simple history on 31 of 31 symbols in testing.</p>`);
  }
  const iv = r.iv;
  if (iv) {
    const rich = iv.minus_garch21;
    const verdict = rich == null ? "" : rich > 0.03 ? "Options are priced <b>above</b> the forecast: expensive (better for sellers, worse for buyers)."
      : rich < -0.03 ? "Options are priced <b>below</b> the forecast: cheap (better for buyers)." : "Options are priced close to the forecast: fair.";
    html += card("Are options cheap or expensive?", `<div class="stats">
        <div class="stat"><span>Implied vol (30 days)</span><b class="num">${pc(iv.iv30)}</b></div>
        <div class="stat"><span>Above / below the GARCH forecast</span><b class="num">${rich == null ? "—" : (rich > 0 ? "+" : "") + pc(rich)}</b></div>
        <div class="stat"><span>Higher than this share of the past year</span><b class="num">${pc(iv.percentile_1y, 0)}</b></div></div>
      <p>${verdict}</p><p class="small muted">From NSE's option closes on ${esc(iv.as_of)}. Context only: selling options when they look expensive was tested and did not beat costs on its own.</p>`);
  }
  $("#riskBody").innerHTML = html || `<div class="notice">No research numbers available yet.</div>`;
}

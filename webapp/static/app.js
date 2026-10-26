"use strict";

const $ = (s, el = document) => el.querySelector(s);
const IST_OFFSET = 19800; // lightweight-charts draws UTC; shift so the axis reads Indian time

const S = { sym: (new URLSearchParams(location.search).get("sym") || store("sym") || "NIFTY").toUpperCase(), tf: "5m", indices: [], quotes: {}, status: {}, plan: null, expiry: null, aiJob: null,
  tab: "today" };

function store(k, v) {
  try {
    if (v === undefined) return localStorage.getItem("pulse." + k);
    localStorage.setItem("pulse." + k, v);
  } catch { return null; }
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}

const nf = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt = (x) => (x == null || isNaN(x) ? "—" : nf.format(x));
const fmt0 = (x) => (x == null || isNaN(x) ? "—" : Math.round(x).toLocaleString("en-IN"));
const rupee = (x) => (x == null ? "—" : "₹" + fmt(x));
const fmtInt = (x) => {
  if (x == null) return "—";
  const a = Math.abs(x), s = x < 0 ? "-" : "";
  if (a >= 1e7) return s + (a / 1e7).toFixed(2) + "Cr";
  if (a >= 1e5) return s + (a / 1e5).toFixed(2) + "L";
  if (a >= 1e3) return s + (a / 1e3).toFixed(1) + "K";
  return String(x);
};
// Where prices came from; "saved (…)" means the live source was unreachable and the last saved bars are shown.
const srcLabel = (x) => (x === "dhan" ? "Dhan live data" : x === "yahoo" ? "Yahoo data (can be delayed)" : `No connection to the data source — showing ${x || "saved data"}`);
const cls = (x) => (x > 0 ? "up" : x < 0 ? "down" : "muted");
const sign = (x) => (x > 0 ? "+" : "");
const pct = (x) => (x == null ? "—" : `${sign(x)}${x.toFixed(2)}%`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const isIndex = (sym) => S.indices.some((i) => i.symbol === sym);
const nameOf = (sym) => S.indices.find((i) => i.symbol === sym)?.name || sym;

// ---------- theme ----------
if (store("theme")) document.documentElement.dataset.theme = store("theme");
$("#themeBtn").onclick = () => {
  const dark = cssVar("--bg") !== "#f6f7f9";
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  store("theme", document.documentElement.dataset.theme);
  applyChartTheme();
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyChartTheme());

// ---------- status + quotes ----------
async function loadStatus() {
  try {
    S.status = await api("/api/status");
    S.indices = S.status.indices;
    const mp = $("#marketPill");
    mp.textContent = S.status.market_open ? "● Market open" : "Market closed";
    mp.classList.toggle("open", S.status.market_open);
  } catch (e) { console.warn(e); }
}

async function loadQuotes() {
  const syms = [...new Set([...S.indices.map((i) => i.symbol), S.sym])];
  try {
    Object.assign(S.quotes, await api("/api/quotes?symbols=" + encodeURIComponent(syms.join(","))));
    renderChips(); renderInst();
  } catch (e) { console.warn(e); }
}

function renderChips() {
  const list = [...S.indices.map((i) => i.symbol), ...(isIndex(S.sym) ? [] : [S.sym])];
  $("#chips").innerHTML = list.map((s) => {
    const q = S.quotes[s];
    return `<button class="chip ${s === S.sym ? "active" : ""}" data-sym="${esc(s)}"><b>${esc(nameOf(s))}</b>
      <span class="num">${q ? fmt(q.ltp) : "—"}</span> ${q ? `<span class="${cls(q.change)} small">${pct(q.change_pct)}</span>` : ""}</button>`;
  }).join("");
}
$("#chips").onclick = (e) => {
  const b = e.target.closest(".chip"); if (!b) return;
  selectSymbol(b.dataset.sym);
  if (!INSTRUMENT_TABS.includes(S.tab) && S.tab !== "plan") showTab("today");   // from Map, Research or My Trades: open its page
};

function renderInst() {
  const q = S.quotes[S.sym];
  $("#instName").textContent = nameOf(S.sym);
  $("#instSub").textContent = isIndex(S.sym) ? "Index · options available" : `NSE stock${q?.name && q.name !== S.sym ? " · " + q.name : ""}`;
  $("#instLtp").textContent = q ? fmt(q.ltp) : "—";
  $("#instChg").innerHTML = q ? `<span class="${cls(q.change)} num">${sign(q.change)}${fmt(q.change)} (${pct(q.change_pct)}) today</span>` : "";
}

function selectSymbol(sym) {
  sym = sym.toUpperCase();
  if (sym === S.sym) return;
  S.sym = sym; S.expiry = null; S.plan = null; store("sym", sym);
  $("#hero").innerHTML = `<div class="loading"><span class="spinner"></span>Reading the market and checking history…</div>`;
  ["#mood", "#record", "#btst", "#history"].forEach((id) => ($(id).innerHTML = ""));
  renderChips(); renderInst();
  firstLoad = true; loadCandles(); loadQuotes(); loadPlan();
  showTab(S.tab, true);
  scrollTo({ top: 0, behavior: "smooth" });
}

// ---------- search ----------
let searchTimer, searchSel = -1;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { $("#results").hidden = true; return; }
  searchTimer = setTimeout(async () => {
    const hits = await api("/api/search?q=" + encodeURIComponent(q)).catch(() => []);
    searchSel = -1;
    $("#results").innerHTML = hits.map((h) => `<div data-sym="${esc(h.symbol)}"><span><b>${esc(h.symbol)}</b> <span class="muted small">${esc(h.name !== h.symbol ? h.name : "")}</span></span><span class="small muted">${h.kind === "INDEX" ? "Index" : "Stock"}</span></div>`).join("") || `<div class="muted">No match</div>`;
    $("#results").hidden = false;
  }, 180);
});
$("#search").addEventListener("keydown", (e) => {
  const items = [...$("#results").querySelectorAll("[data-sym]")];
  if (e.key === "Escape") { $("#results").hidden = true; return; }
  if (!items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    searchSel = (searchSel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((el, i) => el.classList.toggle("sel", i === searchSel));
  } else if (e.key === "Enter") pick(items[Math.max(searchSel, 0)].dataset.sym);
});
$("#results").onclick = (e) => { const d = e.target.closest("[data-sym]"); if (d) pick(d.dataset.sym); };
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) $("#results").hidden = true; });
function pick(sym) { $("#results").hidden = true; $("#search").value = ""; selectSymbol(sym); }

// ---------- the plan ----------
async function loadPlan() {
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

function checksList(c) { return `<ul class="checks">${(c || []).map((x) => `<li class="${x.ok ? "ok" : ""}">${esc(x.text)}</li>`).join("")}</ul>`; }

function renderHero(p) {
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

  let conf = "";
  if (live && v.win_rate != null && v.trades) {
    const good = v.win_rate >= 60;
    conf = `<div class="conf">
      <div class="conf-row"><span>Won <b>${Math.round(v.win_rate * v.trades / 100)} of ${v.trades}</b> similar trades (${v.win_rate}%)</span>
        <span class="${cls(v.avg_r)}">avg ${sign(v.avg_r)}${v.avg_r}× risk after costs</span></div>
      <div class="meter" title="Need 60%+ to call it safe"><i style="width:${v.win_rate}%;background:var(${good ? "--up" : "--warn"})"></i><em style="left:60%"></em></div>
      <div class="small muted" style="margin-top:6px">Confidence: <b>${v.confidence}</b> · the line marks the 60% we require</div></div>`;
  }

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

function renderMood(p) {
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

function renderRecord(p) {
  const r = p.record;
  const rows = Object.entries(r.by_target).map(([t, x]) => `<tr class="${+t === r.chosen ? "pick" : ""}">
    <td>${t}× risk${+t === r.chosen ? " ✓" : ""}</td><td>${x.trades}</td><td>${x.win_rate ?? "—"}${x.win_rate != null ? "%" : ""}</td>
    <td class="${cls(x.avg_r)}">${x.avg_r != null ? sign(x.avg_r) + x.avg_r : "—"}</td></tr>`).join("");
  const side = (k, label) => { const x = r.by_side[k]; return x.trades ? `${label}: <b>${x.win_rate}%</b> of ${x.trades}` : `${label}: none`; };
  const recent = r.last.slice().reverse();                                    // oldest first
  const won = recent.filter((t) => t.r > 0).length;
  const chips = recent.map((t) => `<div class="trade" title="${esc(t.time.slice(0, 10))} · ${t.side === "BUY" ? "buy" : "sell"} setup · ${sign(t.r)}${t.r}× risk after costs">
      <span class="${t.r > 0 ? "w" : "l"}">${t.r > 0 ? "W" : "L"}</span><small class="${cls(t.r)}">${sign(t.r)}${t.r}</small></div>`).join("");
  const target = r.by_target[String(r.chosen)] || {};
  $("#record").innerHTML = `<div class="card-head"><h2>Track record of this setup</h2></div>
    <div class="body"><p class="small muted" style="margin-top:0">We replayed this exact rule over the last ${r.days} trading days: one trade a day, entry after 9:45 AM, exit by 3:15 PM, ${r.cost_pct}% costs included.</p>
      <table class="t"><thead><tr><th>Profit target</th><th>Trades</th><th>Win rate</th><th>Avg result</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="small" style="margin:10px 0 0">${side("BUY", "Buy setups")} · ${side("SELL", "Sell setups")}</p>
      ${chips ? `<div class="small" style="margin-top:12px"><b>The last ${recent.length} of these ${target.trades ?? recent.length} trades</b> (${r.chosen}× risk target), oldest → newest:
        ${won} won, ${recent.length - won} lost</div>
        <div class="trades">${chips}</div>
        <div class="small muted"><b class="up">W</b> = the trade made money after costs · <b class="down">L</b> = it lost money.
        The number under each box is the result in units of risk: +1.5 = gained 1.5× what was risked, −1.0 = lost the full risk. Hover a box for its date.</div>` : ""}
      <p class="note">"Avg result" is the average gain per trade as a share of what you risked: +0.10 means you made 10% of your risk per trade on average. A big win rate with a negative average still loses money.</p></div>`;
}

function renderBtst(p) {
  const b = p.btst, rec = b.record || {};
  const badge = b.side === "BUY" ? (b.safe ? `<span class="badge up">BTST BUY</span>` : `<span class="badge" style="background:var(--warn-soft);color:var(--warn)">SETUP, NOT SAFE</span>`) : `<span class="badge flat">NO BTST TODAY</span>`;
  const levels = b.side === "BUY" ? `<div class="levels" style="margin:12px 0"><div class="lv"><span>Buy near close</span><b>${fmt(b.entry)}</b></div>
      <div class="lv"><span>Stop loss</span><b class="down">${fmt(b.stop_loss)}</b></div><div class="lv"><span>Target next day</span><b class="up">${fmt(b.target)}</b></div></div>` : "";
  $("#btst").innerHTML = `<div class="card-head"><h2>BTST: buy today, sell tomorrow</h2>${badge}</div>
    <div class="body"><p style="margin-top:0">${b.side === "BUY"
      ? "Today's candle looks strong enough to carry into tomorrow morning."
      : "Today's candle isn't strong enough to hold overnight."} Judge it after <b>3:00 PM</b>, when the day's candle is nearly final.</p>
      ${levels}${checksList(b.checks)}
      <p class="note">History: this BTST rule fired ${rec.trades || 0} times in the last 2 years and won ${rec.win_rate ?? "—"}${rec.win_rate != null ? "%" : ""} of them (avg ${rec.avg_r != null ? sign(rec.avg_r) + rec.avg_r : "—"}× risk).</p></div>`;
}

function renderHistory(p) {
  const rows = p.mood.recent.map((d) => `<tr><td>${esc(d.date)}</td><td>${fmt(d.open)}</td><td>${fmt(d.high)}</td><td>${fmt(d.low)}</td><td><b>${fmt(d.close)}</b></td><td class="${cls(d.change_pct)}">${pct(d.change_pct)}</td></tr>`).join("");
  $("#history").innerHTML = `<div class="card-head"><h2>Last 10 sessions</h2><span class="small muted">Switch the chart to Daily for the full history</span></div>
    <div class="body" style="overflow-x:auto"><table class="t"><thead><tr><th>Date</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// ---------- chart ----------
const chart = LightweightCharts.createChart($("#chart"), {
  autoSize: true,
  layout: { background: { type: "solid", color: "transparent" }, fontFamily: "Inter, system-ui, sans-serif" },
  rightPriceScale: { borderVisible: false },
  timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
  crosshair: { mode: 0 },
});
const candleSeries = chart.addCandlestickSeries({ borderVisible: false });
const volSeries = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
const lineOpts = { lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
const ema9Series = chart.addLineSeries(lineOpts);
const ema21Series = chart.addLineSeries(lineOpts);
let planLines = [];

function applyChartTheme() {
  const up = cssVar("--up"), down = cssVar("--down");
  chart.applyOptions({ layout: { textColor: cssVar("--muted") }, grid: { vertLines: { color: cssVar("--grid") }, horzLines: { color: cssVar("--grid") } } });
  candleSeries.applyOptions({ upColor: up, downColor: down, wickUpColor: up, wickDownColor: down });
  ema9Series.applyOptions({ color: cssVar("--ema9") });
  ema21Series.applyOptions({ color: cssVar("--ema21") });
  if (lastBars.length) drawBars(lastBars);
  drawPlanLines();
  if (typeof planCharts !== "undefined") planCharts.forEach((c, sym) => {
    c.ch.applyOptions({ layout: { textColor: cssVar("--muted") }, grid: { vertLines: { color: cssVar("--grid") }, horzLines: { color: cssVar("--grid") } } });
    c.candles.applyOptions({ upColor: up, downColor: down, wickUpColor: up, wickDownColor: down });
    c.e9.applyOptions({ color: cssVar("--ema9") }); c.e21.applyOptions({ color: cssVar("--ema21") });
    drawPlanChartLines(sym);
  });
}

function ema(values, n) { const k = 2 / (n + 1); let prev; return values.map((v) => (prev = prev === undefined ? v : v * k + prev * (1 - k))); }

let lastBars = [], firstLoad = true, candleBusy = false;
function drawBars(bars) {
  const up = cssVar("--up"), down = cssVar("--down"), t = (b) => b.time + IST_OFFSET;
  candleSeries.setData(bars.map((b) => ({ time: t(b), open: b.open, high: b.high, low: b.low, close: b.close })));
  volSeries.setData(bars.map((b) => ({ time: t(b), value: b.volume, color: (b.close >= b.open ? up : down) + "55" })));
  const closes = bars.map((b) => b.close), e9 = ema(closes, 9), e21 = ema(closes, 21);
  ema9Series.setData(bars.map((b, i) => ({ time: t(b), value: e9[i] })));
  ema21Series.setData(bars.map((b, i) => ({ time: t(b), value: e21[i] })));
}

function drawPlanLines() {
  planLines.forEach((l) => candleSeries.removePriceLine(l)); planLines = [];
  const s = S.plan?.signal;
  if (!s || s.side === "WAIT" || S.plan.symbol !== S.sym) return;
  const mk = (price, color, title) => planLines.push(candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
  mk(s.entry, cssVar("--muted"), "Entry"); mk(s.stop_loss, cssVar("--down"), "Stop loss"); mk(s.target, cssVar("--up"), "Target");
}

async function loadCandles() {
  if (candleBusy) return; candleBusy = true;
  const sym = S.sym, tf = S.tf;
  try {
    const r = await api(`/api/candles/${encodeURIComponent(sym)}?tf=${tf}&limit=${tf === "1D" ? 600 : 900}`);
    if (sym !== S.sym || tf !== S.tf) return;
    lastBars = r.bars; drawBars(r.bars);
    if (firstLoad) {
      const n = r.bars.length, show = tf === "5m" ? 160 : tf === "15m" ? 130 : tf === "1h" ? 120 : 250;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - show), to: n + 4 });
      firstLoad = false;
    }
  } catch (e) { console.warn(e); } finally { candleBusy = false; }
}
$("#tfSeg").onclick = (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.tf = b.dataset.tf; firstLoad = true;
  document.querySelectorAll("#tfSeg button").forEach((x) => x.classList.toggle("active", x === b));
  loadCandles();
};

// ---------- option chain ----------
$("#expirySel").onchange = (e) => { S.expiry = e.target.value; loadChain(); };
async function loadOptions() {
  const notice = $("#ocNotice");
  $("#ocTable tbody").innerHTML = ""; $("#ocStats").innerHTML = "";
  const hideChain = (msg) => { notice.hidden = false; notice.textContent = msg; $(".oc-scroll", $("#ocTable").closest(".pad")).hidden = true; $("#expirySel").closest("label").hidden = true; };
  $(".oc-scroll", $("#ocTable").closest(".pad")).hidden = false; $("#expirySel").closest("label").hidden = false;
  if (!isIndex(S.sym)) { hideChain("The live option chain is shown for indices. Pick NIFTY, BANKNIFTY or another index above — the trading costs below work for stocks too."); return; }
  try {
    const exps = await api("/api/expiries/" + S.sym);
    S.expiry = S.expiry && exps.includes(S.expiry) ? S.expiry : exps[0];
    $("#expirySel").innerHTML = exps.map((x) => `<option ${x === S.expiry ? "selected" : ""}>${x}</option>`).join("");
    notice.hidden = true; loadChain();
  } catch (e) { hideChain(e.message.includes("Dhan") ? "The live option chain needs a Dhan connection (DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env). The trading costs below work without it." : e.message); }
}
let chainBusy = false, chainCentered = null;
async function loadChain() {
  if (chainBusy || !S.expiry) return; chainBusy = true;
  const sym = S.sym, exp = S.expiry;
  try {
    const c = await api(`/api/optionchain/${sym}?expiry=${exp}`);
    if (sym === S.sym && exp === S.expiry) renderChain(c);
  } catch (e) { $("#ocNotice").hidden = false; $("#ocNotice").textContent = e.message; } finally { chainBusy = false; }
}
function renderChain(c) {
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

// ---------- AI ----------
const aiJobs = JSON.parse(store("aiJobs") || "{}");
function renderAI() {
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
const RATING_COLORS = { Buy: "--up", Overweight: "--up", Hold: "--warn", Underweight: "--down", Sell: "--down" };
async function pollAI(jobId, sym) {
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
    $("#aiResult").innerHTML = `<div class="verdict" style="background:${cssVar(RATING_COLORS[job.rating] || "--muted")}"><h2>${esc(job.rating)}</h2><div>${esc(nameOf(job.symbol))} · finished ${job.finished}</div></div>
      <div class="report-tabs">${names.map((n, i) => `<button data-i="${i}" class="${i ? "" : "active"}">${esc(n)}</button>`).join("")}</div><div class="report" id="reportBody"></div>`;
    const show = (i) => {
      $("#reportBody").innerHTML = DOMPurify.sanitize(marked.parse(job.reports[names[i]] || ""));
      document.querySelectorAll(".report-tabs button").forEach((b) => b.classList.toggle("active", +b.dataset.i === i));
    };
    $(".report-tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) show(+b.dataset.i); };
    show(0); return;
  }
}

// ---------- tabs ----------
const TABS = ["plan", "record", "today", "risk", "options", "ai", "map", "research", "trades"];
const INSTRUMENT_TABS = ["today", "risk", "options", "ai"];
const loaded = {};

function showTab(tab, force = false) {
  if (!TABS.includes(tab)) tab = "plan";
  const changed = S.tab !== tab;
  S.tab = tab; store("tab", tab);
  if (location.hash.slice(1) !== tab) history.replaceState(null, "", "#" + tab);
  document.querySelectorAll("#tabs button").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.classList.toggle("active", on); b.setAttribute("aria-selected", on);
  });
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.dataset.tab !== tab));
  $("#instArea").hidden = !INSTRUMENT_TABS.includes(tab);
  const key = INSTRUMENT_TABS.includes(tab) ? tab + ":" + S.sym : tab;
  if (!force && !changed && loaded[key]) return;
  loaded[key] = true;
  if (tab === "plan") loadMorning();
  if (tab === "today") loadCandles();
  if (tab === "risk") loadRisk();
  if (tab === "options") { loadOptions(); loadCosts(); }
  if (tab === "ai") renderAI();
  if (tab === "map") loadMap();
  if (tab === "research") loadResearch();
  if (tab === "trades") loadJournalFiles();
  if (tab === "record") loadRecord();
}
$("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); };
addEventListener("hashchange", () => showTab(location.hash.slice(1)));

const pc = (x, d = 1) => (x == null || isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`);
const card = (title, body, extra = "") => `<section class="card"><div class="card-head"><h2>${title}</h2>${extra}</div><div class="body">${body}</div></section>`;

// ---------- risk & volatility ----------
const REGIME_TEXT = {
  calm: ["Calm", "up", "Moves are smaller than usual. Option sellers face less risk; tight stops get hit less often."],
  choppy: ["Choppy", "warn", "Moves are bigger than usual. Use wider stops and smaller size."],
  stress: ["Stress", "down", "Rare, violent markets. Defined-risk trades only, and small size."],
};

// End-of-day data (NSE's daily files, downloaded by the 7:30 PM job) says which close it is from and when it
// updates next, so a date that is not today reads as expected rather than out of date.
function freshLine(f) {
  if (!f) return "";
  if (f.stale) return `<div class="fresh stale">⚠ End-of-day data from <b>${esc(f.as_of_label || "—")}</b>, but the latest close is ${esc(f.expected)}:
    the nightly update (7:30 PM) seems to have missed it. Check the Research tab's nightly job, or run <code>scripts/quant_daily_update.py</code>.</div>`;
  return `<div class="fresh">End-of-day data from <b>${esc(f.as_of_label)}</b> — the latest NSE close${f.today_is_session ? " (today's data comes after the market closes)" : ""}.
    Next update <b>${esc(f.next_update)}</b>. Live prices are on the Plan and Today tabs.</div>`;
}

async function loadRisk() {
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

// ---------- options: measured costs ----------
async function loadCosts() {
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

// ---------- market map ----------
function loadMap() {
  if ($("#mapBody").dataset.ready) return;
  $("#mapBody").dataset.ready = "1";
  $("#mapBody").innerHTML = `<iframe class="map-frame" src="/market-map" title="India Market Map"></iframe>`;
}

// ---------- research ----------
async function loadResearch() {
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

// ---------- my trades (journal) ----------
S.jrHorizon = "all";
async function loadJournalFiles(select) {
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
$("#jrUpload").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const n = $("#jrNotice"); n.hidden = true;
  try {
    const r = await api("/api/journal/upload?name=" + encodeURIComponent(f.name), { method: "POST", body: await f.arrayBuffer() });
    await loadJournalFiles(r.name);
  } catch (err) { n.hidden = false; n.textContent = err.message; }
  e.target.value = "";
};
const money = (x) => (x == null ? "—" : (x < 0 ? "−" : "") + "₹" + fmt0(Math.abs(x)));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const COLS = [["trades", "Trades", (x) => x], ["win_rate", "Won", (x) => pc(x, 0)], ["avg_win", "Avg win", money],
  ["avg_loss", "Avg loss", money], ["net_per_trade", "Per trade", money], ["total_net", "Total", money],
  ["charges_share_of_gross_profit", "Charges ÷ profit", (x) => pc(x, 0)]];
function jrTable(rows) {
  if (!rows.length) return `<p class="muted small">No trades in this group.</p>`;
  return `<div class="oc-scroll"><table class="t"><thead><tr><th></th>${COLS.map((c) => `<th>${c[1]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
    `<tr><td><b>${esc(r.group === "all" ? "All trades" : cap(r.group))}</b></td>${COLS.map(([k, , f]) => `<td class="num ${k.includes("net") ? cls(r[k]) : ""}">${f(r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
async function loadJournal() {
  const name = $("#jrFile").value; if (!name) return;
  const n = $("#jrNotice"); n.hidden = true;
  $("#jrBody").innerHTML = `<div class="loading"><span class="spinner"></span>Reading your trades…</div>`;
  let r;
  try { r = await api(`/api/journal?name=${encodeURIComponent(name)}&horizon=${S.jrHorizon}`); }
  catch (e) { $("#jrBody").innerHTML = ""; n.hidden = false; n.textContent = e.message; return; }
  const o = r.sections["Overall"][0];
  const few = r.round_trips < 30 ? `<div class="notice">Only ${r.round_trips} completed trades: treat this as a first look, not proof. 30–50 trades start to mean something.</div>` : "";
  let html = card("Summary", `<p>${r.trades} orders from ${esc(r.from)} to ${esc(r.to)} → <b>${r.round_trips} completed trades</b>${r.still_open ? `, ${r.still_open} still open (not counted)` : ""}. Charges ${esc(r.charges)}.</p>
    ${o ? `<div class="stats"><div class="stat"><span>Won</span><b class="num">${pc(o.win_rate, 0)}</b></div><div class="stat"><span>Average per trade</span><b class="num ${cls(o.net_per_trade)}">${money(o.net_per_trade)}</b></div>
    <div class="stat"><span>Total</span><b class="num ${cls(o.total_net)}">${money(o.total_net)}</b></div><div class="stat"><span>Charges paid</span><b class="num">${money(o.charges)}</b></div></div>` : ""}${few}`);
  if (r.horizon === "all") html += card("By how long you held", jrTable(r.sections["By holding period"]));
  for (const [title, key] of [["Buying vs selling", "By style"], ["By instrument", "By instrument"], ["By stock / index", "By underlying"],
    ["By time you entered", "By hour of entry"], ["By day of week", "By day of week"], ["By your reason", "By your reason"]]) {
    if (r.sections[key]?.length) html += card(title, jrTable(r.sections[key]));
  }
  $("#jrBody").innerHTML = html;
}

// ---------- plan (morning plan + live call) ----------
const NAMES = { NIFTY: "NIFTY 50", BANKNIFTY: "NIFTY BANK" };
S.morning = null; S.live = {};

// Preview: ?at=2026-10-23T10:30 shows the Plan tab as at that moment, with that day's saved plan.
const PREVIEW_AT = new URLSearchParams(location.search).get("at");
function istNow() {
  if (PREVIEW_AT) { const [d, t] = PREVIEW_AT.split("T"); return { date: d, mins: toMins(t), hhmm: t + " (preview)" }; }
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  const g = (t) => p.find((x) => x.type === t).value;
  return { date: `${g("year")}-${g("month")}-${g("day")}`, mins: +g("hour") * 60 + +g("minute"), hhmm: `${g("hour")}:${g("minute")}` };
}
const toMins = (hhmm) => +hhmm.slice(0, 2) * 60 + +hhmm.slice(3, 5);
const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);

function phase(sess) {
  const now = istNow();
  if (!sess || sess.date !== now.date) return { key: "stale", text: "Plan is not for today — refresh it." };
  if (!sess.trading) return { key: "closed", text: `Market closed today${sess.holiday ? ` (${sess.holiday.replace("*", "")})` : ""}. Next session: ${sess.next_session}.` };
  const m = now.mins, open = toMins(sess.open), first = toMins(sess.first_signal), close = toMins(sess.close);
  if (m < toMins(sess.pre_open)) return { key: "pre", text: `Before the market. Opens at ${sess.open} — in ${dur(open - m)}. Read the morning view below.` };
  if (m < open) return { key: "preopen", text: `Pre-open auction. Trading starts at ${sess.open} — in ${dur(open - m)}.` };
  if (m < first) return { key: "wait", text: `Market open. The rule waits for the first half hour — trade signal from ${sess.first_signal} (in ${dur(first - m)}).` };
  if (m < close) return { key: "live", text: `Market open — closes at ${sess.close} (in ${dur(close - m)}). Exit intraday trades by 15:15.` };
  return { key: "after", text: `Market closed for today at ${sess.close}. Next session: ${sess.next_session}.` };
}

function renderSession() {
  const s = S.morning?.session; if (!s) return;
  const ph = phase(s);
  const steps = [["Pre-open", s.pre_open], ["Open", s.open], ["Signal from", s.first_signal], ["Exit intraday by", "15:15"],
    ["Close", s.close + (s.index_derivatives_close !== s.close ? ` (index F&O ${s.index_derivatives_close})` : "")]];
  $("#sessionBar").innerHTML = `<div class="body"><div class="session-top"><div><div class="ask">${esc(s.weekday)} ${esc(s.date)}</div>
      <div class="phase ${ph.key}">${esc(ph.text)}</div></div><div class="clock num">${istNow().hhmm} IST</div></div>
    ${s.trading ? `<div class="timeline">${steps.map(([k, v]) => `<div><span>${k}</span><b class="num">${esc(v)}</b></div>`).join("")}</div>` : ""}</div>`;
}

S.extraCtx = {};
function planEntries() {
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

// One lot (or one share): what it costs and what it loses at the stop. You choose how many.
function perLot(p) {
  const leg = p.option, s = p.signal;
  if (!leg) return { perShare: Math.abs(s.entry - s.stop_loss) };
  const perUnit = leg.premium && leg.stop_loss ? leg.premium - leg.stop_loss : leg.move_sl;   // premium lost at the stop
  return { loss: perUnit * leg.lot, approx: !leg.premium, cost: leg.premium ? leg.premium * leg.lot : null };
}

function callHtml(sym, p, ph) {
  if (ph.key === "closed" || ph.key === "after" || ph.key === "stale") return `<div class="call idle"><b>No trading now.</b> ${esc(ph.text)}</div>`;
  if (ph.key === "pre" || ph.key === "preopen" || ph.key === "wait")
    return `<div class="call idle"><b>Wait.</b> The trade decision is made live from ${esc(S.morning.session.first_signal)}, using this morning's view and the first half hour of trading. This card updates by itself.</div>`;
  if (!p) return `<div class="call idle"><span class="spinner"></span> Checking the live signal…</div>`;
  const v = p.verdict, s = p.signal, leg = p.option;
  if (!(v.safe && s.side !== "WAIT")) {
    return `<div class="call stop"><b>No trade right now.</b> ${esc(v.blockers[0] || "No clean setup.")}
      <div class="small muted">Checked again every 15 seconds until 15:15. Not trading is a position too.</div></div>`;
  }
  const up = s.side === "BUY", z = perLot(p);
  if (!leg) {
    const sz = `<div class="small">Each share loses about <b>${rupee(z.perShare)}</b> at the stop — pick the quantity so the total is a loss you accept.</div>`;
    return `<div class="call ${up ? "go-up" : "go-down"}"><div class="ask">Take this trade</div>
      <div class="what"><b>${up ? "Buy" : "Short-sell"} ${esc(nameOf(sym))}</b> · intraday, exit by 15:15</div>
      <div class="levels"><div class="lv"><span>Entry</span><b>${fmt(s.entry)}</b></div><div class="lv"><span>Stop loss</span><b class="down">${fmt(s.stop_loss)}</b></div>
        <div class="lv"><span>Target</span><b class="up">${fmt(s.target)}</b></div></div>${sz}
      <div class="small muted">Won ${v.win_rate}% of ${v.trades} similar trades recently (avg ${sign(v.avg_r)}${v.avg_r}× risk after costs). One trade a day. Not a validated edge — use your judgment.</div></div>`;
  }
  const sizing = `<div class="levels"><div class="lv"><span>One lot</span><b>${leg.lot}</b><small>units</small></div>
        <div class="lv"><span>Loss at stop, a lot</span><b class="down">${z.approx ? "≈ " : ""}${money(z.loss)}</b><small>before charges</small></div>
        <div class="lv"><span>Money needed, a lot</span><b>${z.cost != null ? money(z.cost) : "premium × lot"}</b><small>option premium paid</small></div></div>`;
  return `<div class="call ${up ? "go-up" : "go-down"}"><div class="ask">Take this trade</div>
    <div class="what"><b>Buy ${esc(NAMES[sym] || nameOf(sym))} ${fmt0(leg.strike)} ${leg.kind}</b>${leg.expiry ? ` · expiry ${esc(leg.expiry)}` : " · nearest weekly expiry"}</div>
    <div class="levels"><div class="lv"><span>Entry (index)</span><b>${fmt(s.entry)}</b></div><div class="lv"><span>Stop loss (index)</span><b class="down">${fmt(s.stop_loss)}</b></div>
      <div class="lv"><span>Target (index)</span><b class="up">${fmt(s.target)}</b></div>${leg.premium ? `<div class="lv"><span>Premium now</span><b>${rupee(leg.premium)}</b><small>stop ${rupee(leg.stop_loss)} · target ${rupee(leg.target)}</small></div>` : ""}</div>
    ${sizing}
    <div class="small muted">Won ${v.win_rate}% of ${v.trades} similar trades recently (avg ${sign(v.avg_r)}${v.avg_r}× risk after costs). Exit by 15:15. One trade a day. Not a validated edge — use your judgment.</div></div>`;
}

function plainPcr(x) { return x > 1.2 ? "many more puts than calls open (heavy hedging)" : x < 0.8 ? "more calls than puts open" : "calls and puts roughly balanced"; }
function morningHtml(sym, e) {
  const c = e.context, ai = e.ai, em = c.expected_move, t = c.trend, g = c.regime;
  if (c.error) return `<div class="notice">Could not build the view for ${esc(nameOf(sym))}: ${esc(c.error)}</div>`;
  const aiBlock = e.extra ? `<p class="small muted">The 8:30 AM AI view covers NIFTY 50 and NIFTY BANK. For ${esc(nameOf(sym))}, run it on the AI Analysis tab.</p>`
    : !ai ? `<p class="small muted">AI view not built yet (runs at 8:30 AM on trading days).</p>`
    : ai.error ? `<div class="notice">AI view failed: ${esc(ai.error)}</div>`
    : `<div class="ai-line"><span class="badge ${/Buy|Overweight/.test(ai.rating) ? "up" : /Sell|Underweight/.test(ai.rating) ? "down" : "warn"}">${esc(ai.rating)}</span>
        <span class="small muted">AI agents' view from news, sentiment and the bull/bear debate (${ai.minutes} min)</span></div>
       <details class="ai-more"><summary>Read the AI's reasoning</summary><div class="report">${DOMPurify.sanitize(marked.parse(ai.decision || ""))}</div>
         ${ai.news ? `<h3>News</h3><div class="report">${DOMPurify.sanitize(marked.parse(ai.news))}</div>` : ""}</details>`;
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

function renderPlanCards() {
  const m = S.morning; if (!m) return;
  const ph = phase(m.session);
  const entries = planEntries();
  if (!entries) { $("#planBody").dataset.key = ""; $("#planBody").innerHTML = `<div class="loading"><span class="spinner"></span>Building the plan for ${esc(nameOf(S.sym))}…</div>`; return; }
  // The card is built once per plan and instrument (its chart lives in it); later updates only refill the slots.
  const key = m.built_at + "|" + S.sym + "|" + (entries[0][1].extra ? "x" : "");
  if ($("#planBody").dataset.key !== key) {
    $("#planBody").dataset.key = key;
    $("#planBody").innerHTML = entries.map(([sym, e]) => `<section class="card plan-card" data-sym="${esc(sym)}">
      <div class="card-head"><h2>${esc(NAMES[sym] || nameOf(sym))}</h2>${e.context.trend ? `<span class="badge ${e.context.trend.tone}">${esc(e.context.trend.label)}</span>` : ""}</div>
      <div class="body"><h3 class="sub-h">Today's call</h3><div class="call-slot"></div>
        <h3 class="sub-h">Price chart <span class="small muted chart-note"></span></h3>
        <div class="pc-bar"></div><div class="pc-info small"><span class="pc-readout"></span><span class="pc-hint"></span></div>
        <div class="pc-wrap"><div class="plan-chart"></div></div>
        <h3 class="sub-h">AI strategist</h3><div class="strat-slot"></div>
        <h3 class="sub-h">Option chain <span class="small muted chain-note"></span></h3><div class="chain-slot"></div>
        <h3 class="sub-h">Morning view</h3><div class="morning-slot"></div></div></section>`).join("");
    planCharts.clear();
    loadPlanCharts();
    for (const [sym] of entries) { renderStrat(sym); loadNseChain(sym).then(() => loadRank(sym)); }
  }
  for (const [sym, e] of entries) {
    const card = $(`.plan-card[data-sym="${sym}"]`);
    $(".call-slot", card).innerHTML = callHtml(sym, S.live[sym], ph);
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

// One live chart per index in the Plan tab: 5-minute candles of the last sessions. The viewer turns layers on and
// off (averages, trade, expected range, option walls, day levels, swings, crossovers), draws their own lines (kept
// per instrument in this browser) and reads O / H / L / C under the cursor. Only the last price, the target and the
// stop take an axis label; every other level is labelled inside the chart, nudged apart so labels never overlap.
const planCharts = new Map();
const PC_LAYERS = [["ema", "Averages", "--ema9"], ["trade", "Trade", "--up"], ["range", "Expected range", "--muted"],
  ["walls", "Option walls", "--warn"], ["day", "Day levels", "--day"], ["swings", "Swings", "--muted"], ["cross", "Crossovers", "--ema21"]];
const PC_SPANS = [["1", "Today"], ["2", "2D"], ["5", "5D"], ["all", "All"]];
const PC_RIGHT = 14;                                    // empty bars right of the last candle, room for the trade zones
const PC_DASH = { solid: [], dash: [5, 4], dot: [1.5, 3] };
const pcPrefs = (() => { try { return JSON.parse(store("chartPrefs")) || {}; } catch { return {}; } })();
const pcOn = (k) => pcPrefs.layers?.[k] !== false;
const pcSave = () => store("chartPrefs", JSON.stringify(pcPrefs));
function pcDrawings(sym, list) {
  if (list !== undefined) return store("draw." + sym, JSON.stringify(list));
  try { return JSON.parse(store("draw." + sym)) || []; } catch { return []; }
}
const hexA = (c, a) => (/^#[0-9a-f]{6}$/i.test(c) ? c + Math.round(a * 255).toString(16).padStart(2, "0") : c);
const chartTime = (b) => b.time + IST_OFFSET;

// Bands and day dividers under the candles; levels, their labels and the viewer's lines over them.
class PlanOverlay {
  constructor() { this.s = { bands: [], levels: [], days: [], drawings: [], preview: null }; }
  attached({ chart, series, requestUpdate }) { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  set(part) { Object.assign(this.s, part); this.requestUpdate?.(); }
  updateAllViews() {}
  paneViews() {
    return (this.views ||= [
      { zOrder: () => "bottom", renderer: () => ({ draw: (t) => t.useMediaCoordinateSpace((sc) => this.under(sc)) }) },
      { zOrder: () => "top", renderer: () => ({ draw: (t) => t.useMediaCoordinateSpace((sc) => this.over(sc)) }) },
    ]);
  }
  y(p) { return p == null ? null : this.series.priceToCoordinate(p); }
  x(t) { return t == null ? null : this.chart.timeScale().timeToCoordinate(t); }
  under({ context: g, mediaSize: { width: w, height: h } }) {
    g.save();
    const half = this.chart.timeScale().options().barSpacing / 2;
    g.strokeStyle = cssVar("--border"); g.lineWidth = 1; g.setLineDash([3, 4]);
    for (const t of this.s.days) {
      const x = this.x(t); if (x == null) continue;
      g.beginPath(); g.moveTo(Math.round(x - half) + 0.5, 0); g.lineTo(Math.round(x - half) + 0.5, h); g.stroke();
    }
    for (const b of this.s.bands) {
      const y1 = this.y(b.from), y2 = this.y(b.to); if (y1 == null || y2 == null) continue;
      const x0 = b.fromTime != null ? Math.max(0, (this.x(b.fromTime) ?? 0) + half) : 0;
      g.fillStyle = b.color; g.fillRect(x0, Math.min(y1, y2), w - x0, Math.abs(y2 - y1));
    }
    g.restore();
  }
  over({ context: g, mediaSize: { width: w } }) {
    g.save();
    g.font = "600 11px Inter, system-ui, sans-serif"; g.textBaseline = "middle";
    const labels = [], line = (y, color, style, width = 1) => {
      g.strokeStyle = color; g.lineWidth = width; g.setLineDash(PC_DASH[style] || []);
      g.beginPath(); g.moveTo(0, Math.round(y) + 0.5); g.lineTo(w, Math.round(y) + 0.5); g.stroke();
    };
    for (const l of this.s.levels) {
      const y = this.y(l.price); if (y == null) continue;
      line(y, l.color, l.style);
      if (l.label) labels.push({ y, text: l.label, color: l.color });
    }
    const draw = cssVar("--draw");
    for (const d of [...this.s.drawings, this.s.preview].filter(Boolean)) {
      const style = d.preview ? "dash" : "solid";
      if (d.type === "h") {
        const y = this.y(d.p); if (y == null) continue;
        line(y, draw, style, 1.5);
        if (!d.preview) labels.push({ y, text: fmt(d.p), color: draw });
      } else if (d.type === "t") {
        const xa = this.x(d.a.t), ya = this.y(d.a.p), xb = this.x(d.b.t), yb = this.y(d.b.p);
        if ([xa, ya, xb, yb].some((v) => v == null)) continue;
        g.strokeStyle = draw; g.lineWidth = 1.5; g.setLineDash(PC_DASH[style]);
        g.beginPath(); g.moveTo(xa, ya); g.lineTo(xb, yb); g.stroke();
        g.setLineDash([]); g.fillStyle = draw;
        for (const [x, y] of [[xa, ya], [xb, yb]]) { g.beginPath(); g.arc(x, y, 3, 0, 2 * Math.PI); g.fill(); }
      }
    }
    g.setLineDash([]);
    labels.sort((a, b) => a.y - b.y);
    let last = -1e9;
    const bg = cssVar("--panel");
    for (const l of labels) {
      const y = Math.max(l.y, last + 16); last = y;
      const tw = g.measureText(l.text).width;
      g.fillStyle = bg; g.globalAlpha = 0.92;
      g.beginPath(); g.roundRect(4, y - 8, tw + 12, 16, 4); g.fill();
      g.globalAlpha = 1; g.strokeStyle = l.color; g.lineWidth = 1; g.stroke();
      g.fillStyle = l.color; g.fillText(l.text, 10, y + 0.5);
    }
    g.restore();
  }
}

function planChart(sym) {
  if (planCharts.has(sym)) return planCharts.get(sym);
  const card = $(`.plan-card[data-sym="${sym}"]`), el = card && $(".plan-chart", card); if (!el) return null;
  const ch = LightweightCharts.createChart(el, { autoSize: true, layout: { background: { type: "solid", color: "transparent" }, textColor: cssVar("--muted"),
      fontFamily: "Inter, system-ui, sans-serif" }, grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--grid") } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: PC_RIGHT }, crosshair: { mode: 0 } });
  const up = cssVar("--up"), down = cssVar("--down");
  const c = { ch, card, candles: ch.addCandlestickSeries({ borderVisible: false, upColor: up, downColor: down, wickUpColor: up, wickDownColor: down }),
    e9: ch.addLineSeries({ ...lineOpts, color: cssVar("--ema9") }), e21: ch.addLineSeries({ ...lineOpts, color: cssVar("--ema21") }),
    overlay: new PlanOverlay(), lines: [], keep: [], bars: [], fitted: false, tool: null, pending: null, hover: false };
  c.candles.attachPrimitive(c.overlay);
  // The price scale always takes in the trade's entry, target and stop, so they never sit off the chart.
  c.candles.applyOptions({ autoscaleInfoProvider: (base) => {
    const r = base(); if (!r || !c.keep.length) return r;
    return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...c.keep), maxValue: Math.max(r.priceRange.maxValue, ...c.keep) } };
  } });
  planCharts.set(sym, c);
  ch.subscribeClick((p) => pcClick(sym, p));
  ch.subscribeCrosshairMove((p) => pcMove(sym, p));
  pcToolbar(sym);
  return c;
}

function pcToolbar(sym) {
  const c = planCharts.get(sym), bar = $(".pc-bar", c.card);
  bar.innerHTML = `<div class="pc-group">${PC_LAYERS.map(([k, name, col]) =>
      `<button class="pc-chip" data-layer="${k}" title="Show / hide ${name.toLowerCase()}"><i style="background:var(${col})"></i>${name}</button>`).join("")}</div>
    <div class="pc-group">${PC_SPANS.map(([k, name]) => `<button class="pc-btn" data-span="${k}">${name}</button>`).join("")}
      <span style="width:6px"></span>
      <button class="pc-btn" data-tool="h" title="Horizontal line: click a price">— Line</button>
      <button class="pc-btn" data-tool="t" title="Trend line: click two points">╱ Trend</button>
      <button class="pc-btn" data-act="undo" title="Remove your last line">Undo</button>
      <button class="pc-btn" data-act="clear" title="Remove all your lines on this chart">Clear</button></div>`;
  bar.onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const { layer, span, tool, act } = b.dataset;
    if (layer) {
      pcPrefs.layers = { ...pcPrefs.layers, [layer]: !pcOn(layer) }; pcSave();
      planCharts.forEach((_, s) => { pcSyncBar(s); drawPlanChartLines(s); });
    } else if (span) {
      pcPrefs.span = span; pcSave();
      planCharts.forEach((_, s) => { pcSyncBar(s); pcSpan(s); });
    } else if (tool) {
      pcTool(sym, c.tool === tool ? null : tool);
    } else if (act) {
      const d = pcDrawings(sym);
      if (act === "undo") d.pop(); else if (d.length && confirm("Remove all your lines on this chart?")) d.length = 0;
      pcDrawings(sym, d); pcTool(sym, null); drawPlanChartLines(sym);
    }
  };
  pcSyncBar(sym);
}

function pcSyncBar(sym) {
  const c = planCharts.get(sym);
  c.card.querySelectorAll("[data-layer]").forEach((b) => b.classList.toggle("on", pcOn(b.dataset.layer)));
  c.card.querySelectorAll("[data-span]").forEach((b) => b.classList.toggle("on", b.dataset.span === (pcPrefs.span || "2")));
  c.card.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === c.tool));
}

function pcTool(sym, tool) {
  const c = planCharts.get(sym); if (!c) return;
  c.tool = tool; c.pending = null; c.overlay.set({ preview: null });
  $(".pc-wrap", c.card).classList.toggle("drawing", !!tool);
  $(".pc-hint", c.card).textContent = tool === "h" ? "Click a price to place the line · Esc to cancel"
    : tool === "t" ? "Click the first point · Esc to cancel" : "";
  pcSyncBar(sym);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") planCharts.forEach((c, s) => c.tool && pcTool(s, null)); });

// The candle under x (the last one when x is right of the data): trend points sit on candle times.
function pcTimeAt(c, x) {
  const n = c.bars.length, i = c.ch.timeScale().coordinateToLogical(x);
  return n && i != null ? chartTime(c.bars[Math.max(0, Math.min(n - 1, Math.round(i)))]) : null;
}

function pcClick(sym, p) {
  const c = planCharts.get(sym); if (!c?.tool || !p.point) return;
  const raw = c.candles.coordinateToPrice(p.point.y); if (raw == null) return;
  const price = Math.round(raw * 20) / 20, d = pcDrawings(sym);
  const t = pcTimeAt(c, p.point.x);
  if (c.tool === "h") d.push({ type: "h", p: price });
  else if (t == null) return;
  else if (!c.pending) { c.pending = { t, p: price }; $(".pc-hint", c.card).textContent = "Click the second point · Esc to cancel"; return; }
  else d.push({ type: "t", a: c.pending, b: { t, p: price } });
  pcDrawings(sym, d); pcTool(sym, null); drawPlanChartLines(sym);
}

function pcMove(sym, p) {
  const c = planCharts.get(sym); if (!c) return;
  const bar = p.time != null && p.seriesData?.get(c.candles);
  c.hover = !!bar;
  pcReadout(sym, bar || null, bar ? p.seriesData.get(c.e9)?.value : null, bar ? p.seriesData.get(c.e21)?.value : null, p.time);
  if (!c.tool || !p.point) return;
  const price = c.candles.coordinateToPrice(p.point.y); if (price == null) return;
  if (c.tool === "h") c.overlay.set({ preview: { type: "h", p: price, preview: true } });
  else if (c.pending) c.overlay.set({ preview: { type: "t", a: c.pending, b: { t: pcTimeAt(c, p.point.x), p: price }, preview: true } });
}

// O / H / L / C, change and the averages of the candle under the cursor (the last candle otherwise).
function pcReadout(sym, bar, e9, e21, time) {
  const c = planCharts.get(sym), el = c && $(".pc-readout", c.card); if (!el) return;
  if (!bar) {
    const n = c.bars.length; if (!n) { el.innerHTML = ""; return; }
    const closes = c.bars.map((x) => x.close);
    bar = c.bars[n - 1]; time = chartTime(bar); e9 = ema(closes, 9)[n - 1]; e21 = ema(closes, 21)[n - 1];
  }
  const ch = bar.open ? (bar.close - bar.open) / bar.open * 100 : 0;
  const when = new Date(time * 1000).toLocaleString("en-IN", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  el.innerHTML = `${esc(when)} &nbsp; O <b>${fmt(bar.open)}</b> H <b>${fmt(bar.high)}</b> L <b>${fmt(bar.low)}</b> C <b>${fmt(bar.close)}</b>
    <span class="${cls(ch)}">${pct(ch)}</span>${pcOn("ema") && e9 != null ? ` &nbsp; <span style="color:var(--ema9)">EMA 9 ${fmt(e9)}</span> &nbsp; <span style="color:var(--ema21)">EMA 21 ${fmt(e21)}</span>` : ""}`;
}

function pcDayStarts(bars) {
  const out = []; let prev;
  bars.forEach((b, i) => { const d = Math.floor(chartTime(b) / 86400); if (d !== prev) { out.push(i); prev = d; } });
  return out;
}

function pcSpan(sym) {
  const c = planCharts.get(sym), n = c?.bars.length; if (!n) return;
  const span = pcPrefs.span || "2", starts = pcDayStarts(c.bars);
  const from = span === "all" ? 0 : starts[Math.max(0, starts.length - Number(span))];
  c.ch.timeScale().setVisibleLogicalRange({ from: from - 1, to: n - 1 + PC_RIGHT });
}

// Previous session's high / low / close and today's open, from the 5-minute bars.
function pcDayLevels(bars) {
  const st = pcDayStarts(bars); if (st.length < 2) return null;
  const prev = bars.slice(st.at(-2), st.at(-1));
  return { high: Math.max(...prev.map((b) => b.high)), low: Math.min(...prev.map((b) => b.low)), close: prev.at(-1).close, open: bars[st.at(-1)].open };
}

// A swing high / low is the highest high / lowest low of the k candles either side of it (12 = an hour each side).
function pcSwings(bars, k = 12) {
  const out = [];
  for (let i = k; i < bars.length - k; i++) {
    const w = bars.slice(i - k, i + k + 1);
    if (bars[i].high === Math.max(...w.map((b) => b.high))) out.push({ i, high: true });
    else if (bars[i].low === Math.min(...w.map((b) => b.low))) out.push({ i, high: false });
  }
  return out;
}

async function loadPlanCharts() {
  for (const [sym] of planEntries() || []) {
    const c = planChart(sym); if (!c) continue;
    try {
      const r = await api(`/api/candles/${sym}?tf=5m&limit=300`);
      const closes = r.bars.map((b) => b.close), e9 = ema(closes, 9), e21 = ema(closes, 21);
      c.bars = r.bars;
      c.candles.setData(r.bars.map((b) => ({ time: chartTime(b), open: b.open, high: b.high, low: b.low, close: b.close })));
      c.e9.setData(r.bars.map((b, i) => ({ time: chartTime(b), value: e9[i] })));
      c.e21.setData(r.bars.map((b, i) => ({ time: chartTime(b), value: e21[i] })));
      if (!c.fitted) { pcSpan(sym); c.fitted = true; }
      const note = $(".chart-note", c.card); if (note) note.textContent = `5-minute candles · ${srcLabel(r.source)}`;
      if (!c.hover) pcReadout(sym, null);
      drawPlanChartLines(sym);
    } catch (e) { console.warn(e); }
  }
}

function drawPlanChartLines(sym) {
  const c = planCharts.get(sym); if (!c) return;
  c.lines.forEach((l) => c.candles.removePriceLine(l)); c.lines = []; c.keep = [];
  const col = { up: cssVar("--up"), down: cssVar("--down"), text: cssVar("--text"), muted: cssVar("--muted"), warn: cssVar("--warn"), day: cssVar("--day") };
  const levels = [], bands = [], bars = c.bars, lastT = bars.length ? chartTime(bars.at(-1)) : null;
  const level = (price, color, label, style = "dash") => price && levels.push({ price, color, label, style });
  const axis = (price, color, title) => price && c.lines.push(c.candles.createPriceLine({ price, color, lineWidth: 1.5, lineStyle: 0, axisLabelVisible: true, title }));
  // A trade drawn like a position: a green zone from the entry to the target and a red one to the stop, right of the last candle.
  const position = (entry, target, stop) => {
    c.keep.push(...[entry, target, stop].filter(Boolean));
    if (entry && target) bands.push({ from: entry, to: target, color: hexA(col.up, 0.14), fromTime: lastT });
    if (entry && stop) bands.push({ from: entry, to: stop, color: hexA(col.down, 0.13), fromTime: lastT });
  };
  c.e9.applyOptions({ visible: pcOn("ema") }); c.e21.applyOptions({ visible: pcOn("ema") });

  const em = (S.morning?.indices?.[sym] || S.extraCtx[sym])?.context?.expected_move;
  if (pcOn("range") && em && S.morning.session.trading) {
    bands.push({ from: em.day_low, to: em.day_high, color: hexA(col.muted, 0.06) });
    level(em.day_high, col.muted, `Expected high ${fmt0(em.day_high)}`); level(em.day_low, col.muted, `Expected low ${fmt0(em.day_low)}`);
  }
  const oc = S.nse[sym]?.summary;
  if (pcOn("walls") && oc) {
    level(oc.resistance, col.warn, `Call wall ${fmt0(oc.resistance)}`, "dot"); level(oc.support, col.warn, `Put wall ${fmt0(oc.support)}`, "dot");
  }
  const dl = pcOn("day") && pcDayLevels(bars);
  if (dl) {
    level(dl.high, col.day, `Prev high ${fmt0(dl.high)}`, "dot"); level(dl.low, col.day, `Prev low ${fmt0(dl.low)}`, "dot");
    level(dl.close, col.day, `Prev close ${fmt0(dl.close)}`); level(dl.open, col.day, `Open ${fmt0(dl.open)}`);
  }
  if (pcOn("trade")) {
    const p = S.live[sym];
    if (p?.verdict?.safe && p.signal?.side !== "WAIT") {
      level(p.signal.entry, col.text, `Entry ${fmt0(p.signal.entry)}`, "solid");
      axis(p.signal.target, col.up, "Target"); axis(p.signal.stop_loss, col.down, "Stop");
      position(p.signal.entry, p.signal.target, p.signal.stop_loss);
    }
    const r = curRes(sym), a = r?.plan;
    if (a && a.strategy !== "no_trade") {
      const who = r.source === "pulse" ? `#${r.rank}` : "AI", lo = a.underlying_entry_low, hi = a.underlying_entry_high;
      if (lo && hi) {
        bands.push({ from: lo, to: hi, color: hexA(col.text, 0.07) });
        level(hi, col.text, `${who} entry ${fmt0(lo)} – ${fmt0(hi)}`, "dot"); level(lo, col.text, null, "dot");
      } else level(lo || hi, col.text, `${who} entry ${fmt0(lo || hi)}`, "dot");
      position(lo && hi ? (lo + hi) / 2 : lo || hi, a.underlying_target, a.underlying_stop);
      axis(a.underlying_target, col.up, `${who} target`); axis(a.underlying_stop, col.down, `${who} stop`);
      const t = S.ticket[sym], leg = t && r?.priced?.legs[t.i];
      if (leg) level(leg.strike, cssVar("--ema9"), `${leg.action} ${fmt0(leg.strike)} ${leg.type} strike`, "dot");
    }
  }

  const marks = [];
  if (pcOn("swings")) for (const s of pcSwings(bars)) {
    marks.push({ time: chartTime(bars[s.i]), position: s.high ? "aboveBar" : "belowBar", shape: "circle", color: col.muted, size: 0.4 });
  }
  if (pcOn("cross") && bars.length > 22) {
    const closes = bars.map((b) => b.close), f = ema(closes, 9), sl = ema(closes, 21);
    for (let i = 22; i < bars.length; i++) {
      const was = f[i - 1] - sl[i - 1], now = f[i] - sl[i];
      if (was <= 0 && now > 0) marks.push({ time: chartTime(bars[i]), position: "belowBar", shape: "arrowUp", color: col.up, size: 0.8 });
      if (was >= 0 && now < 0) marks.push({ time: chartTime(bars[i]), position: "aboveBar", shape: "arrowDown", color: col.down, size: 0.8 });
    }
  }
  c.candles.setMarkers(marks.sort((x, y) => x.time - y.time));
  c.overlay.set({ bands, levels, days: pcDayStarts(bars).slice(1).map((i) => chartTime(bars[i])), drawings: pcDrawings(sym) });
}

function renderPlan() { renderSession(); renderPlanCards(); }

async function loadMorning() {
  try { S.morning = await api("/api/morning" + (PREVIEW_AT ? "?date=" + PREVIEW_AT.slice(0, 10) : "")); } catch (e) { $("#planBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  renderPlan(); loadLive();
}
async function loadLive() {
  if (S.morning && phase(S.morning.session).key !== "stale") loadPlanCharts();
  if (!S.morning || !["wait", "live"].includes(phase(S.morning.session).key)) return;
  for (const [sym] of planEntries() || []) {
    try { S.live[sym] = await api("/api/plan/" + encodeURIComponent(sym)); } catch { /* keep the last one */ }
  }
  renderPlanCards();
}

// ---------- Plan tab: NSE option chain and the AI strategist ----------
// The chain comes from NSE (OI in units, as trading apps show it). The AI proposes one defined-risk strategy or
// none; the server checks it and prices it at the bid / ask, per lot.
S.nse = {}; S.nseExp = {}; S.nseView = store("nseView") || "oi"; S.strat = {};
const STRAT_NAMES = { no_trade: "No trade", long_call: "Buy a call", long_put: "Buy a put", bull_call_spread: "Bull call spread",
  bear_put_spread: "Bear put spread", bull_put_spread: "Bull put spread", bear_call_spread: "Bear call spread", iron_condor: "Iron condor" };
const lakh = (x) => (x == null ? "—" : fmtInt(Math.round(x)));
const stratJobs = JSON.parse(store("stratJobs") || "{}");

async function loadNseChain(sym, expiry) {
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

function legsAt(sym) {          // strike|type -> "BUY" / "SELL" from the AI's proposal, to mark them in the chain
  const r = curRes(sym), out = {};
  if (r && !r.rejected && r.expiry === S.nse[sym]?.expiry) (r.plan.legs || []).forEach((l) => (out[l.strike + l.option_type] = l.action));
  return out;
}

function focusLeg(sym) {         // the leg whose ticket is open, if it is on the chain shown
  const t = S.ticket[sym], r = curRes(sym);
  return t && r?.priced && r.expiry === S.nse[sym]?.expiry ? r.priced.legs[t.i] : null;
}

// How old NSE's snapshot is, e.g. " (52 s ago)"; NSE stamps "26-Oct-2026 11:44:29" in IST.
function nseAge(ts) {
  const m = /(\d{2}):(\d{2}):(\d{2})$/.exec(ts || ""); if (!m || PREVIEW_AT) return "";
  const now = istNow(), secs = now.mins * 60 + new Date().getSeconds() - (+m[1] * 3600 + +m[2] * 60 + +m[3]);
  return secs >= 0 && secs < 3600 ? ` (${secs < 90 ? secs + " s" : Math.round(secs / 60) + " min"} ago)` : "";
}

function renderNseChain(sym) {
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
  slot.querySelectorAll("[data-exp]").forEach((b) => (b.onclick = () => loadNseChain(sym, b.dataset.exp).then(() => loadRank(sym))));
  slot.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => { S.nseView = b.dataset.view; store("nseView", S.nseView); renderNseChain(sym); }));
  $(".chain-refresh", slot).onclick = () => loadNseChain(sym);
  const sc = $(".plan-oc", slot), atm = $("tr.spot-row", sc) || $("tr.atm", sc);
  if (atm && slot.dataset.centered !== c.expiry) { sc.scrollTop = atm.offsetTop - sc.clientHeight / 2; slot.dataset.centered = c.expiry; }
}

function renderStrat(sym) {
  const slot = $(`.plan-card[data-sym="${sym}"] .strat-slot`); if (!slot) return;
  const st = S.strat[sym] || {};
  const ask = `<div class="strat-ask"><button class="btn primary strat-go" ${st.running ? "disabled" : ""}>${st.running ? "Analysing…" : st.result ? "Ask again" : `Analyse ${esc(NAMES[sym] || nameOf(sym))} with AI`}</button>
    <span class="small muted">${st.running ? `<span class="spinner"></span> Reading the chart, trend, volatility, option chain and news view (about a minute) — started ${esc(st.started || "")}`
      : `Uses expiry <b>${esc(S.nseExp[sym] || "nearest")}</b> (pick another in the chain below). Figures are per lot; you choose how many.`}</span></div>`;
  const v = S.view[sym], cand = typeof v === "number" ? S.rank[sym]?.data?.candidates?.[v] : null;
  const detail = cand ? stratHtml(cand, sym) : st.error ? `<div class="notice">${esc(st.error)}</div>` : st.result ? stratHtml(st.result, sym) : "";
  slot.innerHTML = rankHtml(sym) + `<h4 class="mini-h">Second opinion from the AI</h4>` + ask
    + (cand && st.result ? `<div class="small"><a href="#" class="show-ai">Show the AI's suggestion instead</a></div>` : "") + detail;
  slot.querySelectorAll("[data-rank]").forEach((r) => (r.onclick = () => { S.view[sym] = +r.dataset.rank; S.ticket[sym] = null; refreshStrat(sym); }));
  if ($(".show-ai", slot)) $(".show-ai", slot).onclick = (e) => { e.preventDefault(); S.view[sym] = "ai"; S.ticket[sym] = null; refreshStrat(sym); };
  if ($(".rank-refresh", slot)) $(".rank-refresh", slot).onclick = () => loadRank(sym);
  $(".strat-go", slot).onclick = () => startStrat(sym);
  slot.querySelectorAll("[data-leg]").forEach((b) => (b.onclick = () => openTicket(sym, +b.dataset.leg)));
  if ($(".take-trade", slot)) $(".take-trade", slot).onclick = () => takeTrade(sym);
  if (S.ticket[sym]) renderTicket(sym);
}

async function startStrat(sym) {
  S.strat[sym] = { running: true, started: istNow().hhmm.slice(0, 5) }; S.view[sym] = "ai"; renderStrat(sym);
  try {
    const { job } = await api("/api/strategy", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, expiry: S.nseExp[sym] || null }) });
    stratJobs[sym] = job; store("stratJobs", JSON.stringify(stratJobs));
    pollStrat(sym, job);
  } catch (e) { S.strat[sym] = { error: e.message }; renderStrat(sym); }
}

async function pollStrat(sym, job) {
  try {
    const j = await api("/api/strategy/" + job);
    if (j.status === "running") { S.strat[sym] = { running: true, started: j.started }; renderStrat(sym); setTimeout(() => pollStrat(sym, job), 3000); return; }
    S.strat[sym] = j.status === "done" ? { result: j.result } : { error: j.error };
    S.ticket[sym] = null; S.view[sym] = "ai";
  } catch { delete stratJobs[sym]; store("stratJobs", JSON.stringify(stratJobs)); S.strat[sym] = {}; }   // server restarted
  renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym);
}
Object.entries(stratJobs).forEach(([sym, job]) => pollStrat(sym, job));   // a result survives a page reload

// How each leg goes into Dhan, so every number labelled Target / Stop loss can be typed into a Super order
// (Dhan: a BUY needs target > entry > stop, a SELL needs target < entry < stop).
//  super    — single option, or the SELL leg of a credit spread: Super order with target + stop loss
//  hedge    — the BUY leg of a credit spread: plain Limit, no target / stop; close it right after the SELL leg exits
//  together — debit spread / iron condor legs: Limit orders, closed together by hand at the index levels
//             (a stop on the bought leg alone could leave the sold leg naked)
const CREDIT = ["bear_call_spread", "bull_put_spread"];
function legRole(strategy, legs, l) {
  if (legs.length === 1) return "super";
  if (CREDIT.includes(strategy)) return l.action === "SELL" ? "super" : "hedge";
  return "together";
}
function legLevelsOk(l, tgt, stop) {          // the Super-order rule; anything else is not enterable in Dhan
  return tgt != null && stop != null && (l.action === "BUY" ? tgt > l.price && stop < l.price : tgt < l.price && stop > l.price);
}
const ROLE_NOTE = {
  super: (l) => l.action === "BUY" ? "Super order: target above the entry, stop loss below." : "Super order on the sold leg: target below the entry, stop loss above (you gain when its price falls).",
  hedge: () => "Protection only — a plain Limit order, no target or stop loss. Place it first; sell it right after the SELL leg's target or stop fills.",
  together: () => "Limit order, no target / stop loss in Dhan. Close both legs by hand when NIFTY reaches its target or stop (grey = expected price then).",
};

// The AI's trade, explained the way a broker app shows an order: each leg is a contract with its own entry,
// target and stop-loss premium (what to type into Dhan); clicking a leg opens its ticket (premium chart, depth,
// how to place it) and marks it on the chain and the index chart.
S.ticket = {};
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
function contractName(sym, expiry, l) {
  const [d, m] = String(expiry).split("-");
  return `${sym} ${+d} ${String(m).toUpperCase().slice(0, 3)} ${fmt0(l.strike).replace(/,/g, "")} ${l.type === "CE" ? "CALL" : "PUT"}`;
}
const pnl = (x) => (x == null ? "—" : `<span class="${cls(x)}">${x > 0 ? "+" : x < 0 ? "−" : ""}₹${fmt0(Math.abs(x))}</span>`);

// Pulse's own evidence score: which of the data agree with the trade's direction and structure.
function evidenceHtml(e) {
  if (!e) return "";
  const mark = { agree: ["✓", "up"], neutral: ["•", "muted"], against: ["✗", "down"] };
  return `<details class="evidence"><summary>Why the score is ${e.score}/100 — ${e.checks.filter((c) => c.verdict === "agree").length} of ${e.checks.length} checks agree</summary>
    <ul class="plain">${e.checks.map((c) => `<li><b class="${mark[c.verdict][1]}">${mark[c.verdict][0]}</b> <b>${esc(c.name)}</b> <span class="muted small">(${c.weight} pts)</span> — ${esc(c.why)}</li>`).join("")}</ul>
    <div class="small muted">Strong ≥ 70 · Moderate 45–69 · Weak &lt; 45. Agreement is not proof: no strategy here has passed the project's tests. The AI track record (Trade Record tab) shows how each band actually performs.</div></details>`;
}

function stratHtml(res, sym) {
  const a = res.plan, pr = res.priced, lv = res.levels;
  const biasCls = { bullish: "up", bearish: "down", neutral: "flat", unclear: "warn" }[a.bias];
  const head = `<div class="strat-head"><div><div class="ask">${res.source === "pulse" ? `Pulse ranked trade #${res.rank}` : "AI suggestion"} · expiry ${esc(res.expiry)}</div>
      <div class="what"><b>${esc(STRAT_NAMES[a.strategy])}</b> ${a.strategy !== "no_trade" ? `— ${esc(res.strategy_text)}` : ""}</div></div>
    <div><span class="badge ${biasCls}">${esc(a.bias)}</span> <span class="badge flat">AI confidence ${esc(a.confidence)}</span>
      ${res.evidence ? `<span class="badge score-${res.evidence.label.toLowerCase()}">Pulse score ${res.evidence.score} · ${esc(res.evidence.label)}</span>` : ""}</div></div>
    ${evidenceHtml(res.evidence)}
    ${res.retried ? `<div class="small muted">The AI's first answer was refused (${esc(res.retried.join("; "))}); this is its corrected answer.</div>` : ""}
    ${res.ai_record ? `<div class="small muted">Saved to the AI track record on the <a href="#record">Trade Record</a> tab, which settles it at its target, stop or expiry.</div>` : ""}`;
  const read = `<p>${esc(a.market_read)}</p>`;
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
      ${CREDIT.includes(a.strategy)
        ? `Put the <b>Super order</b> (target + stop loss) on the <b>SELL</b> leg only. When it fills at its target or stop, <b>sell the BUY leg</b> straight away. Never put a stop loss on the BUY leg: if it fired alone, the sold leg would be left unprotected.`
        : `Dhan's Super order cannot manage this spread safely, so use plain Limit orders and close <b>both</b> legs by hand when ${esc(name)} reaches its target or stop (the spread is then worth about <b class="up">${rupee(sp.at_target)}</b> or <b class="down">${rupee(sp.at_stop)}</b>). Buy back the <b>SELL</b> leg first, then sell the BUY leg.`}</div>`;
  const econ = pr ? `<div class="levels">
      <div class="lv"><span>${pr.debit ? "You pay" : "You receive"}</span><b>${rupee(Math.abs(pr.net_per_unit))}</b><small>per unit · ${money(Math.abs(pr.net_per_unit) * pr.lot)} a lot</small></div>
      <div class="lv"><span>Worst case at expiry</span><b class="down">${money(pr.max_loss_per_lot)}</b><small>a lot, if you never exit</small></div>
      <div class="lv"><span>Best case at expiry</span><b class="up">${pr.max_profit_per_lot == null ? "open-ended" : money(pr.max_profit_per_lot)}</b><small>a lot${pr.reward_to_risk != null ? ` · ${pr.reward_to_risk.toFixed(2)}× the risk` : ""}</small></div>
      <div class="lv wide"><div><span>Break-even at expiry</span><b>${pr.breakevens.map(fmt0).join(" / ")}</b></div><div><span>Lot size</span><b>${pr.lot}</b></div>
        <div><span>Charges a lot, in and out</span><b>${res.charges_per_lot != null ? "≈ " + money(res.charges_per_lot) : "—"}</b></div></div></div>` : "";
  const kl = (a.key_levels || []).map((l) => `<li><b class="num">${fmt0(l.price)}</b> ${esc(l.label)}</li>`).join("");
  return `<div class="call ${a.strategy === "no_trade" ? "idle" : a.bias === "bearish" ? "go-down" : a.bias === "bullish" ? "go-up" : "idle"}">${head}
      ${story}${legs}<div class="ticket-slot"></div>${together}${econ}
      ${pr ? `<div class="take-row">${res._taken ? `<span class="badge up">Recorded ✓</span> <span class="small">Follow it on the <a href="#record">Trade Record</a> tab.</span>`
        : `<button class="btn primary take-trade">Take this trade (dummy, 1 lot)</button> <span class="small muted">Records it on the Trade Record tab at these prices and tracks its profit and loss. No real order.</span>`}</div>` : ""}
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
    <p class="small muted">${res.source === "pulse" ? "Built by Pulse's rules from the live option chain and" : `GPT-5 analysis (${res.seconds}s) checked and`} priced by Pulse at the live bid / ask. Not a validated edge and not advice — no strategy here has passed the project's tests.</p>`;
}

// NIFTY levels from low to high, so "target below, stop above" (or the reverse) is visible at a glance.
function ladder(a, spot, down) {
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

async function openTicket(sym, i) {
  const res = curRes(sym); if (!res) return;
  S.ticket[sym] = S.ticket[sym]?.i === i ? null : { i, data: null };          // a second tap closes it
  renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym);
  const leg = (res.levels?.legs || res.priced.legs)[i];
  if (!S.ticket[sym] || !leg.id) return;
  try { S.ticket[sym].data = await api("/api/contract?id=" + encodeURIComponent(leg.id)); } catch (e) { S.ticket[sym].data = { error: e.message }; }
  if (S.ticket[sym]?.i === i) renderTicket(sym);
  $(`.plan-card[data-sym="${sym}"] .plan-oc tr.focus`)?.scrollIntoView({ block: "nearest" });
}

let ticketChart = null;
function renderTicket(sym) {
  const slot = $(`.plan-card[data-sym="${sym}"] .ticket-slot`), t = S.ticket[sym], res = curRes(sym);
  if (ticketChart) { ticketChart.remove(); ticketChart = null; }
  if (!slot) return;
  if (!t || !res) { slot.innerHTML = ""; return; }
  const l = (res.levels?.legs || res.priced.legs)[t.i], d = t.data, lot = res.lot, buy = l.action === "BUY";
  const role = legRole(res.plan.strategy, res.levels?.legs || res.priced.legs, l), dhan = role === "super" && legLevelsOk(l, l.premium_at_target, l.premium_at_stop);
  const nm = NAMES[sym] || sym;
  const chgPct = l.ltp && l.chg != null ? (l.chg / (l.ltp - l.chg)) * 100 : null;
  const totB = l.total_buy_qty || 0, totS = l.total_sell_qty || 0, bidPct = totB + totS ? (totB / (totB + totS)) * 100 : null;
  slot.innerHTML = `<div class="ticket">
    <div class="ticket-head"><div><div class="ask">${buy ? "Buy" : "Sell"} · tap the card again to close</div><h3>${esc(contractName(sym, res.expiry, l))}</h3>
      <div class="ticket-ltp"><b>${fmt(l.ltp)}</b> <span class="${cls(l.chg)}">${sign(l.chg)}${fmt(l.chg)}${chgPct != null ? ` (${sign(chgPct)}${chgPct.toFixed(2)}%)` : ""}</span></div></div>
      <div class="ticket-ohlc">${[["High", d?.high], ["Low", d?.low], ["Prev. close", d?.prev_close]].map(([k, v]) => `<div><span>${k}</span><b>${v != null ? fmt(v) : "—"}</b></div>`).join("")}</div></div>
    <div class="ticket-chart">${!d ? `<div class="loading"><span class="spinner"></span>Loading the option's price from NSE…</div>` : d.error ? `<div class="notice">${esc(d.error)}</div>` : ""}</div>
    <div class="ticket-grid">
      <div class="ticket-box"><h4 class="mini-h">How to place it in Dhan</h4>
        <table class="facts small-facts">
          <tr><th>Side</th><td><span class="leg-tag ${buy ? "buy" : "sell"}">${l.action}</span></td></tr>
          <tr><th>Lot</th><td>1 lot = <b>${lot}</b> qty (you choose how many lots)</td></tr>
          <tr><th>Order type</th><td>${dhan ? "<b>Super</b> order (limit + target + stop loss in one)" : role === "hedge" ? "<b>Limit</b> order — protection, place it first" : "<b>Limit</b> order — close both legs together by hand"}</td></tr>
          <tr><th>Limit price</th><td><b>${rupee(l.price)}</b> <span class="muted small">(${buy ? "the best ask" : "the best bid"} now)</span></td></tr>
          ${dhan ? `<tr><th>Target</th><td><b class="up">${rupee(l.premium_at_target)}</b> ${l.pnl_target_per_lot != null ? `<span class="small">(${pnl(l.pnl_target_per_lot)} a lot)</span>` : ""}</td></tr>
          <tr><th>Stop loss</th><td><b class="down">${rupee(l.premium_at_stop)}</b> ${l.pnl_stop_per_lot != null ? `<span class="small">(${pnl(l.pnl_stop_per_lot)} a lot)</span>` : ""}</td></tr>`
          : `<tr><th>Target / stop</th><td>${role === "hedge" ? "<b>none</b> — sell it right after the SELL leg's target or stop fills" : `<b>none in Dhan</b> — close by hand when ${esc(nm)} reaches its target or stop`}</td></tr>
          <tr><th>Expected price</th><td class="small">at ${esc(nm)} target <b class="ref">${rupee(l.premium_at_target)}</b> · at ${esc(nm)} stop <b class="ref">${rupee(l.premium_at_stop)}</b></td></tr>`}
          <tr><th>${buy ? "Money needed" : "Margin"}</th><td>${buy ? `<b>${money(l.price * lot)}</b> a lot (premium × qty)` : `set by Dhan; with the bought leg placed first it is close to the spread's worst case, <b>${money(res.priced.max_loss_per_lot)}</b> a lot`}</td></tr>
        </table></div>
      <div class="ticket-box"><h4 class="mini-h">Market depth (best price)</h4>
        <table class="depth"><thead><tr><th>Qty</th><th>Bid</th><th>Ask</th><th>Qty</th></tr></thead>
          <tbody><tr><td>${l.bid_qty != null ? fmt0(l.bid_qty) : "—"}</td><td class="up">${fmt(l.bid)}</td><td class="down">${fmt(l.ask)}</td><td>${l.ask_qty != null ? fmt0(l.ask_qty) : "—"}</td></tr></tbody></table>
        <div class="depth-tot small"><span>Total buy <b>${fmt0(totB)}</b></span><span>Total sell <b>${fmt0(totS)}</b></span></div>
        ${bidPct != null ? `<div class="bidbar"><div style="width:${bidPct}%">${bidPct.toFixed(0)}% bids</div><div>${(100 - bidPct).toFixed(0)}% offers</div></div>` : ""}
        <div class="small muted">Spread ${fmt(l.ask - l.bid)} (${l.ask && l.bid ? (((l.ask - l.bid) / ((l.ask + l.bid) / 2)) * 100).toFixed(1) : "—"}%). NSE publishes only the best level; Dhan shows 5.</div>
        <div class="small muted">IV ${l.iv ? l.iv.toFixed(1) + "%" : "—"} · OI ${lakh(l.oi)}</div></div>
    </div></div>`;
  if (!d || d.error || !d.points?.length) return;
  const el = $(".ticket-chart", slot);
  ticketChart = LightweightCharts.createChart(el, { autoSize: true, layout: { background: { type: "solid", color: "transparent" }, textColor: cssVar("--muted"),
      fontFamily: "Inter, system-ui, sans-serif" }, grid: { vertLines: { color: cssVar("--grid") }, horzLines: { color: cssVar("--grid") } },
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false }, crosshair: { mode: 0 } });
  const s = ticketChart.addAreaSeries({ lineColor: cssVar("--ema9"), topColor: "rgba(47,111,237,.18)", bottomColor: "rgba(47,111,237,0)", lineWidth: 2, priceLineVisible: false });
  let last = 0; s.setData(d.points.filter(([tm]) => (tm > last ? ((last = tm), true) : false)).map(([tm, p]) => ({ time: tm, value: p })));
  const mk = (price, color, title, style = 2) => price && s.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
  mk(l.price, cssVar("--text"), buy ? "Buy at" : "Sell at", 0);
  if (dhan) { mk(l.premium_at_target, cssVar("--up"), "Target"); mk(l.premium_at_stop, cssVar("--down"), "Stop loss"); }
  else { mk(l.premium_at_target, cssVar("--muted"), `at ${nm} target`); mk(l.premium_at_stop, cssVar("--muted"), `at ${nm} stop`); }
  ticketChart.timeScale().fitContent();
}

// ---------- Trade Record: dummy trades taken from the AI strategist ----------
// One lot each. Marked live from the NSE chain at the price each leg could be closed at; when the index reaches the
// AI's target or stop the trade is flagged (never closed for you). Stored on this computer (reports/trade_record).
async function takeTrade(sym) {
  const res = curRes(sym); if (!res) return;
  const btn = $(`.plan-card[data-sym="${sym}"] .take-trade`); if (btn) btn.disabled = true;
  try {
    const t = await api("/api/trades", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(res) });
    res._taken = t.id; renderStrat(sym); loaded.record = false;
  } catch (e) { alert(e.message); if (btn) btn.disabled = false; }
}

const FLAG_TEXT = { target: ["Target reached", "up"], stop: ["Stop reached", "down"], expired: ["Expired", "warn"] };
const legShort = (l) => `${l.action === "BUY" ? "B" : "S"} ${fmt0(l.strike).replace(/,/g, "")} ${l.type}`;

async function loadRecord() {
  const el = $("#recordBody");
  let d;
  try { d = await api("/api/trades"); } catch (e) { el.innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  const s = d.stats;
  const stat = (k, v, c = "") => `<div class="lv"><span>${k}</span><b class="${c}">${v}</b></div>`;
  const summary = `<section class="card"><div class="card-head"><h2>Your trades — summary</h2><span class="small muted">trades you took · 1 lot each · after charges</span></div>
    <div class="body"><div class="levels rec-stats">
      ${stat("Total P&L (closed)", money(s.net), cls(s.net))}${stat("Open trades now", `${s.open}${s.open ? ` · ${money(s.open_pnl)}` : ""}`, s.open ? cls(s.open_pnl) : "")}
      ${stat("Closed trades", s.closed)}${stat("Won / lost", `${s.wins} / ${s.losses}`)}
      ${stat("Win rate", s.win_rate != null ? s.win_rate.toFixed(0) + "%" : "—")}${stat("Average a trade", money(s.avg), cls(s.avg))}
      ${stat("Best", money(s.best), "up")}${stat("Worst", money(s.worst), "down")}</div></div></section>`;
  const open = d.open.length ? d.open.map(openTradeHtml).join("")
    : `<section class="card"><div class="body"><p class="muted">No open trades. On the Plan tab, ask the AI strategist and press <b>Take this trade</b> to record one here.</p></div></section>`;
  const hist = !d.closed.length ? `<p class="muted pad">Closed trades appear here with their profit or loss.</p>`
    : `<div class="oc-scroll"><table class="t rec-hist"><thead><tr><th>Taken</th><th>Closed</th><th>Trade</th><th>Legs: entry → exit</th><th>NIFTY in → out</th><th>Why closed</th><th>Gross</th><th>Charges</th><th>Net P&L</th><th></th></tr></thead><tbody>
      ${d.closed.map((t) => `<tr><td>${esc(t.taken_at)}</td><td>${esc(t.closed_at)}</td><td><b>${esc(NAMES[t.symbol] || t.symbol)}</b><br><span class="small muted">${esc(STRAT_NAMES[t.strategy] || t.strategy)} · ${esc(t.expiry)}</span></td>
        <td class="small">${t.legs.map((l) => `${legShort(l)} ${fmt(l.entry)} → ${fmt(l.exit)}`).join("<br>")}</td>
        <td class="num">${fmt0(t.spot_at_entry)} → ${fmt0(t.spot_at_exit)}</td><td class="small">${esc(t.reason)}</td>
        <td class="num ${cls(t.gross_pnl)}">${money(t.gross_pnl)}</td><td class="num">${money(t.charges)}</td><td class="num"><b class="${cls(t.net_pnl)}">${money(t.net_pnl)}</b></td>
        <td><button class="btn small-btn rec-del" data-id="${t.id}" title="Remove from the record">✕</button></td></tr>`).join("")}</tbody></table></div>`;
  el.innerHTML = summary + `<h3 class="sub-h rec-h">Your open trades</h3>` + open +
    `<section class="card"><div class="card-head"><h2>Your history</h2></div>${hist}</section>` + aiRecordHtml(d.ai);
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
}

// Every AI suggestion, recorded automatically and settled by rule (target / stop / expiry): how good is the AI,
// and does a higher Pulse score really do better?
function aiRecordHtml(ai) {
  if (!ai) return "";
  const s = ai.stats, band = ai.by_score;
  const row = (k, b) => `<tr><td><span class="badge score-${k.toLowerCase()}">${k}</span></td><td class="num">${b.closed}</td><td class="num">${b.wins} / ${b.losses}</td>
    <td class="num">${b.win_rate != null ? b.win_rate.toFixed(0) + "%" : "—"}</td><td class="num ${cls(b.net)}">${money(b.net)}</td><td class="num ${cls(b.avg)}">${money(b.avg)}</td></tr>`;
  const legsTxt = (t) => t.legs.map((l) => `${legShort(l)} ${fmt(l.entry)}${l.exit != null ? ` → ${fmt(l.exit)}` : ""}`).join("<br>");
  const all = [...ai.open, ...ai.closed];
  const rows = all.map((t) => {
    const live = t.status === "open" ? t.live || {} : null;
    return `<tr><td>${esc(t.taken_at)}</td><td><b>${esc(NAMES[t.symbol] || t.symbol)}</b><br><span class="small muted">${esc(STRAT_NAMES[t.strategy] || t.strategy)} · ${esc(t.expiry)}</span></td>
      <td>${t.score != null ? `<span class="badge score-${(t.score_label || "").toLowerCase()}">${t.score} ${esc(t.score_label)}</span>` : "—"}<br><span class="small muted">AI: ${esc(t.ai_confidence || "—")}</span></td>
      <td class="small">${legsTxt(t)}</td><td class="num small">${fmt0(t.index_target)} / ${fmt0(t.index_stop)}</td>
      <td class="small">${live ? `open · ${esc(NAMES[t.symbol] || t.symbol)} ${fmt0(live.spot)}` : `${esc(t.reason)}<br><span class="muted">${esc(t.closed_at)}</span>`}</td>
      <td class="num"><b class="${cls(live ? live.pnl : t.net_pnl)}">${money(live ? live.pnl : t.net_pnl)}</b>${live ? `<br><span class="small muted">now</span>` : ""}</td>
      <td><button class="btn small-btn rec-del" data-id="${t.id}" title="Remove from the record">✕</button></td></tr>`;
  }).join("");
  return `<section class="card"><div class="card-head"><h2>AI suggestions — track record</h2><span class="small muted">every suggestion, 1 lot, settled at its target, stop or expiry · after charges</span></div>
    <div class="body">
      <div class="levels rec-stats">
        <div class="lv"><span>Suggestions</span><b>${s.closed + s.open}</b><small>${s.open} still open</small></div>
        <div class="lv"><span>Won / lost</span><b>${s.wins} / ${s.losses}</b><small>${s.win_rate != null ? s.win_rate.toFixed(0) + "% won" : "none settled yet"}</small></div>
        <div class="lv"><span>Total P&L (settled)</span><b class="${cls(s.net)}">${money(s.net)}</b><small>average ${money(s.avg)}</small></div>
        <div class="lv"><span>Open now</span><b class="${cls(s.open_pnl)}">${money(s.open_pnl)}</b><small>before charges</small></div></div>
      <h4 class="mini-h">By Pulse score</h4>
      <table class="t"><thead><tr><th>Score</th><th>Settled</th><th>Won / lost</th><th>Win rate</th><th>Total P&L</th><th>Average</th></tr></thead>
        <tbody>${["Strong", "Moderate", "Weak"].map((k) => row(k, band[k])).join("")}</tbody></table>
      <p class="small muted">A handful of trades proves nothing either way; judge a score band after dozens of settled suggestions.</p>
    </div>
    ${all.length ? `<div class="oc-scroll"><table class="t rec-hist"><thead><tr><th>Asked</th><th>Trade</th><th>Score</th><th>Legs: entry → exit</th><th>Target / stop</th><th>Status</th><th>P&L</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<p class="muted pad">Every suggestion from the AI strategist will appear here.</p>`}</section>`;
}

function recLevels(t, l) {        // target / stop cells of a recorded leg, by its role in Dhan
  const role = legRole(t.strategy, t.legs, l), lg = { action: l.action, price: l.entry };
  if (role === "hedge") return `<td class="num muted">none</td><td class="num muted">none</td>`;
  if (role === "super" && legLevelsOk(lg, l.target, l.stop)) return `<td class="num up">${fmt(l.target)}</td><td class="num down">${fmt(l.stop)}</td>`;
  return `<td class="num ref">(${fmt(l.target)})</td><td class="num ref">(${fmt(l.stop)})</td>`;
}

function openTradeHtml(t) {
  const v = t.live || {}, down = t.index_target < t.index_stop, name = NAMES[t.symbol] || t.symbol;
  const flags = [...new Set([...(t.alerts || []).map((a) => a.kind), ...(v.flags || [])])];
  const banners = flags.map((f) => {
    const a = (t.alerts || []).find((x) => x.kind === f), [txt, c] = FLAG_TEXT[f];
    const extra = f === "expired" ? "The expiry has passed: close it to settle at the expiry value."
      : `${a ? `at ${esc(a.at)} (${esc(name)} ${fmt0(a.spot)}${a.pnl != null ? `, P&L then ${money(a.pnl)}` : ""})` : "now"} — close the trade when you are ready.`;
    return `<div class="rec-flag ${c}"><b>${txt}</b> ${extra}</div>`;
  }).join("");
  const plan = { underlying_target: t.index_target, underlying_stop: t.index_stop, underlying_entry_low: t.entry_low, underlying_entry_high: t.entry_high };
  const lad = v.spot != null && t.index_target != null ? ladder(plan, v.spot, down) : "";
  return `<section class="card rec-open"><div class="card-head"><h2>${esc(name)} · ${esc(STRAT_NAMES[t.strategy] || t.strategy)}</h2>
      <div class="rec-pnl ${cls(v.pnl)}">${v.pnl != null ? money(v.pnl) : "—"}<small>P&L now, before charges</small></div></div>
    <div class="body">
      <div class="small muted">Taken ${esc(t.taken_at)} · expiry ${esc(t.expiry)} · 1 lot (${t.lot} qty) · ${esc(name)} at entry ${fmt0(t.spot_at_entry)}${v.spot != null ? `, now <b>${fmt0(v.spot)}</b>` : ""}
        ${v.as_of ? ` · prices from NSE as of ${esc(v.as_of.slice(-8))}${nseAge(v.as_of)}` : ""}</div>
      ${banners}${v.error ? `<div class="notice">${esc(v.error)}</div>` : ""}
      ${lad}
      <table class="t legs"><thead><tr><th>Leg</th><th>Entry</th><th title="What you could close it at now: a bought option at the bid, a sold one at the ask — not the last traded price">Now (to close)</th><th>Target</th><th>Stop loss</th><th>P&L</th></tr></thead><tbody>
        ${t.legs.map((l, i) => {
          const now = v.legs?.[i]?.now, p = now != null ? (now - l.entry) * (l.action === "BUY" ? 1 : -1) * t.lot : null;
          return `<tr><td><span class="leg-tag ${l.action === "BUY" ? "buy" : "sell"}">${l.action}</span> ${esc(contractName(t.symbol, t.expiry, l))}</td>
            <td class="num">${fmt(l.entry)}</td><td class="num"><b>${fmt(now)}</b></td>${recLevels(t, l)}
            <td class="num ${cls(p)}">${p != null ? money(p) : "—"}</td></tr>`;
        }).join("")}</tbody></table>
      <div class="rec-actions"><span class="small muted">Book profit if ${esc(name)} reaches <b class="up">${fmt0(t.index_target)}</b> · exit if it reaches <b class="down">${fmt0(t.index_stop)}</b>.
        Worst case at expiry ${money(t.max_loss_per_lot)}.</span>
        <span><button class="btn primary small-btn rec-close" data-id="${t.id}">Close trade</button>
        <button class="btn small-btn rec-del" data-id="${t.id}">Remove</button></span></div>
    </div></section>`;
}

// ---------- Pulse trade ranking: concrete trades with strikes, entry, target and stop, best first ----------
S.rank = {}; S.view = {};
function curRes(sym) {          // the trade shown in the detail card: a ranked one, or the AI's suggestion
  const v = S.view[sym];
  if (typeof v === "number") return S.rank[sym]?.data?.candidates?.[v] || null;
  return S.strat[sym]?.result || null;
}
function refreshStrat(sym) { renderStrat(sym); renderNseChain(sym); drawPlanChartLines(sym); }

async function loadRank(sym) {
  const r = S.rank[sym] = S.rank[sym] || {};
  r.loading = true; renderStrat(sym);
  try {
    r.data = await api(`/api/rank/${encodeURIComponent(sym)}${S.nseExp[sym] ? "?expiry=" + encodeURIComponent(S.nseExp[sym]) : ""}`); r.error = null;
    if (S.view[sym] === undefined && r.data.candidates.length && !S.strat[sym]?.result) S.view[sym] = 0;   // show #1 by default
    if (typeof S.view[sym] === "number" && S.view[sym] >= r.data.candidates.length) S.view[sym] = 0;
  } catch (e) { r.error = e.message; }
  r.loading = false;
  if (!S.ticket[sym]) refreshStrat(sym); else renderStrat(sym);
}

function rankHtml(sym) {
  const r = S.rank[sym];
  if (!r || (r.loading && !r.data)) return `<div class="loading"><span class="spinner"></span>Ranking trades from the live chain…</div>`;
  if (r.error && !r.data) return `<div class="notice">Ranking unavailable: ${esc(r.error)}</div>`;
  const d = r.data, name = NAMES[sym] || sym;
  if (!d.candidates.length) return `<div class="call idle">No tradable setup with live two-sided prices right now.</div>`;
  const v = S.view[sym];
  const rows = d.candidates.map((c, i) => {
    const lv = c.levels, a = c.plan, e = c.evidence;
    const legs = lv.legs.map((l) => `<div><span class="leg-tag ${l.action === "BUY" ? "buy" : "sell"}">${l.action}</span> ${esc(contractName(sym, c.expiry, l))}</div>`).join("");
    const prem = (k) => lv.legs.map((l) => {
      const role = legRole(a.strategy, lv.legs, l);
      if (k === "price") return `<div>${fmt(l.price)}</div>`;
      if (role === "hedge") return `<div class="muted">none</div>`;
      return role === "super" && legLevelsOk(l, l.premium_at_target, l.premium_at_stop) ? `<div>${fmt(l[k])}</div>` : `<div class="ref">(${fmt(l[k])})</div>`;
    }).join("");
    return `<tr data-rank="${i}" class="${v === i ? "on" : ""}">
      <td class="num"><b>#${c.rank}</b></td>
      <td><span class="badge score-${e.label.toLowerCase()}">${e.score}</span><div class="small muted">${esc(e.label)}</div></td>
      <td><b>${esc(STRAT_NAMES[a.strategy])}</b><div class="small ${a.bias === "bearish" ? "down" : "up"}">${esc(a.bias)}</div></td>
      <td class="rank-legs">${legs}</td>
      <td class="num">${prem("price")}</td><td class="num up">${prem("premium_at_target")}</td><td class="num down">${prem("premium_at_stop")}</td>
      <td class="num"><span class="up">${fmt0(a.underlying_target)}</span><br><span class="down">${fmt0(a.underlying_stop)}</span></td>
      <td class="num"><b class="up">+₹${fmt0(lv.pnl_target_per_lot)}</b><br><b class="down">−₹${fmt0(-lv.pnl_stop_per_lot)}</b></td>
      <td class="num">${c.ratio.toFixed(1)} : 1</td></tr>`;
  }).join("");
  return `<div class="rank-head"><div><h4 class="mini-h">Ranked trades — best first</h4>
      <div class="small muted">Built by Pulse from the live ${esc(name)} chain (${esc(d.expiry)}): ${d.considered} tradable candidates, top ${d.candidates.length} shown.
      Ranked by the evidence score, then by profit-to-loss at the levels. Tap a row for its orders, ticket and the Take button.
      Target / stop loss are Dhan Super-order prices; <span class="ref">(grey)</span> = expected price when ${esc(name)} hits its level, closed by hand; "none" = protection leg.</div></div>
      <button class="btn small-btn rank-refresh" ${r.loading ? "disabled" : ""}>${r.loading ? "Updating…" : "Refresh"}</button></div>
    <div class="oc-scroll rank-scroll"><table class="t rank"><thead><tr><th>Rank</th><th>Score</th><th>Trade</th><th>Orders (Dhan)</th><th>Entry ₹</th><th>Target ₹</th><th>Stop loss ₹</th><th>${esc(name)} target / stop</th><th>Per lot at target / stop</th><th>Profit : loss</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="small muted">Premium targets and stops are estimates for ${esc(name)} reaching its target or stop today. One lot each; charges not included here (shown in the card). Not a validated edge.</div>`;
}

// ---------- start ----------
(async function init() {
  applyChartTheme();
  await loadStatus();
  renderChips(); renderInst();
  showTab(TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : store("tab") || "plan");
  loadQuotes(); loadCandles(); loadPlan();
  setInterval(loadQuotes, 3000);
  setInterval(loadCandles, 5000);
  setInterval(loadPlan, 15000);
  setInterval(() => { if (S.tab === "options") loadChain(); }, 4000);
  setInterval(loadStatus, 60000);
  setInterval(() => { if (S.tab === "plan" && S.morning && phase(S.morning.session).key === "live") (planEntries() || []).forEach(([sym]) => { if (!S.ticket[sym]) loadRank(sym); }); }, 60000);
  setInterval(() => { if (S.tab === "record") loadRecord(); }, 15000);
  setInterval(() => { if (S.tab === "plan") { renderSession(); loadLive(); } }, 15000);
  setInterval(() => { if (S.tab === "plan" && S.morning && phase(S.morning.session).key === "live") (planEntries() || []).forEach(([sym]) => loadNseChain(sym)); }, 15000);
})();

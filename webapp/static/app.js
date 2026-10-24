"use strict";

const $ = (s, el = document) => el.querySelector(s);
const IST_OFFSET = 19800; // lightweight-charts draws UTC; shift so the axis reads Indian time

const S = { sym: store("sym") || "NIFTY", tf: "5m", indices: [], quotes: {}, status: {}, plan: null, expiry: null, aiJob: null,
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
$("#chips").onclick = (e) => { const b = e.target.closest(".chip"); if (b) selectSymbol(b.dataset.sym); };

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

  const src = p.source === "dhan" ? "Dhan live data" : "Yahoo data (can be delayed)";
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
const TABS = ["plan", "today", "risk", "options", "ai", "map", "research", "trades"];
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

async function loadRisk() {
  const sym = S.sym;
  $("#riskBody").innerHTML = `<div class="loading"><span class="spinner"></span>Loading…</div>`;
  let r;
  try { r = await api("/api/risk/" + encodeURIComponent(sym)); }
  catch (e) { $("#riskBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  if (sym !== S.sym) return;
  let html = "";
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
  $("#costCard").innerHTML = `<div class="card-head"><h2>What it costs to trade (bid–ask spread)</h2><div class="seg" id="costSeg">${tabsHtml}</div></div><div class="body" id="costBody"></div>`;
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
  $("#researchBody").innerHTML =
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

// ---------- plan (morning plan + live call + sizing) ----------
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

function riskLimit() {
  const cap = +($("#capital").value || 0), pctv = +($("#riskPct").value || 0);
  return { cap, pct: pctv, max: cap > 0 && pctv > 0 ? (cap * pctv) / 100 : null };
}
["capital", "riskPct"].forEach((id) => {
  const el = $("#" + id), saved = store(id); if (saved) el.value = saved;
  el.addEventListener("input", () => { store(id, el.value); renderRisk(); renderPlanCards(); });
});
function renderRisk() {
  const r = riskLimit();
  $("#riskOut").innerHTML = r.max ? `You lose at most <b>${money(r.max)}</b> on any one trade (${r.pct}% of ${money(r.cap)}). Trade sizes below follow this.`
    : `Enter your capital and the most you are willing to lose on one trade (1% is a common limit). Nothing leaves this computer.`;
}

function sizeTrade(p) {
  const leg = p.option, s = p.signal, r = riskLimit();
  if (!leg || !r.max) return null;
  const perUnit = leg.premium && leg.stop_loss ? leg.premium - leg.stop_loss : leg.move_sl;   // premium lost at the stop
  const perLot = perUnit * leg.lot;
  const lots = perLot > 0 ? Math.floor(r.max / perLot) : 0;
  return { perLot, lots, approx: !leg.premium, loss: lots * perLot, cost: leg.premium ? leg.premium * leg.lot * lots : null,
    exposure: s.entry * leg.lot * lots, leverage: r.cap ? (s.entry * leg.lot * lots) / r.cap : null };
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
  const up = s.side === "BUY", z = sizeTrade(p);
  const sizing = !riskLimit().max ? `<div class="small warn-c">Enter your capital and risk limit above to see how many lots.</div>`
    : z.lots < 1 ? `<div class="small warn-c">One lot risks about ${money(z.perLot)} — more than your limit of ${money(riskLimit().max)}. Skip this trade.</div>`
    : `<div class="levels"><div class="lv"><span>Lots</span><b>${z.lots}</b><small>${z.lots * leg.lot} units</small></div>
        <div class="lv"><span>Max loss at stop</span><b class="down">${z.approx ? "≈ " : ""}${money(z.loss)}</b><small>within your limit</small></div>
        <div class="lv"><span>Money needed</span><b>${z.cost != null ? money(z.cost) : "premium × lots"}</b><small>option premium paid</small></div>
        <div class="lv"><span>Leverage</span><b>${z.leverage != null ? z.leverage.toFixed(1) + "×" : "—"}</b><small>index exposure ÷ capital</small></div></div>`;
  return `<div class="call ${up ? "go-up" : "go-down"}"><div class="ask">Take this trade</div>
    <div class="what"><b>Buy ${esc(NAMES[sym])} ${fmt0(leg.strike)} ${leg.kind}</b>${leg.expiry ? ` · expiry ${esc(leg.expiry)}` : " · nearest weekly expiry"}</div>
    <div class="levels"><div class="lv"><span>Entry (index)</span><b>${fmt(s.entry)}</b></div><div class="lv"><span>Stop loss (index)</span><b class="down">${fmt(s.stop_loss)}</b></div>
      <div class="lv"><span>Target (index)</span><b class="up">${fmt(s.target)}</b></div>${leg.premium ? `<div class="lv"><span>Premium now</span><b>${rupee(leg.premium)}</b><small>stop ${rupee(leg.stop_loss)} · target ${rupee(leg.target)}</small></div>` : ""}</div>
    ${sizing}
    <div class="small muted">Won ${v.win_rate}% of ${v.trades} similar trades recently (avg ${sign(v.avg_r)}${v.avg_r}× risk after costs). Exit by 15:15. One trade a day. Not a validated edge — use your judgment.</div></div>`;
}

function plainPcr(x) { return x > 1.2 ? "many more puts than calls open (heavy hedging)" : x < 0.8 ? "more calls than puts open" : "calls and puts roughly balanced"; }
function morningHtml(sym, e) {
  const c = e.context, ai = e.ai, em = c.expected_move, t = c.trend, g = c.regime;
  const aiBlock = !ai ? `<p class="small muted">AI view not built yet (runs at 8:30 AM on trading days).</p>`
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
  $("#planBody").innerHTML = Object.entries(m.indices).map(([sym, e]) => `<section class="card plan-card">
      <div class="card-head"><h2>${esc(NAMES[sym] || sym)}</h2>${e.context.trend ? `<span class="badge ${e.context.trend.tone}">${esc(e.context.trend.label)}</span>` : ""}</div>
      <div class="body"><h3 class="sub-h">Today's call</h3>${callHtml(sym, S.live[sym], ph)}
        <h3 class="sub-h">Morning view</h3>${morningHtml(sym, e)}</div></section>`).join("");
  const job = m.ai_job || {};
  $("#planStamp").innerHTML = `Plan built ${esc(m.built_at)}${job.running ? ` · AI view running since ${esc(job.started)}…` : ""}.
    <button class="btn small-btn" id="planRefresh">Refresh data</button>
    ${m.session.trading && !PREVIEW_AT ? `<button class="btn small-btn" id="planAi" ${job.running ? "disabled" : ""}>Run AI view now (~20 min)</button>` : ""}`;
  $("#planRefresh").onclick = async () => { $("#planRefresh").disabled = true; S.morning = await api("/api/morning/refresh", { method: "POST" }).catch(() => S.morning); renderPlan(); };
  if ($("#planAi")) $("#planAi").onclick = async () => { try { await api("/api/morning/ai", { method: "POST" }); } catch (e) { alert(e.message); } loadMorning(); };
}

function renderPlan() { renderSession(); renderRisk(); renderPlanCards(); }

async function loadMorning() {
  try { S.morning = await api("/api/morning" + (PREVIEW_AT ? "?date=" + PREVIEW_AT.slice(0, 10) : "")); } catch (e) { $("#planBody").innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  renderPlan(); loadLive();
}
async function loadLive() {
  if (!S.morning || !["wait", "live"].includes(phase(S.morning.session).key)) return;
  for (const sym of Object.keys(S.morning.indices)) {
    try { S.live[sym] = await api("/api/plan/" + sym); } catch { /* keep the last one */ }
  }
  renderPlanCards();
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
  setInterval(() => { if (S.tab === "plan") { renderSession(); loadLive(); } }, 15000);
})();

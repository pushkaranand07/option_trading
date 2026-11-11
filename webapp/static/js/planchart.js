// The Plan tab's live chart per index, with its layers, drawings and readout.
import { api } from "./api.js";
import { chart, chartOff, chartProblem, ema, lineOpts } from "./chart.js";
import { cls, esc, fmt, fmt0, pct, srcLabel } from "./format.js";
import { planEntries } from "./plan.js";
import { S } from "./state.js";
import { curRes } from "./strat.js";
import { $, IST_OFFSET, cssVar, store } from "./util.js";

// One live chart per index in the Plan tab: 5-minute candles of the last sessions. The viewer turns layers on and
// off (averages, trade, expected range, option walls, day levels, swings, crossovers), draws their own lines (kept
// per instrument in this browser) and reads O / H / L / C under the cursor. Only the last price, the target and the
// stop take an axis label; every other level is labelled inside the chart, nudged apart so labels never overlap.
export const planCharts = new Map();
export const PC_LAYERS = [["ema", "Averages", "--ema9"], ["trade", "Trade", "--up"], ["range", "Expected range", "--muted"],
  ["walls", "Option walls", "--warn"], ["day", "Day levels", "--day"], ["swings", "Swings", "--muted"], ["cross", "Crossovers", "--ema21"]];
export const PC_SPANS = [["1", "Today"], ["2", "2D"], ["5", "5D"], ["all", "All"]];
export const PC_RIGHT = 14;                                    // empty bars right of the last candle, room for the trade zones
export const PC_DASH = { solid: [], dash: [5, 4], dot: [1.5, 3] };
export const pcPrefs = (() => { try { return JSON.parse(store("chartPrefs")) || {}; } catch { return {}; } })();
export const pcOn = (k) => pcPrefs.layers?.[k] !== false;
export const pcSave = () => store("chartPrefs", JSON.stringify(pcPrefs));
export function pcDrawings(sym, list) {
  if (list !== undefined) return store("draw." + sym, JSON.stringify(list));
  try { return JSON.parse(store("draw." + sym)) || []; } catch { return []; }
}
export const hexA = (c, a) => (/^#[0-9a-f]{6}$/i.test(c) ? c + Math.round(a * 255).toString(16).padStart(2, "0") : c);
export const chartTime = (b) => b.time + IST_OFFSET;

// Bands and day dividers under the candles; levels, their labels and the viewer's lines over them.
export class PlanOverlay {
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

export function planChart(sym) {
  if (planCharts.has(sym)) return planCharts.get(sym);
  const card = $(`.plan-card[data-sym="${sym}"]`), el = card && $(".plan-chart", card); if (!el) return null;
  if (chartProblem()) return chartOff(el, true);
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

export function pcToolbar(sym) {
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

export function pcSyncBar(sym) {
  const c = planCharts.get(sym);
  c.card.querySelectorAll("[data-layer]").forEach((b) => b.classList.toggle("on", pcOn(b.dataset.layer)));
  c.card.querySelectorAll("[data-span]").forEach((b) => b.classList.toggle("on", b.dataset.span === (pcPrefs.span || "2")));
  c.card.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === c.tool));
}

export function pcTool(sym, tool) {
  const c = planCharts.get(sym); if (!c) return;
  c.tool = tool; c.pending = null; c.overlay.set({ preview: null });
  $(".pc-wrap", c.card).classList.toggle("drawing", !!tool);
  $(".pc-hint", c.card).textContent = tool === "h" ? "Click a price to place the line · Esc to cancel"
    : tool === "t" ? "Click the first point · Esc to cancel" : "";
  pcSyncBar(sym);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") planCharts.forEach((c, s) => c.tool && pcTool(s, null)); });

// The candle under x (the last one when x is right of the data): trend points sit on candle times.
export function pcTimeAt(c, x) {
  const n = c.bars.length, i = c.ch.timeScale().coordinateToLogical(x);
  return n && i != null ? chartTime(c.bars[Math.max(0, Math.min(n - 1, Math.round(i)))]) : null;
}

export function pcClick(sym, p) {
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

export function pcMove(sym, p) {
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
export function pcReadout(sym, bar, e9, e21, time) {
  const c = planCharts.get(sym), el = c && $(".pc-readout", c.card); if (!el) return;
  if (!bar) {
    const n = c.bars.length; if (!n) { el.innerHTML = ""; return; }
    const closes = c.bars.map((x) => x.close);
    bar = c.bars[n - 1]; time = chartTime(bar); e9 = ema(closes, 9)[n - 1]; e21 = ema(closes, 21)[n - 1];
  }
  const ch = bar.open ? (bar.close - bar.open) / bar.open * 100 : 0;
  const when = new Date(time * 1000).toLocaleString("en-IN", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  el.innerHTML = `${esc(when)} &nbsp; O <b>${fmt(bar.open)}</b> H <b>${fmt(bar.high)}</b> L <b>${fmt(bar.low)}</b> C <b>${fmt(bar.close)}</b>
    <span class="${cls(ch)}">${pct(ch)}</span>${pcOn("ema") && e9 != null ? ` &nbsp; <span style="color:var(--ema9-text)">EMA 9 ${fmt(e9)}</span> &nbsp; <span style="color:var(--ema21-text)">EMA 21 ${fmt(e21)}</span>` : ""}`;
}

export function pcDayStarts(bars) {
  const out = []; let prev;
  bars.forEach((b, i) => { const d = Math.floor(chartTime(b) / 86400); if (d !== prev) { out.push(i); prev = d; } });
  return out;
}

export function pcSpan(sym) {
  const c = planCharts.get(sym), n = c?.bars.length; if (!n) return;
  const span = pcPrefs.span || "2", starts = pcDayStarts(c.bars);
  const from = span === "all" ? 0 : starts[Math.max(0, starts.length - Number(span))];
  c.ch.timeScale().setVisibleLogicalRange({ from: from - 1, to: n - 1 + PC_RIGHT });
}

// Previous session's high / low / close and today's open, from the 5-minute bars.
export function pcDayLevels(bars) {
  const st = pcDayStarts(bars); if (st.length < 2) return null;
  const prev = bars.slice(st.at(-2), st.at(-1));
  return { high: Math.max(...prev.map((b) => b.high)), low: Math.min(...prev.map((b) => b.low)), close: prev.at(-1).close, open: bars[st.at(-1)].open };
}

// A swing high / low is the highest high / lowest low of the k candles either side of it (12 = an hour each side).
export function pcSwings(bars, k = 12) {
  const out = [];
  for (let i = k; i < bars.length - k; i++) {
    const w = bars.slice(i - k, i + k + 1);
    if (bars[i].high === Math.max(...w.map((b) => b.high))) out.push({ i, high: true });
    else if (bars[i].low === Math.min(...w.map((b) => b.low))) out.push({ i, high: false });
  }
  return out;
}

export async function loadPlanCharts() {
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

export function drawPlanChartLines(sym) {
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
    const r = curRes(sym), a = r?.plan;
    if (a && a.strategy !== "no_trade") {
      const who = r._label ? `Scan #${r.rank}` : `AI #${r.rank}`, lo = a.underlying_entry_low, hi = a.underlying_entry_high;
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

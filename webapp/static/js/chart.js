// The Today tab's main price chart.
import { api } from "./api.js";
import { esc } from "./format.js";
import { drawPlanChartLines, planCharts } from "./planchart.js";
import { S } from "./state.js";
import { $, IST_OFFSET, cssVar } from "./util.js";

// ---------- chart ----------
// Why no chart can be drawn (null: the chart library loaded). Without it the page still runs, minus its charts.
export const chartProblem = () => (typeof LightweightCharts === "undefined" || !LightweightCharts?.createChart
  ? "Chart unavailable: the chart library did not load. Prices, plans and the record still work; reload the page to retry." : null);
// The main chart says why; the smaller charts only say "Chart unavailable", so the reason shows once.
export const chartOff = (el, brief) => { if (el) el.innerHTML = `<div class="notice">${esc(brief ? "Chart unavailable." : chartProblem())}</div>`; return null; };
export const lineOpts = { lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
export let chart = null, candleSeries = null, volSeries = null, ema9Series = null, ema21Series = null;
if (chartProblem()) chartOff($("#chart"));
else {
  chart = LightweightCharts.createChart($("#chart"), {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, fontFamily: "Inter, system-ui, sans-serif" },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    crosshair: { mode: 0 },
  });
  candleSeries = chart.addCandlestickSeries({ borderVisible: false });
  volSeries = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
  ema9Series = chart.addLineSeries(lineOpts);
  ema21Series = chart.addLineSeries(lineOpts);
}
export let planLines = [];

export function applyChartTheme() {
  if (!chart) return;
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

export function ema(values, n) { const k = 2 / (n + 1); let prev; return values.map((v) => (prev = prev === undefined ? v : v * k + prev * (1 - k))); }

export let lastBars = [], firstLoad = true, candleBusy = false;
export const resetChartView = () => { firstLoad = true; };   // the next load sets the visible range again (a new symbol)
export function drawBars(bars) {
  if (!chart) return;
  const up = cssVar("--up"), down = cssVar("--down"), t = (b) => b.time + IST_OFFSET;
  candleSeries.setData(bars.map((b) => ({ time: t(b), open: b.open, high: b.high, low: b.low, close: b.close })));
  volSeries.setData(bars.map((b) => ({ time: t(b), value: b.volume, color: (b.close >= b.open ? up : down) + "55" })));
  const closes = bars.map((b) => b.close), e9 = ema(closes, 9), e21 = ema(closes, 21);
  ema9Series.setData(bars.map((b, i) => ({ time: t(b), value: e9[i] })));
  ema21Series.setData(bars.map((b, i) => ({ time: t(b), value: e21[i] })));
}

export function drawPlanLines() {
  if (!chart) return;
  planLines.forEach((l) => candleSeries.removePriceLine(l)); planLines = [];
  const s = S.plan?.signal;
  if (!s || s.side === "WAIT" || S.plan.symbol !== S.sym) return;
  const mk = (price, color, title) => planLines.push(candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
  mk(s.entry, cssVar("--muted"), "Entry"); mk(s.stop_loss, cssVar("--down"), "Stop loss"); mk(s.target, cssVar("--up"), "Target");
}

export async function loadCandles() {
  if (candleBusy || !chart) return; candleBusy = true;
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

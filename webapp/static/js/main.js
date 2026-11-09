// Start-up: theme, first load and the pollers.
import { loadStatus } from "./banners.js";
import { applyChartTheme, loadCandles } from "./chart.js";
import { loadQuotes, renderChips, renderInst } from "./instrument.js";
import { pollNseChains } from "./nsechain.js";
import { loadChain } from "./options.js";
import { loadLive, renderSession } from "./plan.js";
import { loadRecord } from "./record.js";
import { loadRules } from "./rules.js";
import { createScheduler } from "./scheduler.js";
import { S } from "./state.js";
import { TABS, showTab } from "./tabs.js";
import { loadPlan } from "./today.js";
import { $, cssVar, store } from "./util.js";

// ---------- theme ----------
if (store("theme")) document.documentElement.dataset.theme = store("theme");
$("#themeBtn").onclick = () => {
  const dark = cssVar("--bg") !== "#f6f7f9";
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  store("theme", document.documentElement.dataset.theme);
  applyChartTheme();
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyChartTheme());

// ---------- the pollers: one scheduler, started once the status has loaded ----------
export const poller = createScheduler()
  .every("quotes", 3000, loadQuotes)
  .every("candles", 5000, loadCandles)
  .every("plan", 15000, loadPlan)
  .every("option chain", 4000, loadChain, () => S.tab === "options")
  .every("status", 60000, loadStatus)
  .every("trade record", 15000, loadRecord, () => S.tab === "record")
  .every("plan tab", 15000, () => { renderSession(); return loadLive(); }, () => S.tab === "plan")
  .every("nse chains", 15000, pollNseChains);             // itself only on the Plan tab during the live session

// ---------- start ----------
(async function init() {
  applyChartTheme();
  await Promise.all([loadRules(), loadStatus()]);          // the trading rules from the server, then everything else
  renderChips(); renderInst();
  showTab(TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : store("tab") || "plan");
  loadQuotes(); loadCandles(); loadPlan();
  poller.start();
})();

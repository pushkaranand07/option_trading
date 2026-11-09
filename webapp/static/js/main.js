// Start-up: theme, first load and the pollers.
import { loadStatus } from "./banners.js";
import { applyChartTheme, loadCandles } from "./chart.js";
import { loadQuotes, renderChips, renderInst } from "./instrument.js";
import { pollNseChains } from "./nsechain.js";
import { loadChain } from "./options.js";
import { loadLive, renderSession } from "./plan.js";
import { loadRecord } from "./record.js";
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
  setInterval(() => { if (S.tab === "record") loadRecord(); }, 15000);
  setInterval(() => { if (S.tab === "plan") { renderSession(); loadLive(); } }, 15000);
  setInterval(pollNseChains, 15000);
})();

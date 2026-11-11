// Tab switching, and the Map tab.
import { renderAI } from "./ai.js";
import { loadCandles } from "./chart.js";
import { loadJournalFiles } from "./journal.js";
import { loadCosts, loadOptions } from "./options.js";
import { loadMorning } from "./plan.js";
import { loadRecord } from "./record.js";
import { loadResearchTab } from "./research.js";
import { loadRisk } from "./risk.js";
import { loadScanner } from "./scanner.js";
import { S } from "./state.js";
import { $, store } from "./util.js";

// ---------- tabs ----------
export const TABS = ["plan", "scanner", "record", "today", "risk", "options", "ai", "map", "research", "trades"];
export const INSTRUMENT_TABS = ["today", "risk", "options", "ai"];
export const loaded = {};

export function showTab(tab, force = false) {
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
  if (tab === "scanner") loadScanner();
  if (tab === "today") loadCandles();
  if (tab === "risk") loadRisk();
  if (tab === "options") { loadOptions(); loadCosts(); }
  if (tab === "ai") renderAI();
  if (tab === "map") loadMap();
  if (tab === "research") loadResearchTab();
  if (tab === "trades") loadJournalFiles();
  if (tab === "record") loadRecord();
}
$("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); };
addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// ---------- market map ----------
export function loadMap() {
  if ($("#mapBody").dataset.ready) return;
  $("#mapBody").dataset.ready = "1";
  $("#mapBody").innerHTML = `<iframe class="map-frame" src="/market-map" title="India Market Map"></iframe>`;
}

// The page-wide banners and the forward test's status line, from /api/status.
import { api } from "./api.js";
import { esc } from "./format.js";
import { S } from "./state.js";
import { $ } from "./util.js";

// ---------- status + quotes ----------
export const banner = (sel, text) => { const el = $(sel); if (el) { el.hidden = !text; el.textContent = text || ""; } };
// The page-wide banners' text from /api/status (null: no banner). store_problem, monitor and degraded are optional:
// an older server sends none of them.
export const bannerTexts = (st) => ({ calendar: st?.calendar_warning || null,
  v2: st?.v2?.fingerprint_problem ? `${ftName()} forward test: ${st.v2.fingerprint_problem}.` : null,
  code: st?.code?.stale ? `This server runs code from ${st.code.running.slice(0, 7)} (started ${st.code.started_at.replace("T", " ")}); the checkout is at ${st.code.repo.slice(0, 7)}. Restart the server to run the latest code.` : null,
  store: st?.store_problem ? `Trade record problem: ${st.store_problem}` : null,     // the server's message is complete: what failed, any copy made, writes stopped
  monitor: st?.monitor?.fail_count >= 3 ? `Auto-settle is failing: ${st.monitor.fail_count} checks in a row${st.monitor.last_error ? ` (last error: ${st.monitor.last_error})` : ""}. Open paper trades are not being closed at their target, stop or exit time until it recovers${st.monitor.last_ok_at ? `; it last worked at ${String(st.monitor.last_ok_at).replace("T", " ")}` : ""}.` : null,
  degraded: degradedText(st?.degraded) });
// The degraded notice: each part the server could not check, except the calendar (always shown by #calWarn) and v2
// while a v2 line is on the page (it lives only on the Plan tab; elsewhere the notice is the one place it shows).
// Each warning once. A malformed list shows nothing rather than stopping every banner.
export const v2LineOnPage = () => { try { return document.querySelectorAll(".v2-line").length > 0; } catch { return false; } };
export function degradedText(list, v2Shown = v2LineOnPage()) {
  const hide = v2Shown ? ["calendar", "v2"] : ["calendar"];
  const parts = (Array.isArray(list) ? list : []).filter((d) => d && typeof d === "object" && d.part && !hide.includes(d.part));
  return parts.length ? `Running with parts missing: ${parts.map((d) => `${d.part}${d.reason ? ` (${d.reason})` : ""}`).join("; ")}.` : null;
}
// The forward test's version as the server reports it (data keys keep the name "v2"; the test running is v3).
export const ftName = () => `v${S.status?.v2?.version || "3"}`;
// Did today's answer count for the forward test: YES / NO / NOT YET (the server says why).
export function v2LineHtml() {
  const v = S.status?.v2; if (!v) return "";
  const c = { YES: "up", NO: "down", "NOT YET": "warn" }[v.state] || "muted";
  return `${ftName()} aaj ka answer counted: <b class="${c}">${esc(v.state)}</b>${v.reason ? ` — ${esc(v.reason)}` : ""}`;
}
export async function loadStatus() {
  try {
    S.status = await api("/api/status");
    S.indices = S.status.indices;
    const mp = $("#marketPill");
    const mh = S.status.muhurat?.state === "open";
    mp.textContent = S.status.market_open ? "● Market open" : mh ? "● Muhurat open" : "Market closed";
    mp.classList.toggle("open", S.status.market_open || mh);
    const b = bannerTexts(S.status);
    banner("#calWarn", b.calendar);
    banner("#v2Warn", b.v2);
    banner("#codeWarn", b.code);
    banner("#storeWarn", b.store);
    banner("#monitorWarn", b.monitor);
    banner("#degradedWarn", b.degraded);
    document.querySelectorAll(".v2-line").forEach((e) => (e.innerHTML = v2LineHtml()));
  } catch (e) { console.warn(e); }
}

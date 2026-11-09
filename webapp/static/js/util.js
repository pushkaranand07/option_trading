// Small browser helpers: the DOM query, this browser's saved settings and the IST clock.
export const $ = (s, el = document) => el.querySelector(s);
export const IST_OFFSET = 19800; // lightweight-charts draws UTC; shift so the axis reads Indian time
export function store(k, v) {
  try {
    if (v === undefined) return localStorage.getItem("pulse." + k);
    localStorage.setItem("pulse." + k, v);
  } catch { return null; }
}
export const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ---------- IST clock ----------
// Preview: ?at=2026-10-23T10:30 shows the Plan tab as at that moment, with that day's saved plan.
export const PREVIEW_AT = new URLSearchParams(location.search).get("at");
export function istNow() {
  if (PREVIEW_AT) { const [d, t] = PREVIEW_AT.split("T"); return { date: d, mins: toMins(t), hhmm: t + " (preview)" }; }
  const p = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  const g = (t) => p.find((x) => x.type === t).value;
  return { date: `${g("year")}-${g("month")}-${g("day")}`, mins: +g("hour") * 60 + +g("minute"), hhmm: `${g("hour")}:${g("minute")}` };
}
export const toMins = (hhmm) => +hhmm.slice(0, 2) * 60 + +hhmm.slice(3, 5);
export const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);

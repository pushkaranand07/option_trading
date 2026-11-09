// Number, text and HTML formatting shared by every view.
export const nf = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fmt = (x) => (x == null || isNaN(x) ? "—" : nf.format(x));
export const fmt0 = (x) => (x == null || isNaN(x) ? "—" : Math.round(x).toLocaleString("en-IN"));
export const rupee = (x) => (x == null ? "—" : "₹" + fmt(x));
export const fmtInt = (x) => {
  if (x == null) return "—";
  const a = Math.abs(x), s = x < 0 ? "-" : "";
  if (a >= 1e7) return s + (a / 1e7).toFixed(2) + "Cr";
  if (a >= 1e5) return s + (a / 1e5).toFixed(2) + "L";
  if (a >= 1e3) return s + (a / 1e3).toFixed(1) + "K";
  return String(x);
};
// Where prices came from; "saved (…)" means the live source was unreachable and the last saved bars are shown.
export const srcLabel = (x) => (x === "dhan" ? "Dhan live data" : x === "yahoo" ? "Yahoo data (can be delayed)" : `No connection to the data source — showing ${x || "saved data"}`);
export const cls = (x) => (x > 0 ? "up" : x < 0 ? "down" : "muted");
export const sign = (x) => (x > 0 ? "+" : "");
export const pct = (x) => (x == null ? "—" : `${sign(x)}${x.toFixed(2)}%`);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Markdown from the AI as safe HTML; if marked or DOMPurify failed to load, the text is shown as it is, escaped.
export const mdHtml = (s) => (typeof marked !== "undefined" && typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(marked.parse(s || ""))
  : `<pre class="report-raw">${esc(s)}</pre>`);
export const pc = (x, d = 1) => (x == null || isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`);
export const card = (title, body, extra = "") => `<section class="card"><div class="card-head"><h2>${title}</h2>${extra}</div><div class="body">${body}</div></section>`;

// End-of-day data (NSE's daily files, downloaded by the 7:30 PM job) says which close it is from and when it
// updates next, so a date that is not today reads as expected rather than out of date.
export function freshLine(f) {
  if (!f) return "";
  if (f.stale) return `<div class="fresh stale">⚠ End-of-day data from <b>${esc(f.as_of_label || "—")}</b>, but the latest close is ${esc(f.expected)}:
    the nightly update (7:30 PM) seems to have missed it. Check the Research tab's nightly job, or run <code>scripts/quant_daily_update.py</code>.</div>`;
  return `<div class="fresh">End-of-day data from <b>${esc(f.as_of_label)}</b> — the latest NSE close${f.today_is_session ? " (today's data comes after the market closes)" : ""}.
    Next update <b>${esc(f.next_update)}</b>. Live prices are on the Plan and Today tabs.</div>`;
}

export const money = (x) => (x == null ? "—" : (x < 0 ? "−" : "") + "₹" + fmt0(Math.abs(x)));
export const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export const lakh = (x) => (x == null ? "—" : fmtInt(Math.round(x)));

export const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
export function contractName(sym, expiry, l) {
  const [d, m] = String(expiry).split("-");
  return `${sym} ${+d} ${String(m).toUpperCase().slice(0, 3)} ${fmt0(l.strike).replace(/,/g, "")} ${l.type === "CE" ? "CALL" : "PUT"}`;
}
export const pnl = (x) => (x == null ? "—" : `<span class="${cls(x)}">${x > 0 ? "+" : x < 0 ? "−" : ""}₹${fmt0(Math.abs(x))}</span>`);

// No score: its inputs (trend, PCR, OI) showed no edge under the tested conditions in the LightGBM test (same-day AUC 0.502) and model suite v1 (docs/data_catalog.md).
export const COST_NOTE = "cost model unverified";
export const RECORDED_NOTE = `<p class="small muted">recorded trades, not a test (not registered before entry); ${COST_NOTE}</p>`;

// Loads webapp/static/app.js in a sandbox with a stub browser, then calls one render function with JSON arguments
// and prints its HTML. Used by tests/test_ui_regressions.py to test what the page shows, not how it is marked up.
//   node tests/js/render.js '<js expression>'      e.g.  'aiRecordHtml(ARGS[0])'   (ARGS from stdin JSON)
const fs = require("fs"), vm = require("vm"), path = require("path");
const app = fs.readFileSync(path.join(__dirname, "..", "..", "webapp", "static", "app.js"), "utf8");
const el = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "classList" ? { toggle() {}, add() {}, remove() {}, contains: () => false }
    : k === "querySelectorAll" ? () => [] : k === "dataset" || k === "style" ? {} : el),
  set: () => true, apply: () => el,
});
const never = () => new Promise(() => {});
const ctx = {
  console, Intl, Math, JSON, Date, Number, String, Array, Object, Set, Map, Promise, URLSearchParams, isNaN, parseFloat, parseInt,
  document: el, location: { search: "", hash: "" }, history: { replaceState() {} }, localStorage: { getItem: () => null, setItem() {} },
  fetch: never, setInterval: () => 0, setTimeout: () => 0, clearTimeout() {}, addEventListener() {}, matchMedia: () => el,
  getComputedStyle: () => ({ getPropertyValue: () => "" }), LightweightCharts: el, marked: { parse: (x) => x }, DOMPurify: { sanitize: (x) => x },
  requestAnimationFrame: () => 0, Headers, ResizeObserver: function () { return el; }, alert() {}, confirm: () => false, window: null,
};
ctx.window = ctx;
// RENDER_DROP=LightweightCharts,marked: run as if those libraries had failed to load (tests the page's fallbacks).
for (const k of (process.env.RENDER_DROP || "").split(",").filter(Boolean)) delete ctx[k];
vm.createContext(ctx);
vm.runInContext(app, ctx, { filename: "app.js" });
const input = fs.readFileSync(0, "utf8");
vm.runInContext(`var ARGS = ${input || "[]"};`, ctx);
Promise.resolve(vm.runInContext(process.argv[2], ctx)).then((x) => process.stdout.write(String(x)));   // an async call is awaited

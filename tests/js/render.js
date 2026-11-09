// Loads the page's ES modules (webapp/static/js, from main.js down its static imports) in a sandbox with a stub
// browser, then evaluates one JS expression with JSON arguments and prints the result (usually HTML). Every module's
// exports are visible to the expression by name, as the page's functions were when it was one script. Used by
// tests/test_ui_regressions.py and the other UI tests to check what the page shows, not how it is marked up.
//   node tests/js/render.js '<js expression>'      e.g.  'recordHtml(ARGS[0])'   (ARGS from stdin JSON)
// The modules run through vm.SourceTextModule, which needs --experimental-vm-modules: without it this script runs
// itself again with the flag, so callers keep calling plain `node tests/js/render.js`.
const fs = require("fs"), vm = require("vm"), path = require("path");
if (!vm.SourceTextModule) {
  const r = require("child_process").spawnSync(process.execPath, ["--experimental-vm-modules", "--no-warnings", __filename, ...process.argv.slice(2)],
    { stdio: "inherit" });
  process.exit(r.status ?? 1);
}
const JS = path.join(__dirname, "..", "..", "webapp", "static", "js");
const el = new Proxy(function () {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "classList" ? { toggle() {}, add() {}, remove() {}, contains: () => false }
    : k === "querySelectorAll" ? () => [] : k === "dataset" || k === "style" ? {} : el),
  set: () => true, apply: () => el,
});
const never = () => new Promise(() => {});
const ctx = {
  console, Intl, Math, JSON, Date, Number, String, Array, Object, Set, Map, Promise, URLSearchParams, isNaN, parseFloat, parseInt,
  document: el, location: { search: "", hash: "" }, history: { replaceState() {} }, localStorage: { getItem: () => null, setItem() {} },
  fetch: never, setInterval: () => 0, setTimeout: () => 0, clearTimeout() {}, clearInterval() {}, addEventListener() {}, matchMedia: () => el,
  getComputedStyle: () => ({ getPropertyValue: () => "" }), LightweightCharts: el, marked: { parse: (x) => x }, DOMPurify: { sanitize: (x) => x },
  requestAnimationFrame: () => 0, Headers, ResizeObserver: function () { return el; }, alert() {}, confirm: () => false, window: null,
};
ctx.window = ctx;
// RENDER_DROP=LightweightCharts,marked: run as if those libraries had failed to load (tests the page's fallbacks).
for (const k of (process.env.RENDER_DROP || "").split(",").filter(Boolean)) delete ctx[k];
vm.createContext(ctx);

// The module graph: each file once, by its path; "./x.js?v=123" is the file x.js (the query only busts the browser's cache).
const modules = new Map();
function load(file) {
  if (!modules.has(file)) {
    modules.set(file, new vm.SourceTextModule(fs.readFileSync(file, "utf8"), { context: ctx, identifier: file }));
  }
  return modules.get(file);
}
const resolve = (spec, from) => path.resolve(path.dirname(from), spec.split("?")[0]);

(async () => {
  const main = load(path.join(JS, "main.js"));
  await main.link((spec, ref) => load(resolve(spec, ref.identifier)));
  await main.evaluate();
  // The exports go on one object the test's expression is evaluated against (live: a getter per name), NOT on the
  // sandbox's globals: there a module that forgot an import would still find the name, hiding a ReferenceError the
  // browser throws (audit 2026-11: planchart.js / lineOpts).
  const exportsByName = {}, owner = {};
  for (const [file, m] of modules) {
    for (const name of Object.keys(m.namespace)) {
      if (name in exportsByName || name in ctx) throw new Error(`${path.basename(file)} exports ${name}, which ${owner[name] || "the sandbox"} already has`);
      owner[name] = path.basename(file);
      Object.defineProperty(exportsByName, name, { get: () => m.namespace[name], enumerable: true });
    }
  }
  const input = fs.readFileSync(0, "utf8");
  vm.runInContext(`var ARGS = ${input || "[]"};`, ctx);
  ctx.__exports = exportsByName;
  const x = await vm.runInContext(`with (__exports) { ${process.argv[2]} }`, ctx);   // an async call is awaited
  process.stdout.write(String(x));
})().catch((e) => { process.stderr.write(String(e?.stack || e)); process.exit(1); });

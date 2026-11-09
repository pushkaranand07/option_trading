// One timer for every poller. Each task has an interval and a condition (say, "only on the Plan tab"); the timer
// ticks once a second and starts each task that is due and whose condition holds. A task whose last run has not
// finished (its promise still pending) is skipped that turn, so a slow request is never doubled. While the page is
// hidden nothing runs; when it is shown again each overdue task runs once, then keeps its interval.
// The clock, the timer and the visibility check can be replaced, so a test can drive it without waiting.
export function createScheduler({ tick = 1000, now = () => Date.now(), timer = (fn, ms) => setInterval(fn, ms),
  hidden = () => document.hidden === true } = {}) {
  const tasks = [];
  const start1 = (t) => {
    if (t.running) return;                                // the last run is still going: skip this turn
    const failed = (e) => console.warn(`poll ${t.name} failed`, e);
    let result;
    try { result = t.fn(); } catch (e) { failed(e); return; }   // started right away, as a setInterval callback was
    if (typeof result?.then !== "function") return;           // finished already
    t.running = true;
    Promise.resolve(result).catch(failed).finally(() => { t.running = false; });
  };
  const s = {
    tasks,
    // Adds a task: fn runs every `ms` milliseconds while when() is true (the time passes whether or not it is).
    every(name, ms, fn, when = () => true) { tasks.push({ name, every: ms, fn, when, next: null, running: false }); return s; },
    tick() {
      if (hidden()) return;
      const t0 = now();
      for (const t of tasks) {
        if (t.next == null || t0 < t.next - tick / 2) continue;      // half a tick early counts: the timer drifts
        t.next += t.every;
        if (t.next <= t0) t.next = t0 + t.every;                    // came back from hidden or a frozen tab: run once
        if (t.when()) start1(t);
      }
    },
    start() {
      const t0 = now();
      tasks.forEach((t) => { t.next = t0 + t.every; });
      timer(() => s.tick(), tick);
      try { document.addEventListener("visibilitychange", () => s.tick()); } catch { /* no document: no visibility */ }
      return s;
    },
  };
  return s;
}

"""P3: the page polls through one scheduler (static/js/scheduler.js): one timer, each task with its interval and its
condition, a task never started again while its last run is still going, nothing polled while the tab is hidden.
The intervals and conditions are the ones the page's eight setInterval calls had."""

import json

import pytest

from tests.test_ui_regressions import pytestmark as _needs_node, render

pytestmark = _needs_node


def js(expr: str):
    return json.loads(render(expr))


# A scheduler on a fake clock: T is the time in ms, tick() is what the one timer calls every second.
FAKE = """
var T = 0, TIMERS = 0, HIDDEN = false;
var s = createScheduler({ now: () => T, timer: () => { TIMERS += 1; return 1; }, hidden: () => HIDDEN });
var at = (ms) => { while (T < ms) { T += 1000; s.tick(); } };
var flush = () => new Promise((r) => { let n = 0; const step = () => (++n > 10 ? r() : Promise.resolve().then(step)); step(); });   // settle pending runs
"""


@pytest.mark.unit
def test_the_pollers_keep_their_intervals_and_conditions():
    out = js("""
      const t = (fn) => poller.tasks.find((x) => x.fn === fn);
      const when = (task, tab) => { S.tab = tab; return task.when(); };
      const live = poller.tasks.find((x) => x.name === 'plan tab');
      JSON.stringify({
        n: poller.tasks.length,
        every: [t(loadQuotes).every, t(loadCandles).every, t(loadPlan).every, t(loadChain).every, t(loadStatus).every,
                t(loadRecord).every, live.every, t(pollNseChains).every],
        always: [loadQuotes, loadCandles, loadPlan, loadStatus, pollNseChains].every((f) => ['plan', 'options', 'record', 'map'].every((tab) => when(t(f), tab))),
        chain: ['options', 'plan', 'record'].map((tab) => when(t(loadChain), tab)),
        record: ['record', 'plan', 'options'].map((tab) => when(t(loadRecord), tab)),
        plan: ['plan', 'today', 'record'].map((tab) => when(live, tab)),
      })""")
    assert out == {"n": 8, "every": [3000, 5000, 15000, 4000, 60000, 15000, 15000, 15000], "always": True,
                   "chain": [True, False, False], "record": [True, False, False], "plan": [True, False, False]}


@pytest.mark.unit
def test_the_plan_tab_task_renders_the_session_and_loads_the_live_call():
    src = render("String(poller.tasks.find((x) => x.name === 'plan tab').fn)")
    assert "renderSession()" in src and "loadLive()" in src


@pytest.mark.unit
def test_one_timer_runs_every_task_at_its_own_interval():
    out = js(FAKE + """
      var A = 0, B = 0, ON = true;
      s.every('a', 3000, () => { A += 1; }).every('b', 4000, () => { B += 1; }, () => ON);
      s.start(); at(12000); ON = false; at(24000);
      JSON.stringify({ A, B, TIMERS })""")
    assert out == {"A": 8, "B": 3, "TIMERS": 1}       # a: 3, 6, ... 24 s; b: 4, 8, 12 s, then its condition is false


@pytest.mark.unit
def test_a_task_is_not_started_again_while_its_last_run_is_still_going():
    out = js(FAKE + """
      var CALLS = 0, done;
      s.every('slow', 3000, () => { CALLS += 1; return new Promise((r) => { done = r; }); });
      s.start(); at(9000);
      const during = CALLS;
      done();
      flush().then(() => { at(12000); return JSON.stringify({ during, after: CALLS }); })""")
    assert out == {"during": 1, "after": 2}


@pytest.mark.unit
def test_a_failing_run_is_logged_and_the_task_keeps_running():
    out = js(FAKE + """
      var CALLS = 0, WARNED = 0; console.warn = () => { WARNED += 1; };
      s.every('bad', 3000, () => { CALLS += 1; if (CALLS === 1) throw new Error('x'); return Promise.reject(new Error('y')); });
      s.start(); at(3000);
      flush().then(() => { at(6000); return flush(); }).then(() => JSON.stringify({ CALLS, WARNED }))""")
    assert out == {"CALLS": 2, "WARNED": 2}


@pytest.mark.unit
def test_nothing_is_polled_while_the_page_is_hidden_and_it_catches_up_once_when_shown():
    out = js(FAKE + """
      var A = 0;
      s.every('a', 3000, () => { A += 1; });
      s.start(); at(3000); HIDDEN = true; at(30000);
      const hidden = A;
      HIDDEN = false; s.tick();
      JSON.stringify({ hidden, shown: A })""")
    assert out == {"hidden": 1, "shown": 2}

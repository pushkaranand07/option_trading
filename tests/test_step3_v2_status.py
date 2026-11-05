"""Audit step 3: v2's state is visible. The Plan page says whether today's answer counted (YES / NO / NOT YET, with the
reason); a fingerprint mismatch shows a red banner on every page and is checked when the server starts (never
auto-updated); the settlement script reads v2's registry and leaves out rows before the spec's first session; your
refused Takes are kept as not-taken rows under My picks, outside the stats."""

from datetime import date, datetime

import pytest
import pytz

from tests.test_take_honest_entry import chain, take, world  # noqa: F401  (world is a fixture)
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from tradingagents.research import ai_settle, registry
from webapp import ai_test, server, signals, trade_record as tr

IST = pytz.timezone("Asia/Kolkata")
APP = (server.STATIC / "app.js").read_text(encoding="utf-8")
PAGE = (server.STATIC / "index.html").read_text(encoding="utf-8")
LEGS = [{"action": "BUY", "type": "CE", "strike": 24350.0}]


def t(day, hour, minute=0):
    return IST.localize(datetime(*day, hour, minute))


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_test, "REGISTRY", tmp_path / "v2.jsonl")
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None, raising=False)
    return tmp_path / "v2.jsonl"


def register(day, hour=9, minute=30, status="entered", spec_hash=None, symbol="NIFTY"):
    now = t(day, hour, minute)
    row = registry.register_structure(ai_test.REGISTRY, day=now.date(), symbol=symbol, expiry="09-Nov-2026", spec_hash=spec_hash or ai_test.SPEC_SHA256,
                                      now=now, outcome="trade", structure="long_call", direction="bullish", legs=LEGS, max_risk_indicative=1.0)
    registry.record_entry(ai_test.REGISTRY, registration=row["hash"], now=now, status=status,
                          **({"legs": [LEGS[0] | {"price": 143.4}]} if status == "entered" else {"reason": "ValueError: no two-sided quote"}))


THU = (2026, 11, 5)


@pytest.mark.unit
def test_an_entered_first_answer_counts(reg):
    register(THU)
    s = ai_test.today_status(t(THU, 11))
    assert s["state"] == "YES" and "09:30" in s["reason"] and "later runs" in s["reason"]


@pytest.mark.unit
def test_a_void_entry_does_not_count(reg):
    register(THU, status="void")
    s = ai_test.today_status(t(THU, 11))
    assert s["state"] == "NO" and "void" in s["reason"] and "no two-sided quote" in s["reason"]


@pytest.mark.unit
@pytest.mark.parametrize(("hour", "minute", "state", "word"), [(9, 20, "NOT YET", "09:30"), (11, 0, "NOT YET", "first"), (15, 5, "NO", "missed")])
def test_without_an_answer_it_is_not_yet_or_missed(reg, hour, minute, state, word):
    s = ai_test.today_status(t(THU, hour, minute))
    assert s["state"] == state and word in s["reason"]


@pytest.mark.unit
def test_a_fingerprint_mismatch_means_no(reg, monkeypatch):
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: "the prompt differs from the frozen test")
    s = ai_test.today_status(t(THU, 11))
    assert s["state"] == "NO" and "fingerprint" in s["reason"]


@pytest.mark.unit
def test_weekends_and_days_before_the_first_session(reg):
    assert ai_test.today_status(t((2026, 11, 7), 11))["state"] == "NO SESSION"
    s = ai_test.today_status(t((2026, 11, 4), 11))
    assert s["state"] == "NO" and "before v2" in s["reason"]
    assert ai_test.V2_FIRST_SESSION == date(2026, 11, 5) and tr.V2_FIRST_SESSION is ai_test.V2_FIRST_SESSION    # one definition


@pytest.fixture
def real_prompt(monkeypatch):
    """The real prompt fingerprint, against the spec; the model settings pinned to the spec's (the suite's config differs),
    and a switch to simulate fingerprinted code changing."""
    monkeypatch.setattr(ai_test, "model_settings", lambda: ai_test.read_spec()["version"]["model"])
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    real, changed = ai_test.prompt_fingerprint, {"on": False}
    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "changed" if changed["on"] else real())
    return changed


@pytest.mark.unit
def test_a_real_fingerprint_problem_is_found_and_record_uses_the_same_check(real_prompt):
    assert ai_test.fingerprint_problem() is None                                 # the real code matches the frozen spec
    real_prompt["on"] = True
    assert "fingerprint" in ai_test.fingerprint_problem()
    import inspect
    assert "fingerprint_problem(spec)" in inspect.getsource(ai_test.record)


@pytest.mark.unit
def test_the_red_banner_appears_on_a_mismatch_and_goes_when_restored(real_prompt):
    real_prompt["on"] = True                                                     # fingerprinted code "changed"
    assert "fingerprint" in server.status()["v2"]["fingerprint_problem"]
    assert "fingerprint" in server.v2_startup_check()
    real_prompt["on"] = False                                                    # restored
    assert server.status()["v2"]["fingerprint_problem"] is None and server.v2_startup_check() is None
    assert 'id="v2Warn"' in PAGE and 'class="notice danger"' in PAGE
    loader = APP[APP.index("async function loadStatus"):]
    assert "bannerTexts(S.status)" in loader[:1200] and 'banner("#v2Warn", b.v2)' in loader[:1200] and 'banner("#calWarn", b.calendar)' in loader[:1200]


@pytest.mark.unit
def test_the_plan_page_shows_todays_v2_line():
    assert "v2 aaj ka answer counted" in APP and "v2LineHtml()" in APP[APP.index("function renderStrat("):][:3000]
    assert ".v2-line" in APP[APP.index("async function loadStatus"):][:1500]


@pytest.mark.unit
def test_the_settlement_script_reads_v2_and_leaves_out_rows_before_the_first_session(reg):
    import importlib.util

    spec = importlib.util.spec_from_file_location("ai_test_settle", ai_test.ROOT / "scripts" / "ai_test_settle.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.REAL_REGISTRY == ai_test.REGISTRY and script.REAL_RUN_APPROVED is False
    register((2026, 11, 4), 12, 58, symbol=ai_settle.SYNTHETIC)                 # same spec hash, a day before the first session
    register(THU, symbol=ai_settle.SYNTHETIC)
    sessions = {date(2026, 11, 4), date(2026, 11, 5)}
    counts = ai_settle.interim_counts(ai_test.REGISTRY, ai_test.SPEC_SHA256, sessions, starts=ai_test.V2_FIRST_SESSION)
    assert (counts["questions"], counts["entered"]) == (1, 1)


@pytest.mark.unit
def test_your_refused_take_is_kept_under_my_picks_outside_the_stats(world):
    world["live"]["chain"] = chain(spot=world["call"]["plan"]["underlying_entry_high"] + 30)
    r = take(world)
    assert r.status_code == 400 and "entry zone" in r.json()["detail"]
    o = tr.overview(lambda *a: chain())
    [row] = o["you"]["not_taken"]
    assert "entry zone" in row["reason"] and row["source"] == "you" and o["you"]["stats"]["open"] == 0
    assert "notTakenRowsHtml(d.you.not_taken" in APP and "notTakenRowsHtml(ai.not_taken" in APP

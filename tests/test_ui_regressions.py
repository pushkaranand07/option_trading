"""UI regression tests: what the page SHOWS, checked by running the real webapp/static/app.js in Node (tests/js/render.js)
on sample data. They guard behaviours from steps 1-3 and the trade record so a redesign cannot drop them silently:
My picks and AI #1 stats shown apart, not-taken rows listed with their reason, expired or market-closed runs without a
Take button, the v2 status line, the fingerprint-mismatch banner, the warnings shown as text, what was bought and for
how much. They check text, not markup; the only contract with the markup is [data-view="you"] / [data-view="ai"]."""

import html as _html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_strategist import CHAIN
from webapp import strategist as st

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")


def render(expr: str, *args) -> str:
    out = subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), expr], input=json.dumps(list(args)),
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def text(html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def view(html: str, name: str) -> str:
    start = html.index(f'data-view="{name}"')
    other = html.find('data-view="', start + 10)
    return html[start:other if other != -1 else len(html)]


def stats(net, closed=1, wins=1, losses=0, open_=0):
    return {"closed": closed, "open": open_, "net": net, "wins": wins, "losses": losses, "win_rate": 100.0 * wins / max(closed, 1),
            "avg": net, "best": net, "worst": net, "open_pnl": 0}


def closed_trade(**kw):
    t = {"id": "c1", "source": "you", "status": "closed", "taken_at": "2026-11-04 11:27", "closed_at": "2026-11-04 13:56", "symbol": "NIFTY",
         "expiry": "09-Nov-2026", "strategy": "long_call", "lot": 65, "lots": 1, "net_entry": -140.15, "debit": True,
         "legs": [{"action": "BUY", "type": "CE", "strike": 23900.0, "entry": 140.15, "exit": 165.7}], "spot_at_entry": 23823,
         "spot_at_exit": 23893, "reason": "closed by you", "gross_pnl": 1661.0, "charges": 72.0, "net_pnl": 1589.0, "alerts": []}
    return t | kw


def not_taken(reason, source):
    return {"id": f"n-{source}", "source": source, "status": "not_taken", "taken_at": "2026-11-05 09:30", "symbol": "NIFTY",
            "expiry": "09-Nov-2026", "strategy": "bull_call_spread", "reason": reason, "run_id": "r1", "candidate": 0,
            "legs": [{"action": "BUY", "type": "CE", "strike": 24350.0, "shown_price": 145.65}, {"action": "SELL", "type": "CE", "strike": 24450.0, "shown_price": 102.9}]}


def record(you=None, ai=None):
    you = {"open": [], "closed": [], "not_taken": [], "stats": stats(0, closed=0, wins=0)} | (you or {})
    ai = {"open": [], "closed": [], "not_taken": [], "stats": stats(0, closed=0, wins=0), "v2_stats": stats(0, closed=0, wins=0)} | (ai or {})
    return {"you": you, "ai": ai, "open": you["open"], "closed": you["closed"], "stats": you["stats"]}


@pytest.fixture(scope="module")
def candidate():
    ctx = {"spot": 22600, "days_to_expiry": 2, "expected_move": {"day_pct": 0.01}, "option_chain": {"summary": {}}}
    c = st.rank("NIFTY", built=(ctx, CHAIN | {"summary": {"atm_iv": 14.0}, "expiry": "27-Oct-2099"}), top=1)["candidates"][0]
    return json.loads(json.dumps(c, default=str)) | {"ai_why": "trend and the call wall agree"}


def ai_run(candidate, **kw):
    return {"symbol": "NIFTY", "expiry": "27-Oct-2099", "asked_at": "2026-11-05 09:40", "run_id": "r1", "considered": 16, "trades": [candidate],
            "market_read": "range", "news_read": "", "agents": {"source": "complete analysis", "at": "09:05", "minutes": 7}} | kw


# ---------------------------------------------------------------- the trade record

@pytest.mark.unit
def test_my_picks_and_ai_1_stats_are_shown_apart():
    html = render("recordHtml(ARGS[0])", record(you={"stats": stats(-200, wins=0, losses=1)}, ai={"stats": stats(500)}))
    you, ai = text(view(html, "you")), text(view(html, "ai"))
    assert "−₹200" in you and "₹500" not in you
    assert "₹500" in ai and "−₹200" not in ai


@pytest.mark.unit
def test_not_taken_rows_are_listed_with_their_reason_in_their_own_view():
    html = render("recordHtml(ARGS[0])", record(you={"not_taken": [not_taken("outside this trade's entry zone", "you")]},
                                                ai={"not_taken": [not_taken("the quotes are 130 s old (limit 120 s)", "ai")]}))
    you, ai = text(view(html, "you")), text(view(html, "ai"))
    assert "not taken" in you and "outside this trade's entry zone" in you and "130 s old" not in you
    assert "not taken" in ai and "130 s old" in ai and "outside this trade's entry zone" not in ai


@pytest.mark.unit
def test_a_closed_trade_says_what_was_bought_at_what_price_and_for_how_much():
    you = text(view(render("recordHtml(ARGS[0])", record(you={"closed": [closed_trade()], "stats": stats(1589)})), "you"))
    assert "Kharida" in you and "₹9,109.75" in you and "₹10,770.50" in you and "₹1,589" in you


@pytest.mark.unit
def test_the_warnings_are_shown_as_text_outside_any_collapsed_box():
    html = render("recordHtml(ARGS[0])", record(you={"closed": [closed_trade()], "stats": stats(1589)}))
    shown = re.sub(r"<details.*?</details>", "", html, flags=re.S)            # what is visible without opening anything
    for warning in ("cost model unverified", "recorded trades, not a test"):
        assert warning in text(shown), warning


# ---------------------------------------------------------------- the plan tab

@pytest.mark.unit
def test_an_expired_or_market_closed_run_shows_no_take_button(candidate):
    live = render("aiListHtml('NIFTY', ARGS[0])", ai_run(candidate))
    assert "Take (dummy" in live
    for flag in ({"expired": True}, {"market_closed": True}):
        locked = render("aiListHtml('NIFTY', ARGS[0])", ai_run(candidate, **flag))
        assert "Take (dummy" not in locked and ("expired" in locked or "market band" in locked.lower()), flag


@pytest.mark.unit
def test_a_locked_trade_card_shows_no_take_button(candidate):
    assert "Take this trade" in render("stratHtml(ARGS[0], 'NIFTY')", candidate)
    locked = render("stratHtml(Object.assign(ARGS[0], { _locked: 'run expired' }), 'NIFTY')", candidate)
    assert "Take this trade" not in locked and "run expired" in locked


@pytest.mark.unit
def test_the_v2_status_line_says_the_state_and_the_reason():
    line = text(render("S.status = ARGS[0]; v2LineHtml()", {"v2": {"state": "NO", "reason": "void entry at 09:30: no two-sided quote"}}))
    assert "v2 aaj ka answer counted" in line and "NO" in line and "void entry at 09:30" in line


@pytest.mark.unit
def test_a_fingerprint_mismatch_gives_the_red_banner_and_a_clean_state_gives_none():
    bad = json.loads(render("JSON.stringify(bannerTexts(ARGS[0]))", {"v2": {"fingerprint_problem": "the prompt fingerprint differs"}}))
    assert "the prompt fingerprint differs" in bad["v2"]
    clean = json.loads(render("JSON.stringify(bannerTexts(ARGS[0]))", {"v2": {"fingerprint_problem": None}}))
    assert clean["v2"] is None and clean["calendar"] is None
    page = (ROOT / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="v2Warn"[^>]*class="notice danger"', page)


@pytest.mark.unit
def test_each_warning_appears_once_on_the_record_page_with_both_views_full():
    full = {"closed": [closed_trade()], "stats": stats(1589)}
    html = render("recordHtml(ARGS[0])", record(you=full | {"not_taken": [not_taken("outside this trade's entry zone", "you")]},
                                                ai=full | {"not_taken": [not_taken("the quotes are 130 s old (limit 120 s)", "ai")]}))
    page = text(html)
    assert page.count("cost model unverified") == 1 and page.count("recorded trades, not a test") == 1
    assert 'data-view="you"' in html and 'data-view="ai"' in html                   # both views are on the page, one shown


@pytest.mark.unit
def test_the_calendar_shows_each_day_invested_and_profit_in_its_own_view():
    day4 = [closed_trade(id="a"), closed_trade(id="b", net_entry=-143.85, net_pnl=3028.0, legs=[{"action": "BUY", "type": "CE", "strike": 23850.0, "entry": 143.85, "exit": 191.6}])]
    day5 = [closed_trade(id="c", taken_at="2026-11-05 09:41", closed_at="2026-11-05 09:56", net_entry=-105.10, net_pnl=1899.0,
                         legs=[{"action": "BUY", "type": "CE", "strike": 24450.0, "entry": 105.10, "exit": 135.35}])]
    open5 = [closed_trade(id="d", status="open", taken_at="2026-11-05 09:47", net_entry=-146.85, closed_at=None, net_pnl=None, live={"pnl": 130.0},
                          legs=[{"action": "BUY", "type": "CE", "strike": 24400.0, "entry": 146.85}])]
    html = render("recordHtml(ARGS[0])", record(you={"closed": day4 + day5, "open": open5, "stats": stats(6516, closed=3, wins=3)},
                                                ai={"closed": [closed_trade(id="x", net_pnl=-500.0)], "stats": stats(-500, wins=0, losses=1)}))
    you, ai = text(view(html, "you")), text(view(html, "ai"))
    assert "Day by day" in you and "November 2026" in you
    # 4 Nov: two trades, ₹9,109.75 + ₹9,350.25 = ₹18,460 in, ₹1,589 + ₹3,028 = ₹4,617 out of closed trades
    assert re.search(r"\b4\b.*?₹4,617.*?₹18,460.*?2 trades", you)
    # 5 Nov: one closed (₹1,899) and one open (₹130 now); ₹6,831.50 + ₹9,545.25 = ₹16,376.75 in
    assert re.search(r"\b5\b.*?₹1,899.*?₹16,376\.75.*?2 trades.*?₹130 open", you)
    assert "−₹500" in ai and "₹4,617" not in ai                                     # each view has its own calendar

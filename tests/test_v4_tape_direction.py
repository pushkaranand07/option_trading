"""Forward test v4 (docs/PA_54): today's tape, not the research agents' multi-week rating, decides which direction's trades
the AI may rank. On 2026-11-11 BANKNIFTY rose 2.3% while all 10 runs ranked a bearish trade #1, following an "Underweight"
rating; the intraday rule said WAIT all morning because RSI ran above 70. Synthetic bars and chains; no network, no LLM."""

import numpy as np
import pandas as pd
import pytest

from tests.test_strategist import CHAIN
from webapp import signals, strategist as st

CH = CHAIN | {"summary": {"atm_iv": 14.0, "resistance": 23000, "support": 22000}, "expiry": "27-Oct-2099"}
CTX = {"spot": 22600, "days_to_expiry": 2, "expected_move": {"day_pct": 0.01}, "option_chain": {"summary": CH["summary"]}}


def bars(path, day="2026-11-11"):
    """5-minute bars from 09:15 IST following ``path`` (closes), after a flat previous session."""
    prev = pd.date_range("2026-11-10 09:15", periods=75, freq="5min", tz="Asia/Kolkata")
    now = pd.date_range(f"{day} 09:15", periods=len(path), freq="5min", tz="Asia/Kolkata")
    close = np.r_[np.full(len(prev), path[0]), np.asarray(path, dtype=float)]
    df = pd.DataFrame({"close": close}, index=prev.append(now))
    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"], df["low"], df["volume"] = df[["open", "close"]].max(axis=1) + 2, df[["open", "close"]].min(axis=1) - 2, 0
    return df


def ask(tape, rating="Underweight"):
    seen = {}

    def llm(ctx, shown):
        seen["ctx"], seen["shown"] = ctx, shown
        return st.RankedAnswer(market_read="m", news_read="n", bias="bearish",
                               picks=[st.RankedPick(candidate=k, why="w", confidence="low") for k in range(1, len(shown) + 1)])

    r = st.ai_ranked("NIFTY", llm=llm, agents=lambda s: {"rating": rating, "decision": "trim into strength"}, built=(dict(CTX), CH),
                     moves=lambda s: {}, tape=lambda s: tape)
    return r, seen


@pytest.mark.unit
def test_a_steady_rally_reads_up_even_with_rsi_far_above_70():
    up = bars(np.linspace(60470, 61030, 18))                    # 09:15-10:40, straight up like BANKNIFTY on 2026-11-11
    f = signals.intraday_frame(up)
    assert f["rsi"].iloc[-1] > 70 and signals.intraday_signal(up)["side"] == "WAIT"     # the rule is silent...
    t = signals.today_tape(up)
    assert t["direction"] == "up" and t["checks"] == {"above_vwap": True, "ema9_above_ema21": True, "above_open": True}   # ...the tape is not
    assert t["as_of"] == "10:40" and t["day_open"] == pytest.approx(60470, abs=1)


@pytest.mark.unit
def test_a_fall_reads_down_and_a_round_trip_reads_mixed():
    assert signals.today_tape(bars(np.linspace(25340, 25230, 18)))["direction"] == "down"
    round_trip = np.r_[np.linspace(100, 110, 9), np.linspace(110, 101, 9)]         # up, then most of it given back
    t = signals.today_tape(bars(round_trip))
    assert t["direction"] == "mixed" and t["checks"]["above_open"] is True and t["checks"]["above_vwap"] is False
    assert signals.today_tape(bars([100, 101]))["direction"] == "mixed"             # two bars: too early to say
    assert signals.today_tape(pd.DataFrame())["direction"] == "mixed"


@pytest.mark.unit
def test_an_up_tape_offers_only_bullish_trades_whatever_the_rating():
    r, seen = ask({"direction": "up"}, rating="Underweight")
    assert seen["shown"] and {x["direction"] for x in seen["shown"]} == {"bullish"}
    assert r["trades"] and {t["plan"]["bias"] for t in r["trades"]} == {"bullish"} and r["tape"] == {"direction": "up"}
    assert seen["ctx"]["today_tape"] == {"direction": "up"}                         # the AI is told why


@pytest.mark.unit
def test_a_down_tape_offers_only_bearish_trades_and_a_mixed_one_offers_both():
    _, down = ask({"direction": "down"}, rating="Overweight")
    assert {x["direction"] for x in down["shown"]} == {"bearish"}
    _, mixed = ask({"direction": "mixed"})
    assert {x["direction"] for x in mixed["shown"]} == {"bullish", "bearish"}


@pytest.mark.unit
def test_a_tape_that_cannot_be_read_offers_both_and_says_why():
    def broken(symbol):
        raise RuntimeError("no bars")

    seen = {}
    r = st.ai_ranked("NIFTY", llm=lambda c, s: seen.setdefault("shown", s) and st.RankedAnswer(market_read="m", news_read="", bias="unclear", picks=[]),
                     agents=lambda s: {}, built=(dict(CTX), CH), moves=lambda s: {}, tape=broken)
    assert r["tape"] == {"direction": "mixed", "why": "error: no bars"}
    assert {x["direction"] for x in seen["shown"]} == {"bullish", "bearish"}


@pytest.mark.unit
def test_the_prompt_puts_the_tape_first_and_the_research_as_risk_context():
    assert st.TAPE_ALLOWS == {"up": ("bullish",), "down": ("bearish",)}
    p = " ".join(st.RANK_SYSTEM.split())
    assert "today's tape leads" in p and "multi-week portfolio view" in p
    assert "never as a reason by itself to bet against today's tape" in p and '"Overbought" alone is not a reason' in p

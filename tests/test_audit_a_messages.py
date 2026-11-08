"""Audit (A-messages): every user-facing string of the trade record lives in one ``MESSAGES`` mapping, with the
exact text it had before the move. The expected strings below are copied from the code before the refactor."""

import inspect
import re

import pytest

from webapp import trade_record as tr

M = tr.MESSAGES if hasattr(tr, "MESSAGES") else {}


def say(key, **kw):
    return M[key].format(**kw)


@pytest.mark.unit
@pytest.mark.parametrize("key, kw, text", [
    ("market_closed", {}, "Market band hai: abhi ke prices pe asli order nahi lag sakta. 9:15 ke baad karna."),
    ("exit_market_closed", {}, "Market band hai: band karne ka asli price abhi nahi hai. 9:15 ke baad band karna; "
                               "expiry ke baad trade expiry value pe band hota hai."),
    ("run_expired", {}, "Yeh run expired hai (kisi aur din ka): uske prices aaj ke nahi. Analysis dobara chala, phir Take kar."),
    ("quotes_no_timestamp", {}, "the chain has no timestamp, so its quotes may be old"),
    ("quotes_bad_timestamp", {"ts": "x y"}, "the chain's timestamp 'x y' could not be read"),
    ("quotes_not_today", {"day": "04-Nov-2026"}, "the quotes are from 04-Nov-2026, not today"),
    ("quotes_clock_behind", {"nse_time": "10:00:45", "ahead": 45}, "NSE's time (10:00:45) is 45 s ahead of this computer's clock: check the clock"),
    ("quotes_too_old", {"age": 300, "limit": 120}, "the quotes are 300 s old (limit 120 s)"),
    ("run_not_on_file", {}, "This run is not on file: run the analysis again."),
    ("no_such_candidate", {"n": 3}, "This run has no trade #3."),
    ("prices_unavailable_take", {"error": "boom"}, "Live prices unavailable (boom): not taken. Try again in a moment."),
    ("nse_refused", {"why": "the quotes are 300 s old (limit 120 s)"}, "NSE: the quotes are 300 s old (limit 120 s). Not taken; try again in a moment."),
    ("outside_entry_zone", {"symbol": "NIFTY", "spot": 22650.456, "lo": 22580.0, "hi": 22640.0},
     "NIFTY is at 22,650.46, outside this trade's entry zone 22,580-22,640: not taken."),
    ("leg_unquoted", {"strike": 22600.0, "type": "CE"}, "22,600 CE has no live bid / ask right now: not taken."),
    ("no_trade_in_suggestion", {}, "There is no trade to take in this suggestion."),
    ("bet_exists", {"direction": "bullish", "symbol": "NIFTY", "bet": "abc", "started": "2026-11-05 09:20"},
     "Is disha (bullish) ka ek NIFTY bet pehle se chal raha hai (bet abc, shuru 2026-11-05 09:20). Isi bet mein ek aur trade jodna hai?"),
    ("prices_unavailable", {"error": "boom"}, "Live prices unavailable: boom"),
    ("unknown_trade", {}, "Unknown trade."),
    ("already_closed", {}, "This trade is already closed."),
    ("leg_no_price", {}, "A leg has no live price; try again in a moment."),
    ("reason_reached", {"kind": "target"}, "target reached"),
    ("reason_range_broken", {}, "range broken"),
    ("reason_expired", {}, "expired"),
    ("reason_by_you", {}, "closed by you"),
    ("range_bug_note", {}, "reopened 2026-11-04: it had been closed by a bug that read this range trade's single index target / stop "
                           "as a directional trade's"),
    ("event_exit_pending", {"hit": "stop", "legs": "23450 PE, 23600 PE"}, "exit pending: reached its stop but has no quote for 23450 PE, 23600 PE"),
    ("event_removed", {}, "removed from the record by you"),
    ("v2_before_start", {"version": 3, "first": "2026-11-05"}, "before v3 started (2026-11-05)"),
    ("v2_nothing", {"version": 3}, "v3 registered nothing that day"),
    ("v2_counted_this", {"version": 3}, "v3 counted this trade"),
    ("v2_counted_other", {"version": 3}, "v3 counted a different trade that day"),
    ("v2_recorded", {"version": 3, "outcome": "no_trade"}, "v3 recorded no_trade that day"),
])
def test_each_message_keeps_its_exact_text(key, kw, text):
    assert say(key, **kw) == text


@pytest.mark.unit
def test_the_domain_functions_raise_no_inline_text():
    """No TradeError / BetExists is built from a string literal any more: they all read MESSAGES."""
    src = inspect.getsource(tr)
    assert M and not re.findall(r"(?:TradeError|BetExists)\(\s*f?[\"']", src)

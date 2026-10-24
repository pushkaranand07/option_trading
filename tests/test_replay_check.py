"""Phase 9 replay check: faithful quant numbers pass, invented numbers and validation claims are caught."""

import pytest

from tradingagents.analytics import replay_check as rc

QUANT = """QUANT CONTEXT for RELIANCE as known before the open of 2026-03-23
Market regime (NIFTY, HMM, as of close 2026-03-20): CHOPPY since 2026-02-09 (p calm 0.00, choppy 1.00, stress 0.00).
  next 10 sessions: GARCH 24.6%, GJR 24.5%, EWMA 23.2%
  20-session historical: 22.6%.
  next 10 sessions: ±4.9% = ±Rs 69 on the last close Rs 1,414
30-day ATM implied vol (2026-03-20): 24.4%
  IV percentile over the past year: 95%
  relative_strength: gates rejected; 19 out-of-sample trades, Sharpe -0.09
NO quant signal has passed the gates."""


@pytest.mark.unit
def test_faithful_quotes_pass_including_agent_rounding():
    report = ("The HMM regime is choppy since 2026-02-09. GARCH forecasts 24.6% volatility over the next 10 sessions, "
              "an expected move of about ±4.9% (≈ Rs 69 on Rs 1,414). Implied vol is 24% and sits in the 95% "
              "percentile. None of the quant signals is validated, so this is context only.")
    res = rc.check([report], QUANT)
    assert res.passed, (res.unsupported, res.claims)
    assert res.sentences >= 3


@pytest.mark.unit
def test_an_invented_volatility_number_is_caught():
    res = rc.check(["GARCH expects 31.5% volatility next week."], QUANT)
    assert [n for n, _ in res.unsupported] == ["31.5%"]


@pytest.mark.unit
def test_a_percentage_cannot_borrow_a_trade_count():
    # 19 appears in the tool only as a trade count, never as a percentage.
    res = rc.check(["Implied vol is 19%."], QUANT)
    assert [n for n, _ in res.unsupported] == ["19%"]


@pytest.mark.unit
def test_decimals_must_be_close_but_whole_numbers_may_round():
    assert not rc.check(["EWMA vol is 23%."], QUANT).unsupported            # 23.2 rounded by the agent
    assert rc.check(["EWMA vol is 23.9%."], QUANT).unsupported               # a decimal that is wrong


@pytest.mark.unit
def test_validation_claims_are_flagged_unless_negated():
    claim = rc.check(["Our GARCH-based quant signal is validated and supports a buy."], QUANT)
    assert len(claim.claims) == 1
    fine = rc.check(["No quant signal has passed the gates; the regime model is not validated as a direction signal."],
                    QUANT)
    assert fine.claims == []


@pytest.mark.unit
def test_sentences_without_quant_words_are_not_checked():
    res = rc.check(["Revenue grew 12.7% and the stock trades at 23.5x earnings."], QUANT)
    assert res.sentences == 0 and res.passed


# ---- v2, built from the 2026-10-24 replay's real false alarms

ADANI = """next  5 sessions: ±14.8% = ±Rs 409 on the last close Rs 2,761
next 10 sessions: ±19.4% = ±Rs 537 on the last close Rs 2,761
IV percentile over the past year: 92%"""


@pytest.mark.unit
def test_v2_ignores_other_tools_numbers_and_accepts_agent_rounding():
    text = ("Price is above the 50- and 200-day SMAs (19221.42), RSI ~52, in a CALM regime with ATR 161. "
            "Expected moves from GARCH are roughly ±14.8% over 5 sessions; ±20% two-week expected moves. "
            "IV is in the 92nd percentile.")
    res = rc.check_v2([text], ADANI)
    assert res.passed, (res.unsupported, res.claims)
    assert rc.check([text], ADANI).unsupported                         # v1 flagged the SMA / RSI / ATR numbers


@pytest.mark.unit
def test_v2_still_catches_an_invented_quant_number_and_a_real_claim():
    res = rc.check_v2(["The GARCH forecast is 31.5% for next week. Our quant signal is validated."], ADANI)
    assert [n for n, _ in res.unsupported] == ["31.5%"]
    assert len(res.claims) == 1


@pytest.mark.unit
def test_v2_claims_need_a_quant_subject_and_skip_cross_validated():
    text = ("Here is a focused, cross-validated read using the quant research regime context. "
            "Adani gives investors access to energy transition via a proven incubator model.")
    assert rc.check_v2([text], ADANI).claims == []

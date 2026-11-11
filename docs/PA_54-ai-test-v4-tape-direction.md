# PA-54: Forward test version 4, direction from today's tape

| | |
|---|---|
| **Status** | Built. Spec v4 frozen (`docs/ai_strategist_test_v4.json`). **No trade has counted under v4.** v3 closed with 2 counted trades |
| **Scope** | `webapp/signals.py` (`today_tape`), `webapp/strategist.py` (`today_tape`, `TAPE_ALLOWS`, `ai_ranked`, `RANK_SYSTEM`), `webapp/ai_test.py`, `webapp/static/js/tradeview.js` (one line), tests |
| **Related** | [PA-53](PA_53-ai-test-v3-single-options.md), [PA-52](PA_52-ai-ranked-trades-and-test-v2.md) |
| **Date** | 2026-11-11 |

Research and decision support only, not investment advice. **Cost model unverified.**

## What went wrong

On 2026-11-11 BANKNIFTY rose from 59,741 (previous close) to about 61,100 (+2.3%). All 10 AI runs that morning ranked a **bearish** trade #1. The user lost about ₹4,000.

The cause, from the saved runs (`reports/ai_runs/by_id`, `reports/ai_runs/inputs`):

1. **The direction came from the research agents' rating.** In 33 saved runs with the market open, the #1's direction matched the rating in 30: Overweight gave bullish 15 times, Underweight gave bearish 15 out of 15. The 3 exceptions were Overweight runs on 2026-11-09, a flat day.
2. **That rating is a multi-week portfolio view.** The agents' decision that day: "Underweight: trim into strength, hedge 30–50% for 4–6 weeks with 30–45 day put spreads". It is not a call on the session.
3. **The intraday rule was silent.** It needs RSI between 50 and 70. On a strong trend day RSI runs above 70, so the rule said WAIT all morning (RSI 78–93), and the rating was the only directional input left.
4. **The AI read "overbought" as "will fall".** Every run's market read said "strong uptrend, buyers in control, above VWAP", then ranked a fade, citing the Underweight rating, the choppy regime and the 61,000 call wall. The wall broke at 10:40.

## Decision (the user's, 2026-11-11)

"Whatever problems you find, fix them." Agreed earlier the same day: the direction should come from today's market, which closes v3 and starts a new test and a new count.

## What changed

- **`signals.today_tape(bars)`**: "up" when the last 5-minute bar is above VWAP, EMA 9 is above EMA 21, and price is above today's open. "down" when all three point the other way. "mixed" otherwise, or with fewer than 3 bars today. It reuses `intraday_frame` and leaves out its RSI band on purpose.
- **`ai_ranked`**: a clear tape offers the AI only candidates in its direction (`TAPE_ALLOWS`). A mixed or unreadable tape offers both, as before. The tape goes into the AI's context and the run (`res.tape`).
- **Prompt**: the direction bullet now says today's tape leads. The agents' research is a multi-week view, to be used for news and event risk and for lowering confidence, never by itself to bet against today's tape. "Overbought" alone is not a reason to fade a trend day. The structure bullet (v3) is unchanged.
- **Replay of 2026-11-11** (BANKNIFTY's real 5-minute bars): the tape read "up" at 09:30, 09:45, 10:00, 10:30 and 10:45. Every run that morning would have been offered bullish trades only.
- **Fingerprint**: `5a5fdbb3…` (v3) → `0698d1cae660b037fefc6289875f8028a7d20301614dc56b87f94658187fdf95` (v4). It now also covers `strategist.today_tape`, `signals.today_tape`, `signals.intraday_frame` and `TAPE_ALLOWS`. Function keys carry their module name.
- **Spec v4**: a copy of v3 with a new version number, date, fingerprint, registry (`reports/ai_test/v4/`), `supersedes` v3 (sha `173667b7…`, 2 counted trades) and the user's decision. The stop date (2027-11-01), interim check, pass rule, baselines and power table are unchanged.
- **First session**: 2026-11-12, if this reaches main before 09:30 that day. If merged later, `ai_test.FIRST_SESSION` must move to the first weekday session after the merge.
- **Card**: the AI list says what the tape was and which direction it allowed.

## Not changed

- **The index target and stop.** They are still set from the typical move to expiry, so they are far away for an intraday trade. The user put the stop-loss question aside for later.
- **The intraday rule** (Today tab), the research agents and the model settings.

## Known limits

- **[UNTESTED]** Following the tape is not a proven edge. It removes trades against what the day is visibly doing. It will be whipsawed on a choppy day when the tape flips (a mixed tape then offers both sides).
- **[UNVERIFIED]** The 5-minute bars come from the app's candle source (Yahoo when Dhan is off) and can be delayed.
- The rating still reaches the AI. On a mixed day the AI may still lean on it.
- v3's 2 trades are not settled or reported. Like v1.1 and v2, they stay on file unedited.

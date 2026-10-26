# PA-26 — Pulse evidence score, debit-spread fix, one retry, and an AI track record

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/strategist.py` (`check_structure`, `evidence`, retry in `recommend`, auto-record in `start`), `webapp/trade_record.py` (`source`, auto-settle, `by_score`), `webapp/static/*`, `tests/test_strategist.py`, `tests/test_trade_record.py` |
| **Related** | [PA-23](PA_23-ai-strategist-and-nse-option-chain.md), [PA-25](PA_25-trade-record.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/evidence-score` |
| **Date** | 2026-10-26 |

## 1. Problem

The user's screenshot showed three problems:

1. **A wrongful refusal.** A bear put spread was refused with "the sold 22300 PE has no protective bought option".
   This was a bug: the check only accepted protection *further out of the money*. It wrongly refused every debit
   spread (bear put, bull call), which are limited-risk.
2. **A contradictory answer.** The same answer said "bullish" while proposing a bearish trade.
3. **Low confidence.** The AI rated its own confidence "low".

The user asked for analysis "where confidence is strong, not low", and for a proper record of the suggested strikes.

## 2. Decisions (user)

| Question | Choice |
|---|---|
| Confidence | **Show all suggestions, ranked by a score** (Pulse's own evidence score next to the AI's confidence) |
| Record | **Auto-record every AI suggestion** and settle it by rule, to measure how good the AI is |

## 3. Change

### Safety check fixed

Every sold option must be paired with a bought option of the same type, at any strike. A vertical spread caps the
risk either way. Naked selling is still refused.

### Bias must match the strategy

A bullish bias with a bearish structure (or the reverse) is now a problem. The directions:

- **Bullish:** long call, bull call spread, bull put spread.
- **Bearish:** long put, bear put spread, bear call spread.
- **Neutral:** iron condor.

### One automatic retry

If the first answer fails a check, the AI is asked again with the exact reasons. The result is refused only if the
second answer also fails. The page shows when an answer was corrected.

### Prompt

The prompt now says to prefer the direction most of the evidence agrees on, and to report high confidence only
when most of it agrees.

### Pulse evidence score (`strategist.evidence`)

The score runs from 0 to 100 and is independent of the AI's self-rating. Each check agrees (full points), is neutral
(half) or disagrees (none):

| Check | Points | Agrees when |
|---|---|---|
| Daily trend | 25 | trend tone matches the direction (20/50/200-day averages) |
| Today's intraday rule | 15 | the rule says buy for a bullish trade, sell for a bearish one (wait = neutral) |
| Option prices vs the trade | 20 | selling premium when options are expensive vs the GARCH forecast, buying when cheap |
| Room to the target | 20 | the target is within a typical move to expiry (one-day move × √days); more than twice that disagrees |
| Option walls | 10 | bearish below the call wall, bullish above the put wall, neutral between them |
| Foreign investors | 10 | FII index-futures long share below 35% (bearish) or above 65% (bullish) |

The bands are **Strong** (70 or more), **Moderate** (45–69) and **Weak** (below 45). The AI card shows the score
badge and an expandable list of each check with its reason.

### AI track record

- **Recording.** Every valid suggestion is saved automatically as a one-lot trade with `source: "ai"`, its score and
  the AI's confidence.
- **Settling by rule.** It closes at the live close-out prices when the index reaches the stop or the target (the
  stop if both), or at intrinsic value after expiry, using the last index level seen.
- **Your trades are unchanged.** Trades you take yourself are still only flagged, and you close them.
- **On the Trade Record tab:**
  - suggestions, won / lost, settled P&L and open P&L;
  - a table **by Pulse score**: settled, won / lost, win rate, total and average P&L per band;
  - every suggestion with its strikes, entry → exit, target and stop, status and P&L.

The tab notes that a handful of trades proves nothing; a score band should be judged after dozens of settled
suggestions.

## 4. Tests

- **`tests/test_strategist.py`:**
  - bear put and bull call spreads are accepted;
  - a bias mismatch is refused;
  - an answer wrong twice is refused, and the second call received the reasons;
  - an answer corrected on the retry is accepted;
  - the evidence score is 100 when everything agrees, Weak when the data disagrees, and absent for no trade.
- **`tests/test_trade_record.py`:**
  - an AI suggestion settles itself at the target while your own trade is only flagged;
  - the score bands are counted;
  - a suggestion settles at the stop, and at expiry.

Unit suite passes. Ruff is clean, and `node --check` passes.

## 5. Verification

Live on 2026-10-26 at 10:03:

- **The suggestion:** GPT-5 proposed a bear call spread, sell 22800 CE at 96.95 / buy 22900 CE at 59.80, with
  target 22,550 and stop 22,820. The AI rated its confidence medium.
- **The score:** **92, Strong.** Trend, option prices, room to the target, walls and FII agreed. Today's rule was
  neutral (no setup yet).
- **The record:** it was auto-recorded and marked live at +₹23.
- **Screenshots:** the Plan card with the score breakdown, and the Trade Record tab's AI section.

## 6. Risks and open items

- The score measures agreement in the data, not a proven edge.
- The weights are chosen, not fitted. Revisit them once the track record has enough settled suggestions per band.
- Every "Ask again" records another suggestion, so repeated asks in one session all count.
- Settlement runs only while the web server is running (the background check runs once a minute in market hours).

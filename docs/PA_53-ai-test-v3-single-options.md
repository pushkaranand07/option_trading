# PA-53 — Forward test version 3: single bought options compete with spreads

| | |
|---|---|
| **Status** | Built. Spec v3 frozen (`docs/ai_strategist_test_v3.json`). **No trade has counted under v3.** v2 closed with 2 counted trades |
| **Scope** | `webapp/strategist.py` (`RANK_SYSTEM`, one bullet); `webapp/ai_test.py`; `webapp/trade_record.py` and `webapp/static/app.js` (labels only); `scripts/ai_test_settle.py` (docstring); tests |
| **Related** | [PA-52](PA_52-ai-ranked-trades-and-test-v2.md), [PA-51](PA_51-ai-test-stop-date.md) |
| **Date** | 2026-11-08 |

Research and decision support only, not investment advice. **Cost model unverified.**

## What the user asked

The user trades one lot with ₹15,000 and wants plain "buy a call" / "buy a put" trades as well as spreads. In the 27 saved AI runs (`reports/ai_runs/by_id`) the AI's #1 was a spread every time: bull call 15, bear put 5, bull put 4, bear call 3. A single bought option was in the ranked 8 in 26 of 27 runs, but only at #4 to #8.

## Decisions (the user's, 2026-11-08)

| Question | Choice |
|---|---|
| How to get single-option trades | **Change the main ranking.** The user rejected two alternatives: a separate AI question, and a display-only label |
| Forward test | **Close v2, freeze v3.** A changed prompt is a new test (v2 spec: "changing the prompt ... starts a new test and a new count") |
| Selling a naked call or put | **Not offered.** Margin is about ₹1 lakh+ a lot and the loss is unlimited, so it can't be placed with ₹15,000 |
| Muhurat | **Never a counted session.** The user does not trade it. Its data is still stored |

## What changed

- **Prompt:** the "buying vs selling options" bullet now says that no structure is preferred by default. A single bought option suits a clear, quick move with implied vol that isn't rich. A spread suits a slower or capped move, rich implied vol, or heavy time decay. When the evidence for a quick move is strongest, a single bought option is ranked #1. Candidates, prices, levels, the model and the number ranked (8) are unchanged.
- **Fingerprint:** `6660b707…` (v2) → `5a5fdbb32e977360b8ed0c9fa45107bbd7ddc315299b825d168f79d4fbc89bd4` (v3, in the spec).
- **Spec v3:** a copy of v2 with a new version number, date, fingerprint, registry (`reports/ai_test/v3/`), the Muhurat rule and `supersedes` v2 (sha `30dbdfec…`, 2 counted trades). The stop date (2027-11-01), interim check (2027-05-01), power table, pass rule and baselines are unchanged.
- **First session:** 2026-11-09, if this reaches main before 09:30 that day. If it's merged later, `ai_test.FIRST_SESSION` must move to the first weekday session after the merge.
- **Muhurat:** `today_status` says NO SESSION; `record` registers nothing; the missed-day filler skips it.
- **Labels:** the page and the Trade Record say "v3" (the server sends the version). Data keys (`v2`, `v2_stats`, CSV `is_v2_counted`) keep their names so existing files and CSV readers don't break.

## Known limits

- **[UNKNOWN] Whether the AI will actually rank single options #1 more often.** The prompt invites it but doesn't force it. Check the next runs' #1 by structure.
- A single bought option close to expiry loses value quickly. No structure in this project has a proven edge.
- v2's 2 trades are not settled or reported. Like v1.1, they stay on file unedited.

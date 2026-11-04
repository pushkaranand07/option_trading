# PA-52 — The AI's ranked trades, one list; forward test version 2

| | |
|---|---|
| **Status** | Built. Spec v2 frozen. **No trade has counted under v2.** Questions count from the first weekday session after this is on main |
| **Scope** | `webapp/strategist.py` (`ai_ranked`, `RANK_SYSTEM`, `RankedAnswer`, `start`); `webapp/ai_test.py`; new `docs/ai_strategist_test_v2.json`; `webapp/trade_record.py` (close rule); `webapp/static/*`; tests |
| **Related** | [PA-49](PA_49-ai-strategist-test.md), [PA-51](PA_51-ai-test-stop-date.md), [PA-25](PA_25-trade-record.md), [PA-27](PA_27-pulse-trade-ranking.md) |
| **Date** | 2026-11-04 |

Research and decision support only, not investment advice. **Cost model unverified.**

## What the user asked

The Plan tab showed two answers that could contradict each other: the AI's single suggestion (an iron condor) and Pulse's rule ranking (buy a call), each behind its own typed UNTESTED box. The user wanted one simple flow: run the AI strategy once, let it read everything, including the news and the agents, and see the 8 best trades ranked by the analysis, not by profit size, each with a Take button.

## Decisions (the user's, 2026-11-04)

| Question | Choice |
|---|---|
| Forward test v1.1 | **Close it** and start v2, whose #1 is the trade that counts |
| What the AI reads | First a **fresh full multi-agent run** on every click; changed the same day to **two buttons**: **Complete analysis** runs the research (news, yesterday's market, sentiment, bull / bear debate) once a day and saves it (`reports/ai_runs/research/<symbol>_<date>.json`); **Quick analysis** reuses it, or the 8:30 morning view, with the live data (1-2 minutes) and is refused when neither exists |
| The UNTESTED label | **None.** First one badge, then removed entirely the same day, before any trade counted under v2. Results still say "cost model unverified" |
| How many trades | **Exactly 8**, strongest first |
| The Plan tab | Chart, then **one** button and **one** list. The "Today's call" card, the rule ranking and the OI-wall game plan left the Plan tab |
| When the trades change | **Only on the next run.** Each run is saved (`reports/ai_runs/<symbol>.json`) and shown again after a reload or restart |
| When a taken trade closes | **Whichever comes first:** the index level, or a Super-order leg's premium |

## How it works

1. **Research:** `morning.ai_view` runs the TradingAgents graph for the instrument, which takes several minutes. If it fails, the ranking still runs on the live data and the page says there was no news.
2. **Context:** `build_context` builds it as before, plus today's intraday moves (`today_moves`: open, high, low, the biggest dip and rally, each half hour from 9:15). This run's research replaces the 8:30 view.
3. **Candidates:** `rank` builds every directional defined-risk structure with a live two-sided quote, priced at the bid / ask, with the index target and stop set by its rule. The AI sees them numbered in strategy and strike order, so the list does not suggest a ranking of its own.
4. **Ranking:** one LLM call (`RANK_SYSTEM`) returns exactly 8 numbers, strongest first, each with a reason and a confidence. The code drops unknown or repeated numbers. The AI cannot change a strike, a price, a target or a stop.
5. The #1 goes into the AI track record and into forward test v2.

Each trade shows its exact entry: a Limit price per leg (the bid / ask at the run) and the NIFTY entry zone, with the target and stop in premium and in NIFTY points. The rule ranking (`/api/rank`) still runs on the server, because its #1 is v2's rule baseline, but it is no longer shown.

## Known limits

- **The weaker of the 8 are weak by design.** When the evidence supports only a few trades, the rest are ranked lower with low confidence. Version 1 of this prompt allowed fewer, and ranked 4 of 16 in the live test.
- **Bullish and bearish trades can sit in one list** when the AI reads a range: for example a bull put spread below support and a bear call spread under the call wall.
- **No iron condors in the candidates.** Only directional structures are built.
- **The research agents' own prompts and the news they fetch are not in the prompt hash** (UNVERIFIED in the spec).

## Version 1.1

Closed with **1 trade registered** (2026-11-04, bull call spread). Its spec (`4a7c59bb…`) and its registry (`reports/ai_test/registry.jsonl`) stay on file, unedited. That trade is neither settled nor reported, and it is never pooled with v2. Version 2 writes to `reports/ai_test/v2/`. `scripts/ai_test_settle.py` still reads v1.1's registry and has to be pointed at v2's before v2 is settled.

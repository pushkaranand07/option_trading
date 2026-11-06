# Rating stability test (decision rule fixed before any run)

**Written:** 2026-11-06, before any run of this test. The rule below is not changed after results are seen.

## Question
The AI #1's direction comes from the multi-agent rating: it matched the rating in 19 of 19 saved runs
(4–6 Nov 2026). Does that rating stay the same when the input stays the same?

## Method
- Script: [scripts/research_rating_stability.py](../scripts/research_rating_stability.py).
- **Runs:** N full multi-agent runs of `^NSEI` for today. This is the same graph and config as the app's Complete
  analysis (`webapp/morning.py` `ai_view`).
- **Market closed:** the script refuses to run while the NSE session is open. Prices do not move between runs, so
  a flip is model noise, not new data. News fetched by the agents can still change between runs. Runs start
  together, in parallel, to keep that small, and each run's start time is saved.
- **Same lessons:** each run reads its own copy of one snapshot of the memory log, and settlement is switched off.
  Every run therefore gets the same "lessons from prior decisions", and no run writes to the real memory log.
- **No response cache:** the code sets no LangChain LLM cache, checkpointing is off, and the temperature is the
  provider's default. Each run makes fresh model calls. Provider prompt caching only lowers input cost; outputs are
  still sampled.
- **Nothing registers:** the script never calls the strategist, the forward test, the trade record or the research
  store. It hashes the v2 registry, the research files and the morning plan before and after the runs, and fails
  if any of them changed. The v2 window (09:30–15:00) is closed in any case.
- **Tokens:** every run's token usage is recorded. The first run goes alone (a pilot), and its cost is reported
  before the rest run.

## Direction of a rating
Buy and Overweight count as bullish, Hold as neutral, Underweight and Sell as bearish, and REVIEW as review. A
**flip** is a run whose direction differs from the most common direction across the runs. The flip count is the
number of runs outside the majority.

## Decision rule (5 runs)
| Flips in 5 | Reading | Decision |
|---|---|---|
| 2 or more | the direction is mostly noise | Decision D (stop pursuing the edge) is confirmed |
| 1 | noisy | leans to D |
| 0 | **inconclusive**, not "stable": with a true flip rate of 30%, 0 of 5 happens about 17% of the time | run 10 if the cost allows |

A rule for 10 runs is added in its own commit before any 10-run batch starts.

**Whatever the result, a stable rating is not a correct rating.** At best, this test removes one question. It
cannot show an edge; only the v2 forward test can.

## Saved per run
Rating, direction, start and end time, the token usage, and a short summary of each agent's output: the four
analyst reports, the research manager, the trader, the risk judge and the final decision. These go to
`reports/rating_stability/<date-time>/` (git-ignored).

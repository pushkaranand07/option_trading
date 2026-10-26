# PA-30 — Plan tab: complete AI analysis below the chart, then the AI strategist's trade built from it

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/analysis.py` (new), `webapp/ai.py` (`run_analysis`, `reports`), `webapp/strategist.py` (`build_context` / `recommend` take an analysis; `todays_analysis`; prompt rule), `webapp/server.py` (`POST /api/analysis`, `GET /api/analysis/{symbol}`), `webapp/static/*` (AI analysis section), `tests/test_webapp_analysis.py`, `tests/test_strategist.py` |
| **Related** | [PA-23](PA_23-ai-strategist-and-nse-option-chain.md), [PA-27](PA_27-pulse-trade-ranking.md), [PA-29](PA_29-plan-chart-tools.md) |
| **Pull request** | branch `feature/plan-ai-analysis` (on top of `feature/plan-chart-tools`) |
| **Date** | 2026-10-26 |

## 1. Problem

The user asked for the complete AI analysis below the Plan chart. When it finishes, the AI strategist's trade should
be shown in the second-opinion card.

Before this change:

- The full multi-agent analysis lived only on the AI Analysis tab.
- The Plan tab's second opinion used, at most, an excerpt of the 8:30 AM morning view.

## 2. Change

### One run, two steps (`webapp/analysis.py`)

1. **Analysis.** `ai.run_analysis` runs all four analysts (price & indicators, news, social sentiment,
   fundamentals), then the bull-vs-bear debate, the trader and the risk team. About 15–20 minutes.
2. **Strategy.** `strategist.recommend(..., analysis=run)` runs on the option chain and prices as they are when the
   analysis finishes (about a minute).
   - The analysis goes into the LLM's context as `ai_analysis`: rating, the final decision (3,000 characters), and
     excerpts of the trader's plan, price, news, sentiment and fundamentals reports.
   - The morning view is left out.
   - A new prompt rule: weigh the analysis, but where it disagrees with the data the data wins, and a real conflict
     means lower confidence or `no_trade`.
   - A valid trade goes into the AI track record, like every AI suggestion.

**Run rules:**

- One run per instrument at a time; a second start returns the running one.
- The latest run per instrument is saved to `reports/analysis/<SYMBOL>.json`, which is gitignored. It is saved
  before it shows as finished, so a reload or a restart keeps it.
- If the strategy step fails, the analysis still stands and the error is shown.
- **Ask again** (the quick second opinion) now builds on today's finished analysis too, when there is one.

### Endpoints

- **`POST /api/analysis`** `{symbol, expiry}`: starts a run. Returns 400 if Azure is not set up.
- **`GET /api/analysis/{symbol}`**: returns one of:
  - the running state, with the finished steps;
  - the latest saved run;
  - `{"status": "none"}`.

### Page (Plan tab, between the chart and the AI strategist)

- **Idle:** what the run does and how long it takes, plus a **Run complete AI analysis** button.
- **Running:** a checklist of the 7 stages plus the strategy step, ticked as they finish, and the elapsed time. The
  page polls every 5 s, and the user can leave the page.
- **Done:**
  - the rating;
  - when the run finished and how long it took;
  - report tabs: Final decision, Price & indicators, News, Social sentiment, Fundamentals, Trader's plan;
  - **Run again**;
  - a line naming the trade built from the analysis.
- **Earlier day:** a run from an earlier day is marked as such, and its trade is not put in the second-opinion card.
- **Second opinion.** Today's trade moves into the **Second opinion from the AI** card, unless a newer AI suggestion
  is already there. The card says "Built from the complete AI analysis (above) that finished HH:MM, rated X; priced
  on the chain at HH:MM."

## 3. Checked

- **Unit tests.** `tests/test_webapp_analysis.py` (7):
  - the run order, and the analysis reaching the strategist;
  - one run at a time;
  - a failed analysis, and that it can run again;
  - a failed strategy keeps the analysis;
  - the context carries the analysis instead of the morning view;
  - Ask again uses only today's finished run.
- **Full suite:** 1672 passed, 6 skipped.
- **Browser.** Headless Chrome with real clicks went idle → running (checklist) → done (reports) → trade in the
  second-opinion card, with no page errors.
  - Only the LLM parts were stand-ins: an analysis that steps through its stages in seconds, and a strategist LLM
    that proposes a bear call spread.
  - The live chain, pricing, checks and rendering were the real code.
  - Nothing was written to the AI track record.

A real run was not made: it takes 15–20 minutes of Azure calls, and the user starts it.

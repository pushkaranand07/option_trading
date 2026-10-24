# PA-32 — Web app in seven simple tabs

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/static/index.html`, `webapp/static/app.js`, `webapp/static/style.css`, `webapp/server.py`, new `webapp/quant.py`, `tradingagents/analytics/quant_report.py` (`quant_signal_data`), `tests/test_webapp_quant.py` |
| **Related** | [PA-02](PA_02-webapp.md), [PA-30](PA_30-webapp-lots-and-holidays.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/webapp-tabs` |
| **Date** | 2026-10-24 |

## 1. Problem

The user asked for the whole front end in proper tabs, simple to understand (user). The web app was one long page
(answer, chart, trend, record, BTST, history, a folded option chain and AI panel). None of the research work —
regime, expected move, measured spreads, Market Map, verdicts, paper trading, the nightly job, the trade journal — was
visible in it.

## 2. Decisions (user)

Tabs chosen by the user: **Today, Risk & Volatility, Options, AI Analysis, Market Map, Research, My Trades** (no
separate Help tab; the beginner glossary stays at the bottom of Today). Every card answers one plain question
("How calm is the market?", "How far could it move?", "Are options cheap or expensive?", "What it costs to trade").

## 3. What was built

| Tab | Content |
|---|---|
| Today | The existing page, unchanged in behaviour |
| Risk & Volatility | Regime with probabilities and what it means; expected move for 5 / 10 / 21 days in % and ₹ with the likely range; GARCH vs a simple average; implied vol vs forecast and its 1-year rank — all from `quant_signal_data` (same numbers and timing rule as the agents' report) |
| Options | Live option chain (Dhan) plus the measured bid-ask spread per strike and expiry from the nightly NSE quotes, with "you pay half the spread each time" |
| AI Analysis | The multi-agent analysis, with the Phase 9 result stated |
| Market Map | The Market Map page embedded (and full screen) |
| Research | What is in use; every tested idea with a plain name, verdict (Passed / Rejected / Insight only) and what happened; paper trading; the nightly job's last run |
| My Trades | Add a Dhan tradebook (saved to `reports/journal/`, ≤ 10 MB, .csv/.xlsx/.xls, file name reduced to a plain name), pick a holding period, see results by period, style, instrument, stock, hour, weekday and reason |

Tabs load their data when first opened; the address (`#risk`, `#trades`, …) opens a tab directly. The instrument bar
shows only on the four instrument tabs. Wide tables scroll inside their card on small screens.

## 4. Tests

`tests/test_webapp_quant.py`: spreads read the latest snapshot around the money; research lists ideas in plain words
and hides baselines; risk outside the universe says so; upload names reduced to a plain file name; wrong types and
oversize files refused; upload → list → analysis of a small tradebook. Unit suite: 1,485 passed; ruff clean.

## 5. Verification

The app was run locally and each tab screenshotted in headless Edge with real data (NIFTY regime calm, expected
10-day move ±2.9% / ±₹663, NIFTY Oct-27 spreads 0.93× the cost model, 17 tested ideas, the nightly job's last run).
My Trades was checked with a synthetic tradebook, deleted afterwards.

## 6. Risks and open items

- The option chain still needs Dhan credentials; the measured spreads work without them.
- Research names and one-line results are kept in `webapp/quant.py` (`IDEA_INFO`); a new idea needs a line there or
  it shows its raw name.

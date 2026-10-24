# PA-18 — Market Map 2021–26: regulatory changes and market events measured against NSE data

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `scripts/market_map.py`, `scripts/market_map_template.html`, `docs/market_events_2021_2026.json` (now [data/market_events_2021_2026.json](data/market_events_2021_2026.json)), `scripts/quant_daily_update.py`, `tests/test_market_map.py`, `tests/test_quant_daily.py` |
| **Related** | [PA-19](PA_19-weekend-nse-sessions.md) (weekend-session bug this work exposed), [PA-03](PA_03-quant-foundation-nse-data-store.md) (NSE store), [PA-08](PA_08-regime-detection-hmm.md) (regime shading), [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) and [PA-13](PA_13-daily-refresh-scheduler-fix.md) (daily refresh), [architecture/17-market-map.md](architecture/17-market-map.md), [architecture/11-nse-data-store.md](architecture/11-nse-data-store.md), [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) |
| **Pull request** | #17, #18, #21 (all branch `quant/market-map`) |
| **Date** | 2026-10-24 |

Research and decision support only — not investment advice.

---

## 1. Problem

The user wanted to see what each law change and market event of 2021–2026 actually did to the Indian market: a
timeline, a market network and an event → impact map, built from official and news sources, measured on the project's
own verified NSE data — and kept inside the project rather than published anywhere else.

## 2. Root cause / findings

**News figures vs NSE closes.** NIFTY moves quoted in news reports were cross-checked against the NSE index closes in
the store: **19 of 22 exact**. One event date was corrected (US tariffs → 2025-04-03) and one intraday figure was
removed. The cross-check of the Sunday 2026-02-01 Budget session could not be matched because that session was missing
from the store — the weekend-session bug fixed in [PA-19](PA_19-weekend-nse-sessions.md).

**Contract counts mislead.** NSE changed lot sizes during 2021–26, which makes contract counts jump without any change
in activity. Options activity is therefore measured by **notional value traded**.

**Findings shown on the page** (from [PROGRESS_TRACKER.md](PROGRESS_TRACKER.md)):

| Finding | Number |
|---|---|
| Elections, median NIFTY move on the day | 2.7% |
| Geopolitical events | 2.1% |
| Tax and margin rule changes | ~0.2% |
| A typical day | 0.5% |
| When BANKNIFTY weekly options ended (Nov-2024) | NIFTY options value +33–43%, BANKNIFTY −52–70% |
| Sunday 2026-02-01 Budget, measured on its own session (after PA-19) | NIFTY −1.96% |

## 3. Decisions

- **Timeline, market network and event → impact map (user).**
- **Official and news sources, each event with its source (user).**
- **Everything inside the project, not published elsewhere (user).** The page is a local HTML file under `reports/`,
  gitignored because it embeds NSE data. The events file holds public facts only, no market data.
- **Measure, don't quote:** every impact on the page is computed from NSE files; news text is a description only.
- **Value traded, not contract count** for options activity; BANKNIFTY added alongside NIFTY (commit `8905f34`).
- **No double counting:** a big day detected in the data that a researched event already explains is shown once, as
  that event.
- **Budget FY26 kept as its own event** (2025-02-01): its market-reaction text had been folded into another entry
  and was split back out in PR #21 (commit `76873ba`).

## 4. What was built / changed

| Part | What it does |
|---|---|
| `scripts/market_map.py` (#17) | Builds the series from the NSE store and prices; detects events in the data (8 largest NIFTY falls, 5 largest rises, every NIFTY / BANKNIFTY lot-size change); measures each event's impact; builds the correlation network |
| Impact window | From the first session on or after the event date: NIFTY day / 5-day / 20-day move, India VIX before and 5 sessions after, realised vol 20 sessions before and after, NIFTY and BANKNIFTY options value traded, NIFTY put-call ratio, FII long share, regime. Needs 21 sessions of history |
| Market network | Correlations of daily returns of the 29 stocks, NIFTY, BANKNIFTY, India VIX and FII positioning, for 2021–22, 2023–24, 2025–26; links shown where \|r\| ≥ 0.45 |
| `scripts/market_map_template.html` (#18) | The page: **timeline** (NIFTY, India VIX, NIFTY options value traded, regime shading, event markers), **impact map** (each event by NIFTY day move vs India VIX change; medians by event type), **event → impact ledger**, **market network** |
| Output | `reports/market_map/india-market-map.html` (gitignored); `--note` adds a line to the page's update log |
| Researched events (#18, #21) | `docs/market_events_2021_2026.json`: SEBI, NSE, RBI and Budget / Finance Act changes plus market events, each with a source URL |
| Daily job (#18) | `scripts/quant_daily_update.py` rebuilds the page after the tracker step, every weekday at 19:30 |

The events file was later moved to `docs/data/` in the docs restructure ([PA-26](PA_26-docs-restructure.md)).

## 5. Tests

`tests/test_market_map.py`:
- Impact is measured from the first session on or after the event date.
- Impact needs a month of history and a session after.
- Detected events include the price jump and the lot-size change.
- The page embeds the data safely.

`tests/test_quant_daily.py`: daily-job step order includes `market_map` after `tracker`. Unit suite at PR #21:
1,336 passed.

## 6. Results

- The Market Map page builds from the local store and is rebuilt every weekday.
- Researched events: **54 regulatory changes and 53 market events**. Eight market events describe the same day as an
  RBI or Budget row and were merged into it as its "market reaction" (`source2`), so the file holds **99 entries**:
  54 `regulatory` and 45 `news` (commit `252db3d` said 98 before the Budget FY26 reaction was split back out in PR #21).
  With the 13 data-detected events the page lists 112. The PR #21 body and the tracker's "54 market events" were
  imprecise and are corrected in the tracker.
- Findings: see section 2.

## 7. Verification

- News-quoted NIFTY moves checked against NSE closes (19/22 exact; corrections applied).
- After the weekend-session fix ([PA-19](PA_19-weekend-nse-sessions.md)) the page was rebuilt; the Sunday 2026-02-01
  Budget session is measured on its own session (−1.96%), and its NIFTY close in the store (24,825.45) equals the
  reported close.

## 8. Risks and open items

- Event descriptions and dates come from news and circulars; only the NIFTY moves were cross-checked against NSE.
- The page embeds NSE data and must stay local (gitignored).
- Event impacts on a single day mix the event with everything else that happened that day; the page does not separate
  them.

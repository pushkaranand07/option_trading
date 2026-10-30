# PA-38 — Dataset B (intraday): free-source probe; nothing ingested

| | |
|---|---|
| **Status** | Parked, no usable source (user, 2026-10-30); nothing ingested, no logger started |
| **Scope** | new `tradingagents/research/intraday.py` (bar-end `known_from`, source labelling), `tests/test_research_intraday.py`; `docs/data_catalog.md` |
| **Related** | [data catalog](data_catalog.md), [PA-31](PA_31-research-splits-and-locked-loader.md) (protected range) |
| **Pull request** | branch `data/step-b-intraday-probe` |
| **Date** | 2026-10-28 |

Research and decision support only, not investment advice.

## 1. Problem

The user decided against a Dhan token: dataset B (intraday) uses free sources only. Probe each candidate, measure
depth, coverage, terms, adjustment, timezone and bar labelling, mark it USABLE / LIMITED / NOT USABLE, and stop before
ingesting. No source whose terms forbid storing or research use may be used (user).

Every probe request ended on 2026-10-26: the forward holdout (from 2026-10-27) was not requested. Free intraday
history lies almost entirely in the locked range (2025+), so only counts and timestamps were read from it.

## 2. Results

| Source | Granularity and real earliest bar (requested, not assumed) | Coverage | Terms | Verdict |
|---|---|---|---|---|
| **Yahoo Finance** (via `yfinance` 1.7.0, `^NSEI`) | 1m: 2026-09-29 (8 days per request, ~30 days); 2m: 2026-09-11; 5m / 15m / 90m: 2026-08-31 (60 days); 30m: 2026-08-31, bars aligned to :00 / :30 (first 09:00); 60m: 2024-10-30 (730 days); daily: 2010-01-04 | Spot only (no NSE futures or options intraday) | Yahoo Terms §2(d)(9): you agree not to "access or collect data ... using any automated means ... for any purpose without our express, prior permission"; §2(d)(10) on databases built from its content | **NOT USABLE** (terms) |
| **NSE public pages** (e.g. the intraday chart API) | Current session only (no intraday history offered); not measured, because the only data it serves is inside the forward holdout | Indices and equities, spot only | NSE Terms of Use: "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting) on or in relation to our Website"; Copyright: content may be downloaded "for personal, non-commercial or educational purpose" | **NOT USABLE** (terms) |
| **Free broker APIs** (Upstox, Angel One SmartAPI, Fyers, Zerodha Kite Connect personal) | Not probed: each needs an account and login the user does not have | — | Not read | **NOT PROBED** |

Measured from Yahoo before its terms were read (counts and timestamps only, all in the locked range): timestamps are in
IST and stamp the **bar start** (last 1m bar 15:29, last 5m bar 15:25, last 60m bar 15:15); a 1m session has 375 bars
(4 sessions in the window to 2026-10-26: 1,500 bars; one 5-session window had 1,863 of 1,875). Adjustment, the close
against NSE's bhavcopy and the share of F&O stocks covered were **not measured**: further automated requests would breach
the terms above.

**Usable free intraday depth: none.** Even ignoring terms, the only open-period intraday a free source offered was
Yahoo's 60-minute bars for 2024-10-30 to 2024-12-31; every finer bar is in the locked range.

## 3. What was built

`tradingagents/research/intraday.py`: `bar_known_from` (a bar is public at its end, capped at 15:30), `stamp` (adds
`known_from` and a required `source`), `check_single_source` (refuses a series that mixes sources). Tests:
`tests/test_research_intraday.py` (bar end, never start; source required; no splicing). Nothing is downloaded or stored.

## 4. Decisions

| Question | Choice |
|---|---|
| Ingest any source | No: none passes (user decides) |
| Forward logger (user's step 6) | Not started: it was for "whatever source passes step 1", and none does |

## 5. Open items

Yahoo's 60-minute bars for 2024-10-30 to 2024-12-31 exist but were not collected. The terms question, its quotes and the
inventory of all automated collection are open items in the [data catalog](data_catalog.md). No broker API is probed until
the user has an account and its terms permit storing data for research.

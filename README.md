# Pulse — NSE research and paper-trading tool

**Status: research, unproven.** No trading strategy or signal in this repository has passed its tests. It records
paper trades only and places no orders. It is not financial advice and must not be used to size real-money trades.

Current numbers, as of 6 Nov 2026 unless stated, from the repository's own data (see [Current results](#current-results)):

- **Research models:** no edge found under the stated conditions, **1,532 trials** ([docs/models_v1_refit_report.md](docs/models_v1_refit_report.md)).
- **Forward test of the AI strategist (v3):** started 9 Nov 2026 with 0 counted trades so far, after v2 was closed
  on 8 Nov with 2 counted trades. The test needs at least 50 settled trades before any number is reported, and its stop date is **1 Nov 2027**.
- **Paper record, AI #1:** 4 bets closed, 1 won and 3 lost. **Your picks:** 2 bets closed, 2 won. Both samples are far
  too small to show skill or its absence.

Built by [Pushkar Anand](https://github.com/pushkaranand07), for one person trading by hand on Dhan.

---

## What it does

One web app (FastAPI and a single page) with nine tabs:

| Tab | What it does now |
|---|---|
| **Plan** | The morning plan for NIFTY and BANKNIFTY (trend, last session, expected range, mood, PCR, FII positioning, the AI agents' read). Then the **AI strategist**: you press *Complete analysis* (a fresh multi-agent research run) or *Quick analysis* (reuses today's research). The app builds and prices defined-risk option candidates from the live NSE chain, and one LLM call ranks 8 of them, best first, each with a reason. Each card has a *Take (dummy, 1 lot)* button. |
| **Trade Record** | Paper trades, 1 lot each, in two views: **My picks** (your Takes) and **AI #1** (the AI's top pick of each run, recorded by itself during market hours). The entry is the fresh chain's ask for a bought leg and bid for a sold leg, at the moment of the Take. A monitor marks open trades every 60 seconds and closes them at the target, the stop or expiry. Trades of the same source, index and direction count as one **bet**. Also: a month calendar, refused Takes with their reason, a full detail per trade, and a CSV download. |
| **Today** | Index and stock charts with quotes. |
| **Risk & Volatility** | Calm / choppy / stress regime, the expected move over 5, 10 and 21 days, implied vs forecast volatility. |
| **Options** | Live option chain and measured bid-ask spreads. |
| **AI Analysis** | The multi-agent LLM debate on one instrument (analysts, bull and bear researchers, trader, risk team), ending in a rating with reasons. |
| **Market Map** | SEBI / NSE / RBI / Budget changes and market events since 2021, with their measured effect on NIFTY, India VIX and options. |
| **Research** | Every research test, with its verdict. |
| **My Trades** | Upload a Dhan tradebook and see your own results by holding period, side, stock, entry time and reason. |

There is no live "take this trade now" call on the page any more. The intraday rule still feeds the strategist's
context ([webapp/strategist.py](webapp/strategist.py) `build_context`).

## Architecture

```
NSE archives (F&O, OI, delivery, indices) ──► point-in-time Parquet store ──► research layer (volatility, regime,
                                                                              backtests, gates)      │
NSE live option chain ──► candidates priced at bid / ask ──► one LLM ranks 8 ──► Plan tab cards ──► Take
News, fundamentals ──► multi-agent research (once a day) ───────┘                                   │
                                                                                                     ▼
                               Trade Record (reports/trade_record/trades.json, events.log) ◄── monitor (60 s)
                               Forward test v3 registry (reports/ai_test/v3/registry.jsonl, hash-chained)
```

Key files:

| File | Role |
|---|---|
| [webapp/server.py](webapp/server.py) | FastAPI app, all endpoints; starts the trade monitor |
| [webapp/strategist.py](webapp/strategist.py) | Candidate structures, pricing, target / stop levels, the ranking prompt and call |
| [webapp/trade_record.py](webapp/trade_record.py) | Paper trades: entry and exit gates, marking, settling, bets, stats, CSV |
| [webapp/option_chain.py](webapp/option_chain.py) | NSE option chain (display window and full chain) |
| [webapp/ai_test.py](webapp/ai_test.py) | Forward test v3: registration before entry, prompt fingerprint |
| [webapp/dhan_guard.py](webapp/dhan_guard.py) | The one door to Dhan: market data only, account endpoints blocked |
| [webapp/build_info.py](webapp/build_info.py) | The running commit; the page warns when the server runs older code |
| [webapp/static/js/main.js](webapp/static/js/main.js) | The page: ES modules under `webapp/static/js/` (plain JS, no build step), one scheduler for its polling |
| `tradingagents/` | Multi-agent framework, NSE data vendors, analytics and research code |

## Setup (Windows)

**Requirements:** Python 3.13, Git, PowerShell.

```powershell
git clone https://github.com/pushkaranand07/option_trading.git
cd option_trading
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,quant]" -r webapp\requirements.txt
copy .env.example .env      # then add your keys
```

**Keys in `.env`** (names only; never commit values):

| For | Variables |
|---|---|
| The LLM (one provider) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, or `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, … |
| Which models | `TRADINGAGENTS_LLM_PROVIDER`, `TRADINGAGENTS_DEEP_THINK_LLM`, `TRADINGAGENTS_QUICK_THINK_LLM` |
| Live quotes (optional) | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` (market data only, see below) |
| Macro data (optional) | `FRED_API_KEY` |

`.env` (and `.env.enterprise`, if present) is read only from the repository root (the folder with this README), never
from a parent folder, so a copy or worktree below another project does not pick up its keys. Values already set in
the environment win. `TRADINGAGENTS_NO_DOTENV=1` turns loading of both files off (the tests run that way). [.env.example](.env.example) lists
every variable with a one-line comment.

**Dhan is used for market data only.** Every Dhan request goes through
[webapp/dhan_guard.py](webapp/dhan_guard.py), which allows only quotes, charts, the option chain, the expiry list and
the public security master. Orders, positions, holdings, funds, the trade book and any unknown endpoint are blocked
before a request is sent. There is no override: the old `DHAN_ACCOUNT_ACCESS` switch was removed, so reaching the account would need a code change.
Each Dhan call is logged without the token (`_audit/dhan_calls.log`, or `DHAN_CALL_LOG`).

**Build the NSE data store** (one time; slow, resumable):

```powershell
.venv\Scripts\python.exe scripts\quant_backfill.py
.venv\Scripts\python.exe scripts\quant_build_store.py
.venv\Scripts\python.exe scripts\quant_daily_update.py
```

**Run:**

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 (or http://localhost:8000). The server has **no login**. Binding to 127.0.0.1 keeps other
computers out, but it does not stop a web page open in your own browser from sending requests to it, so the server
also checks every request:

- **Host:** only `127.0.0.1` and `localhost` are served; any other Host header gets 400 (this blocks DNS rebinding).
- **`X-Pulse-Request: 1`:** every request that can change something (anything but GET / HEAD / OPTIONS) must carry
  this header. The page adds it; a form or script on another site cannot add it without the browser asking the
  server first, and the server does not agree.
- **Origin:** when the browser names an Origin (or a Referer) on such a request, it must be `http://127.0.0.1` or
  `http://localhost`.

Never start it with `--host 0.0.0.0` or put it behind a tunnel or proxy: that would open your trade record to the
network.

**Restart the server after every pull or merge.** Python code is loaded once at start-up, so a server left running
keeps the old code. Until you restart it, every page shows a red banner: "This server runs code from <commit> ...
Restart the server to run the latest code." The page also shows a red banner when the trade record cannot be read
(writes are blocked; a damaged file is copied aside first), when auto-settle has failed 3 times in a row, and a notice when a
part of the server is degraded.

**Scheduled jobs** (Windows Task Scheduler, [docs/development/scheduled-job-operations.md](docs/development/scheduled-job-operations.md)):
`scripts\morning_plan.cmd` (8:30 AM) and `scripts\quant_daily_update.cmd` (7:30 PM: NSE data, forecasts, regime,
Market Map, research paper ledger, option quotes).

**Other commands:**

```powershell
.venv\Scripts\python.exe -m cli.main                                    # one multi-agent analysis in the terminal
.venv\Scripts\python.exe scripts\trade_journal.py <tradebook.xlsx> --horizon intraday
.venv\Scripts\python.exe scripts\market_map.py                          # → reports\market_map\india-market-map.html
.venv\Scripts\python.exe scripts\ai_test_backup.py --dest <folder>      # dated copy of the forward-test registry
```

## How evaluation works

- **Research models** (`tradingagents/analytics`, `scripts/quant_*`, `scripts/research_*`): point-in-time data,
  walk-forward splits frozen before testing, costs included, a random-entry comparison and a deflated Sharpe ratio
  that counts every attempt ([tradingagents/analytics/gates.py](tradingagents/analytics/gates.py)).
- **Paper entries are priced honestly:** a Take is refused unless the run is today's, the market is open, the index
  is inside the trade's entry zone, the quotes are under 120 seconds old and every leg has a live bid and ask. The run's
  price is kept beside the filled one. A refused Take is listed with its reason and never counted.
- **Provenance:** every trade row stores its run, candidate, mode, research source, AI rank, quote age, the commit the
  server was running and when the server started. Rows entered while the market was closed are shown but not counted.
- **Forward test v3** ([docs/ai_strategist_test_v3.json](docs/ai_strategist_test_v3.json), frozen; registry
  `reports/ai_test/v3/`; started 9 Nov 2026). It replaced v2
  ([docs/ai_strategist_test_v2.json](docs/ai_strategist_test_v2.json)), closed on 8 Nov 2026 with 2 counted trades,
  because the AI's #1 was a spread in all 27 saved runs; v3 lets single bought calls and puts compete with spreads.
  - What counts: the AI's #1 from the first answer of each session, 09:30–15:00 IST, NIFTY.
  - Registered before entry in an append-only, hash-chained registry. A changed prompt or model (the fingerprint)
    stops a run from counting.
  - Baseline: the same structure at the same strike distances in a random direction, priced from the saved entry chain.
  - Pass rule: the 2.5th percentile of a bootstrap by expiry week must be above 0.
  - Timeline: an interim check on 1 May 2027 (counts only), the stop on 1 Nov 2027.
  - Power: about 260 trades are reachable by the stop. That gives about 48% power at an edge of 20% of max risk and
    about 92% at 30%. **The test can detect only very large edges.**
- **Trade Record stats are not the test.** The AI #1 view records every run's top pick (several a day). Win / loss is
  per bet, and net P&L counts closed trades only.

## Current results

As of **6 Nov 2026**, read from `reports/` (git-ignored, on the author's machine):

| | Trades | Bets | Bets won / lost | Net P&L, closed | Open P&L |
|---|---|---|---|---|---|
| AI #1 (paper) | 12 | 5 (1 open) | 1 / 3 | ₹934.70 | ₹4,842.50 |
| My picks (paper) | 11 | 3 (1 open) | 2 / 0 | ₹17,058.47 | ₹243.75 |

- **Forward test v3:** started 9 Nov 2026. No performance figure is allowed before the stop date.
- **Forward test v2 (closed 8 Nov 2026):** 2 counted trades (5 and 6 Nov), both bull call spreads on the 9 Nov
  expiry. They stay on file and are not settled or reported.
- **Research:** GARCH volatility forecasts beat historical volatility out of sample on 31 of 31 symbols, and the
  regime model separates future volatility (11.5% vs 15.1%). Both are used for the expected move and regime only,
  not as direction signals. Every direction or return idea tested so far failed (model suite v1 closed at 1,532
  trials).

None of this is evidence of an edge. Six closed bets cannot tell skill from luck.

## Known limitations

- **No proven edge.** See above. The forward test may end without an answer.
- **Paper fills are not broker fills.** Exits are checked every 60 seconds, not triggered on the exchange like a Dhan
  Super order. Premium targets and stops assume the same implied volatility and the same day. The cost model has
  not been checked against real Dhan contract notes.
- **The monitor runs inside the server process,** with no supervisor. If the server stops, trades are not settled;
  while it runs, the page shows a red banner after 3 failed checks in a row.
- **Single process, JSON file store.** Run one worker only. The store lock covers file reads and writes only; prices are
  fetched outside it. A malformed row is set aside (named on the page) and left in the file untouched.
- **No authentication.** The Host, Origin and `X-Pulse-Request` checks stop other web pages, not other programs
  on this computer: anything running as you can still call the API. Run it on 127.0.0.1 only.
- **Backups:** the forward-test backup script runs by hand and may point at the same disk.
- **Data sources:** NSE's public endpoints are unofficial and can change or block.
- **Old rows:** some trade rows from 4 Nov 2026 predate fixes (a reopened iron condor, a 15:33 row not counted).
  They are kept as they were, with notes.

## Project structure

| Path | What is there |
|---|---|
| `webapp/` | The web app: server, strategist, trade record, morning plan, forward test |
| `webapp/static/` | The page: `index.html`, `js/` (ES modules), `style.css`, `vendor/` (pinned libraries) |
| `tradingagents/agents/`, `tradingagents/graph/` | Multi-agent LLM framework (from TradingAgents) |
| `tradingagents/dataflows/vendors/nse/` | NSE data: calendar, derivatives, flows, indices |
| `tradingagents/analytics/` | Data store, volatility, regime, backtests, costs, gates, paper ledger, journal |
| `tradingagents/research/` | Forward-test registry |
| `option_backtester/` | Options backtesting engine (adapted from optopsy, AGPL v3) |
| `scripts/` | Data download, store build, research runs, daily and morning jobs, forward-test settle and backup |
| `docs/` | Architecture, features, frozen test specs, one change record per change (`PA_XX`) |
| `tests/` | about 2,600 tests (`pytest`); a Node harness renders the page in tests |
| `cli/` | Terminal interface to the multi-agent analysis |

## Development

```powershell
.venv\Scripts\python.exe -m pytest -q                                   # the suite (integration tests excluded by default)
.venv\Scripts\python.exe -m pytest -q --clock 2026-11-05T20:00:00+05:30 # the suite at a fixed IST time
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe scripts\check_doc_links.py
```

One branch and one pull request per change. This repository is public: data, keys, account details and personal
trades are never committed (`reports/` is git-ignored).

## Changes since the previous README (4 Nov 2026)

From the git log, PRs #94 to #116:

- **Plan:** the AI ranks 8 priced trades (Complete or Quick analysis), with a plain Hinglish line per trade; the old
  live call and game-plan cards were removed.
- **Honest entry:** Takes are priced from a fresh chain at bid / ask, with entry-zone, quote-age and market-hours
  checks; the AI's #1 is recorded through the same path; refused Takes are kept with their reason.
- **Provenance:** run, candidate, mode, research source, commit and server start on every row; an event log.
- **Forward test v2** started 5 Nov 2026, with a startup check and a status banner.
- **Trade Record redesign:** two views, a month calendar, detail per trade, CSV.
- **Root-cause fixes:** far strikes priced from the full chain, one entry gate, one exit gate (market state only),
  one session function and one clock, one same-trade check, rows outside the session not counted, "exit pending"
  when a leg has no quote.
- **One bet:** same source, index and direction form one bet; win / loss per bet; a confirm dialog before adding to
  a running bet.

## Built on open source

- The multi-agent framework started from **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** by
  Tauric Research, Apache License 2.0 ([LICENSE](LICENSE)).
- `option_backtester/` is adapted from **[optopsy](https://github.com/michaelchu/optopsy)**, GNU AGPL v3
  ([option_backtester/LICENSE](option_backtester/LICENSE)).

Market data: NSE India (archives and public APIs), Yahoo Finance, Dhan.

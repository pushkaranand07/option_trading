# Pulse — India market research & options trading assistant

**Built by [Pushkar Anand](https://github.com/pushkaranand07).**

Pulse is a personal research system for trading NIFTY, BANKNIFTY and large NSE stocks. Every weekday it reads the
market before the open, builds a plan, and during the session tells you — in plain English — whether there is a trade
worth taking, how big it should be for **your** risk limit, and why. A team of AI agents adds a news and sentiment
view, and a strict research layer tests every trading idea on years of NSE data before anything is trusted.

> **Research and decision support only — not investment advice.** Pulse never places orders. You decide and trade
> yourself (built for manual trading on Dhan). Past results do not guarantee future ones, and no strategy wins every time.

---

## What it does

| | |
|---|---|
| **Morning plan (8:30 AM)** | For NIFTY and BANKNIFTY: trend, last session, expected range for the day, market mood, put-call ratio, foreign-investor positioning, and the AI agents' read of news and sentiment |
| **Live call (9:45 AM – 3:15 PM)** | "Wait", "No trade right now" with the reason, or "Take this trade" — option, entry, stop, target, and **lots sized so the stop loses at most your limit** |
| **Risk & volatility** | Calm / choppy / stress regime, expected move for 5 / 10 / 21 days in % and ₹, whether options are cheap or expensive |
| **Options** | Live option chain, and what each strike really costs to trade (bid-ask spreads measured from NSE every evening) |
| **AI analysis** | A team of LLM agents — analysts, bull and bear researchers, trader, risk team, portfolio manager — debates one instrument and gives a rating (Buy, Overweight, Hold, Underweight or Sell) with reasons |
| **Market Map 2021 → today** | Every SEBI / NSE / RBI / Budget change and market event since 2021, with its measured impact on NIFTY, India VIX and options trading |
| **Research** | Every trading idea tested, with a plain-English verdict: what works, what failed, and why |
| **My Trades** | Add your Dhan tradebook and see what actually makes or loses money in your own trades — by holding period, buying vs selling, stock, entry time and reason |

All of it lives in one web app with eight simple tabs: **Plan · Today · Risk & Volatility · Options · AI Analysis ·
Market Map · Research · My Trades**.

---

## How it works

```
 NSE archives & APIs ──► point-in-time data store ──► research layer ─────────► web app (8 tabs)
 (F&O, OI, delivery,      (every value dated by when    (volatility, regime,      ▲
  index closes, quotes,    it was actually known)         backtests, verdicts)     │
  board meetings)                                                                  │
 Yahoo / Dhan prices ─────────────────────────────────► live intraday rule ───────┤
 News, fundamentals ──► AI agent team (LLM) ──────────► rating and reasoning ─────┘
                                                                        8:30 AM morning job · 7:30 PM nightly job
```

- **Data you can trust.** Official NSE files (F&O bhavcopy, participant open interest, delivery, index closes,
  option quotes, board meetings) from 2018 (F&O and index files from 2015), including weekend special sessions (Budget days, Muhurat). Every
  value is stored with the date it became known, so no test can peek into the future.
- **Honest research.** Walk-forward testing, real Dhan brokerage and statutory charges, measured slippage, comparison
  against random entry, a deflated Sharpe ratio that counts every attempt, and rules frozen in git before testing.
- **Two scheduled jobs (Windows Task Scheduler).** 8:30 AM builds the morning plan; 7:30 PM downloads the day's NSE
  data, refreshes forecasts, regime, the Market Map, paper trading and option quotes.

## What the research has found

| | Verdict |
|---|---|
| GARCH volatility forecasts → expected move | ✅ **In use** — beat simple historical volatility on 31 of 31 symbols, out of sample |
| Market regime (calm / choppy / stress) | ✅ **In use** — separates future volatility (11.5% vs 15.1%); not a direction signal |
| Measured option spreads | ✅ **In use** — real costs, measured every evening |
| AI agents quoting the research numbers | ✅ **Checked** — 10 full analyses, no number invented |
| More than a dozen trading ideas (trend rules, machine-learning models, option-selling strategies, a pretrained AI forecaster) | ❌ **None has passed yet** — each looked good somewhere and failed on unseen years or after real costs |

That last row is the system doing its job: catching ideas that only work in a backtest before real money is at risk.
Details for every test: [docs/](docs/README.md).

---

## Quick start (Windows)

**Requirements:** Python 3.13, Git, PowerShell.

```powershell
git clone https://github.com/pushkaranand07/option_trading.git
cd option_trading
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev,quant]" -r webapp\requirements.txt
copy .env.example .env      # then add your keys (see below)
```

**Keys in `.env`** (names only — never commit values):

| For | Variables |
|---|---|
| The AI agents (one provider) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` — or `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, … |
| Which models | `TRADINGAGENTS_LLM_PROVIDER`, `TRADINGAGENTS_DEEP_THINK_LLM`, `TRADINGAGENTS_QUICK_THINK_LLM` |
| Live quotes and option chain (optional) | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` |
| Macro data (optional) | `FRED_API_KEY` |

**Build the NSE data store** (one-time; the download is slow and resumable):

```powershell
.venv\Scripts\python.exe scripts\quant_backfill.py           # NSE archives, 2018 → yesterday
.venv\Scripts\python.exe scripts\quant_build_store.py        # point-in-time Parquet store
.venv\Scripts\python.exe scripts\quant_daily_update.py       # forecasts, regime, Market Map, …
```

**Run the app:**

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8000
```

Open **http://localhost:8000** — the Plan tab opens first. Enter your capital and the most you will lose on one
trade; they stay in your browser.

**Schedule the daily jobs:** see [docs/development/scheduled-job-operations.md](docs/development/scheduled-job-operations.md)
(8:30 AM morning plan, 7:30 PM nightly update).

## A trading day with Pulse

| Time (IST) | What happens |
|---|---|
| 8:30 AM | Morning plan built (data + AI view, about 20 minutes) |
| 9:00 – 9:15 | Pre-open; the Plan tab counts down |
| 9:15 – 9:45 | **Wait** — the first half hour is watched, not traded |
| 9:45 AM – 3:15 PM | Live call every 15 seconds: no trade, or a trade sized to your limit |
| 3:15 PM | Exit intraday trades |
| 3:30 PM | Close (index derivatives close at 3:45 PM from 7-Dec-2026) |
| 7:30 PM | Nightly update: NSE data, forecasts, Market Map, paper trading, option quotes |

---

## Other ways to use it

```powershell
# One full AI analysis from the command line
.venv\Scripts\python.exe -m cli.main

# Your own trades, by holding period (file stays in reports/journal/)
.venv\Scripts\python.exe scripts\trade_journal.py reports\journal\tradebook.xlsx --horizon intraday

# The Market Map as a standalone page
.venv\Scripts\python.exe scripts\market_map.py      # → reports\market_map\india-market-map.html
```

## Project layout

| Path | What is there |
|---|---|
| `webapp/` | The Pulse web app (FastAPI + one page, eight tabs) and the morning plan |
| `tradingagents/agents/`, `tradingagents/graph/` | The AI agent team and how they debate |
| `tradingagents/dataflows/vendors/nse/` | NSE data: calendar (holidays, special sessions), derivatives, flows, indices |
| `tradingagents/analytics/` | Research layer: data store, volatility, regime, backtests, costs, gates, paper trading, journal |
| `option_backtester/` | Options backtesting engine |
| `scripts/` | Data download, store build, research runs, daily and morning jobs, Market Map, trade journal |
| `docs/` | Full documentation: architecture, features, guides, and one change record per change (PA_01 …) |
| `tests/` | About 1,500 unit tests |

## Documentation

Start at **[docs/README.md](docs/README.md)** — what the system is, how each part works, how to use it, and why
every decision was made. Progress and open items: [docs/PROGRESS_TRACKER.md](docs/PROGRESS_TRACKER.md).

## Development

```powershell
.venv\Scripts\python.exe -m pytest -q -m unit       # unit tests
.venv\Scripts\python.exe -m ruff check .            # lint
.venv\Scripts\python.exe scripts\check_doc_links.py # every docs link resolves
```

One branch and one pull request per change, with its record in `docs/PA_XX-….md`
([git workflow](docs/development/git-workflow.md)). This repository is public: data, keys, account details and
personal trades are never committed.

---

## Built on open source

Pulse extends two open-source projects, as their licences require us to note:

- The AI agent framework started from **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** by Tauric
  Research — Apache License 2.0 ([LICENSE](LICENSE)).
- `option_backtester/` is adapted from **[optopsy](https://github.com/michaelchu/optopsy)** — GNU AGPL v3
  ([option_backtester/LICENSE](option_backtester/LICENSE)).

Market data: NSE India (official archives and APIs), Yahoo Finance, Dhan.

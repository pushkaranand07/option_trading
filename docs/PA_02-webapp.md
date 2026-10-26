# PA-02 — "Pulse Trader" web app

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `webapp/` (`server.py`, `market_data.py`, `signals.py`, `planner.py`, `ai.py`, `static/`, `requirements.txt`) |
| **Related** | [PA-01](PA_01-india-market-intelligence-baseline.md) · [PA-08](PA_08-relative-strength-model.md) (webapp lint fixes) · [architecture/01-system-overview.md](architecture/01-system-overview.md) · [architecture/06-data-vendors.md](architecture/06-data-vendors.md) · [architecture/09-cli-webapp-and-reports.md](architecture/09-cli-webapp-and-reports.md) |
| **Pull request** | #1 (branch `webapp`); PR commit `f47d680`, on `main` as `b82a6e4` |
| **Date** | 2026-10-22 (merged) |

---

## 1. Problem

The TradingAgents framework runs from a CLI. A single browser page was wanted that shows live quotes, a plain-English
trade plan per instrument, an option-chain read, and can start a full TradingAgents analysis.

## 2. Root cause / findings

Not a fix; new feature. The PR has no description. Facts below come from the code's own docstrings.

- Yahoo Finance is delayed and has no Indian option chains, so the option chain needs Dhan's API.
- Dhan's limits (quotes 1 per second, one unique option-chain request per 3 seconds) are respected by caching each
  response at least that long (`webapp/market_data.py`).

## 3. Decisions

- **Data:** DhanHQ v2 when `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are set in `.env`, Yahoo Finance otherwise.
- **Deep analysis:** TradingAgents on Azure OpenAI (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`,
  `AZURE_OPENAI_DEPLOYMENT_NAME`), run as background jobs the page polls.
- **Plans checked against history:** the same per-bar rules drive the live signal and the backtest, so the win rate
  shown is the record of exactly the rule firing now. The plan says "take this trade" only when that rule has won
  often enough recently, the bigger trend agrees, and the time of day allows it; otherwise it says there is no safe
  trade and why.
- Signals only — the page's own footer says "This is not investment advice and no orders are placed"; the user
  places trades by hand on Dhan.

## 4. What was built / changed

| File | What it does |
|---|---|
| `webapp/server.py` | FastAPI app. Routes: `/`, `/api/status`, `/api/search`, `/api/quotes`, `/api/candles/{symbol}`, `/api/plan/{symbol}`, `/api/optionchain/{symbol}`, `/api/expiries/{symbol}`, `POST /api/ai`, `/api/ai/{job_id}` |
| `webapp/market_data.py` | Dhan / Yahoo data, Dhan scrip master, response cache |
| `webapp/signals.py` | EMA, RSI, ATR; intraday (5-minute) setup, BTST (buy today, sell tomorrow; daily) setup, option-chain view; IST market-open check |
| `webapp/planner.py` | Backtests the rule on the instrument's own history; picks a target (0.5, 0.75, 1, 1.5 × risk); thresholds: at least 10 trades, 60% win rate, +0.05 R average after costs; entries 09:45–14:30, exit by 15:15; option leg at 0.55 delta by default |
| `webapp/ai.py` | Runs the TradingAgents graph as a job and reports each step (analysts, debate, trader, risk) |
| `webapp/static/` | `index.html`, `app.js`, `style.css` |
| `webapp/requirements.txt` | `fastapi>=0.110`, `uvicorn>=0.29` |

Run: `python -m uvicorn webapp.server:app --port 8000`, then open `http://localhost:8000`.
10 files, 1,800 lines added.

## 5. Tests

None added in this PR.

## 6. Results

Not recorded.

## 7. Verification

Not recorded.

## 8. Risks and open items

- Three ruff findings in `webapp/` (ambiguous variable name, duplicate branch, string-split literal) were left
  until `8df7ad0` ([PA-08](PA_08-relative-strength-model.md)).
- The planner's win-rate thresholds are fixed constants; whether they were checked out of sample: not recorded.
- Dhan and Azure credentials live only in the local `.env`; never commit them.
- Research and decision support only; not investment advice.

## Folded-in changes (web app, 2026-10-24 → 26)

Merged here on 2026-10-26; the full texts are in git history.

- **Real lot sizes and holidays.**
  - Hard-coded index lots were wrong (NIFTY 75 → 65 in Jan-2026). They are now read from Dhan's public scrip master,
    taking the most common lot per index (NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120, SENSEX 20), with the
    table as fallback.
  - Market open / closed now comes from the NSE calendar, so holidays are closed and special sessions open.
- **Tabs.** The single page became tabs chosen by the user: Today, Risk & Volatility, Options, AI Analysis,
  Market Map, Research, My Trades. Plan and Trade Record were added later. Every card answers one plain question.
  Tabs load on first open; `#risk`, `#trades`, … open a tab directly.
- **Surviving a dropped connection.** When Yahoo or the internet is unreachable, charts and the live call
  serve the last good candles, kept in memory and in `~/.tradingagents/cache/webapp_candles/`. They are labelled
  "saved (last bar …)" instead of failing with 502. The trigger was the PC's DNS outage on 2026-10-25.
- **Fresher option prices.** Measured live: NSE's free option chain updates about every 45 s and is already
  30–60 s old when fetched.
  - Pulse's own delay was cut from about 60 s to about 25 s: server cache 30 → 10 s, Plan-tab chain refresh
    30 → 15 s.
  - Every price shows NSE's timestamp and its age.
  - Real time needs the Dhan API token.
- **End-of-day data dates.** Risk, Options costs and Research use NSE's end-of-day files, downloaded by the
  7:30 PM job, so on a weekday morning they show the previous close.
  - `quant.freshness()` (NSE calendar) adds a line on each tab: "End-of-day data from Fri 23 Oct — the latest NSE
    close. Next update today 7:30 PM".
  - The line becomes a warning if a nightly run was missed.

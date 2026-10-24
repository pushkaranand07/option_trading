# Web app ("Pulse Trader")

> **Status:** Current.
> **Scope:** `webapp/` — starting it, what the page and its endpoints do, settings, known issues.
> Architecture: [../architecture/09-cli-webapp-and-reports.md](../architecture/09-cli-webapp-and-reports.md).
> **Last verified against the code:** 2026-10-24

---

## 1. What it does

One page for NSE indices and stocks that answers "is there a trade right now?" in plain English. For the instrument
you pick it shows:

- **The answer**: BUY CALL / BUY PUT (indices), BUY / SELL intraday short (stocks), or NO SAFE TRADE / NO TRADE with
  the reasons, plus entry, stop loss and target.
- **The track record** of exactly that rule on the 5-minute history the app loads (59 calendar days from Dhan, a
  60-day period from Yahoo — `market_data.TIMEFRAMES`), after a cost
  allowance: trades, win rate, average result in units of risk (R).
- **A price chart** (5 min, 15 min, 1 hour, daily) with EMA 9 / EMA 21, target and stop lines.
- **Market mood**: trend label from the 20/50/200-day averages, returns, 52-week range, typical daily move.
- **BTST** (buy today, sell tomorrow) setup and its record.
- **Recent sessions** table.
- **Option chain** (Dhan only): OI, change in OI, IV, premiums, PCR (put-call ratio of open interest), max pain,
  OI-based support and resistance.
- **AI deep analysis**: runs the TradingAgents multi-agent graph for today (2–6 minutes per the page text).
- A glossary for beginners.

It shows rule-based setups and AI opinions. It places no orders. It is research and decision support, not investment
advice; past win rates do not guarantee future ones.

## 2. Starting it

From the repository root, with the project environment (see [../development/local-setup.md](../development/local-setup.md)):

```powershell
.venv\Scripts\python.exe -m pip install -e . -r webapp\requirements.txt
.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8000
```

Then open `http://localhost:8000`. `webapp/requirements.txt` adds `fastapi` and `uvicorn`; they are not in
`pyproject.toml`.

The page refreshes itself: quotes every 3 s, candles every 5 s, the plan every 15 s, the option chain every 4 s while
its panel is open, status every 60 s. The theme choice is kept in the browser's `localStorage`.

## 3. Settings

All read from `.env` in the repository root (names only; never commit values).

| Variable | Needed for | Without it |
|---|---|---|
| `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` | Live quotes, candles, the full NSE equity list (Dhan scrip master), expiries and option chains | Yahoo Finance is used (delayed); search offers a built-in Nifty 50 list; the option chain shows an error |
| `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME` | Enabling the AI deep analysis button | `POST /api/ai` answers 400 "Add ... to .env and restart" |
| `TRADINGAGENTS_LLM_PROVIDER` and the model variables | Which provider the AI analysis actually uses (see known issues) | Defaults from `default_config.py` |
| `TRADINGAGENTS_CACHE_DIR` | Where the Dhan scrip master is cached (`dhan-scrip-master.csv`) | `~/.tradingagents/cache` |

The Dhan access token expires every 24 hours; the app turns Dhan error codes `DH-901` / `807`–`810` into "generate a
new one", and `DH-902` / `806` into "no Data API subscription".

## 4. Endpoints

| Method and path | What it returns |
|---|---|
| `GET /` | The page |
| `GET /api/status` | `dhan` (configured), `azure` (configured), `azure_problem`, `market_open`, `indices` |
| `GET /api/search?q=REL` | Up to 12 matches: indices first, then equities starting with, then containing, the text |
| `GET /api/quotes?symbols=NIFTY,RELIANCE` | Per symbol: `ltp`, `prev_close`, `change`, `change_pct`, OHLC, `source` |
| `GET /api/candles/NIFTY?tf=5m&limit=900` | `bars` (time, OHLC, volume) and `source` |
| `GET /api/plan/NIFTY` | `verdict` (action, safe, blockers, win rate, trades, avg R, confidence), `signal`, `target_r`, `option`, `mood`, `record`, `btst` |
| `GET /api/expiries/NIFTY` | Expiry list (Dhan) |
| `GET /api/optionchain/NIFTY?expiry=` | `spot`, `lot`, `step`, `rows` (±15 strikes) and `view` (ATM, PCR, max pain, bias, support, resistance, ATM IV) |
| `POST /api/ai` with `{"symbol": "NIFTY", "analysts": ["market","news","social","fundamentals"]}` | `{"job": "<id>"}` |
| `GET /api/ai/<id>` | `status` (`running` / `done` / `error`), `steps`, `rating`, `reports` |

Indices offered: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX (`market_data.INDICES`).

## 5. Known issues

- **Lot sizes** come from Dhan's public scrip master (most common lot per index, refreshed daily;
  `market_data.index_lots`). If it cannot be fetched, `INDICES` applies (NIFTY 65, BANKNIFTY 30, FINNIFTY 60,
  MIDCPNIFTY 120, SENSEX 20 as of 2026-10-24). Until 2026-10-24 the table was the only source and was out of date
  (NIFTY 75, BANKNIFTY 35, …) ([PA-30](../PA_30-webapp-lots-and-holidays.md)).
- **Market status** follows the NSE calendar (holidays, special sessions; Muhurat days closed in regular hours) via
  `signals.market_open`; before 2026-10-24 any weekday 09:15–15:30 counted as open.
- **The Azure check does not choose the provider.** `/api/ai` requires the three Azure variables, but the graph is
  built with `build_default_config()`, whose provider is `TRADINGAGENTS_LLM_PROVIDER` (default `openai`). To run the
  analysis on Azure, also set `TRADINGAGENTS_LLM_PROVIDER=azure` and the model variables.
- **AI jobs live in memory** and are lost on restart; the analysis always uses today's date.
- **Yahoo fallback** is delayed and has no Indian option chains; the option leg then uses an estimated delta of 0.55
  and shows no premium.
- **Small samples.** The track record covers about two months of 5-minute bars with at most one trade a day; a 60%
  win rate over 10 trades is weak evidence. (A comment in `market_data.py` calls this window "~60 sessions"; it is
  59–60 calendar days.)
- **Separate from the NSE safeguards.** The web app does not use the NSE vendor layer (publication status, dated lot
  sizes, missing-session checks).
- `market_data.dhan_profile()` exists but no endpoint uses it.

## 6. Files

`webapp/server.py`, `webapp/market_data.py`, `webapp/signals.py`, `webapp/planner.py`, `webapp/ai.py`,
`webapp/static/index.html`, `webapp/static/app.js`, `webapp/static/style.css`, `webapp/requirements.txt`.

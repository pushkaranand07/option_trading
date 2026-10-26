# Web app ("Pulse Trader")

> **Status:** Current.
> **Scope:** `webapp/` — starting it, what the page and its endpoints do, settings, known issues.
> Architecture: [../architecture/09-cli-webapp-and-reports.md](../architecture/09-cli-webapp-and-reports.md).
> **Last verified against the code:** 2026-10-24

---

## 1. What it does

Nine tabs, in plain English (since 2026-10-24, [PA-32](../PA_32-webapp-tabs.md), [PA-33](../PA_33-morning-plan.md), [PA-34](../PA_34-ai-strategist-and-nse-option-chain.md)).
**Plan** opens first; the next four follow the index or stock picked at the top; the last three are about the market
and your own trading.

| Tab | Shows | Data |
|---|---|---|
| **Plan** | Today's session (pre-open, open, signal from 9:45, exit by 15:15, close — 15:45 for index F&O from 7-Dec-2026), and for NIFTY and BANKNIFTY: **today's call** (wait / no trade / take this trade, with what one lot costs and loses at the stop; you choose the number of lots) the **AI strategist** (one defined-risk options strategy or none for the picked instrument, with entry / target / stop on the chart, priced per lot at the live bid / ask, with the charges for one lot; each order shown as in Dhan with its target and stop-loss premium, and a ticket per leg — premium chart, depth, how to place it — marked on the chain and the chart, [PA-36](../PA_36-trade-ticket-and-premium-levels.md)), the **NSE option chain** (OI / volume / IV views, per-strike PCR, walls, max pain, the AI's strikes tagged) and the **morning view** (AI rating and reasoning, trend, expected range, last session, regime, PCR, FII positioning, options) | `reports/morning/` (8:30 AM job) + the live rule |
| **Trade Record** | Dummy trades taken from the AI strategist (1 lot each): live P&L at the close-out price, flags when the index reaches the AI's target or stop (you close the trade), history with gross, charges and net P&L, win rate ([PA-38](../PA_38-trade-record.md)) | `reports/trade_record/trades.json` (on this computer) + NSE chain |
| **Today** | Should I trade this today? The rule-based answer, chart, trend, track record, BTST, last 10 sessions, glossary | Dhan / Yahoo (below) |
| **Risk & Volatility** | Market regime (calm / choppy / stress), expected move for 5 / 10 / 21 days in % and ₹ with the likely range, GARCH forecast, implied vol vs forecast | The quant store (validated tools) |
| **Options** | Live option chain (Dhan), and the measured bid-ask spread per strike: what each trade really costs | Dhan; NSE closing quotes captured nightly |
| **AI Analysis** | The multi-agent analysis and its rating | The configured LLM |
| **Market Map** | The 2021–26 law-change and event map | `reports/market_map/` |
| **Research** | What is in use, every idea tested with its verdict in plain words, paper trading, the nightly job's last run | Trial log, paper ledger, `daily_status.json` |
| **My Trades** | Your Dhan tradebook by holding period (intraday / week / month / longer), style, instrument, stock, hour, weekday, reason | Files you add; kept in `reports/journal/` |

The Today tab in detail:

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
the Options tab is open, status every 60 s. Each tab loads its data when first opened; the tab and theme are kept in
the browser's `localStorage`, and the address (`#risk`, `#trades`, …) opens a tab directly.

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
| `GET /api/chain/NIFTY?expiry=` | NSE option chain: `spot`, `atm`, `lot`, `expiry`, `expiries`, `rows` (±15 strikes; OI and volume in units, PCR) and `summary` (PCR, call / put wall, max pain, ATM IV); 404 when the symbol has no NSE options |
| `GET /api/contract?id=OPTIDXNIFTY27-10-2026CE22700.00` | One option's premium through the session (NSE ticks), `high`, `low`, `last`, `prev_close` |
| `POST /api/strategy` with `{"symbol", "expiry"}` | `{"job": "<id>"}` |
| `GET /api/trades`, `POST /api/trades` (body: the strategist's result), `POST /api/trades/<id>/close`, `DELETE /api/trades/<id>` | Trade Record: open trades with live marks and flags, closed trades, totals |
| `GET /api/strategy/<id>` | `status`; when done, `result`: `plan` (the AI's read, strategy, legs, levels, reasoning), `priced` (per lot), `charges_per_lot`, `levels` (per leg: premium at the target and the stop, P&L per lot; spread value), `warnings` or `rejected` |
| `GET /api/optionchain/NIFTY?expiry=` | `spot`, `lot`, `step`, `rows` (±15 strikes) and `view` (ATM, PCR, max pain, bias, support, resistance, ATM IV) |
| `POST /api/ai` with `{"symbol": "NIFTY", "analysts": ["market","news","social","fundamentals"]}` | `{"job": "<id>"}` |
| `GET /api/ai/<id>` | `status` (`running` / `done` / `error`), `steps`, `rating`, `reports` |
| `GET /api/risk/NIFTY` | `regime`, `vol`, `expected_move`, `iv` (`quant_report.quant_signal_data`; only values known before today's open) |
| `GET /api/spreads/RELIANCE` | Latest captured closing bid/ask per expiry around the money, spread %, real ÷ model |
| `GET /api/research` | `in_use`, `tested` (plain name, verdict, result), `paper`, `daily_job`, `approved` |
| `GET /market-map` | The Market Map page (404 until `scripts/market_map.py` has run) |
| `GET /api/journal/files`, `POST /api/journal/upload?name=…` (raw file body, ≤ 10 MB, .csv/.xlsx/.xls), `GET /api/journal?name=…&horizon=all\|intraday\|week\|month\|long` | Your tradebooks and their analysis |

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

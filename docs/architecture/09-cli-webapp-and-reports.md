# 09 — CLI, web app and reports

> **Status:** Current.
> **Scope:** `cli/` (the `tradingagents` command), `webapp/` (the "Pulse Trader" page: `server.py`, `ai.py`,
> `planner.py`, `signals.py`, `market_data.py`, `static/`), and report generation (`tradingagents/reporting.py`,
> `tradingagents/report_html.py`, `tradingagents/compliance.py`, and section "VI. Quant Context" from
> `tradingagents/analytics/quant_report.py`).
> **Last verified against the code:** 2026-10-24

---

## 1. Overview

There are three ways to use the system:

| Entry point | What it is | Uses the agent graph? |
|---|---|---|
| `tradingagents` (CLI, `cli/main.py`) | Interactive or flag-driven analysis of one ticker on one date; also `backtest`, `login`, `logout` | Yes |
| `main.py` | A short Python example: `TradingAgentsGraph(...).propagate("NVDA", "2026-09-01")` | Yes |
| `webapp/` (FastAPI) | A single page of rule-based intraday / BTST setups for NSE instruments, with an optional "AI deep analysis" that runs the graph | Only for the AI panel |

The agent graph itself is described in [02-agent-pipeline.md](02-agent-pipeline.md).

## 2. The CLI (`cli/`)

`pyproject.toml` declares `tradingagents = "cli.main:app"` (a Typer app).

### 2.1 Commands

| Command | Purpose | Options |
|---|---|---|
| `tradingagents` (no subcommand) | Run one analysis | `--ticker`, `--date`, `--analysts` (comma-separated, e.g. `market,news`), `--save/--no-save`, `--show/--no-show`, `--html/--no-html`, `--portfolio <json>`, `--checkpoint/--no-checkpoint`, `--clear-checkpoints` |
| `tradingagents backtest TICKERS --start --end` | Score past decisions over a grid of tickers and dates (`tradingagents/backtest.py`) | `--every` (days, default 7), `--analysts`, `--asset-type stock\|crypto`, `--portfolio`, `--run-id` (continue a sweep) |
| `tradingagents login <plan>` / `logout <plan>` | Sign in / out of a ChatGPT plan for the `chatgpt` provider | — |

### 2.2 Analysis flow

1. **No terminal?** `run_analysis` (`cli/run.py`) lists every flag / environment variable still missing
   (`selections.unattended_gaps`) and exits before calling any model.
2. **Questions** (`cli/selections.py`, prompts in `cli/prompts.py`): Step 1 ticker, 2 analysis date, 3 output
   language, 4 analysts, 5 research depth, 6 LLM provider, 7 quick and deep models, 8 provider-specific thinking /
   reasoning effort. A question is skipped when its flag or `TRADINGAGENTS_*` variable is set. The previous run's
   stable answers are offered as defaults (`cli/prefs.py`, saved to `~/.tradingagents/cli_prefs.json`); ticker and
   date are never remembered.
3. **Config** (`_build_run_config`): copies `DEFAULT_CONFIG` and applies the answers. Research depth sets both debate
   round counts unless `TRADINGAGENTS_MAX_DEBATE_ROUNDS` / `_MAX_RISK_ROUNDS` are set (environment wins).
4. **Run**: builds `TradingAgentsGraph` and streams it into a Rich live view (`cli/display.py`): agent status, messages,
   tool calls, the current report, token counts (`cli/stats_handler.py`) and per-analyst wall time.
5. **Logs while running** go to `<results_dir>/<TICKER>/<DATE>/`: `message_tool.log` (messages and tool calls) and
   `reports/<section>.md` as each section completes. The ticker is checked with `safe_ticker_component`.
6. **Rating check**: if no rating can be read from the final decision, the run is marked for review, not as a position.
7. **Save and show** (`_offer_reports`): the report tree is written by `graph.save_reports(...)` to
   `<results_dir>/reports/<TICKER>_<YYYYmmdd_HHMMSS>/` by default (section 4). The HTML page is written unless
   `--no-html`; at the prompt the user is offered to open it in a browser (not over SSH).

On Windows, a terminal with no console buffer (piped or embedded) cannot host the prompts; the CLI prints one line
telling the user to use Windows Terminal, PowerShell or cmd.exe.

### 2.3 Update notices

`cli/updates.py` checks GitHub releases and the upstream announcements server at most once a day in a background
thread and caches the answer in `~/.tradingagents/update_check.json`. It runs only at an interactive terminal, not in
CI, and is turned off with `TRADINGAGENTS_NO_UPDATE_CHECK=1`.

## 3. The web app (`webapp/`)

"Pulse Trader" — one page that turns market data into a plain-English trade plan checked against the instrument's
own recent history. It is **separate from the agent pipeline**: it has its own data access and its own rules, and it
does not use the NSE vendor layer in [07-india-market-layer.md](07-india-market-layer.md). It places no orders.

### 3.1 Files

| File | Role |
|---|---|
| `server.py` | FastAPI app; loads `.env` from the repository root; serves `static/` and the JSON API |
| `market_data.py` | Prices, quotes, candles, option chains. DhanHQ v2 when `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are set, Yahoo Finance otherwise. In-memory TTL cache (`_TTLCache`) |
| `signals.py` | Indicators (EMA, RSI, ATR, VWAP) and the rules: intraday 5-minute setup, BTST (buy today, sell tomorrow) daily setup, option-chain read (PCR, max pain, OI support / resistance, ATM IV) |
| `planner.py` | Backtests the same rules on recent data and builds the plan: verdict, blockers, target choice, option leg, market mood, track record |
| `ai.py` | Runs the TradingAgents graph as a background thread job the page polls |
| `static/index.html`, `app.js`, `style.css` | The page (TradingView lightweight-charts, marked and DOMPurify from CDNs) |

### 3.2 Endpoints

| Method and path | Returns |
|---|---|
| `GET /` | The page |
| `GET /api/status` | Whether Dhan and Azure are configured, any Azure problem, whether the market is open, the index list |
| `GET /api/search?q=` | Matching indices and NSE equities |
| `GET /api/quotes?symbols=A,B` | Last price, change, OHLC (up to 30 symbols) |
| `GET /api/candles/{symbol}?tf=5m&limit=1500` | Bars for `1m`, `5m`, `15m`, `1h` or `1D`, plus the source (`dhan` / `yahoo`) |
| `GET /api/plan/{symbol}` | The trade plan (`planner.plan`, cached 10 s) |
| `GET /api/expiries/{symbol}` | Option expiries (Dhan only) |
| `GET /api/optionchain/{symbol}?expiry=` | Chain rows ±15 strikes around ATM plus `view` (`signals.option_view`) (Dhan only) |
| `POST /api/ai` `{symbol, analysts}` | Starts an AI job; returns its id. 400 if the Azure variables are missing |
| `GET /api/ai/{job_id}` | Job status, completed steps, rating and report sections |

Any exception inside a data call becomes HTTP 502 with the message as detail.

### 3.3 How the plan is decided (`planner.build_plan`)

- **Intraday rule** (`signals.intraday_frame`): BUY needs all four bull conditions (above VWAP, EMA 9 > EMA 21,
  RSI 50–70, above the day's open) **and** the daily trend (20/50-day EMAs, as of the previous close) up; SELL the
  mirror. Risk per trade = max(1.2 × ATR, 0.2% of price).
- **Backtest** (`backtest_intraday`): entries 09:45–14:30 IST, one trade a day, exit at target, stop (checked first)
  or 15:15; round-trip cost 0.01% of price for indices and 0.04% for stocks. Run for targets of 0.5, 0.75, 1.0 and
  1.5 × risk; `pick_target` takes the highest win rate whose average result is at least `MIN_EDGE = 0.05` R over at
  least `MIN_TRADES = 10` trades.
- **Verdict**: "take the trade" only with no blockers — at least 10 similar trades, win rate at least
  `SAFE_WIN_RATE = 60%`, positive average after costs, not against the daily trend, and inside 09:45–14:30. Otherwise
  "NO SAFE TRADE" or "NO TRADE", with the reasons.
- **Option leg** (indices only): one strike in the money; premium, delta and IV from the Dhan chain when available,
  else delta 0.55 as an estimate.
- **BTST**: at least 3 of 4 daily conditions (2 of 3 without volume); backtested with a 1R target.

### 3.4 AI deep analysis (`ai.py`)

`start()` runs `TradingAgentsGraph(selected_analysts=..., config=build_default_config())` in a daemon thread for
**today's date**, streams it, records the decision with `graph.record_decision`, and stores the status, steps and the
final-decision / analyst / trader reports in an in-memory dict. Jobs are lost when the server restarts.

Details for users (starting it, settings, known issues): [../features/webapp.md](../features/webapp.md).

## 4. Reports

### 4.1 The report tree (`tradingagents/reporting.py`)

`write_report_tree(final_state, ticker, save_path, settings=None, html=True)` is shared by the CLI and
`TradingAgentsGraph.save_reports`, so a programmatic run writes the same files as a CLI run:

| Section heading | Folder | Files |
|---|---|---|
| I. Analyst Team Reports | `1_analysts/` | `market.md`, `sentiment.md`, `news.md`, `fundamentals.md` |
| II. Research Team Decision | `2_research/` | `bull.md`, `bear.md`, `manager.md` |
| III. Trading Team Plan | `3_trading/` | `trader.md` |
| IV. Risk Management Team Decision | `4_risk/` | `aggressive.md`, `conservative.md`, `neutral.md` |
| V. Portfolio Manager Decision | `5_portfolio/` | `decision.md` |
| VI. Quant Context | `6_quant/` | `quant.md` |

Only sections with content are written. `complete_report.md` joins them under a header (`_header`): ticker, analysis
date, rating, generation time, version, providers and models per tier, analysts, debate rounds, data vendors, and
the memory-log note. It always ends with the **compliance section**.

### 4.2 Section VI. Quant Context

`_quant_part` adds the quant layer's context when the ticker is in its research universe
(`quant_report.store_symbol` maps `RELIANCE.NS`, `RELIANCE` or `^NSEI` to the store symbol; anything else returns
`None` and no section is written). The text is `quant_report.quant_signal_text(ticker, trade_date)`: regime,
volatility, implied-volatility and validation lines as known **before the open** of the analysis date, plus a
survivorship note. Any error is swallowed: a report is never lost because the quant store is unavailable. See
[16-quant-context-in-agents.md](16-quant-context-in-agents.md) and [10-quant-layer-overview.md](10-quant-layer-overview.md).

### 4.3 Compliance (`tradingagents/compliance.py`)

`compliance_section(text)` renders `DISCLAIMER` (research and decision support only; not investment advice or a
research report under the SEBI (Research Analysts) Regulations, 2014) plus every finding of `review(text)`: phrases
regulators treat as red flags (assured or guaranteed returns, "risk-free", "sure-shot", certainty claims, claims to
replicate a named investor), with their line. Negated phrases are not flagged. The model's text is never rewritten.

### 4.4 The HTML page (`tradingagents/report_html.py`)

`render_report(...)` writes `complete_report.html`: one self-contained page with inline styles, light and dark
themes, no script, and a Content-Security-Policy `default-src 'none'; style-src 'unsafe-inline'`. Agent text is
rendered as CommonMark (`markdown-it-py`) with raw HTML and images turned off, so nothing a model wrote can inject
markup or load a remote asset. The compliance section is included.

## 5. Related documents

- [01-system-overview.md](01-system-overview.md)
- [04-llm-providers-and-configuration.md](04-llm-providers-and-configuration.md) — providers, `TRADINGAGENTS_*` variables
- [05-memory-reflection-and-checkpoints.md](05-memory-reflection-and-checkpoints.md) — checkpoints, the memory log
- [../development/local-setup.md](../development/local-setup.md)

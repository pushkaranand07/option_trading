# Analysis pipeline (multi-agent analysis of one ticker)

> **Status:** Current.
> **Scope:** running a TradingAgents analysis from `main.py`, the `tradingagents` CLI or Python: inputs,
> outputs, settings, cost, known issues.
> **Last verified against the code:** 2026-10-24

---

## 1. What it does

Given a ticker and a date, a team of LLM agents studies the instrument and returns a rating: **Buy,
Overweight, Hold, Underweight or Sell**, or **REVIEW** when no rating could be read from the final decision.

Four analysts (market, sentiment, news, fundamentals) write reports; a bull and a bear researcher argue; a
research manager writes a plan; a trader proposes a trade; three risk analysts argue about it; a portfolio
manager decides. How it is built: [02 Agent pipeline](../architecture/02-agent-pipeline.md) and
[03 Agents and tools](../architecture/03-agents-and-tools.md).

The output is research and decision support, not investment advice. Nothing places an order. Every saved
report ends with a SEBI-aware disclaimer (`tradingagents/compliance.py`).

## 2. How to run it

Step-by-step for Windows: [Running an analysis](../guides/running-an-analysis.md).

| Way | Command | Notes |
|---|---|---|
| CLI, interactive | `tradingagents` or `python -m cli.main` | Asks for ticker, date, analysts, depth, provider, models; shows live progress |
| CLI, no questions | `tradingagents --ticker RELIANCE.NS --date 2026-10-23 --analysts market,news,fundamentals --save --no-show` | Provider, models, language and depth must then come from `TRADINGAGENTS_*` variables |
| Script | `python main.py` | Runs `propagate("NVDA", "2026-09-01")` with `debug=True`; edit the file to change ticker or date |
| Python | `TradingAgentsGraph(config=...).propagate(ticker, date)` | Returns `(final_state, signal)`; call `save_reports()` for the report files |
| Many dates | `tradingagents backtest RELIANCE.NS --start ... --end ... --every 7` | Scores ratings over a grid, in its own memory log under `results_dir/backtest/<run_id>/` |

CLI flags on the main command (`cli/main.py`): `--ticker`, `--date`, `--analysts`, `--save/--no-save`,
`--show/--no-show`, `--html/--no-html`, `--checkpoint/--no-checkpoint`, `--clear-checkpoints`, `--portfolio`.
Run with no terminal, the CLI lists every flag or variable still missing before calling any model
(`unattended_gaps` in `cli/selections.py`).

## 3. Inputs

| Input | Rules |
|---|---|
| Ticker | Yahoo Finance symbol with exchange suffix: `RELIANCE.NS`, `^NSEI`, `^NSEBANK`, `AAPL`, `BTC-USD`. Letters, digits and `. _ - ^ =`, at most 32 characters (`is_valid_ticker_input`) |
| Date | `YYYY-MM-DD`, today or earlier. A future date is refused |
| Analysts | Any of `market`, `sentiment` (key `social`), `news`, `fundamentals`; at least one. Fundamentals is not offered for crypto |
| Research depth (CLI) | Shallow = 1, Medium = 3, Deep = 5; sets both `max_debate_rounds` and `max_risk_discuss_rounds` |
| Portfolio (optional) | JSON file for `--portfolio`: `cash`, `currency`, `positions` (each `ticker`, `quantity`, optional `average_price`) (`tradingagents/portfolio.py`) |

Every data tool is capped at the analysis date, so an earlier date gives a historical run. Two exceptions noted
in the code: social-media feeds and the company profile are not archived (see section 8).

## 4. Outputs

- **Signal** — the 5-tier rating or `REVIEW` (printed by `main.py`; shown by the CLI, which warns when it is
  `REVIEW`).
- **Saved report** (CLI "Save report?" or `save_reports()`): `results_dir/reports/<TICKER>_<YYYYMMDD_HHMMSS>/`
  with `complete_report.md`, `complete_report.html`, and folders `1_analysts`, `2_research`, `3_trading`,
  `4_risk`, `5_portfolio`, plus `6_quant/quant.md` when the ticker is in the quant universe.
- **State log** — `results_dir/<TICKER>/TradingAgentsStrategy_logs/full_states_log_<date>.json`.
- **Memory log entry** — the decision, pending, in `~/.tradingagents/memory/trading_memory.md`; settled by a
  later run once 5 trading days have traded ([05](../architecture/05-memory-reflection-and-checkpoints.md)).
- **CLI only** — `results_dir/<TICKER>/<date>/message_tool.log` and `reports/<section>.md`.

`results_dir` defaults to `~/.tradingagents/logs` (on Windows, `C:\Users\<you>\.tradingagents\logs`).

## 5. Files

| File | Role |
|---|---|
| `main.py` | Minimal script |
| `cli/main.py`, `cli/run.py`, `cli/selections.py`, `cli/prompts.py` | CLI commands, run loop, questions |
| `tradingagents/graph/trading_graph.py` | `TradingAgentsGraph`, `propagate()` |
| `tradingagents/agents/` | The agents and tools |
| `tradingagents/reporting.py`, `tradingagents/report_html.py` | Report tree and HTML page |
| `tradingagents/backtest.py` | The `backtest` command |

## 6. Settings

All in `tradingagents/default_config.py`, overridable by `TRADINGAGENTS_*` variables in `.env`
([04](../architecture/04-llm-providers-and-configuration.md)). The ones that matter most for a run:

| Setting | Default | Effect |
|---|---|---|
| `llm_provider`, `quick_think_llm`, `deep_think_llm` | `openai`, `gpt-6-luna`, `gpt-6-sol` | On this machine `.env` sets `azure` and `gpt-5` for both |
| `max_debate_rounds`, `max_risk_discuss_rounds` | 1, 1 | More rounds = more LLM calls |
| `max_tool_rounds` | 20 | Cap on each analyst's tool rounds |
| `output_language` | English | Language of reports |
| `checkpoint_enabled` | False | Resume a crashed run |
| `holding_period_days` | 5 | Window used to score the decision later |
| `data_vendors` | yfinance and others | Where data comes from ([06](../architecture/06-data-vendors.md)) |

## 7. Cost

Each analysis makes many LLM calls. With the default settings and all four analysts, the minimum is **12**
model calls: one each for the four analysts' final turns, Bull, Bear, Research Manager, Trader, the three risk
analysts and the Portfolio Manager. On top of that:

- one more call per tool round of the Market, News and Fundamentals analysts (up to `max_tool_rounds` = 20
  each, plus a wrap-up call);
- one reflection call per past decision settled during the run;
- a retry as free text whenever a structured-output call fails;
- each extra debate round adds 2 calls (research) and 3 calls (risk).

The CLI shows the live count of LLM calls, tool calls and tokens (`cli/stats_handler.py`). Token use and money
cost per run are not recorded in the repository. Measured once: the Phase 9 replay's first run (2 debate rounds,
GPT-5) took 10.0 minutes ([PA-25](../PA_25-phase9-replay-and-report-wording.md)).

## 8. Known issues (from code comments and code)

- **Sentiment is not point-in-time.** StockTwits and Reddit serve recent items and are not archived, so a
  historical run's sentiment inputs are not as of the analysis date (`agents/analysts/sentiment_analyst.py`).
- **Company profile is today's.** For a historical date only the current company name is given, marked as such;
  sector and exchange are left out (`agents/context.py`).
- **Not reproducible bit-for-bit.** `temperature` can reduce variation, but reasoning models largely ignore it
  and no setting makes output identical across runs (`default_config.py`).
- **Azure: one deployment for both tiers.** `AZURE_OPENAI_DEPLOYMENT_NAME` is used for quick and deep alike
  (`llm_clients/azure_client.py`).
- **Azure: reasoning effort not applied.** `TRADINGAGENTS_OPENAI_REASONING_EFFORT` is forwarded only for the
  `openai` and `chatgpt` providers (`llm_clients/factory.py`).
- **News Analyst prompt** does not mention `get_india_fii_dii_flows`, although the tool is offered to it.
- **REVIEW.** If the Portfolio Manager's decision has no readable rating the run is recorded as `REVIEW`, not
  as Hold; re-run or read the decision yourself (`agents/rating.py`).
- **Windows console.** The interactive CLI needs a real console buffer; from a piped or embedded terminal it
  stops with "no Windows console available" (`cli/main.py`). Use flags, or run from Windows Terminal,
  PowerShell or cmd.exe.
- **A run's own decision** is settled only by a later run (or `settle_pending()`), not by itself.

# Running an analysis

> **Status:** Current.
> **Scope:** step-by-step: run one TradingAgents analysis on Windows, pick the ticker and date, find the results.
> **Last verified against the code:** 2026-10-24

---

The result is research and decision support, not investment advice. Each run makes many LLM calls (at least
12 with default settings), so it costs money on a paid provider. Details:
[Analysis pipeline](../features/analysis-pipeline.md).

## 1. Before the first run

1. Open PowerShell or Windows Terminal (not a piped or embedded terminal: the interactive questions need a real
   console).
2. Go to the repository folder, e.g. `cd "C:\coding\stock market\TradingAgents"`.
3. Check that `.env` exists in that folder. On this machine it already selects Azure OpenAI GPT-5 for both
   model tiers. Never paste its contents anywhere public.
4. Check Python works: `.venv\Scripts\python.exe --version` (Python 3.11 or newer is required by
   `pyproject.toml`).

## 2. Pick the ticker

Use the Yahoo Finance symbol, with its exchange suffix:

| You want | Type |
|---|---|
| An NSE stock | `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS` |
| A BSE stock | `RELIANCE.BO` |
| NIFTY 50 index | `^NSEI` |
| Bank NIFTY index | `^NSEBANK` |

For NSE stocks and indices the agents also get the NSE tools (FII/DII flows, lot size and expiries, delivery %,
index-volume check). For NSE F&O stocks, NIFTY and BANKNIFTY they also get the quant report.

In `cmd.exe`, `^` is a special character: write `"^NSEI"` in quotes. In PowerShell it works as is.

## 3. Pick the date

- Format `YYYY-MM-DD`, today or earlier. A future date is refused.
- Today's date = a normal analysis. An earlier date = a historical run: tools serve data only up to that date
  (social-media posts are the exception; they are always recent).

## 4. Run it

**Option A — interactive CLI** (asks each question; Enter accepts the default):

```powershell
.venv\Scripts\python.exe -m cli.main
```

**Option B — no questions** (everything given as flags; provider, models, language and depth come from `.env`
or `TRADINGAGENTS_*` variables):

```powershell
.venv\Scripts\python.exe -m cli.main --ticker RELIANCE.NS --date 2026-10-23 --analysts market,sentiment,news,fundamentals --save --no-show
```

Each flag skips only its own question; anything not set is still asked. To be asked nothing, `.env` also needs
`TRADINGAGENTS_OUTPUT_LANGUAGE`, `TRADINGAGENTS_MAX_DEBATE_ROUNDS` and `TRADINGAGENTS_MAX_RISK_ROUNDS`. Run
without a terminal (e.g. from a scheduler), the CLI lists whatever is missing before it calls any model.

**Option C — `main.py`**: open `main.py`, change `"NVDA"` and `"2026-09-01"` in the `propagate(...)` line, then
run `.venv\Scripts\python.exe main.py`. It prints every agent message and the final rating.

Optional flags: `--checkpoint` (resume if the run crashes), `--portfolio holdings.json` (your holdings and cash;
keep that file out of the repository), `--no-html` (skip the HTML page).

## 5. Read the result

The final rating is one of **Buy, Overweight, Hold, Underweight, Sell**. **REVIEW** means no rating could be read:
re-run, or read the decision text yourself.

## 6. Where results go

All under `C:\Users\<you>\.tradingagents\` unless `TRADINGAGENTS_RESULTS_DIR` or `TRADINGAGENTS_MEMORY_LOG_PATH`
is set:

| What | Where |
|---|---|
| Saved report (open the HTML in a browser) | `logs\reports\<TICKER>_<YYYYMMDD_HHMMSS>\complete_report.html` and `complete_report.md` |
| Each agent's section | the same folder, `1_analysts\` … `5_portfolio\` (and `6_quant\` for quant-universe tickers) |
| Full state of the run (JSON) | `logs\<TICKER>\TradingAgentsStrategy_logs\full_states_log_<date>.json` |
| CLI message log | `logs\<TICKER>\<date>\message_tool.log` |
| Memory log (past decisions and lessons) | `memory\trading_memory.md` |

The decision is scored 5 trading days later, the next time any analysis runs, and the lesson is shown to future
runs ([Memory, reflection and checkpoints](../architecture/05-memory-reflection-and-checkpoints.md)).

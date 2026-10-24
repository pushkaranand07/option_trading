# Memory, reflection and checkpoints

> **Status:** Current.
> **Scope:** `tradingagents/memory/` (memory log, settlement, reflection), checkpoints
> (`tradingagents/graph/checkpointer.py`), the files a run writes under `results_dir`, and what persists
> between runs.
> **Last verified against the code:** 2026-10-24

---

## 1. The idea

Each finished run records its decision. Once the decision's holding window has traded, a later run measures
how it did against a benchmark, asks the quick model for a short lesson, and stores it. The Portfolio Manager
of later runs reads those lessons. Nothing is retrained: "memory" here is a Markdown file of past decisions and
lessons placed into a prompt.

## 2. The memory log (`memory/log.py`)

`TradingMemoryLog` keeps an append-only Markdown file at `memory_log_path`
(default `~/.tradingagents/memory/trading_memory.md`). Entries are separated by `<!-- ENTRY_END -->`.

A new entry, written by `store_decision()` at the end of a run (no LLM call):

```
[2026-09-01 | RELIANCE.NS | Hold | pending]

DECISION:
<the Portfolio Manager's final_trade_decision>
```

The values above are an illustration of the format, not a real entry.

Rules in the code:

- **One entry per ticker and date.** If any entry for that ticker and date exists, pending or settled, a
  re-run adds nothing.
- The rating stored is the run's `final_rating`, else read from the text, else `REVIEW`.
- Writes take a file lock (`dataflows/files.py`, `locked`). Updates are written to a temp file and swapped in,
  so a crash cannot leave a half-written log.
- `memory_log_max_entries` (default `None`) prunes the oldest settled entries when set; pending entries are never
  pruned.

When settled, the tag becomes
`[date | ticker | rating | raw return | alpha | Nd | resolved:YYYY-MM-DD]` and a `REFLECTION:` section is added.

## 3. Settlement (`memory/settlement.py`)

`settle_pending(ticker, …)` and `settle_all_pending(…)`:

1. Take the settlement lock (`memory_log.settling()`), so two runs never pay for the same reflection. With
   `wait=False` (used inside a run) a pass already running elsewhere is left to do the work.
2. For each pending entry, `fetch_returns()` gets daily closes from Yahoo. Entry is the **first close after the
   analysis date**; exit is `holding_period_days` (default 5) trading days later.
3. If the full window has not traded yet, the entry stays pending for a later run.
4. The benchmark comes from `resolve_benchmark()`: `benchmark_ticker` if set, else `benchmark_map` by suffix
   (`.NS` → `^NSEI`, `.BO` → `^BSESN`, no suffix → `SPY`). Alpha = stock return − benchmark return.
5. `Reflector.reflect_on_final_decision()` asks the quick model for 2–4 plain sentences: what the alpha shows,
   which part of the thesis it supports or undercuts, one lesson. The prompt says plainly when the window is too
   short to judge the thesis.
6. `update_with_outcome()` writes the result. A price or reflection failure leaves the entry pending and is
   reported in `Settlement.failed`.

## 4. Reflection reaches the next run

The graph's **Memory Log** node (`TradingAgentsGraph._memory_step`) runs beside the analysts:

1. `settle_all_pending(wait=False)` — every ticker's due decisions, not only this ticker's.
2. `get_past_context(ticker, as_of=…)` — up to 5 settled entries for the same ticker (decision and lesson) and
   up to 3 lessons from other tickers, most recent first.
3. For a **historical** run (trade date before today) `as_of` is the trade date: only lessons whose
   `resolved:` date is on or before it are used, so a backtest does not learn from the future. Entries without a
   resolution date are then left out. A current-date run uses no filter.

Only the Portfolio Manager reads `past_context`. A failure here does not stop the run; `memory_note` says what
could not be settled or read, and the saved report shows it.

A run's own decision stays pending until a later run (or `settle_pending()`) settles it.

## 5. Checkpoints

Off by default (`checkpoint_enabled: False`). Turn on with `TRADINGAGENTS_CHECKPOINT_ENABLED=true` or the CLI
flag `--checkpoint`.

| Item | Detail |
|---|---|
| Storage | One SQLite file per ticker: `data_cache_dir/checkpoints/<TICKER>.db`, via LangGraph's `SqliteSaver` |
| Thread ID | `thread_id(ticker, date, signature)`: first 16 hex digits of a SHA-256 |
| Signature | `_run_signature()`: analysts, debate and risk rounds, asset type, portfolio fingerprint, graph layout, and a hash of every config key except `results_dir`, `data_cache_dir`, `memory_log_path`, `checkpoint_enabled`, `llm_max_retries` |
| Resume | If a checkpoint exists for the same thread, the graph is invoked with `None` and LangGraph continues from the last saved step |
| Cleanup | `clear_checkpoint_on_success()` deletes the thread's rows after a finished run; `--clear-checkpoints` deletes every checkpoint file (including SQLite `-wal`/`-shm` files) |

Any change to settings (model, provider, analysts, depth, vendors, language, portfolio) gives a new signature,
so the run starts fresh instead of mixing reports from different settings.

## 6. Files a run writes

| File | Written by | Path |
|---|---|---|
| Full state log (JSON) | `_log_state()` | `results_dir/<TICKER>/TradingAgentsStrategy_logs/full_states_log_<date>.json` |
| CLI message and tool log | `cli/run.py` | `results_dir/<TICKER>/<date>/message_tool.log` |
| CLI live report sections | `cli/run.py` | `results_dir/<TICKER>/<date>/reports/<section>.md` |
| Saved report tree | `save_reports()` / `write_report_tree()` | `results_dir/reports/<TICKER>_<YYYYMMDD_HHMMSS>/` (`complete_report.md`, `complete_report.html`, numbered section folders) |
| Memory log | `TradingMemoryLog` | `memory_log_path` |
| Checkpoints | `checkpointer.py` | `data_cache_dir/checkpoints/` |

The state log includes all reports, both debates, the plans, the final decision, `final_rating` and
`run_settings()`. `run_settings()` is an allowlist: version, providers, model names, analysts, rounds, language
and vendors. It never records endpoints, keys or local paths.

Tickers are checked by `safe_ticker_component()` before being used in a path, so a ticker cannot point outside
these folders.

## 7. What persists between runs

| Persists | Does not persist |
|---|---|
| Memory log entries and lessons | LLM conversation state (each run starts from a fresh initial state) |
| Checkpoints of unfinished runs (when enabled) | Checkpoints of finished runs (deleted) |
| State logs and saved reports | Anything in the model itself |
| Data cache under `data_cache_dir` (including the quant store) | |

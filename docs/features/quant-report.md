# Quant report (section VI of every analysis)

> **Status:** Current.
> **Scope:** the quant context the agents quote and the "VI. Quant Context" report section.
> **Last verified against the code:** 2026-10-24

Research and decision support only, not investment advice.

---

## 1. What it does for you

For any of the 29 research stocks, NIFTY or BANKNIFTY, every TradingAgents analysis gets a block of numbers the agents
must quote rather than guess:

- the **market regime** (calm / choppy / stress) and since when;
- **volatility forecasts** (GARCH, GJR, EWMA) for the next 5, 10 and 21 sessions;
- the **expected move**: a one-standard-deviation range from the GARCH forecast, in % and in rupees on the last close
  (about 2 in 3 moves stay inside it) — useful for stop distance and strike width on Dhan;
- **30-day implied volatility**, how far it sits above or below the forecast, and its percentile over the past year;
- the **verdict of every quant test**, worded so nothing reads as validated.

Only data known before the analysis date's open is used. While no signal has passed its tests, the report says so in
plain words and the agents may use the numbers as risk context only.

## 2. How to use it

Run an analysis as usual for a ticker in the universe (for example `RELIANCE.NS`, `^NSEI`, `^NSEBANK`). The market
analyst calls the tool `get_quant_signal_report`; the saved report gets a section **"VI. Quant Context"** in both the
Markdown and HTML output.

To see the text directly:

```powershell
.venv\Scripts\python.exe -c "from tradingagents.analytics.quant_report import quant_signal_text; print(quant_signal_text('RELIANCE.NS', '2026-10-23'))"
```

## 3. Files

| File | Role |
|---|---|
| `tradingagents/analytics/quant_report.py` | Builds the text |
| `tradingagents/agents/tools.py` | `get_quant_signal_report` tool |
| `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/managers/portfolio_manager.py` | Prompt rules |
| `tradingagents/reporting.py` | Section VI |

## 4. Settings and inputs

No settings. It reads `<data_cache_dir>/quant/store/` (`regime/`, `vol_forecasts/`, `iv/`, `prices/`) and
`trial_log.sqlite`, which the daily refresh keeps current ([daily-refresh.md](daily-refresh.md)).

## 5. Outputs

Plain text in the agents' context, and `6_quant/quant.md` plus the HTML section in each saved report.

## 6. Known issues

- Tickers outside the universe get a one-line "no quant numbers" note; the section is left out of their reports.
- If the store has not been built or refreshed, lines say "not available" or show the last known date.
- The universe is today's survivors; the report carries the survivorship note.
- The Phase 9 replay check (do agents quote these numbers faithfully?) was running on 2026-10-24; first findings and
  the result: [PA-25](../PA_25-phase9-replay-and-report-wording.md).

How it is built: [../architecture/16-quant-context-in-agents.md](../architecture/16-quant-context-in-agents.md).

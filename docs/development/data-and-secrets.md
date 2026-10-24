# Data and secrets

> **Status:** Current.
> **Scope:** what lives outside git, what may be committed, and the public-repository rule.
> **Last verified against the code:** 2026-10-24

---

## 1. The rule

**The repository is public.** Nothing goes into a commit, a pull request, an issue or a document that is a key or token,
an account number, the user's capital figure, personal trade data, or raw NSE data. When in doubt, keep it local.

## 2. What lives outside git

Everything the quant layer downloads or computes lives under `<data_cache_dir>/quant/`. `data_cache_dir` defaults to
`~/.tradingagents/cache` and can be moved with the `TRADINGAGENTS_CACHE_DIR` environment variable.

| Path (under `~/.tradingagents/cache/quant/`) | Content |
|---|---|
| `raw/<kind>/<year>/` and `raw/manifest.csv` | NSE archive files exactly as served (F&O bhavcopy, participant OI, delivery, index closes) and the download manifest |
| `raw/option_quotes/<date>/` | Nightly option bid/ask snapshots (raw JSON) |
| `raw/board_meetings/` | NSE board-meeting lists used for results dates |
| `store/` | The Parquet store, prices, IV, volatility forecasts, regime, quality report, event trades |
| `trial_log.sqlite` | Every backtest run |
| `paper_ledger.sqlite` | Forward paper-trading ledger |
| `daily_status.json`, `daily_update.log` | The scheduled job's status and log |

In the repository folder, gitignored:

| Path | Content |
|---|---|
| `reports/` | All generated output: run reports, `reports/market_map/` (embeds NSE data), `reports/journal/` (your tradebook and round trips), `reports/replay/` (Phase 9 runs) |
| `.env`, `.env.enterprise`, `.envrc` | API keys and LLM settings |
| `.venv/` | The Python environment |
| `**/data_cache/` | Any local data cache |

The user's capital, when it is needed (Stage 4 of the proof plan), is passed to `sizing.py` as an argument or kept as a
local configuration value; it is never stored in the repository.

## 3. What may be committed

- **Code and tests.**
- **Documentation** under `docs/`, following [documentation-standards.md](documentation-standards.md): results as
  measured figures and verdicts, never raw data rows.
- **Sourced public reference data** in `docs/data/`, small and with a source for every entry — for example
  `docs/data/market_events_2021_2026.json` (each event links its official circular or news source).
- **Frozen strategy specs** in `docs/strategies/`.
- **`docs/PROGRESS_TRACKER.md`**, which the daily job rewrites (its progress bars and "Last updated" line only).

## 4. Before committing

```powershell
git status
git diff --cached --stat
```

Check that nothing under `reports/`, no `.env*` file, no `.parquet`, `.sqlite`, raw NSE file, tradebook or contract note
is staged, and that no document names a capital figure or quotes personal trades.

Related: [scheduled-job-operations.md](scheduled-job-operations.md),
[../architecture/11-nse-data-store.md](../architecture/11-nse-data-store.md).

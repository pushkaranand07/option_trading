# Local setup (Windows)

> **Status:** Current.
> **Scope:** setting up a development environment on Windows — Python, the virtual environment, optional extras,
> `.env` keys (names only), the data cache, and running the CLI and the web app.
> **Last verified against the code:** 2026-10-24

---

## 1. Requirements

- **Python 3.13** for this fork. `pyproject.toml` allows `>=3.11`, and CI tests 3.11–3.14 on Linux; the build plan
  records the working environment as Python 3.13.5 with pandas 3.0.6.
- Git, and PowerShell or Windows Terminal. The interactive CLI needs a real console (Windows Terminal, PowerShell or
  cmd.exe); a piped or embedded terminal cannot host its prompts.

## 2. Create the environment

From the repository root:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev,quant]"
```

`.venv` is git-ignored. Calling `.venv\Scripts\python.exe` directly avoids depending on an activated shell; the
scheduled quant job (`scripts/quant_daily_update.cmd`) does the same with `.venv\Scripts\pythonw.exe`.

### 2.1 Optional extras (`[project.optional-dependencies]`)

| Extra | Installs | When you need it |
|---|---|---|
| `dev` | `ruff>=0.16`, `pytest>=8.0`, `pytest-subtests>=0.13` | Always, for development |
| `quant` | `arch`, `hmmlearn`, `lightgbm`, `scikit-learn`, `pyarrow`, `openpyxl` | The quant signal layer and its Parquet store; `openpyxl` reads broker reports for the trade journal |
| `chronos` | `chronos-forecasting>=2.0` (pulls in PyTorch) | The Chronos-Bolt forecasting model (Phase 7); CPU is enough |
| `bedrock` | `langchain-aws>=1.7.9` | The Amazon Bedrock LLM provider |

The options engine's dependencies (`pandas-ta-classic`, `empyrical-reloaded`, `pydantic`) are core dependencies.
The web app needs two more packages listed in `webapp/requirements.txt`:

```powershell
.venv\Scripts\python.exe -m pip install -r webapp\requirements.txt
```

## 3. The `.env` file

Copy `.env.example` to `.env` in the repository root and fill in only what you use. The package loads `.env` (and
`.env.enterprise`, without overriding) from the current directory when it is imported
(`tradingagents/__init__.py`). `.env` and `.env.enterprise` are git-ignored. **Never commit values; this repository
is public.**

| Purpose | Variable names |
|---|---|
| LLM provider keys (set the one you use) | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `DASHSCOPE_CN_API_KEY`, `ZHIPU_API_KEY`, `ZHIPU_CN_API_KEY`, `MINIMAX_API_KEY`, `MINIMAX_CN_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `MOONSHOT_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_COMPATIBLE_API_KEY` |
| Azure OpenAI (`.env.enterprise.example`; also the web app's AI panel) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, optional `OPENAI_API_VERSION` |
| Amazon Bedrock | `AWS_BEARER_TOKEN_BEDROCK` or the AWS credential chain (`AWS_PROFILE`), `AWS_DEFAULT_REGION` |
| Remote Ollama | `OLLAMA_BASE_URL` |
| Data vendors | `FRED_API_KEY` (macro data), `ALPHA_VANTAGE_API_KEY` (only if routed to Alpha Vantage), `SEC_EDGAR_USER_AGENT` (a name and contact address; no key) |
| Social-post screening (optional) | `TYPESAFE_API_KEY`, `TYPESAFE_DEFAULT_MODEL`, `TYPESAFE_BASE_URL` |
| Web app market data (optional) | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` (the token expires every 24 hours) |
| Run settings (skip CLI prompts) | `TRADINGAGENTS_LLM_PROVIDER`, `TRADINGAGENTS_DEEP_THINK_LLM`, `TRADINGAGENTS_QUICK_THINK_LLM`, `TRADINGAGENTS_OUTPUT_LANGUAGE`, `TRADINGAGENTS_MAX_DEBATE_ROUNDS`, `TRADINGAGENTS_MAX_RISK_ROUNDS`, and the others in `tradingagents/default_config.py` (`_ENV_OVERRIDES`) |
| Paths | `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_MEMORY_LOG_PATH` |
| Update check off | `TRADINGAGENTS_NO_UPDATE_CHECK=1` |

The ChatGPT-plan provider uses no key: sign in once with `tradingagents login chatgpt`. Provider details:
[../architecture/04-llm-providers-and-configuration.md](../architecture/04-llm-providers-and-configuration.md).

An invalid `TRADINGAGENTS_*` value (e.g. a misspelt boolean) raises at import rather than being ignored.

## 4. Where data is written

Everything defaults to `%USERPROFILE%\.tradingagents\` (`~/.tradingagents`, from `default_config.py`):

| Path | Contents | Override |
|---|---|---|
| `~/.tradingagents/cache/` | Vendor caches (Yahoo OHLCV CSVs, SEC EDGAR, `nse/`), checkpoints, the quant store (`quant/store/`), the Dhan scrip master | `TRADINGAGENTS_CACHE_DIR` |
| `~/.tradingagents/logs/` | Run logs and saved reports (`<TICKER>/<DATE>/`, `reports/<TICKER>_<timestamp>/`) | `TRADINGAGENTS_RESULTS_DIR` |
| `~/.tradingagents/memory/trading_memory.md` | The decision memory log | `TRADINGAGENTS_MEMORY_LOG_PATH` |
| `~/.tradingagents/cli_prefs.json`, `update_check.json` | CLI remembered answers, update-check cache | — |

Cache layout: [../architecture/06-data-vendors.md](../architecture/06-data-vendors.md#5-caching-and-the-cache-directory).
The cache can be deleted; NSE-derived history (`nse/fii_dii_history.csv`, `nse/index_snapshots.json`,
`nse/lot_size_history.json`) cannot be re-downloaded and is rebuilt only over time.

## 5. Running

### 5.1 CLI

```powershell
.venv\Scripts\tradingagents.exe                       # interactive
.venv\Scripts\tradingagents.exe --ticker RELIANCE.NS --date 2026-10-23 --analysts market,news --save --no-show
.venv\Scripts\python.exe -m cli.main --help           # same app, without the console script
```

Commands and flags: [../architecture/09-cli-webapp-and-reports.md](../architecture/09-cli-webapp-and-reports.md#2-the-cli-cli).

### 5.2 Web app

```powershell
.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8000
```

Open `http://localhost:8000`. See [../features/webapp.md](../features/webapp.md).

### 5.3 Python

`main.py` shows the minimal programmatic run (`TradingAgentsGraph(...).propagate(ticker, date)`).

### 5.4 Docker

A `Dockerfile` and `docker-compose.yml` exist; `TRADINGAGENTS_DATA_DIR` chooses the host folder for results. Not
covered further here.

## 6. Next steps

- Tests and lint: [testing-and-lint.md](testing-and-lint.md).
- Writing docs: [documentation-standards.md](documentation-standards.md).

# Testing and lint

> **Status:** Current.
> **Scope:** the pytest configuration and markers, how to run the suite, what the shared fixtures guarantee, the ruff
> configuration, and Windows notes.
> **Last verified against the code:** 2026-10-24

---

## 1. Quick reference

```powershell
.venv\Scripts\python.exe -m pytest -q -m unit          # the unit suite (what to run before a commit)
.venv\Scripts\python.exe -m pytest -q                  # everything except integration tests (what CI runs)
.venv\Scripts\python.exe -m pytest -q tests\test_nse_client.py     # one file
.venv\Scripts\python.exe -m pytest -q -m integration   # tests that reach real services; only when asked for
.venv\Scripts\python.exe -m ruff check .               # lint the whole repository (what CI runs)
.venv\Scripts\python.exe -m ruff check --fix .         # apply safe fixes
```

Install the tools with the `dev` extra: `pip install -e ".[dev,quant]"` (see [local-setup.md](local-setup.md)).
Several quant-layer tests read and write Parquet files or fit the quant models (`test_quant_datastore.py`,
`test_quant_regime.py`, `test_quant_volatility.py`, ...), so install the `quant` extra too.

## 2. pytest configuration

From `[tool.pytest.ini_options]` in `pyproject.toml`:

| Setting | Value |
|---|---|
| `testpaths` | `tests` |
| `addopts` | `-ra --strict-markers -m "not integration"` |
| `filterwarnings` | `ignore::DeprecationWarning` |

`-ra` prints a reason line for every test that did not pass. `--strict-markers` makes an unregistered marker an
error. Passing `-m` on the command line replaces the `-m "not integration"` from `addopts`.

### 2.1 Markers

| Marker | Meaning |
|---|---|
| `unit` | Fast, isolated unit tests |
| `integration` | Tests requiring external services; excluded by default, run only with `-m integration` |
| `smoke` | Quick sanity checks |

Most test files mark their tests `unit` (with `pytestmark = pytest.mark.unit` or `@pytest.mark.unit`). Eight files
carry no marker, so `-m unit` does not run them; the plain `pytest -q` run does:
`test_analyst_execution.py`, `test_api_key_env.py`, `test_checkpoint_resume.py`, `test_cli_no_console.py`,
`test_crypto_asset_mode.py`, `test_env_overrides.py`, `test_openai_reasoning_effort.py`,
`test_symbol_normalization_paths.py`. Run the full default suite before a pull request.

New tests: mark them `unit` unless they need the network, in which case mark them `integration`.

## 3. What `tests/conftest.py` guarantees

| Guarantee | How |
|---|---|
| **No network** | An autouse fixture makes `socket.connect`, `connect_ex` and `getaddrinfo` raise, and blocks `curl_cffi` (yfinance's HTTP client). Only tests marked `integration` may connect. A test that needs data must use fixtures or mocks |
| **Your settings do not leak in** | Every `TRADINGAGENTS_*` variable from the environment, `.env` and `.env.enterprise` is blanked before the package is imported |
| **Your files are not touched** | `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR` and `TRADINGAGENTS_MEMORY_LOG_PATH` point to a fresh temp directory; the yfinance time-zone cache and the CLI prefs file are redirected too |
| **No real keys needed** | Provider and vendor key variables are set to `placeholder` when empty |
| **Clean config per test** | The global dataflows config is reset to `DEFAULT_CONFIG` before and after each test |
| **Interactive code is testable** | `sys.stdin.isatty` returns True unless a test says otherwise |

So the suite needs no `.env`, no keys and no internet, and never reads or writes `~/.tradingagents`.

## 4. CI

`.github/workflows/ci.yml` (on pushes to `main` and release branches, and on pull requests):

| Job | What it runs |
|---|---|
| `test` | `pip install -e ".[dev]"`, then `pytest -q` on Python 3.11, 3.12, 3.13, 3.14 (Ubuntu), plus 3.12 with `TZ=America/New_York` to catch tests that only pass in UTC |
| `smoke-install` | A plain `pip install .` and `import tradingagents, cli.main` — catches undeclared runtime dependencies |
| `lint` | `ruff check .` |

CI installs only the `dev` extra, not `quant`; how the quant-layer tests behave there is not recorded in this
document.

## 5. Ruff

From `[tool.ruff]` in `pyproject.toml`:

| Setting | Value |
|---|---|
| `line-length` | 100 |
| `target-version` | `py311` |
| `extend-exclude` | `results`, `option_backtester` (the engine keeps its upstream optopsy style) |
| `lint.select` | `E`, `W`, `F`, `I`, `B`, `UP`, `C4`, `SIM` (pycodestyle, pyflakes, isort, bugbear, pyupgrade, comprehensions, simplify) |
| `lint.ignore` | `E501` (line length is left to the formatter) |
| per-file | `**/__init__.py` ignores `F401` (intentional re-exports) |
| `lint.isort` | `combine-as-imports = true` |

The repository is lint-clean under this rule set and CI lints all of it. `ruff format` is **not** applied repo-wide
(deferred, per the comment in `pyproject.toml`), so do not reformat files you are not changing.

## 6. Windows notes

- Call the venv's interpreter directly (`.venv\Scripts\python.exe -m pytest`), so the right environment is used
  whatever shell is active.
- Some tests are skipped on Windows by design: POSIX file-mode checks (`test_api_key_env.py`) and POSIX upgrade
  commands (`test_cli_updates.py`); one test in `test_cli_updates.py` runs only on Windows. `test_cli_no_console.py`
  imports `prompt_toolkit`'s win32 module only on Windows.
- Cache writes use `dataflows/files.replace_file`; on Windows a file held open by another process is kept and the
  write skipped with a warning. Cross-process locks use `msvcrt.locking` (`dataflows/files.locked`).
- CI runs on Linux only, so a Windows-only failure will not show up there; run the suite locally.
- Recorded results: on 2026-10-22 the build plan noted 5 pre-existing failures in ChatGPT-auth, CLI-update and
  yfinance-cache tests ([section 13](../plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md)); commit `8df7ad0`
  (2026-10-23) records "full suite 1536 passed" and the whole repository ruff-clean. Current figures: not recorded
  here — run the suite.

## 7. Where the tests are

All in `tests/`, one file per area, named `test_<area>.py` — for example `test_nse_*.py` and `test_india_*.py`
(India layer), `test_quant_*.py` (quant layer), `test_cli_*.py` (CLI), `test_option_backtester_fixes.py` and
`test_optopsy_bridge_compliance.py` (options engine).

# PA-31 — Small fixes: news-analyst prompt, `.env.example`, unit markers

| | |
|---|---|
| **Status** | Done |
| **Scope** | `tradingagents/agents/analysts/news_analyst.py`, `.env.example`, 8 test files |
| **Related** | [PA-26](PA_26-docs-restructure.md) (where these were found), [development/testing-and-lint](development/testing-and-lint.md) |
| **Pull request** | branch `fix/small-items` |
| **Date** | 2026-10-24 |

## 1. Problems (found while writing the docs)

| Item | Effect |
|---|---|
| The News Analyst is offered `get_india_fii_dii_flows`, but its prompt named only the other four tools | the model was less likely to use FII/DII flows for Indian instruments |
| `ALPHA_VANTAGE_API_KEY` is read by the Alpha Vantage vendor but missing from `.env.example` | a new setup would not know the variable exists |
| 8 test files had no `unit` marker | `pytest -m unit` (the usual run) skipped their 89 tests |

## 2. What changed

- The prompt now names `get_india_fii_dii_flows(curr_date)`: foreign and domestic institutional net flows in Indian
  markets, stating whether the figures are for the requested session (never present earlier figures as today's), and
  "not applicable" outside India — the tool's own contract.
- `.env.example`: a commented `ALPHA_VANTAGE_API_KEY` entry with where to get a free key.
- `pytestmark = pytest.mark.unit` in `test_analyst_execution.py`, `test_api_key_env.py`, `test_checkpoint_resume.py`,
  `test_cli_no_console.py`, `test_crypto_asset_mode.py`, `test_env_overrides.py`, `test_openai_reasoning_effort.py`,
  `test_symbol_normalization_paths.py`. They were already offline-safe (`conftest.py` blocks the network for every
  non-integration test): 86 passed, 3 skipped (POSIX-only) before and after marking.

## 3. Verification

The unit suite now includes those 86 tests; ruff clean.

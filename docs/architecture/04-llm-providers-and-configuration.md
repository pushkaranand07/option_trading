# LLM providers and configuration

> **Status:** Current.
> **Scope:** `tradingagents/llm_clients/` (factory, provider clients, capabilities, model catalog), the quick
> and deep model tiers, `tradingagents/default_config.py` and its `TRADINGAGENTS_*` environment overrides.
> **Last verified against the code:** 2026-10-24

---

## 1. Two model tiers

Every run uses two chat models, built in `TradingAgentsGraph.__init__` with `create_tier_client(config, "deep")`
and `create_tier_client(config, "quick")`:

| Tier | Config key | Used by |
|---|---|---|
| quick | `quick_think_llm` | The four analysts, Bull and Bear, the Trader, the three risk debaters, and the `Reflector` that writes memory-log lessons |
| deep | `deep_think_llm` | Research Manager and Portfolio Manager |

A tier may name its own provider and endpoint (`quick_think_provider`, `deep_think_provider`,
`quick_think_backend_url`, `deep_think_backend_url`). When these are `None` the tier uses `llm_provider` and
`backend_url` (`tier_provider()` and `create_tier_client()` in `tradingagents/llm_clients/factory.py`).

## 2. Files in `tradingagents/llm_clients/`

| File | Role |
|---|---|
| `factory.py` | `create_llm_client(provider, model, base_url, **kwargs)`; `build_llm_kwargs(config)`; `create_tier_client()` |
| `base_client.py` | `BaseLLMClient` (`get_llm()`, `validate_model()`, `warn_if_unknown_model()`); `normalize_content()` turns list-of-blocks replies into plain text |
| `openai_client.py` | `OpenAIClient` for OpenAI and every OpenAI-compatible provider; registry `OPENAI_COMPATIBLE_PROVIDERS` |
| `anthropic_client.py`, `google_client.py`, `azure_client.py`, `bedrock_client.py` | Native clients |
| `chatgpt_auth.py` | Sign-in for the `chatgpt` provider (`tradingagents login chatgpt`) |
| `capabilities.py` | Per-model table of API quirks (`get_capabilities(model_name)`) |
| `model_catalog.py` | Model lists the CLI offers per provider and tier; `get_known_models()` |
| `validators.py` | `validate_model()`: warns, never blocks, on a model name outside the catalog |
| `api_key_env.py` | `PROVIDER_API_KEY_ENV`: which environment variable holds each provider's key |

## 3. Providers

`create_llm_client()` checks the native providers first, then the OpenAI-compatible registry:

- **Native:** `anthropic`, `google`, `azure`, `bedrock`.
- **OpenAI-compatible:** `openai`, `xai`, `deepseek`, `qwen`, `qwen-cn`, `glm`, `glm-cn`, `minimax`,
  `minimax-cn`, `openrouter`, `mistral`, `kimi`, `groq`, `nvidia`, `ollama`, `chatgpt`, `openai_compatible`.

Any other name raises `ValueError("Unsupported LLM provider: …")`.

`capabilities.py` records which models reject which API parameters. For example DeepSeek thinking models and
MiniMax M2.x models do not accept `tool_choice`, so the client leaves it out. Models not listed get the default
(tool choice, JSON mode and JSON schema all supported; structured output by function calling).

`build_llm_kwargs()` forwards provider-specific settings:

| Setting | Forwarded when provider is |
|---|---|
| `google_thinking_level` | `google` |
| `openai_reasoning_effort` | `openai`, `chatgpt` or `azure` (`REASONING_EFFORT_PROVIDERS`); dropped for non-reasoning models (gpt-4o, gpt-4.1, …) |
| `anthropic_effort` | `anthropic` |
| `temperature`, `llm_max_retries`, `max_tokens` | any (Gemini receives `max_output_tokens`) |

## 4. Azure OpenAI (this machine)

On this machine `.env` selects **Azure OpenAI with GPT-5 for both tiers**: `TRADINGAGENTS_LLM_PROVIDER=azure`,
`TRADINGAGENTS_DEEP_THINK_LLM=gpt-5`, `TRADINGAGENTS_QUICK_THINK_LLM=gpt-5`. The key, endpoint and
deployment values are in `.env` only and are not reproduced here.

`AzureOpenAIClient` (`azure_client.py`) builds a LangChain `AzureChatOpenAI`. It reads:

| Variable | Meaning |
|---|---|
| `AZURE_OPENAI_API_KEY` | API key |
| `AZURE_OPENAI_ENDPOINT` | Resource endpoint |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Deployment to call; if unset, the model name is used |
| `OPENAI_API_VERSION` | API version |

Two consequences found in the code:

- `AZURE_OPENAI_DEPLOYMENT_NAME` applies to **both** tiers. When it is set, the quick and deep tiers call the
  same deployment whatever `quick_think_llm` and `deep_think_llm` say.
- `openai_reasoning_effort` (`TRADINGAGENTS_OPENAI_REASONING_EFFORT`) is forwarded for `azure` too since
  2026-10-24 ([PA-29](../PA_29-azure-reasoning-effort.md)); before, it was silently ignored there. The CLI asks the
  reasoning-effort question only for `openai` and `chatgpt`; on Azure set the variable.

`validate_model()` returns `True` for Azure, so any deployment name is accepted without a warning.

## 5. Configuration (`default_config.py`)

`DEFAULT_CONFIG = build_default_config()` is built when the package is imported. `tradingagents/__init__.py`
first loads `.env` (and `.env.enterprise`) from the working directory upwards, without overriding variables
already set.

| Key | Default | Meaning |
|---|---|---|
| `results_dir` | `~/.tradingagents/logs` | Run logs and saved reports (`TRADINGAGENTS_RESULTS_DIR`) |
| `data_cache_dir` | `~/.tradingagents/cache` | Data cache, checkpoints, quant store (`TRADINGAGENTS_CACHE_DIR`) |
| `memory_log_path` | `~/.tradingagents/memory/trading_memory.md` | Memory log (`TRADINGAGENTS_MEMORY_LOG_PATH`) |
| `memory_log_max_entries` | `None` | Cap on settled memory entries; `None` = no pruning |
| `llm_provider` | `"openai"` | Main provider |
| `deep_think_llm` / `quick_think_llm` | `"gpt-6-sol"` / `"gpt-6-luna"` | Model names |
| `backend_url` | `None` | Endpoint for `llm_provider`; `None` = provider default |
| `quick_think_provider`, `deep_think_provider`, `quick_think_backend_url`, `deep_think_backend_url` | `None` | Per-tier overrides |
| `google_thinking_level`, `openai_reasoning_effort`, `anthropic_effort` | `None` | Provider thinking settings |
| `temperature`, `llm_max_retries`, `max_tokens` | `None` | Left to each provider when `None` |
| `checkpoint_enabled` | `False` | Save state after each node |
| `output_language` | `"English"` | Language of reports and decision |
| `max_debate_rounds`, `max_risk_discuss_rounds` | `1`, `1` | Debate depth |
| `max_recur_limit` | `100` | LangGraph recursion limit |
| `max_tool_rounds` | `20` | Tool rounds per analyst |
| `news_article_limit`, `global_news_article_limit`, `global_news_lookback_days` | `20`, `10`, `7` | News sizes |
| `global_news_queries` | five search phrases | Macro headline searches |
| `data_vendors` | see [06](06-data-vendors.md) | Vendor per data category |
| `tool_vendors` | `{}` | Vendor per tool, overrides `data_vendors` |
| `holding_period_days` | `5` | Trading days over which a decision is scored |
| `benchmark_ticker` | `None` | Force one benchmark for every ticker |
| `benchmark_map` | suffix → index | e.g. `.NS` → `^NSEI`, `.BO` → `^BSESN`, no suffix → `SPY` |

## 6. Environment overrides

`_ENV_OVERRIDES` maps each variable to a key. The string is converted to the type of the existing default
(`_coerce`); a bad boolean or number raises `ValueError` at start-up. Empty values are ignored.

| Variable | Key |
|---|---|
| `TRADINGAGENTS_LLM_PROVIDER` | `llm_provider` |
| `TRADINGAGENTS_DEEP_THINK_LLM`, `TRADINGAGENTS_QUICK_THINK_LLM` | `deep_think_llm`, `quick_think_llm` |
| `TRADINGAGENTS_DEEP_THINK_PROVIDER`, `TRADINGAGENTS_QUICK_THINK_PROVIDER` | per-tier provider |
| `TRADINGAGENTS_DEEP_THINK_BACKEND_URL`, `TRADINGAGENTS_QUICK_THINK_BACKEND_URL` | per-tier endpoint |
| `TRADINGAGENTS_LLM_BACKEND_URL` | `backend_url` |
| `TRADINGAGENTS_OUTPUT_LANGUAGE` | `output_language` |
| `TRADINGAGENTS_MAX_DEBATE_ROUNDS`, `TRADINGAGENTS_MAX_RISK_ROUNDS` | debate depths |
| `TRADINGAGENTS_MAX_TOOL_ROUNDS` | `max_tool_rounds` |
| `TRADINGAGENTS_CHECKPOINT_ENABLED` | `checkpoint_enabled` |
| `TRADINGAGENTS_BENCHMARK_TICKER` | `benchmark_ticker` |
| `TRADINGAGENTS_TEMPERATURE`, `TRADINGAGENTS_LLM_MAX_RETRIES`, `TRADINGAGENTS_MAX_TOKENS` | sampling and limits |
| `TRADINGAGENTS_GOOGLE_THINKING_LEVEL`, `TRADINGAGENTS_OPENAI_REASONING_EFFORT`, `TRADINGAGENTS_ANTHROPIC_EFFORT` | thinking settings |

Three more are read directly for paths: `TRADINGAGENTS_RESULTS_DIR`, `TRADINGAGENTS_CACHE_DIR`,
`TRADINGAGENTS_MEMORY_LOG_PATH`. The CLI also reads `TRADINGAGENTS_NO_UPDATE_CHECK`.

Because `DEFAULT_CONFIG` already includes the environment, `main.py` and the CLI pick up `.env` without code
changes. In the CLI, a round count set in the environment wins over the "research depth" answer
(`_build_run_config` in `cli/run.py`).

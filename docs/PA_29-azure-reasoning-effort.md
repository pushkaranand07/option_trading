# PA-29 — Azure: the reasoning-effort setting is applied

| | |
|---|---|
| **Status** | Done |
| **Scope** | `tradingagents/llm_clients/factory.py` (`REASONING_EFFORT_PROVIDERS`), `tradingagents/llm_clients/azure_client.py`, `tests/test_llm_max_retries.py` |
| **Related** | [architecture/04](architecture/04-llm-providers-and-configuration.md), [PA-25](PA_25-phase9-replay-and-report-wording.md) |
| **Pull request** | branch `fix/azure-reasoning-effort` |
| **Date** | 2026-10-24 |

## 1. Problem

Found while writing the docs: `build_llm_kwargs()` forwarded `openai_reasoning_effort` only for the `openai` and
`chatgpt` providers. This machine runs GPT-5 on **Azure** with `TRADINGAGENTS_OPENAI_REASONING_EFFORT=low` in `.env`
— a setting that silently did nothing. The Azure client would have passed it on if it had arrived.

## 2. Verification before the change

One short live call to the Azure GPT-5 deployment with `reasoning_effort="low"`: accepted, reply "ok",
**0 reasoning tokens** — against 128 for the same prompt at the default earlier that day. The setting works on Azure.

## 3. What changed

- `azure` added to `REASONING_EFFORT_PROVIDERS`.
- The Azure client now drops `reasoning_effort` for non-reasoning models (gpt-4o, gpt-4.1, …) with the same check
  as the OpenAI client (`_supports_reasoning_effort`), so a non-reasoning deployment does not start failing with a 400.

## 4. Tests

Forwarded for `openai`, `chatgpt` and `azure`; reaches the Azure model object (`reasoning_effort == "low"`); dropped
for a `gpt-4o` Azure deployment. 41 provider tests pass.

## 5. Effect for the user

**The `.env` value `low` now takes effect**: analyses should be faster and cheaper with shallower model reasoning.
Every run before this change — including the Phase 9 replay — used the deployment's default effort. To keep that
behaviour, set `TRADINGAGENTS_OPENAI_REASONING_EFFORT=medium` or remove the line.

## 6. Risks and open items

- The Phase 9 replay judged runs at the default effort; at `low` the faithfulness of quoted numbers has not been
  re-checked (a new replay would be needed to know).
- Azure still uses one deployment for both the quick and deep tiers (`AZURE_OPENAI_DEPLOYMENT_NAME`).

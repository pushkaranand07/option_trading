# Fingerprint map: what the v4 forward test freezes

The v4 forward test (frozen 2026-11-11, [PA-54](../PA_54-ai-test-v4-tape-direction.md)) counts only while `webapp.ai_test.prompt_fingerprint()` equals the frozen spec value:

**`0698d1cae660b037fefc6289875f8028a7d20301614dc56b87f94658187fdf95`** (`docs/ai_strategist_test_v4.json`). v3's was `5a5fdbb3…`

`tests/test_fingerprint_frozen.py` asserts this value. Run it after every change. If it fails, stop.

## What the hash covers ([webapp/ai_test.py:50-62](../../webapp/ai_test.py#L50-L62))

### 1. The source text of 17 functions

The hash uses `inspect.getsource`, keyed by module and name. v4 added `strategist.today_tape`, `signals.today_tape` and `signals.intraday_frame` (line numbers below are v3's, at bed760e). **Any edit to these functions changes it**: code, comments, whitespace, formatting or lint fixes.

| Function | Lines (at bed760e) | Length |
|---|---|---|
| `webapp.strategist.build_context` | [webapp/strategist.py:105-155](../../webapp/strategist.py#L105-L155) | 51 |
| `webapp.strategist.check_structure` | [webapp/strategist.py:173-207](../../webapp/strategist.py#L173-L207) | 35 |
| `webapp.strategist.price` | [webapp/strategist.py:210-247](../../webapp/strategist.py#L210-L247) | 38 |
| `webapp.strategist.trade_levels` | [webapp/strategist.py:280-309](../../webapp/strategist.py#L280-L309) | 30 |
| `webapp.strategist._index_levels` | [webapp/strategist.py:418-424](../../webapp/strategist.py#L418-L424) | 7 |
| `webapp.strategist._structures` | [webapp/strategist.py:427-453](../../webapp/strategist.py#L427-L453) | 27 |
| `webapp.strategist.rank` | [webapp/strategist.py:456-512](../../webapp/strategist.py#L456-L512) | 57 |
| `webapp.strategist.agents_view` | [webapp/strategist.py:564-568](../../webapp/strategist.py#L564-L568) | 5 |
| `webapp.strategist.today_moves` | [webapp/strategist.py:571-586](../../webapp/strategist.py#L571-L586) | 16 |
| `webapp.strategist.candidates_for_ai` | [webapp/strategist.py:589-601](../../webapp/strategist.py#L589-L601) | 13 |
| `webapp.strategist.ask_rank_llm` | [webapp/strategist.py:604-611](../../webapp/strategist.py#L604-L611) | 8 |
| `webapp.strategist.ai_ranked` | [webapp/strategist.py:614-653](../../webapp/strategist.py#L614-L653) | 40 |
| `webapp.strategist.today_research` | [webapp/strategist.py:672-681](../../webapp/strategist.py#L672-L681) | 10 |
| `webapp.morning.ai_view` | [webapp/morning.py:109-119](../../webapp/morning.py#L109-L119) | 11 |

### 2. Module-level values

| Value | Where |
|---|---|
| `RANK_SYSTEM`, the ranking prompt text | webapp/strategist.py:540 |
| `RankedAnswer.model_json_schema()`, which also covers `RankedPick` | webapp/strategist.py:526-538 |
| `STRATEGIES` descriptions (the `[0]` of each entry) | webapp/strategist.py:29 |
| `TOP_AI = 8` | webapp/strategist.py:523 |
| `TAPE_ALLOWS` (v4: which direction a clear tape allows) | webapp/strategist.py |

### 3. Model settings

These are checked separately by `fingerprint_problem()` against the spec's `version.model`:
- provider: azure
- deep model: gpt-5
- quick model: gpt-5
- reasoning effort: medium

## Safe to edit (not part of the hash)

- Everything else in strategist.py, including `evidence`, `warnings`, `start`, `_run`, `save_run` and `latest_run`.
- All of `market_data.py`, `trade_record.py`, `server.py` and `option_chain.py`; `signals.py` except `today_tape` and `intraday_frame`.
- The rest of `morning.py`.

**Caveat:** the hash covers source text, not behaviour. The fingerprinted functions call unhashed helpers, for example `md.candles`, `nse_oc.chain` and `signals.*`. A change to those helpers can change what the AI sees without changing the fingerprint. This is the core of audit finding M6.

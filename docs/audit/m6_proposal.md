# M6 proposal: a behaviour fingerprint for the forward test

Status: **proposal only, not implemented.** Nothing here changes v3. The user decides at Gate 2.

## 1. What the fingerprint does today

`webapp.ai_test.prompt_fingerprint()` ([webapp/ai_test.py](../../webapp/ai_test.py)) hashes:

- the ranking system prompt `RANK_SYSTEM`;
- `RankedAnswer.model_json_schema()`;
- the `STRATEGIES` descriptions;
- `TOP_AI`;
- the **source text** (`inspect.getsource`) of 14 functions: `ask_rank_llm`, `ai_ranked`, `candidates_for_ai`, `today_moves`, `agents_view`, `today_research`, `build_context`, `rank`, `_structures`, `_index_levels`, `trade_levels`, `price`, `check_structure` and `morning.ai_view`.

The full list is in [fingerprint_map.md](fingerprint_map.md). `fingerprint_problem()` also compares the model settings with the spec's `version.model`.

**Why it hashes text.** It is cheap. It needs no fixtures. And it catches any edit to the code that builds what the LLM sees, however small. That fits the forward-test rule "changing the prompt, the candidate code or the model starts a new test" without anyone judging whether an edit "matters". It was the quickest honest freeze when v1 to v3 were written.

### Problem 1: it freezes refactoring

Any byte that changes inside those 14 functions changes the hash. That includes a comment, whitespace, a lint fix, a rename of a local variable, or moving a line. During this audit it blocked several real fixes:

- M7 had to copy `ask_rank_llm`'s message expression instead of reusing it. A drift test now keeps the two copies identical.
- L6 had to leave the naive `datetime.now()` / `date.today()` calls inside `build_context`, `today_research`, `agents_view` and `ai_ranked`.
- No fix may simplify or harden the ranking code while v3 runs.

So the hash punishes changes that keep behaviour the same, and everything around it piles up workarounds.

### Problem 2: it misses behaviour changes in code it does not hash

The fingerprinted functions call helpers whose source is **not** hashed. Some examples:

| Helper | What a change there does to the AI's input or the counted trade |
|---|---|
| `webapp.market_data.candles` (`md.candles`) | Changes the trend, indicators and levels in `ctx` |
| `webapp.option_chain` / `nse_oc.chain` | Changes strikes, bid/ask, OI walls, PCR, so it changes the candidates and their prices |
| `webapp.signals.*` (rule check, regime, expected move) | Changes `ctx` fields and the rule-based ranking |
| `strategist.evidence`, `warnings`, `charges` | Changes the charges written into the registry entry and what the user sees |
| `morning.context`, `_store_context` | Changes the FII, OI and expected-move fields in `ctx` |
| `tradingagents/` agents' prompts and tools | Change the research text the ranker reads (the spec already marks this `research_limit: UNVERIFIED`) |
| Third-party libraries (pydantic schema rendering, `json.dumps` defaults, langchain structured output) | Can change the bytes sent with no repo change at all |

A one-line change to a helper can change every prompt while the fingerprint stays green. So today's hash is both **too strict** (it fails on edits that keep behaviour) and **too loose** (it passes edits that change behaviour).

## 2. Proposed design: hash behaviour, not text

Freeze **what the LLM is told and how its answer becomes a trade**, measured on fixed inputs. The fingerprint becomes the sha256 of one canonical JSON document with these parts.

| Part | Content | Catches |
|---|---|---|
| `prompt` | `RANK_SYSTEM`, plus the user-message **template**: the output of the message builder on a fixed sentinel `ctx` / `candidates` | Wording, format and ordering of the prompt |
| `schema` | `RankedAnswer.model_json_schema()` (as now) | Answer fields and limits |
| `model` | provider, deployment/model name, reasoning effort, temperature/top_p if set, `max_tokens`, structured-output method | Model or parameter swaps (today's `fingerprint_problem` model check becomes part of the hash) |
| `menu` | `STRATEGIES` descriptions and legs, `TOP_AI` | The menu and how many are ranked |
| `golden` | The outputs of the deterministic pipeline on a fixed set of saved inputs (below) | Any behaviour change in the candidate builder, pricer, levels, checks **and in the helpers they call** |

**Golden fixtures.** These are about 6 to 10 saved cases under `tests/fixtures/forward_test_v4/`. Each case holds:

- a raw option chain (as `nse_oc.chain` returns it);
- the candle frame(s) `md.candles` would return;
- the morning context;
- the agents' research dict;
- a frozen clock time (IST).

Cover different conditions: a trending day, a range day, an expiry day, a chain with missing quotes, a Muhurat-like short session, and a BANKNIFTY case.

For each case, the fingerprint run calls the real code with the network layer replaced by the fixture (`md.candles`, `nse_oc.chain` and `morning.context` patched to return saved data; the clock frozen). It records:

1. `build_context(...)` → `ctx` (canonical JSON);
2. `rank(..., top=10**6)` → the full candidate pool;
3. `candidates_for_ai(pool)` → `shown`, and the order;
4. the exact user message the LLM would get, built by the same function `ask_rank_llm` uses;
5. for 2 or 3 fixed fake answers (`RankedAnswer` with chosen picks), the result of `ai_ranked`'s post-processing;
6. `price`, `check_structure` and `trade_levels` for a fixed set of plans, including the rejections.

The hash covers these outputs, rounded where floats need it (e.g. 6 significant figures) so the platform's last-bit noise does not flip it.

**What this gives.**

- A refactor that keeps behaviour keeps the hash: renames, comments, extracting helpers, lint fixes, reusing `ask_rank_llm`'s builder from the capture in M7.
- A change in any helper that alters what the LLM sees or how a trade is priced **does** change the hash, even in a file the old list never named.
- The fixtures double as regression tests. A failing hash shows *which* case and *which* field changed, not just "something in 14 functions".

**What it still cannot see** (these stay marked UNVERIFIED in the spec, as now):

- live-data behaviour outside the fixtures (a new kind of chain the fixtures don't contain);
- the provider changing the model behind the same deployment name;
- the research agents' outputs, which are LLM text and not reproducible. The research *prompts* could be hashed as text as a separate part, if wanted.

**Implementation sketch** (not done):

- a new `webapp/forward_fingerprint.py` with `behaviour_fingerprint(fixtures_dir) -> (hash, parts)`;
- the user-message builder becomes one shared function, used by `ask_rank_llm` and the M7 capture;
- `ai_test.fingerprint_problem()` compares against `spec.version.behaviour_sha256` for v4;
- the server's start-up check and the Plan banner stay as they are;
- a test asserts the frozen value, as `tests/test_fingerprint_frozen.py` does now.

The fingerprint must not fetch anything. It runs only on fixtures.

## 3. Migration plan

The hash rule in the spec is "changing the prompt, the candidate code or the model starts a new test". A new kind of fingerprint is itself such a change. v3 cannot switch in place.

1. **Close v3 with an audit-trail entry.** Write the date, the reason ("fingerprint method replaced, audit M6") and the count of v3 trades registered so far into the v3 spec's successor, the way v2 was closed in `supersedes`. The v3 spec and registry stay on file, unedited. Like v1.1 and v2, the closed v3 rows are not settled or reported. If the user prefers, they can be settled separately and labelled as a closed test that never reached its sample.
2. **Freeze v4.** Write `docs/ai_strategist_test_v4.json`:
   - same forward-test rules, stop rule and power analysis as v3 (unless the user changes them);
   - `version.behaviour_sha256` and the fixture-set hash;
   - `supersedes: v3` with its trade count.

   Give it a new registry `reports/ai_test/v4/registry.jsonl` and a new `FIRST_SESSION`: the first weekday session after the file is on main, as before.
3. **Land the refactors the old hash blocked** *before* the freeze, so v4's hash already covers them. That includes the shared message builder, IST-only clocks inside the former fingerprinted functions, and L6 inside `build_context` / `today_research`. After the freeze, any change that keeps behaviour is free. A change that alters behaviour fails the hash, and that means v5.
4. **Keep the old text fingerprint as information only** for one release: show both in the start-up log, then drop it.

**What the user loses:**

- **The v3 count restarts at 0.** v3 started on 2026-11-09. Every session it ran is lost from the sample, because the pass rule needs at least 50 settled trades and the stop is 2027-11-01. Each lost week is about 5 fewer possible trades before the stop, unless the v4 stop date moves out by the same amount (the user decides).
- A third test closed in about a week (v1.1, v2, v3) is a pattern worth stating openly in the trial list: each restart is another trial.
- **Best timing:** decide before many v3 sessions build up. The cost of switching only grows.

## 4. Cost and effort

| Item | Estimate |
|---|---|
| Golden fixtures: capture 6 to 10 real chains, candles and contexts from saved runs (`reports/ai_runs`, `reports/ai_test/*/chains`) and trim them | 0.5 to 1 day |
| `behaviour_fingerprint` + canonicalisation (float rounding, key order, clock freeze, network stubs) | 1 day |
| Shared message builder, and wiring `fingerprint_problem` / server check / tests to v4 | 0.5 day |
| v4 spec, supersedes entry, docs (PA note, fingerprint map rewrite) | 0.5 day |
| Review and a dry run: prove that a pure refactor keeps the hash and that a one-line helper change flips it | 0.5 day |
| **Total** | **about 3 to 3.5 working days** |

Running cost: none. There are no LLM calls, because the fingerprint runs only on fixtures with fake answers. It adds a few seconds to start-up and to the test suite.

Ongoing cost: the fixtures must be refreshed only when a v5 is frozen on purpose, never to make a red hash green.

**Risks:**

- Fixtures that are too few can let a behaviour change slip through. Mitigation: cover the edge cases listed above and add a case whenever a live bug shows a gap.
- Float canonicalisation that is too loose hides real changes; too tight, and it flips across machines. Mitigation: round to fixed significant figures and run the check on the user's PC and in CI before freezing.
- Behaviour that depends on the clock (expiry selection, days to expiry) must take its time from the fixture, not from the wall clock.

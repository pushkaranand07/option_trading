# Audit fix report: branch `fix/audit-2026-11`

The audit at commit `0ac755a` scored the project **5.4/10**. This branch fixes every finding from that audit and the issues found while checking the fixes. Every fix was red→green tested and checked by an agent that did not write it. Nothing is pushed: the branch is local and the user merges.

## Result

| | Audit (`0ac755a`) | Now |
|---|---|---|
| Score (strict rubric, fresh agent) | 5.4 | **6.3** at `e5f2d81` (5.8 at `393cfa2`, before S1–S5 were fixed) |
| Tests | 2,101 passed | **2,631 passed, 0 failed**, 24 skipped |
| Coverage, total | 77% | **88%** |
| Coverage, `webapp/server.py` | 51% | **99%** |
| Coverage, `webapp/market_data.py` | 58% | **96%** |
| `ruff check .` | 39 errors | **0** |
| `pip-audit` | clean | clean |
| Load test at 50 concurrent requests: `/api/status` p50 | 1.0 s | **0.59 s** |
| Load test at 50 concurrent requests: `/api/candles/NIFTY` p95 | 4.3 s | **1.85 s** |
| Lighthouse (performance / accessibility / best practices) | 79 / 96 / 96 | **80 / 100 / 100** |
| v3 forward-test fingerprint | `5a5fdbb3…` | **`5a5fdbb3…`**, unchanged, so v3 is still counting |

## Every finding

### Original audit

| ID | Finding | Status | Commit(s) | Test |
|---|---|---|---|---|
| H1 | A damaged `trades.json` read as empty, and the next write wiped the history | Fixed | `8ef0edb` `cd2146d` `146387d` `291095a` | `test_audit_a_h1_store_corrupt` and others. Before: 3 rows plus a stray comma, then one Take, left 1 row. After: the file is untouched, writes are refused, a backup copy is made and a banner is shown |
| H2 | No Host or Origin check (DNS rebinding and CSRF; any website could drive the app and its paid LLM calls) | Fixed | `76cf3ac` | `test_audit_b_h2_host_origin`. Foreign Host: 200 → **400**. Foreign Origin, or a write without `X-Pulse-Request`: → **403** |
| H3 | The forward-test registry had no lock; a race could break the hash chain for good | Fixed | `17b3488` `9c0b0a9` `69bceb6` | Race tests. Old code: 30/30 runs broke the chain or duplicated a day. New code: 0/60. Also safe across separate processes, a crash mid-append is refused, and the lock times out |
| H4 | `.env` was found by walking up parent folders, so any copy of the repo got the live keys | Fixed | `8ee9957` `0fb15be` | `test_dotenv_root_only`. Before: a parent folder's `.env` was loaded. After: only the repo root's `.env` is read |
| M1 | Wrong previous close after a special session (+1.83% shown instead of −0.18%) | Fixed | `f46c983` + 4 follow-ups | `test_audit_d_m1_*`. The previous close now comes from the app's own daily bars, cross-checked against the other sources, with no NaN reaching the page. Cold quote load: 6.2 s → 0.87 s |
| M2 | CSRF on the journal upload | Fixed | `cbfe133` | Only octet-stream, csv or xlsx uploads are accepted (others get 415); a cross-site request gets 403 |
| M3 | The monitor swallowed every error | Fixed | `3d7a0dc` `146387d` | Failures are logged with a traceback, counted, and shown by `monitor_status()` and a banner |
| M4 | `/api/status` returned 500 when the running code was older than the files | Fixed | `632b128` `ad85c83` `63a722d` | It never returns 500; each check that fails is listed under `degraded` |
| M5 | A global lock was held during network calls | Fixed | `5c712dd` | A fetch never holds the lock; races tested 120× each |
| M6 | The fingerprint hashes code text, which blocks refactoring | Proposal only | `24f93bc` | `docs/audit/m6_proposal.md`. **Gate 2: the user chose to keep v3 frozen** |
| M7 | The exact input the LLM saw was not saved | Fixed | `24a66eb` `c4c39cb` `ff29530` | It is saved to `reports/ai_runs/inputs/<run_id>.json`, byte-identical to what is sent, without touching fingerprinted code |
| M8 | Lint gate claimed clean but had 39 errors; CI enforced nothing | Fixed (lint); CI blocked | `5e4cd51` `708fa2f` | ruff 0. CI installs what the tests need and runs the UI harness. **GitHub shows 0 Actions runs ever: an account-level setting only the user can fix** |
| L1 | An unknown expiry silently became another one | Fixed | `9f4ceb3` `a939381` `ab34912` | 400 with the list of valid expiries; 502 when the list itself is unavailable |
| L2 | Upload had no size check before buffering; a malformed xlsx gave a 500 | Fixed | `e353ecd` `b28e116` `8562a95` `52a56fd` | 413 before reading. Zip bombs are refused under any file name. Malformed files get a clean 400 |
| L3 | CDN scripts had no SRI | Fixed | `f5cb3b7` | The three libraries are self-hosted at the same versions and hashes; the page still works if one is missing |
| L4 | Internal error text reached the page | Fixed | `70eb3de` `8e07c81` `c9deffb` | 500 with an error id; upstream failures are 502 with their message; take errors are 400 "Not taken" |
| L5 | `limit` was not checked | Fixed | `908aa2b` | Outside 1–5000 → 422 |
| L6 | Naive clock calls | Fixed outside frozen code | `91216fd` and track commits | IST everywhere except 10 calls inside fingerprinted functions, which stay under the Gate 2 decision |

### Found while checking the fixes

| ID | Finding | Status | Commit |
|---|---|---|---|
| Dhan account access | The project had a live call to the account's `/profile` endpoint, and nothing stopped account calls | Fixed | `bed760e` (guard), `ee91bf8` (no override, Gate 2), `082c08c` `911350d` (exact URL, https only, no redirects, requests no longer block each other). Security verifier: 156 account-access attempts, 0 reached the network |
| Test safety | Tests could write to the real `reports/` folder | Fixed | `a7cbb81` (conftest guard) |
| Plan-tab charts | The ES-module split broke the live charts in the browser | Fixed | `6a2990d`. The test harness now catches forgotten imports |
| Research tab | The tab had been stuck on "Loading…" since an older commit | Fixed | `e1883a8` |
| After-close expiry | A trade that expired after 15:30 stayed open until the next session | Fixed | `487acd4` |
| **S1 (High, fresh re-audit)** | A traversal symbol in `/api/candles/<symbol>` loaded an attacker's pickle, which can run code, through a GET any website can trigger | Fixed | `f815d5a`. Symbols must be plain, and the cache stays inside its own folder |
| S2 | After 15:30 on expiry day the default expiry was the expired contract | Fixed | `cb55a5b` |
| S3 | Expired trades settled at a stale price | Fixed | `e5f2d81` |
| S4 | One malformed row broke the whole record | Fixed | `e5f2d81` |
| S5 | A fresh install had one failing test (torch) | Fixed | `ef3fab2` |

## Gate 2 decisions (the user's)

1. **Keep v3 frozen.** The forward test keeps counting from 9 Nov; M6 is not built.
2. **Remove the `DHAN_ACCOUNT_ACCESS` escape hatch.** Account access now needs a code change.
3. **Keep pausing price polling while the browser tab is hidden.**

## Dhan call log (`_audit/dhan_calls.log`)

There are 2 calls, both `GET images.dhan.co/api-data/api-scrip-master.csv` (the public instrument list, HTTP 200). **Zero account endpoints.** The user's Dhan keys are empty in `.env`, so no other Dhan data was fetched.

## Data safety

`reports/` was backed up to `_backup/20261109-003355/` (1,757 files, SHA-256 manifest). The final check found:
- **every file is still present**;
- every change came from the user's own app or the scheduled jobs;
- no original trade lost or altered an entry;
- `events.log` was only appended to;
- the v1.1 and v2 registries are byte-identical to the backup;
- all three hash chains are intact.

## Left over (ranked)

| # | Item | Why it matters | Effort |
|---|---|---|---|
| 1 | **CI has never run on GitHub** | The tests only prove things on this machine. The user must check Settings → Actions | User |
| 2 | No type checker; mypy (not installed here) reports about 81 errors in `webapp/` | No static safety net | 1–2 days |
| 3 | The 14 fingerprinted functions stay as they are (naive clocks, the 55-branch `evidence()`) | Gate 2 choice; needs v4 (M6) to change | ~3.5 days plus a v3 restart |
| 4 | Leftover `getattr` stand-ins in `server.py` from building the tracks in parallel; v2/v3 naming drift | A renamed function would fail quietly | ~2 h |
| 5 | No security headers (CSP, X-Frame-Options); no gzip; `/api/status` runs `git` on every call | Small hardening and speed gains | ~2 h |
| 6 | `webapp/rules.py` keeps Python copies of the JS rules that only tests use | Could drift from the page | ~1 h |
| 7 | An unreadable (locked) store logs one line per market-hours tick; the settle script calls the strict `verify` without the lock | Log noise; a rare, safe failure | ~1 h |
| 8 | No dependency lock file | Installs are not reproducible | ~1 h |

## How to use the branch

```
git checkout fix/audit-2026-11      # or merge it into main
```

Restart the server on port 8000 after merging: it does not reload new code by itself. Before merging, check GitHub → Settings → Actions, so CI starts running.

## Final re-score (fresh agent, same rubric, at `e5f2d81`): **6.3 / 10, Mid level**

| Area | Score | Cap |
|---|---|---|
| Core | 6 | ≤6: the AI strategist can't be run without paid calls |
| Output | 6 | ≤6: the LLM ranking itself is unverified |
| Code | 6 | – |
| Architecture | 6 | – |
| Testing | 7 | – |
| Security | 7 | – |
| Performance | 6 | ≤6: not measured against the real data store |
| Frontend | 7 | – |
| Docs | 7 | – |
| **Total** | **6.37 → 6.3** | |

Confirmed fixed by that agent:
- The S1 proof of concept no longer runs code.
- S2–S4 hold.
- A fresh install's suite is green: 2,627 passed.

**Why not 7 or 8.** With three areas capped at 6, the other six must average at least 7.67 to reach 7 (they average 6.67). That needs leftovers #2, #4 and #5 above, plus:
- a typed store layer;
- branch coverage;
- the next-morning edge of S2: if NSE still lists yesterday's expiry before the open, it is picked;
- logging Dhan calls that fail at the network level;
- 400 instead of 502 for a rejected symbol.

**8 is not reachable while the caps bind.** Lifting them needs:
- one approved paid LLM run, or a recorded-response fixture that runs `strategist.start` → `ai_test.record` → `take` end to end;
- a load test against the real NSE store and `reports/`.

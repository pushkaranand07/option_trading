# PA-50 — Settlement, baselines and backup for the AI strategist's forward test

| | |
|---|---|
| **Status** | Built and tested on synthetic rows only. **Not cleared for real rows.** Backup not run: no destination chosen |
| **Scope** | new `tradingagents/research/ai_settle.py`, `scripts/ai_test_settle.py`, `scripts/ai_test_backup.py`, `docs/ai_test_backup_restore.md`, `tests/test_ai_test_settlement.py`; `docs/data_catalog.md` |
| **Related** | [PA-49](PA_49-ai-strategist-test.md), [spec](ai_strategist_test_v1.json) |
| **Date** | 2026-11-01 |

Research and decision support only, not investment advice. **Cost model unverified.** The spec, its hash and the registry are unchanged.

## 1. What it does

| Spec rule | Code |
|---|---|
| Hold to expiry, intrinsic on final settlement | `net_percent` |
| Net P&L after charges as % of max risk | `net_percent` |
| Random direction, same strike distances; condor centre moves 1% of spot | `random_variants`, priced from the saved chain |
| 1,000 draws, seeded from the spec hash | `evaluate` |
| Rule-based pick, same exit | `settle`, from the registry row |
| No trade = 0 | `evaluate` |
| Nothing below 50; warning and no verdict to 499 | `evaluate` |
| Verdict once, on the first 500 | `evaluate`; later trades cannot change it |
| Bootstrap by expiry week, 2.5th percentile | `evaluate` |

## 2. Two locks on real rows

1. `REAL_RUN_APPROVED = False` in `scripts/ai_test_settle.py`: the real registry is refused.
2. `settle` refuses any row whose symbol is not `SYNTHETIC` unless approved, so a copy of the registry is refused too.

Opening them needs a reviewed code change. Run with approval, the script still needs settlement prices and NSE sessions passed in as files; reading them from the store is not built.

## 3. Choices the spec does not state

- A random variant with no two-sided quote is left out; if both are, that trade has no random baseline and is counted.
- A trade with no rule-based pick is left out of that baseline's mean and counted. With no picks at all, the verdict is fail.
- Variants and picks use the repo's charges: cost model unverified.
- Void trades do not count toward 50 or 500, and they are reported.

## 4. Limits

A correct result on synthetic rows does not prove the live hook's rows match, because no real row exists. The chain format comes from the code, not from a real saved file.

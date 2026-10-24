# PA-26 — `docs/` restructured: index, folders, one change record per change

| | |
|---|---|
| **Status** | Done (this pull request) |
| **Scope** | everything under `docs/`; path references to moved files in `scripts/market_map.py`, `tradingagents/analytics/gates.py`, `pyproject.toml`, `README.md` |
| **Related** | [development/documentation-standards](development/documentation-standards.md), [README](README.md) |
| **Pull request** | branch `docs/pa-restructure` |
| **Date** | 2026-10-24 |

## 1. Problem

`docs/` held four long documents (two plans, the proof plan, the progress tracker), three strategy specs and a data
file. The history of what changed and why lived only in pull-request descriptions and the tracker's log; there was no
architecture description of the whole system. The user asked for the same structure as their other project: an index,
folders, and a separate `PA_XX-…` change record per change (user).

## 2. Decisions (user)

| Question | Choice |
|---|---|
| Scope | the **whole project** (original agents, CLI, webapp, option backtester, India layer, quant layer) |
| PA split | **one per change / pull request**, in date order |
| Existing documents | **moved into folders**; `PROGRESS_TRACKER.md` stays at the root (the daily job rewrites its bars) |
| Where to work | a **separate git worktree and branch**, so the running Phase 9 replay was not disturbed |

## 3. What changed

| Before | After |
|---|---|
| `docs/QUANT_SIGNAL_LAYER_PLAN.md`, `PROOF_PLAN.md`, `INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md` | `docs/plans/` (links into the code updated for the extra folder level) |
| `docs/market_events_2021_2026.json` | `docs/data/` (`scripts/market_map.py` reads the new path) |
| — | `docs/README.md` index; 26 PA records; `architecture/01–18`; `features/`; `development/`; `guides/`; `archive/` |

Format: [documentation standards](development/documentation-standards.md) — header block, numbered sections, facts only
(numbers from code, pull requests, the tracker or script output; "not recorded" otherwise), plain English, relative
links, nothing private (the repository is public).

## 4. How it was written

Five writers worked in parallel on fixed file lists (architecture of the agent framework; data, India layer, backtester
and UI; the quant layer; PA records 01–13; PA records 14–19); PA records 20–26, the index, the executive summary,
git workflow and the user guides were written by hand. All were checked against the code and each other.

## 5. Verification

A link check over every Markdown file in `docs/` (every relative link must resolve to an existing file); the unit suite
still passes (the only code edits are paths).

## 6. Risks and open items

- Documents describe the code as of 2026-10-24; each carries "Last verified against the code". Changes after that need
  their own PA record and an update of the affected documents.

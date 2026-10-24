# Documentation standards

> **Status:** Current. Written for the docs restructure ([PA-26](../PA_26-docs-restructure.md)).
> **Scope:** every file under `docs/`.
> **Last verified against the code:** 2026-10-24

---

## 1. Layout

| Path | What goes there |
|---|---|
| `docs/README.md` | The index: start-here table, folders, every PA record, every architecture document |
| `docs/PA_XX-short-name.md` | **Change records**, one per change (usually one per pull request), numbered in date order |
| `docs/architecture/NN-name.md` | How the system is built, one topic per file, numbered |
| `docs/features/name.md` | One document per live feature: what it does, how to use it, files, settings, known issues |
| `docs/development/name.md` | Working on the code: setup, tests, git workflow, operations |
| `docs/guides/name.md` | Step-by-step guides for the user (trading on Dhan with the outputs, exporting a tradebook) |
| `docs/plans/` | Plans that are still the reference for ongoing work |
| `docs/strategies/` | Frozen strategy specifications (Stage 0 of the proof plan) with their results appended |
| `docs/data/` | Small, public, sourced reference data the code reads (e.g. the researched market events) |
| `docs/archive/` | History only; never a statement of current behaviour |
| `docs/PROGRESS_TRACKER.md` | Stays at the root: `scripts/update_progress.py` and the daily job rewrite its bars |

File names: lower-case words joined by hyphens; PA records keep the `PA_XX-` prefix (two digits).

## 2. Header block

Every document starts with a title and a short block:

```markdown
# PA-07 — One line saying what changed

| | |
|---|---|
| **Status** | Done · In progress · Plan · Superseded by PA-NN |
| **Scope** | the files / modules touched |
| **Related** | links to other PA records or documents |
| **Pull request** | #N (branch `name`), or the commit hash for direct commits |
| **Date** | YYYY-MM-DD |
```

Architecture, feature, development and guide documents use the blockquote form instead:

```markdown
# Title

> **Status:** Current.
> **Scope:** what this covers.
> **Last verified against the code:** YYYY-MM-DD
```

## 3. PA record sections

Numbered, in this order; leave out a section only if it truly does not apply:

1. **Problem** — what was wrong or missing, in the user's terms
2. **Root cause / findings** — what was actually found (with numbers)
3. **Decisions** — what was chosen and why, including what was considered and rejected; decisions the user made are marked "(user)"
4. **What was built / changed** — modules, scripts, behaviour; a table is fine
5. **Tests** — what the tests prove
6. **Results** — measured outcomes, verdicts
7. **Verification** — how it was checked on real data / in operation
8. **Risks and open items** — what is not known, what is left

## 4. Writing rules

- **Facts only.** Every number comes from the code, a pull request, a commit, the progress tracker, a strategy spec or a
  script's output. If something is not known, say "not recorded" — never estimate a figure into a document.
- **Plain English, short sentences.** Explain trading terms the first time (e.g. "iron condor: sell a put spread and a
  call spread together, losses capped by the wings").
- **Link, don't repeat.** Relative links between documents (`../architecture/12-nse-data-store.md`), and
  `path/to/file.py` for code.
- **Never in a document:** API keys, tokens, account numbers, the user's capital figure, personal trade data, raw NSE
  data. The repository is public.
- **Research only.** Anything about trading says it is research and decision support, not investment advice.
- Dates as `YYYY-MM-DD`; money as `₹1,234`; percentages with the sign where it matters (`−6.5%`).

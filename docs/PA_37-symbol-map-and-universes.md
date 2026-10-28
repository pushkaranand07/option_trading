# PA-37 — Data foundation batch d: symbol continuity map and point-in-time universes

| | |
|---|---|
| **Status** | Done |
| **Scope** | new `scripts/quant_symbol_map.py` → `docs/data/symbol_map_v1.csv`; new `docs/data/universes_v1.json` (rules addendum); new `tradingagents/research/universes.py`; new `scripts/quant_build_universes.py`; tests `tests/test_research_universes.py`, `tests/test_research_import_guard.py`; `docs/data_catalog.md` |
| **Related** | [PA-36](PA_36-base-2010-2014.md), [PA-33](PA_33-fo-universe-count.md), [PA-31](PA_31-research-splits-and-locked-loader.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `data/step-2d-universes` |
| **Date** | 2026-10-28 |

Research and decision support only, not investment advice.

## 1. Problem

Modelling universes are views on the stored base, not deletions (user). Batch d: a map of renamed symbols from NSE's
symbol-change list only; U1 = all indices plus the top 100 stocks by the previous year's F&O turnover; U2 = every
underlying; both point in time; the 2026 ranking, whose inputs are in the locked holdout, done in a sealed function.

## 2. Symbol map (rule A)

Source: NSE's `symbolchange.csv`, saved raw with SHA-256 (`<raw>/nse_lists/2026-10-28_symbolchange.csv`). No
name similarity is used. A link old → new is **mapped** when the new symbol trades F&O in the base and the two never
trade on the same date.

| Result | Count |
|---|---|
| Stocks that left F&O and are an OLD SYMBOL in NSE's list | 57 (57 links) |
| Mapped | **41**: in every one the old symbol's last F&O day is before NSE's effective date and the new symbol's first is on or after it; 0 overlapping dates |
| Unmapped (new symbol never traded F&O; separate series, labelled) | **16**: AIL→GEPIL, ALSTOMT&D→GET&D, AMARAJABAT→ARE&M, BHUSANSTL→TATASTLBSL, CENTURYTEX→ABREL, FINANTECH→63MOONS, FRL→FEL, GUJFLUORO→GFLLIMITED, GUJGASLTD→GUJENERGY, HOTELEELA→HLVLTD, IBREALEST→EMBDL, INFIBEAM→CCAVENUE, JINDALSWHL→JSWHL, NEYVELILIG→NLCINDIA, ORCHIDCHEM→ORCHIDPHAR, STRTECH→STLTECH |

**Discontinuities at the change date (flags only, nothing adjusted):** of the 41 mapped, 33 none; 2 flagged on price and
open interest (DCB→DCBBANK, MAX→MFSL: the stock left F&O years before returning under the new symbol, so the two
sessions compared are years apart); 6 inside the locked holdout, dates only, no price or OI read (IBULHSGFIN→SAMMAANCAP,
ICICIPRULI→ICICILIFE, INDIAINFO→IIFL, LTIM→LTM, TATAMOTORS→TMPV, ZOMATO→ETERNAL). Four mapped links have long gaps
between the two symbols' F&O spells (DCB, IBULHSGFIN, INDIAINFO, MAX).

**Chains** (two listed links meeting at one symbol), kept link by link as NSE lists them: APIL→AIL→GEPIL,
AREVAT&D→ALSTOMT&D→GET&D, LTI→LTIM→LTM, PANTALOONR→FRL→FEL, SESAGOA→SSLT→VEDL, TATATEA→TATAGLOBAL→TATACONSUM. NSE's
list records symbol changes only; whether any of them coincides with a merger or demerger (e.g. TATAMOTORS→TMPV,
SESAGOA→SSLT) is **UNVERIFIED** from this source and flagged for review. Only mapped links are joined into a series.

## 3. Universes (rules B, C, D, E)

The rules were written to `docs/data/universes_v1.json` and committed (`043c514`) **before** any ranking ran. It references
the split file's hash and the symbol map's hash (line-ending normalised); `universes.addendum()` refuses to run if either
changed.

| Rule | Fixed in the addendum |
|---|---|
| Rank field | Sum over calendar year Y−1 of `fut_turnover + opt_turnover` in `base_fo_summary` (rupees as NSE reports them; options at notional), summed across a series' symbols |
| Order, tie-break, cutoff | Turnover descending; equal turnover → series id ascending; rank ≤ 100 |
| Rebalance | Once a year, from the first session of Y; no mid-year additions or replacements |
| Membership on session D | The series is in D's year's universe and has a row with `known_from` = D (it traded the session before, public at D); a name leaves on its real exit |
| Start | U1 2011 (2010 has no prior year in the base); U2 2010 |
| U2 | Every stock and index series (INDIAVIX futures excluded: no options) |
| Protected range | 2026 is ranked inside `sealed_top_n` only. Built through 2026-10-26; the forward holdout is not read |

**Sealed ranking.** `sealed_top_n` returns a frozen set of series ids and nothing else; on any failure it raises
`SealedRankingError` outside the failing block, so no original exception (and no value in it) is attached. **Sealed
year: 2026** (inputs 2025). Open years 2011–2025 (inputs 2010–2024) may report turnover and rank gaps. The build read the
base through the research loader with a logged final-holdout unlock (trial-log event 10) and is trial-log event 11
(`data_build`, counts only).

## 4. Results (rule G)

### Members per year (distinct series)

| Year | U1 (stocks + indices) | U2 (stocks + indices) | U1 as share of U2 |
|---|---|---|---|
| 2010 | — | 232 (227 + 5) | — |
| 2011 | 108 (99 + 9) | 245 (236 + 9) | 44% |
| 2012 | 110 (100 + 10) | 236 (226 + 10) | 47% |
| 2013 | 105 (95 + 10) | 164 (154 + 10) | 64% |
| 2014 | 106 (97 + 9) | 157 (148 + 9) | 68% |
| 2015 | 112 (99 + 13) | 178 (165 + 13) | 63% |
| 2016 | 109 (100 + 9) | 187 (178 + 9) | 58% |
| 2017 | 110 (100 + 10) | 226 (216 + 10) | 49% |
| 2018 | 107 (99 + 8) | 219 (211 + 8) | 49% |
| 2019 | 103 (100 + 3) | 203 (200 + 3) | 51% |
| 2020 | 102 (99 + 3) | 153 (150 + 3) | 67% |
| 2021 | 103 (100 + 3) | 191 (188 + 3) | 54% |
| 2022 | 104 (100 + 4) | 203 (199 + 4) | 51% |
| 2023 | 103 (99 + 4) | 195 (191 + 4) | 53% |
| 2024 | 104 (99 + 5) | 233 (228 + 5) | 45% |
| 2025 | 105 (100 + 5) | 257 (252 + 5) | 41% |
| 2026 (to 2026-10-26) | 106 (100 + 6) | 230 (224 + 6) | 46% |

U1 is a subset of U2 by construction, so the overlap is U1 itself. Years with fewer than 100 U1 stocks are names
ranked in the previous year's top 100 that had left F&O before the year's first session; they are not replaced.

### U1 indices per year

| Year | Count | Indices |
|---|---|---|
| 2011 | 9 | BANKNIFTY, CNXINFRA, CNXIT, CNXPSE, DJIA, MINIFTY, NFTYMCAP50, NIFTY, S&P500 |
| 2012–2013 | 10 | the 2011 list + FTSE100 |
| 2014 | 9 | as 2012 without MINIFTY |
| 2015 | 13 | BANKNIFTY, CNXINFRA, CNXIT, CNXPSE, DJIA, FTSE100, NFTYMCAP50, NIFTY, NIFTYINFRA, NIFTYIT, NIFTYMID50, NIFTYPSE, S&P500 |
| 2016 | 9 | BANKNIFTY, DJIA, FTSE100, NIFTY, NIFTYINFRA, NIFTYIT, NIFTYMID50, NIFTYPSE, S&P500 |
| 2017 | 10 | 2016 + NIFTYCPSE |
| 2018 | 8 | BANKNIFTY, FTSE100, NIFTY, NIFTYCPSE, NIFTYINFRA, NIFTYIT, NIFTYMID50, NIFTYPSE |
| 2019–2020 | 3 | BANKNIFTY, NIFTY, NIFTYIT |
| 2021 | 3 | BANKNIFTY, FINNIFTY, NIFTY |
| 2022–2023 | 4 | BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTY |
| 2024–2025 | 5 | BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTY, NIFTYNXT50 |
| 2026 | 6 | 2025 + NIFTYFPI |

DJIA, S&P500 and FTSE100 are NSE-listed derivatives on foreign indices; they are index underlyings in the base and so
in U1. Whether to keep them in a model universe is not decided here.

### Delisted and renamed names inside the universes

| | U1 | U2 |
|---|---|---|
| Stock series | 233 | 432 |
| Renamed, joined across symbols (mapped links) | 30 | 38 |
| Left F&O before 2026-10-23 (last session read) | 94 | 219 |
| … of them renamed but unmapped (separate series) | 5 | 13 |
| … of them not on NSE's current equity list, reason UNVERIFIED | 36 | 68 |

### Open years: how close the 100th and 101st names were

Turnover of #100 vs #101 (crore rupees): 2011 3.9% apart, 2012 0.1%, 2013 0.2%, 2014 0.1%, 2015 2.9%, 2016 1.2%,
2017 0.3%, 2018 2.3%, 2019 2.8%, 2020 0.2%, 2021 1.4%, 2022 6.7%, 2023 0.2%, 2024 1.7%, 2025 1.8%. In several years the
boundary rests on a 0.1–0.3% turnover difference; a robustness check (U2, or a different N) matters. **2026: sealed,
not reported.** Full figures: `reports/fo_count/universes_v1.log` (local).

## 5. Tests (rule F and condition 2)

| Test | Proves |
|---|---|
| `test_sealed_ranking_returns_only_member_ids_and_leaks_nothing` | Only a set of ids returns; no turnover value appears in logs, stdout / stderr, files or the return value |
| `test_a_failing_sealed_ranking_carries_no_values` | With an internal error that embeds turnover and a rank gap, the raised error has no `__context__` / `__cause__` and its message, repr, args and full traceback hold no value |
| `test_ranking_inputs_never_include_the_modelled_year` | Huge turnover in the modelled year changes nothing |
| `test_membership_on_d_is_identical_from_data_truncated_at_d_minus_1` | Membership on D rebuilt from rows traded before D equals the full build, around a mid-year exit |
| `test_a_name_leaves_on_its_real_exit_and_is_not_replaced` | Exit on the real date, no replacement; stocks only in ranked years |
| `test_ties_break_alphabetically_and_open_ranking_refuses_the_protected_year` | Tie-break; `open_ranking` refuses 2026 |
| `test_renamed_symbols_are_one_series_only_for_mapped_links` | Only mapped links join; unmapped stay separate |
| `test_addendum_matches_the_split_file_and_the_symbol_map` | A changed symbol map is refused |
| `test_real_store_membership_on_d_matches_truncated_rebuild` (opt-in) | The truncation test on the real base, 2015–2016 dates |

## 6. Risks and open items

- Chains and possible merger / demerger links are flagged, not resolved (NSE's list does not say).
- The 100 / 101 boundary is often within 0.3% of turnover.
- Foreign-index derivatives (DJIA, S&P500, FTSE100) are in U1 as indices.
- Membership beyond 2026-10-26 needs the forward holdout: built only by the final pre-registered test.

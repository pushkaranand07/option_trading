# PA-41 — Gate v2 addendum 1: re-measured item d, no-overlap time shift, forward skip rule, ADANIENT

| | |
|---|---|
| **Status** | Done. No model built. One decision open: the forward list source |
| **Scope** | new `docs/gate_v2_addendum_1.json`; `tradingagents/research/gate2.py`, `registry.py`; new `scripts/research_gate2_addendum.py`, `scripts/quant_addendum_diagnostics.py`; `scripts/research_gate2_harness.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-40](PA_40-gate-v2.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `research/gate-v2-addendum` |
| **Date** | 2026-10-30 |

Research and decision support only, not investment advice. **Every result: cost model unverified; slippage is an ASSUMPTION.** Nothing from 2025-01-01 onward was read, and no request was made.

`gate_v1.json` and `gate_v2.json` are unchanged. The addendum has its own hash, `0152d74e…`, logged as trial-log event 16. Trial count: 339 (334 + 5 logged here).

## 1. Item d and the governing number

5,000 runs per cell on fresh seeds, development trades, rule A. Intervals are exact 95%. **The claim is the false-pass rate of the full Tier 1 and Tier 2.**

| h | Cost-carrying null, item d | Zero-mean nulls, worst item d, 100 dates | Worst item d, 150 dates |
|---|---|---|---|
| 1 | 0.00% [0.00, 0.07] | 3.08% [2.62, 3.60] | 2.90% [2.45, 3.40] |
| 2 | 0.00% [0.00, 0.07] | 3.86% [3.34, 4.43] | 3.74% [3.23, 4.30] |
| 3 | 0.00% [0.00, 0.07] | 3.48% [2.99, 4.03] | 3.48% [2.99, 4.03] |
| **5** | **0.00% [0.00, 0.07]** | **4.28% [3.74, 4.88]** | **4.72% [4.15, 5.34]** |
| 10 | at most 0.12% [0.04, 0.26] | 4.02% [3.49, 4.60] | 3.88% [3.36, 4.45] |

At h = 5 the lower end of every interval is below 5%, so this is **not recorded as a known looseness**. The 5.7% from 1,000 runs did not repeat. Item d is still above its nominal 2.5% on the zero-mean nulls at every h. The block was not re-picked.

**Tier 1 and Tier 2 false pass: 0 passes in 5,000 runs at every h, on both nulls, at 100 and 150 dates: 0.00% [0.00, 0.07].**

## 2. Time-shift control

The signal hits 90% before the shift. Direction moves by whole timeline dates, and one timeline date is at least one session. 1,000 runs per cell. A rate above 5% is a FAIL of the harness.

| h | Shift, dates | Tier 1, 100 / 150 dates | Tier 2, 100 / 150 dates | Result |
|---|---|---|---|---|
| 1 | 1, 2, 20 | 0.00% / 0.00% | 0.00% / 0.00% | PASS |
| 2 | 2, 4, 20 | 0.00% / 0.00% | 0.00% / 0.00% | PASS |
| 3 | 3, 6, 20 | 0.00% / 0.00% | 0.00% / 0.00% | PASS |
| 5 | 5, 10, 20 | 0.00% / 0.00% | 0.00% / 0.00% | PASS |
| 10 | 10, 20, 20 | 0.00% / 0.00% | 0.00% / 0.00% | PASS |

Each cell's interval is [0.00, 0.37]. Win rate falls back to the random-direction level (48.2% at h = 10, against 53.5% with the 3-date shift). This confirms the 6.0% in PA-40 came from the shift overlapping the return. At h = 10, 2h and 20 dates are the same run. A row reads the row at the same position on the earlier date, which is not always the same symbol, so this tests market-wide carry-over more strictly than single-stock carry-over.

## 3. Forward skip rule

- Skip a trade only if an action of rule A's kinds, with an announced ex-date after entry and up to exit, was on the list at the signal time.
- An action not announced by the signal time causes no skip. The trade counts as normal, including a large gap loss.
- The forward registry stores the sha256 of the list as it stood at signal time. `registry.register` refuses a signal without one. The registry has no live entries yet, so no history changed.

**Source:** not decided. The only stored list came from one download of NSE's corporate-action data on 2026-10-28, ending 2024-12. **The nightly job does not collect it**, and no collection was started.

**Did rule A use information not announced at signal time? UNVERIFIED per action, both numbers.** Rule A has no announcement test, and it uses a list downloaded in 2026. `caBroadcastDate` is empty on all 22,323 rows. The board-meeting files start in 2017 and cover 29 symbols: only 5 of 822 split and bonus actions have a stored notice. Those 5 notices came at least 50 days before the ex-date, too few to generalize.

**What can be measured is the bound.** The forward rule lies between rule A and skipping nothing. U1, raw trades, 1.5x costs, net % per trade:

| h | Period | Skipped by list | Their mean gross % | Always long, A / skip nothing | Always short, A / skip nothing |
|---|---|---|---|---|---|
| 1 | Development | 0 | n/a | -0.277 / -0.277 | -0.201 / -0.201 |
| 2 | Development | 61 | -47.8 | -0.264 / -0.274 | -0.214 / -0.204 |
| 3 | Development | 122 | -47.9 | -0.250 / -0.270 | -0.228 / -0.208 |
| 5 | Development | 242 | -48.1 | -0.218 / -0.257 | -0.260 / -0.221 |
| 10 | Development | 542 | -48.0 | -0.128 / -0.216 | -0.350 / -0.263 |
| 1 | Validation | 0 | n/a | -0.246 / -0.246 | -0.230 / -0.230 |
| 2 | Validation | 11 | -49.7 | -0.176 / -0.187 | -0.300 / -0.289 |
| 3 | Validation | 22 | -49.9 | -0.107 / -0.129 | -0.369 / -0.348 |
| 5 | Validation | 42 | -49.2 | +0.039 / -0.002 | -0.516 / -0.474 |
| 10 | Validation | 92 | -48.4 | +0.421 / +0.330 | -0.897 / -0.807 |

At h = 5 in validation, always long changes sign across the bound. A long-biased result at h = 5 or h = 10 under rule A can therefore be flattered, and a short-biased one penalized, compared with what forward can see.

## 4. Deviation: demergers and consolidations

The instruction named splits and bonuses. Rule A also skips demergers and consolidations. Kept, and recorded in the catalog. Trades removed only by them, development, U1:

| h | Trades | Positive share | Mean gross % | Extreme |
|---|---|---|---|---|
| 1 | 0 | n/a | n/a | 0 |
| 2 | 7 | 0.0% | -38.2 | 4 |
| 3 | 14 | 7.1% | -38.7 | 8 |
| 5 | 26 | 3.8% | -41.6 | 16 |
| 10 | 56 | 3.6% | -42.2 | 36 |

## 5. ADANIENT, signal 2015-05-25

**A price discontinuity on the ex-date of a listed corporate action. Not a data error.** Whether a holder lost 87% is UNVERIFIED. It stays in rule A results.

| Evidence | Stored finding |
|---|---|
| Action file | `ADANIENT`, ex-date 03-Jun-2015, record date 04-Jun-2015, "Scheme Of Arrangement" |
| Raw F&O file, 06-02 | June future closes 634.40; strikes 460-940 |
| Raw F&O file, 06-03 | June future opens 448.15, closes 110.30; July closes 110.45; strikes 20-680 |
| Open interest, 06-03 | `CHG_IN_OI` equals `OPEN_INT` on all three expiries, a reset rather than a change. 06-04 returns to ordinary changes |
| After 06-03 | Trading continues near that level: 116.90 on 06-04, 100.05 on 06-08 |
| Yahoo bar | **UNVERIFIED.** Stored prices start 2018-01-01; no 2015 bar exists in the store |
| What holders received | **UNVERIFIED.** The file names the scheme, not its terms |

**Corrections to PA-40.** It said the action files list nothing for ADANIENT, and that open interest barely moved. Both were wrong. The list exists, but my filter dropped its subject. The detector's close-to-close open-interest test missed the reset.

**The wider gap.** Rule A's list omits scheme of arrangement, amalgamation, capital reduction and the spelling "De-Merger": 68 rows. Trades in those windows, development, U1, stay in rule A:

| h | Trades | Mean gross % | Extreme |
|---|---|---|---|
| 1 | 0 | n/a | 0 |
| 2 | 9 | -29.7 | 2 |
| 3 | 18 | -30.1 | 6 |
| 5 | 36 | -30.7 | 11 |
| 10 | 81 | -31.4 | 26 |

Of the 115 detector flags, 13 have an action of any subject within 3 days, not 7. The other 102 have none. The gate does not change. Forward, the same kinds stay outside the skip rule unless a later version says otherwise.

## 6. Calendar

The 2027 session list is UNVERIFIED until NSE's 2027 holiday circular is available. All "earliest date" figures are lower bounds.

## 7. Risks and open items

- **Forward list source: the user's decision.**
- **A gap loss may not be an account loss.** Exchanges commonly adjust open F&O positions for corporate actions, and the 03-Jun open-interest reset fits that. No stored document confirms how this one was treated, so this is UNVERIFIED. The forward rule counts the loss as written.
- **Validation was read again** for the bound in section 3. Logged as 5 trials.

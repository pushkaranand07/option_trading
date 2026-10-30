# IV liquidity threshold report

> **Status:** Measured 2026-10-30, before any IV feature was built; the result is in [features_v1.json](features_v1.json).
> **Scope:** european option-chain rows of 2015-2022 only. No return or target was read.

**Result: 25 contracts on the thinner leg**, the smallest candidate with a put-call parity flag rate at or below 1%.

European rows 48,153,514; call-and-put pairs 24,076,408; pairs tested for parity 3,311,011. Flag rate with no threshold: 9.44%.

| Thinner leg, contracts | Tested pairs | Flagged | Flag rate | Rows kept | Share of european rows kept | At or below 1% |
|---|---|---|---|---|---|---|
| 10 | 1,665,593 | 29,460 | 1.769% | 3,572,936 | 7.42% | No |
| 25 | 1,163,298 | 7,518 | 0.646% | 2,535,420 | 5.27% | Yes |
| 50 | 857,669 | 2,432 | 0.284% | 1,900,136 | 3.95% | Yes |
| 100 | 614,638 | 773 | 0.126% | 1,390,772 | 2.89% | Yes |
| 250 | 363,612 | 210 | 0.058% | 861,842 | 1.79% | Yes |
| 500 | 222,172 | 99 | 0.045% | 559,316 | 1.16% | Yes |

## Flag rate by year

| Year | 10 | 25 | 50 | 100 | 250 | 500 |
|---|---|---|---|---|---|---|
| 2015 | 2.20% | 0.86% | 0.37% | 0.18% | 0.07% | 0.03% |
| 2016 | 1.74% | 0.59% | 0.25% | 0.09% | 0.05% | 0.01% |
| 2017 | 1.41% | 0.51% | 0.21% | 0.10% | 0.02% | 0.01% |
| 2018 | 2.37% | 0.85% | 0.36% | 0.19% | 0.09% | 0.05% |
| 2019 | 2.17% | 0.90% | 0.52% | 0.30% | 0.19% | 0.17% |
| 2020 | 2.38% | 0.91% | 0.42% | 0.19% | 0.09% | 0.08% |
| 2021 | 1.36% | 0.46% | 0.19% | 0.08% | 0.04% | 0.04% |
| 2022 | 1.35% | 0.48% | 0.18% | 0.06% | 0.01% | 0.01% |

The rate is tested on pairs where both legs traded. A pair with an untraded leg has no parity test and cannot be liquid at any candidate.

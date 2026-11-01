# Volatility sizing: constant, GARCH, HAR

> **Status:** Run 2026-11-01 from frozen [vol_sizing_test_v1.json](vol_sizing_test_v1.json). **Report-only, with no edge claim.**
> **Scope:** development test folds 2013-2022, U1 stocks, always long, h = 1. All three sizers on identical rows.

**Lower risk is not an edge. Cost model unverified.** Research and decision support only, not investment advice.

Rows: 211,126; dates: 2,336; rows dropped for a missing forecast: 17,588.

## All folds

| Sizer | Volatility % | Max drawdown % | Mean a day % gross | Mean a day % net | Mean weight | Mean daily weight change | Drawdown % at the constant sizer's volatility (hindsight scaling) |
|---|---|---|---|---|---|---|---|
| constant | 19.32 | -86.8 | -0.0288 | -0.2707 | 1.000 | 0.000 | -86.8 |
| garch | 15.32 | -70.9 | -0.0259 | -0.2518 | 0.934 | 0.035 | -89.3 |
| har | 30.25 | -143.4 | -0.0534 | -0.4725 | 1.733 | 0.026 | -91.6 |

## By fold

| Fold | Sizer | Volatility % | Max drawdown % | Mean a day % gross |
|---|---|---|---|---|
| 2013-14 | constant | 21.35 | -36.1 | -0.0471 |
| 2013-14 | garch | 16.31 | -29.8 | -0.0397 |
| 2013-14 | har | 31.75 | -60.4 | -0.0825 |
| 2015-16 | constant | 18.56 | -42.4 | -0.0721 |
| 2015-16 | garch | 15.14 | -35.6 | -0.0602 |
| 2015-16 | har | 29.81 | -71.1 | -0.1221 |
| 2017-18 | constant | 15.57 | -19.9 | -0.0005 |
| 2017-18 | garch | 13.60 | -17.8 | -0.0031 |
| 2017-18 | har | 26.54 | -35.1 | -0.0051 |
| 2019-20 | constant | 23.83 | -31.0 | -0.0059 |
| 2019-20 | garch | 17.09 | -23.0 | -0.0093 |
| 2019-20 | har | 34.42 | -46.2 | -0.0232 |
| 2021-22 | constant | 16.06 | -24.5 | -0.0189 |
| 2021-22 | garch | 14.25 | -21.2 | -0.0176 |
| 2021-22 | har | 28.19 | -42.2 | -0.0350 |

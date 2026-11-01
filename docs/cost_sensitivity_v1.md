# Cost sensitivity: slippage at 1x to 3x

> **Status:** Measured 2026-11-01. Report-only: it decides nothing and changes no verdict.
> **Scope:** development test folds 2013-2022, U1, after the GARCH fix. Trades and settings are the refit's; nothing was refit or re-chosen.

**Cost model unverified.** Charges stay at 1x and only slippage moves, so 1.5x here is not the gate's 1.5x on everything. Slippage itself is an ASSUMPTION: 2 bps per fill on index futures, 5 bps on stocks. Net % per trade. Research and decision support only, not investment advice.

## Best baseline, highest of 20 schedules

| h | 1x | 1.5x | 2x | 3x |
|---|---|---|---|---|
| 1 | -0.131 (always_short) | -0.180 (always_short) | -0.229 (always_short) | -0.327 (always_short) |
| 2 | -0.147 (prev_day) | -0.195 (garch_risk_scaled) | -0.241 (garch_risk_scaled) | -0.334 (garch_risk_scaled) |
| 3 | -0.132 (garch_risk_scaled) | -0.178 (garch_risk_scaled) | -0.224 (garch_risk_scaled) | -0.315 (garch_risk_scaled) |
| 5 | -0.055 (garch_risk_scaled) | -0.101 (garch_risk_scaled) | -0.147 (garch_risk_scaled) | -0.238 (garch_risk_scaled) |
| 10 | +0.115 (always_long) | +0.066 (always_long) | +0.017 (always_long) | -0.081 (always_long) |

## Model cells

| Spec | h | Trades | 1x | 1.5x | 2x | 3x |
|---|---|---|---|---|---|---|
| a logistic | 1 | 124,655 | -0.135 | -0.184 | -0.233 | -0.331 |
| a linear | 1 | 32,141 | -0.152 | -0.199 | -0.247 | -0.343 |
| b LightGBM | 1 | 82,784 | -0.176 | -0.225 | -0.274 | -0.372 |
| d CNN | 1 | 37,068 | -0.200 | -0.249 | -0.298 | -0.396 |
| e ensemble | 1 | 34,703 | -0.159 | -0.208 | -0.257 | -0.356 |
| f rank | 1 | 44,978 | -0.083 | -0.133 | -0.183 | -0.283 |
| a logistic | 2 | 54,479 | -0.148 | -0.197 | -0.246 | -0.344 |
| a linear | 2 | 48,302 | -0.150 | -0.199 | -0.248 | -0.345 |
| b LightGBM | 2 | 71,309 | -0.227 | -0.276 | -0.325 | -0.423 |
| d CNN | 2 | 10,470 | +0.090 | +0.041 | -0.009 | -0.107 |
| e ensemble | 2 | 37,002 | -0.150 | -0.200 | -0.249 | -0.347 |
| f rank | 2 | 57,680 | -0.054 | -0.104 | -0.154 | -0.254 |
| a logistic | 3 | 33,608 | -0.050 | -0.100 | -0.149 | -0.247 |
| a linear | 3 | 48,204 | -0.024 | -0.072 | -0.121 | -0.219 |
| b LightGBM | 3 | 49,023 | -0.325 | -0.374 | -0.423 | -0.521 |
| d CNN | 3 | 18,009 | +0.023 | -0.026 | -0.076 | -0.174 |
| e ensemble | 3 | 40,009 | -0.153 | -0.202 | -0.251 | -0.349 |
| f rank | 3 | 23,724 | -0.008 | -0.058 | -0.108 | -0.208 |
| a logistic | 5 | 26,175 | -0.112 | -0.161 | -0.211 | -0.309 |
| a linear | 5 | 45,110 | -0.004 | -0.053 | -0.102 | -0.200 |
| b LightGBM | 5 | 31,484 | -0.058 | -0.107 | -0.156 | -0.254 |
| d CNN | 5 | 25,249 | +0.076 | +0.027 | -0.022 | -0.120 |
| e ensemble | 5 | 21,099 | +0.081 | +0.032 | -0.017 | -0.115 |
| f rank | 5 | 16,909 | +0.071 | +0.021 | -0.029 | -0.129 |
| a logistic | 10 | 17,771 | -0.161 | -0.210 | -0.259 | -0.357 |
| a linear | 10 | 23,816 | +0.054 | +0.005 | -0.044 | -0.142 |
| b LightGBM | 10 | 20,535 | +0.512 | +0.463 | +0.414 | +0.316 |
| d CNN | 10 | 17,432 | +0.317 | +0.268 | +0.219 | +0.121 |
| e ensemble | 10 | 16,282 | +0.201 | +0.152 | +0.103 | +0.004 |
| f rank | 10 | 16,210 | +0.168 | +0.118 | +0.068 | -0.032 |

# Feature catalog v1

> **Status:** Built 2026-10-30 from frozen [features_v1.json](features_v1.json), hash `97129483…`. No model, and no predictive power measured.
> **Scope:** every feature's definition, source timing, missingness and quality result. Missing is the mean of yearly rates across signal dates; 'Dev' is 2011-2022, 'Val' 2023-2024. U1 has no members before 2011.

Quality result for every row: known_from PASS; truncation PASS. Handling of corporate actions, rolls and holes: PASS ([PA-42](PA_42-feature-library-v1.md)). '>0.95' marks a feature in at least one pair above 0.95: flagged, not dropped. Yearly missingness is in [feature_missingness.md](feature_missingness.md).

## a. Price and volatility

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `ret_1` | sum of log(close_t / close_t-1) on the near contract over 1 sessions; every session must be present | 1 sessions, all required | Next session after source | 1.9% | 0.4% | 1.2% | 0.4% | 2011 | input |  |
| `ret_2` | sum of log(close_t / close_t-1) on the near contract over 2 sessions; every session must be present | 2 sessions, all required | Next session after source | 2.1% | 0.7% | 1.4% | 0.7% | 2011 | input |  |
| `ret_3` | sum of log(close_t / close_t-1) on the near contract over 3 sessions; every session must be present | 3 sessions, all required | Next session after source | 2.3% | 0.9% | 1.6% | 0.9% | 2011 | input |  |
| `ret_5` | sum of log(close_t / close_t-1) on the near contract over 5 sessions; every session must be present | 5 sessions, all required | Next session after source | 2.6% | 1.4% | 2.0% | 1.5% | 2011 | input |  |
| `ret_10` | sum of log(close_t / close_t-1) on the near contract over 10 sessions; every session must be present | 10 sessions, all required | Next session after source | 3.2% | 2.6% | 3.0% | 2.9% | 2011 | input |  |
| `ret_20` | sum of log(close_t / close_t-1) on the near contract over 20 sessions; every session must be present | 20 sessions, all required | Next session after source | 4.4% | 5.0% | 4.8% | 5.7% | 2011 | input |  |
| `ret_60` | sum of log(close_t / close_t-1) on the near contract over 60 sessions; every session must be present | 60 sessions, all required | Next session after source | 9.1% | 14.3% | 11.7% | 14.8% | 2011 | input |  |
| `rv_5` | std of daily log returns x sqrt(252) | 5 sessions, at least 4 present | Next session after source | 2.2% | 0.2% | 1.6% | 0.3% | 2011 | input |  |
| `rv_10` | std of daily log returns x sqrt(252) | 10 sessions, at least 8 present | Next session after source | 2.0% | 0.2% | 1.6% | 0.5% | 2011 | input |  |
| `rv_20` | std of daily log returns x sqrt(252) | 20 sessions, at least 16 present | Next session after source | 2.0% | 0.3% | 2.2% | 1.0% | 2011 | input |  |
| `rv_60` | std of daily log returns x sqrt(252) | 60 sessions, at least 48 present | Next session after source | 2.2% | 0.5% | 4.5% | 1.4% | 2011 | input |  |
| `rv_ratio_5_60` | rv_5 / rv_60 | 5 and 60 sessions | Next session after source | 2.5% | 0.5% | 4.7% | 1.5% | 2011 | input |  |
| `parkinson_20` | sqrt(mean(ln(high/low)^2) / (4 ln 2)) x sqrt(252) | 20 sessions, at least 16 present | Next session after source | 2.0% | 0.3% | 2.1% | 0.9% | 2011 | input | >0.95 |
| `garman_klass_20` | sqrt(mean(0.5 ln(high/low)^2 - (2 ln 2 - 1) ln(close/open)^2)) x sqrt(252) | 20 sessions, at least 16 present | Next session after source | 2.0% | 0.3% | 2.1% | 0.9% | 2011 | input | >0.95 |
| `garch_h1` | annualised GARCH(1,1) t forecast, horizon 1; refit every 63 sessions on returns through the source session only; needs more than 600 returns | expanding | Next session after source | 24.7% | 9.4% | 39.4% | 21.7% | 2013 | input | >0.95 |
| `garch_h5` | annualised GARCH(1,1) t forecast, horizon 5; refit every 63 sessions on returns through the source session only; needs more than 600 returns | expanding | Next session after source | 24.7% | 9.4% | 39.4% | 21.7% | 2013 | input | >0.95 |
| `garch_h10` | annualised GARCH(1,1) t forecast, horizon 10; refit every 63 sessions on returns through the source session only; needs more than 600 returns | expanding | Next session after source | 24.7% | 9.4% | 39.4% | 21.7% | 2013 | input | >0.95 |
| `gap_1` | log(open_t / close_t-1), same contract | 2 sessions | Next session after source | 1.9% | 0.4% | 1.2% | 0.4% | 2011 | input |  |
| `range_1` | (high - low) / close | 1 session | Next session after source | 1.8% | 0.2% | 1.0% | 0.1% | 2011 | input |  |
| `close_loc_1` | (close - low) / (high - low); missing if high = low | 1 session | Next session after source | 1.9% | 0.2% | 1.1% | 0.1% | 2011 | input |  |
| `turnover_ratio_20` | total futures turnover_t / mean of the previous 20 sessions | 21 sessions, at least 16 previous present | Next session after source | 2.0% | 0.3% | 2.2% | 1.0% | 2011 | input |  |
| `turnover_ratio_5_60` | mean turnover of 5 sessions / mean of 60 sessions | 5 and 60 sessions | Next session after source | 2.5% | 0.5% | 4.7% | 1.4% | 2011 | input |  |

## b. Futures and OI

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `oi_chg_1` | sum over contracts on both sessions of (OI_t - OI_t-1) / total OI_t-1. A listed or expired contract does not count, so a roll is not a change | 2 sessions | Next session after source | 1.4% | 0.1% | 0.9% | 0.1% | 2011 | input |  |
| `oi_chg_5` | sum of oi_chg_1 over 5 sessions, all required | 5 sessions | Next session after source | 2.0% | 0.3% | 1.7% | 0.5% | 2011 | input |  |
| `oi_z_60` | z-score of log(total OI) inside the current epoch | 60 sessions in the epoch, at least 40 | Next session after source | 3.8% | 1.5% | 5.5% | 2.2% | 2011 | input |  |
| `oi_rel_252` | percentile of total OI among the window inside the current epoch | 252 sessions in the epoch, at least 126 | Next session after source | 6.8% | 4.5% | 14.0% | 4.9% | 2011 | input |  |
| `oi_near_share` | near contract OI / total OI | 1 session | Next session after source | 1.3% | 0.1% | 0.7% | 0.0% | 2011 | input |  |
| `basis_term` | log(next close / near close) x 365 / calendar days between expiries; both contracts traded | 1 session | Next session after source | 3.1% | 0.3% | 6.1% | 0.6% | 2011 | input |  |
| `basis_spot_index` | log(near close / index close) x 365 / days to expiry; days to expiry at least 3; NIFTY and BANKNIFTY only. Stock spot is not in the base: missing | 1 session | Next session after source | 99.0% | 98.3% | 99.5% | 99.1% | 2015 | input |  |
| `oi_reset_flag` | 1 if a contract with OI > 0 on the previous session has oi_change = open_interest | 1 session | Next session after source | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | handling_flag |  |
| `disc_flag` | 1 if the source session is a discontinuity (see handling rules) | 1 session | Next session after source | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | handling_flag |  |
| `sessions_since_disc` | sessions since the last discontinuity of this symbol; missing if none | expanding | Next session after source | 53.4% | 33.7% | 62.7% | 41.7% | 2011 | handling_flag |  |

## c. Options

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `atm_iv_front` | mean of call and put Black-76 IV at the liquid pair nearest the forward, within 2.5%, front expiry | 1 session | Next session after source | 34.9% | 3.0% | 56.3% | 9.8% | 2011 | input |  |
| `atm_iv_next` | same, next expiry | 1 session | Next session after source | 95.0% | 76.8% | 97.2% | 85.7% | 2011 | input |  |
| `iv_term_slope` | atm_iv_next - atm_iv_front | 1 session | Next session after source | 95.1% | 76.8% | 97.2% | 85.7% | 2011 | input |  |
| `iv_term_ratio` | atm_iv_next / atm_iv_front | 1 session | Next session after source | 95.1% | 76.8% | 97.2% | 85.7% | 2011 | input |  |
| `atm_iv_chg_1` | ATM IV today - ATM IV on the previous session, same expiry only | 2 sessions | Next session after source | 42.7% | 5.2% | 62.9% | 14.5% | 2011 | input |  |
| `atm_iv_rel_252` | percentile of atm_iv_front in the window | 252 sessions, at least 126 | Next session after source | 43.8% | 4.1% | 66.6% | 14.1% | 2011 | input |  |
| `iv_minus_rv_20` | atm_iv_front - rv_20 | 20 sessions | Next session after source | 35.0% | 3.0% | 56.4% | 10.5% | 2011 | input |  |
| `skew_5` | put IV at the liquid strike nearest 0.95F, in [0.90, 0.98], minus call IV at the liquid strike nearest 1.05F, in [1.02, 1.10], front expiry | 1 session | Next session after source | 79.8% | 31.6% | 87.9% | 50.0% | 2011 | input |  |
| `skew_5_norm` | skew_5 / atm_iv_front | 1 session | Next session after source | 80.5% | 31.6% | 88.4% | 50.2% | 2011 | input |  |
| `pcr_volume_liquid` | put contracts / call contracts over liquid pairs of all stored expiries | 1 session | Next session after source | 22.2% | 1.0% | 45.9% | 4.2% | 2011 | input |  |
| `pcr_oi_liquid` | put OI / call OI over liquid pairs of all stored expiries | 1 session | Next session after source | 22.2% | 1.0% | 45.9% | 4.2% | 2011 | input |  |
| `max_pain_dist` | log(max-pain strike / forward), front expiry; OI of all stored european strikes (OI is not a price, so the liquidity filter does not apply); at least 5 strikes | 1 session | Next session after source | 31.1% | 2.4% | 53.1% | 8.3% | 2011 | input |  |
| `n_liquid_pairs` | log(1 + number of liquid pairs) | 1 session | Next session after source | 0.0% | 0.0% | 6.5% | 0.0% | 2011 | input |  |

## d. Participant

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `fii_fut_idx_net` | FII (long - short) / (long + short), index futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `fii_fut_idx_net_chg_5` | fii_fut_idx_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `fii_fut_stk_net` | FII (long - short) / (long + short), stock futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `fii_fut_stk_net_chg_5` | fii_fut_stk_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `fii_opt_idx_call_net` | FII (long - short) / (long + short), index calls | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `fii_opt_idx_put_net` | FII (long - short) / (long + short), index puts | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `dii_fut_idx_net` | DII (long - short) / (long + short), index futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `dii_fut_idx_net_chg_5` | dii_fut_idx_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `dii_fut_stk_net` | DII (long - short) / (long + short), stock futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `dii_fut_stk_net_chg_5` | dii_fut_stk_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `dii_opt_idx_call_net` | DII (long - short) / (long + short), index calls | 1 session | Next session after source | 54.0% | 43.7% | 57.6% | 43.7% | 2015 | input |  |
| `dii_opt_idx_put_net` | DII (long - short) / (long + short), index puts | 1 session | Next session after source | 54.2% | 0.0% | 57.8% | 0.0% | 2015 | input |  |
| `client_fut_idx_net` | Client (long - short) / (long + short), index futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `client_fut_idx_net_chg_5` | client_fut_idx_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `client_fut_stk_net` | Client (long - short) / (long + short), stock futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `client_fut_stk_net_chg_5` | client_fut_stk_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `client_opt_idx_call_net` | Client (long - short) / (long + short), index calls | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `client_opt_idx_put_net` | Client (long - short) / (long + short), index puts | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `pro_fut_idx_net` | Pro (long - short) / (long + short), index futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `pro_fut_idx_net_chg_5` | pro_fut_idx_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `pro_fut_stk_net` | Pro (long - short) / (long + short), stock futures | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `pro_fut_stk_net_chg_5` | pro_fut_stk_net today minus 5 sessions earlier, both present | 6 sessions | Next session after source | 54.4% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `pro_opt_idx_call_net` | Pro (long - short) / (long + short), index calls | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |
| `pro_opt_idx_put_net` | Pro (long - short) / (long + short), index puts | 1 session | Next session after source | 54.0% | 0.0% | 57.6% | 0.0% | 2015 | input |  |

## e. Delivery

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `deliv_pct` | deliverable / traded quantity, EQ series, as NSE reports it | 1 session | Next session after source | 54.1% | 0.0% | 57.8% | 0.0% | 2015 | input |  |
| `deliv_chg_1` | deliv_pct today - previous session | 2 sessions | Next session after source | 54.2% | 0.0% | 57.9% | 0.0% | 2015 | input |  |
| `deliv_rel_20` | deliv_pct - mean of the previous 20 sessions | 21 sessions, at least 16 previous | Next session after source | 55.2% | 0.0% | 58.8% | 0.1% | 2015 | input |  |

## f. Market state

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `vix` | India VIX close | 1 session | Next session after source | 33.7% | 0.0% | 38.8% | 0.0% | 2015 | input |  |
| `vix_chg_1` | log(vix today / previous session) | 2 sessions | Next session after source | 34.0% | 0.0% | 39.1% | 0.0% | 2015 | input |  |
| `vix_chg_5` | log(vix today / 5 sessions earlier) | 6 sessions | Next session after source | 34.2% | 0.0% | 39.2% | 0.0% | 2015 | input |  |
| `vix_z_60` | z-score of vix | 60 sessions, at least 40 | Next session after source | 35.0% | 0.0% | 40.0% | 0.0% | 2015 | input |  |
| `nifty_ret_5` | log(NIFTY close / 5 sessions earlier) | 6 sessions | Next session after source | 40.8% | 0.0% | 45.4% | 0.0% | 2015 | input |  |
| `nifty_ret_20` | log(NIFTY close / 20 sessions earlier) | 21 sessions | Next session after source | 41.3% | 0.0% | 45.8% | 0.0% | 2015 | input | >0.95 |
| `nifty_ret_60` | log(NIFTY close / 60 sessions earlier) | 61 sessions | Next session after source | 42.6% | 0.0% | 47.1% | 0.0% | 2016 | input |  |
| `nifty_above_ma_50` | 1 if NIFTY close > 50-session mean | 50 sessions, all required | Next session after source | 46.0% | 0.0% | 50.1% | 0.0% | 2016 | input |  |
| `nifty_above_ma_200` | 1 if NIFTY close > 200-session mean | 200 sessions, all required | Next session after source | 59.0% | 0.0% | 62.2% | 0.0% | 2017 | input |  |
| `nifty_fut_ret_20` | ret_20 of NIFTY near future; available before 2015, unlike the index file | 20 sessions | Next session after source | 1.3% | 4.1% | 1.9% | 4.1% | 2010 | input | >0.95 |
| `banknifty_fut_ret_20` | ret_20 of BANKNIFTY near future | 20 sessions | Next session after source | 1.3% | 8.1% | 1.9% | 8.1% | 2010 | input |  |
| `breadth_up_1_U1` | share of U1 stock members with ret_1 > 0, among those with a value; at least 20 | 1 session | Next session after source | 0.1% | 0.2% | 7.8% | 0.2% | 2011 | input | >0.95 |
| `breadth_up_20_U1` | share of U1 stock members with ret_20 > 0, among those with a value; at least 20 | 1 session | Next session after source | 1.3% | 4.1% | 8.9% | 4.1% | 2011 | input | >0.95 |
| `breadth_up_60_U1` | share of U1 stock members with ret_60 > 0, among those with a value; at least 20 | 1 session | Next session after source | 4.0% | 12.2% | 11.4% | 12.2% | 2011 | input | >0.95 |
| `breadth_up_1_U2` | share of U2 stock members with ret_1 > 0, among those with a value; at least 20 | 1 session | Next session after source | 0.1% | 0.2% | 0.1% | 0.2% | 2010 | input | >0.95 |
| `breadth_up_20_U2` | share of U2 stock members with ret_20 > 0, among those with a value; at least 20 | 1 session | Next session after source | 1.3% | 4.1% | 1.9% | 4.1% | 2010 | input | >0.95 |
| `breadth_up_60_U2` | share of U2 stock members with ret_60 > 0, among those with a value; at least 20 | 1 session | Next session after source | 4.0% | 12.2% | 5.6% | 12.2% | 2010 | input | >0.95 |

## g. Calendar

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `day_of_week` | signal date weekday, Monday = 0 | none | signal date itself; the calendar and the listed expiries are public before it | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | input |  |
| `days_to_expiry` | calendar days from signal date to the nearest expiry on or after it, from contracts listed on the source session | none | signal date itself; the calendar and the listed expiries are public before it | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | input |  |
| `expiry_week` | 1 if days_to_expiry <= 7 | none | signal date itself; the calendar and the listed expiries are public before it | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | input |  |
| `days_since_prev_session` | calendar days from the source session to the signal date | none | signal date itself; the calendar and the listed expiries are public before it | 0.0% | 0.0% | 0.0% | 0.0% | 2011 | input |  |
| `board_days_to_next` | calendar days to the next stored board meeting with a notice already public | none | the notice's own timestamp: only notices stamped before 15:30 IST on the signal date count | 97.9% | 94.6% | 98.8% | 97.0% | 2017 | input | >0.95 |
| `board_days_since_last` | calendar days since the last stored board meeting with a notice already public | none | the notice's own timestamp: only notices stamped before 15:30 IST on the signal date count | 89.1% | 72.8% | 94.0% | 85.0% | 2018 | input |  |
| `results_days_to_next` | same, meetings whose purpose names results | none | the notice's own timestamp: only notices stamped before 15:30 IST on the signal date count | 98.0% | 94.8% | 98.9% | 97.1% | 2017 | input | >0.95 |
| `results_days_since_last` | same, meetings whose purpose names results | none | the notice's own timestamp: only notices stamped before 15:30 IST on the signal date count | 89.1% | 72.8% | 94.0% | 85.0% | 2018 | input |  |

## h. Cross-sectional ranks

| Feature | Formula | Window | known_from | Dev U1 missing | Val U1 | Dev U2 | Val U2 | First year | Role | Flag |
|---|---|---|---|---|---|---|---|---|---|---|
| `rank_U1_ret_1` | percentile rank of ret_1 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.2% | 47.5% | 47.1% | 2011 | input | >0.95 |
| `rank_U1_ret_5` | percentile rank of ret_5 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.7% | 1.2% | 47.8% | 47.6% | 2011 | input | >0.95 |
| `rank_U1_ret_20` | percentile rank of ret_20 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 2.5% | 4.7% | 48.9% | 49.5% | 2011 | input | >0.95 |
| `rank_U1_rv_20` | percentile rank of rv_20 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 47.5% | 47.0% | 2011 | input | >0.95 |
| `rank_U1_turnover_ratio_20` | percentile rank of turnover_ratio_20 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 47.5% | 47.0% | 2011 | input | >0.95 |
| `rank_U1_oi_chg_1` | percentile rank of oi_chg_1 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 47.5% | 47.0% | 2011 | input | >0.95 |
| `rank_U1_oi_z_60` | percentile rank of oi_z_60 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 2.3% | 1.3% | 48.7% | 47.7% | 2011 | input | >0.95 |
| `rank_U1_atm_iv_front` | percentile rank of atm_iv_front among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 34.8% | 2.5% | 65.3% | 48.3% | 2011 | input | >0.95 |
| `rank_U1_iv_minus_rv_20` | percentile rank of iv_minus_rv_20 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 34.8% | 2.6% | 65.3% | 48.3% | 2011 | input | >0.95 |
| `rank_U1_skew_5` | percentile rank of skew_5 among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 87.1% | 30.9% | 93.1% | 63.4% | 2011 | input | >0.95 |
| `rank_U1_pcr_oi_liquid` | percentile rank of pcr_oi_liquid among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 20.5% | 0.7% | 57.8% | 47.4% | 2011 | input | >0.95 |
| `rank_U1_deliv_pct` | percentile rank of deliv_pct among U1 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 54.1% | 0.0% | 75.6% | 47.0% | 2015 | input | >0.95 |
| `rank_U2_ret_1` | percentile rank of ret_1 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.2% | 0.2% | 0.3% | 2011 | input | >0.95 |
| `rank_U2_ret_5` | percentile rank of ret_5 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.7% | 1.2% | 1.0% | 1.4% | 2011 | input | >0.95 |
| `rank_U2_ret_20` | percentile rank of ret_20 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 2.5% | 4.7% | 3.8% | 5.6% | 2011 | input | >0.95 |
| `rank_U2_rv_20` | percentile rank of rv_20 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 1.2% | 0.9% | 2011 | input | >0.95 |
| `rank_U2_turnover_ratio_20` | percentile rank of turnover_ratio_20 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 1.2% | 0.9% | 2011 | input | >0.95 |
| `rank_U2_oi_chg_1` | percentile rank of oi_chg_1 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 0.1% | 0.0% | 0.2% | 0.1% | 2011 | input | >0.95 |
| `rank_U2_oi_z_60` | percentile rank of oi_z_60 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 2.3% | 1.3% | 4.7% | 2.1% | 2011 | input | >0.95 |
| `rank_U2_atm_iv_front` | percentile rank of atm_iv_front among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 34.7% | 2.5% | 56.7% | 9.7% | 2011 | input | >0.95 |
| `rank_U2_iv_minus_rv_20` | percentile rank of iv_minus_rv_20 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 34.8% | 2.6% | 56.9% | 10.5% | 2011 | input | >0.95 |
| `rank_U2_skew_5` | percentile rank of skew_5 among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 86.6% | 30.9% | 91.9% | 50.1% | 2011 | input | >0.95 |
| `rank_U2_pcr_oi_liquid` | percentile rank of pcr_oi_liquid among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 20.5% | 0.7% | 45.6% | 4.2% | 2011 | input | >0.95 |
| `rank_U2_deliv_pct` | percentile rank of deliv_pct among U2 stock members on the signal date; ties averaged; at least 20 values | 1 date | Next session after source | 54.1% | 0.0% | 57.8% | 0.0% | 2015 | input | >0.95 |

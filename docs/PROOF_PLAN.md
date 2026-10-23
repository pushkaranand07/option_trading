# Proof Plan — from "looks good in a backtest" to "safe to trade on Dhan"

> Written 2026-10-23. Companion to [QUANT_SIGNAL_LAYER_PLAN.md](QUANT_SIGNAL_LAYER_PLAN.md) and
> [PROGRESS_TRACKER.md](PROGRESS_TRACKER.md). Research and decision support only — not investment advice.

---

## 1. What "100% success" can and cannot mean

No plan can make a trading strategy win 100% of the time, or guarantee it keeps working: markets change, and every
test of the past is evidence, not proof. Anyone promising otherwise is overfitting or selling something.

What this plan **does** make close to 100% certain:

| Guarantee | How |
|---|---|
| **No real money goes behind a strategy that has not proven itself on data it has never seen** | Every strategy must pass a forward (future) test after its rules are frozen — see Stage 3 |
| **Every loss is capped before the trade is placed** | Defined-risk structures only, fixed % of capital at risk, portfolio limit — section 6 |
| **A strategy that stops working is detected quickly and switched off** | Pre-set kill rules at every stage — section 5 |
| **Results cannot be "massaged" after the fact** | Rules frozen in git before each test; every attempt in the trial log — Stage 0 |

---

## 2. Where we are now (the starting line)

| Item | Status | Evidence so far |
|---|---|---|
| GARCH volatility forecasts | ✅ validated as a **risk tool** | beat historical vol on 31/31 symbols, out of sample |
| Regime model | ✅ validated as a **risk tool** | next-month vol 11.5% (calm) vs 15.1% (choppy), p = 0.026 |
| **Pooled VRP iron condor** (NIFTY + BANKNIFTY, 4 staggered books) | 🟡 **candidate #1** | 84 trades, 87% wins, +12.7% of risk/trade, beats random timing in 100% of runs, deflated Sharpe 0.934 (bar 0.95) |
| Quiet-stock iron condor (5 stocks GARCH predicts quietest) | ❌ rejected (2026-10-23) | GARCH's picks lose less than random (beats random 92%), but selling stock condors loses money: Sharpe −0.44 (random −0.84, all stocks −1.22) |
| MA trend, LightGBM ×3, relative strength ×2 | ❌ rejected | no predictive skill or no edge after costs |

**Trials so far:** 16 logged runs, 178 parameter combinations. This number matters: the more ideas tried on the same
2018–2026 history, the more likely one looks good by luck. That is why the decisive test (Stage 3) uses **future data**.

---

## 3. The evidence ladder

A strategy climbs one stage at a time. It cannot skip a stage, and it falls off the ladder the moment it fails one.

### Stage 0 — Freeze the rules (1 day)
Before any further testing of a candidate:
1. Write its **complete specification** in `docs/strategies/<name>.md`: instrument, entry signal, strike selection,
   exits, position size, costs, what data it uses and when that data is known.
2. Commit it to git. The commit hash is the strategy's identity; **any change = a new strategy that starts again at Stage 1**.
3. Record the spec in the trial log.

*Pass:* spec committed. *Why:* it makes it impossible to adjust rules after seeing results.

### Stage 1 — Backtest gates (already built)
Walk-forward, out of sample, after Dhan costs and slippage, against random and "always trade" baselines.

| Gate | Pass mark |
|---|---|
| Look-ahead check | 0 mismatches |
| Out-of-sample trades | ≥ 100 |
| Deflated Sharpe (counts every trial) | ≥ 0.95 |
| Out-of-sample / in-sample Sharpe | ≥ 0.5 |
| Profitable test windows | ≥ 70% |
| Max drawdown vs annual return | ≤ 2× |
| Regimes | profitable in ≥ 2 regimes, or switched off where it loses |
| Neighbouring settings | ≥ 50% of the chosen setting's Sharpe |

*A strategy that misses only on trade count* (like candidate #1) may go to Stage 3 as **paper only**: the future will
supply the missing trades. It may **not** go to Stage 4 until Stage 3 has supplied them.

### Stage 2 — Stress tests (new; 1–2 days per candidate)
Make the backtest try to break it:

| Test | Pass mark |
|---|---|
| **Costs ×2** (brokerage, STT, slippage doubled) | still profitable |
| **Slippage on wings ×3** (illiquid far strikes) | still profitable |
| **Worst periods**: Mar-2020 crash, Jun-2024 election day, Adani episodes | loss per event ≤ the defined max risk × open positions; no single event > 10% of capital at the planned size |
| **Block bootstrap** of the out-of-sample trades (10,000 resamples) | 95% confidence interval of mean return per trade excludes 0 |
| **Trade-order Monte Carlo** | 95th-percentile drawdown fits the kill rule in section 5 |
| **Start-date shift** (start 1, 2, 3 months later) | same sign and similar size of result |

### Stage 3 — Forward paper trading (the decisive test)
The rules are frozen (Stage 0). Every evening the scheduled refresh records the trades the strategy **would** open,
priced at the next session's real NSE closes, with full costs, and tracks them to exit. No money is involved.

This is the only test that cannot be overfit: the data did not exist when the rules were written.

**How long?** Until there are enough new trades to tell a real edge from luck:

    trades needed ≈ (2 × spread of trade results ÷ average trade result)²

| Candidate | Backtest: avg / spread per trade (of max risk) | Trades needed | Trades per year | **Time needed** |
|---|---|---|---|---|
| Pooled VRP condor | +11.1% / 20% (measured: frozen rules, 95 trades 2021–26) | 14 by the formula → **30** (the plan's floor) | ~17 | **~21 months** |

The index condor fires rarely, so its forward proof takes time. The faster candidate (the quiet-stock condor) was
rejected, so this is the realistic timeline unless a new candidate (e.g. your own idea) trades more often.

**Early stopping (sequential test):** checked monthly, so a clearly good or clearly bad strategy does not have to wait
the full time. Stop and **reject** if the running result is below the backtest's 5th-percentile path; **pass early** only if
the one-sided test of "mean trade result > 0" reaches p < 0.01 with at least 30 trades.

*Pass:* mean trade result > 0 with p < 0.05 on forward trades; hit rate inside the backtest's 95% band; no kill rule hit.

### Stage 4 — Small live trading on Dhan (you place every order)
- **Risk 0.5% of capital per trade** (half the plan's normal cap), **≤ 3% total open risk**.
- You place orders yourself from the system's daily list; record your actual fills.
- **Minimum 3 months and 30 live trades.**

*Pass:* live results inside the paper-trading band; **real slippage ≤ 1.5× the model**; no kill rule hit.

### Stage 5 — Scale up, slowly
Risk per trade 0.5% → 0.75% → 1% (the hard cap), one step per **100 live trades** that stay inside the band.
Monthly re-check of every gate on all data to date. **Never above 1% per trade or 4% total open risk.**

---

## 4. Schedule

| When | Step | Who |
|---|---|---|
| ✅ 2026-10-23 | Quiet-stock condor judged: **rejected** | me |
| ✅ 2026-10-23 | Stage 0 spec frozen: `docs/strategies/vrp_condor_pooled.md` | me |
| ✅ 2026-10-23 | **Paper-trading ledger built** and added to the daily refresh; VRP condor paper trades start **Mon 2026-10-26** | me |
| Next | Stage 2 stress tests for the VRP condor | me |
| Days 4–5 | Phase 9 replay check (agents never invent numbers) — only if you approve the LLM cost | me |
| Weeks 1–… | Stage 3 paper trading runs automatically every weekday at 19:30 | automatic |
| Monthly | Review: forward results vs backtest band; sequential test; kill rules | me + you |
| After Stage 3 pass | Stage 4 on Dhan at 0.5% risk | **you** place orders |
| Throughout | Your own idea (Phase 5) can enter the ladder at Stage 0 at any time | you + me |

---

## 5. Kill rules (decided now, applied automatically)

| Stage | Switch the strategy **off** if any of these happen |
|---|---|
| 3 (paper) | running result below the backtest's 5th-percentile path · 8 losing trades in a row · a single trade loses more than its defined max risk (means a pricing or rule bug) |
| 4 (live) | drawdown > 2× the backtest's worst monthly drawdown · 8 losses in a row · real slippage > 2× model for a month · any order placed outside the rules |
| Any | data feed stale or missing for 2 sessions · daily refresh fails 2 days running · NSE changes lot sizes / expiry rules (re-validate first) |

A strategy switched off goes back to Stage 0. Restarting it unchanged requires a written reason.

---

## 6. Risk limits (non-negotiable at every live stage)

1. **Defined risk only:** iron condors / spreads with long wings. No naked short options, ever.
2. **Per trade:** max loss (wing width − credit) × lot ≤ the stage's % of capital (0.5% → max 1%).
3. **Total open risk** ≤ 3% of capital (Stage 4), ≤ 4% (Stage 5).
4. **Event filter:** no new stock condor within 5 sessions before that company's results; no new index condor in
   the week of the Union Budget or general-election results.
5. **Exit before expiry day** for stock options (they are physically settled — avoid delivery obligations).
6. **Margin:** keep ≥ 2× the broker's margin requirement free.
7. **Sizing:** `tradingagents/analytics/sizing.py` (¼-Kelly, capped) — the lower of Kelly and the stage cap.

---

## 7. What is needed from you

| Item | Why | When |
|---|---|---|
| Approve this plan (or change it) | it sets the rules everything is judged by | now |
| Your capital figure (private; stays on your machine as a config value) | to turn % risk into rupees and lots | before Stage 4 |
| One Dhan contract note | confirm the cost model within ₹1 | before Stage 4 |
| Phase 9 replay: 50 / 10 / skip | LLM cost | any time |
| Your own trading idea | the best chance of an edge the generic tests missed | any time |

---

## 8. Honest odds

Most strategies that reach Stage 3 fail there — that is normal and is the plan working. Of what we have today:
- the **risk tools** (GARCH, regime, expected move) are already proven and in use;
- **candidate #1** (pooled VRP condor) has the right shape of evidence but will take years of forward data to prove;
- the **quiet-stock condor** is the best hope for a faster answer, *if* its backtest holds up tonight.

If nothing survives Stage 3, the result is still valuable: you will not have lost money on a strategy that only
worked in a backtest — which is how most retail options traders lose it.

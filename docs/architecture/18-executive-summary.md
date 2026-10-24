# Executive summary

> **Status:** Current.
> **Scope:** the whole project in five minutes. Research and decision support only — not investment advice.
> **Last verified against the code:** 2026-10-24

---

## 1. What this is

A research system for trading Indian markets, used by one person who places every trade manually on Dhan. It has three
layers:

| Layer | What it does | Details |
|---|---|---|
| **Agents** | A team of LLM agents (analysts, bull and bear researchers, trader, risk team, portfolio manager) studies one stock or index on one date and gives a 5-tier rating with reasons | [02](02-agent-pipeline.md), [03](03-agents-and-tools.md) |
| **India data** | NSE files and APIs (F&O bhavcopy, participant open interest, delivery, index closes, option quotes, board meetings), a trading calendar with special sessions, India-specific agent tools | [06](06-data-vendors.md), [07](07-india-market-layer.md), [11](11-nse-data-store.md) |
| **Quant layer** | Tests trading ideas the hard way — walk-forward, real Dhan costs, random baselines, deflated Sharpe, rules frozen before testing — and feeds only validated numbers to the agents | [10](10-quant-layer-overview.md), [12](12-evaluation-and-validation.md) |

Around them: an options backtester ([08](08-option-backtester.md)), a CLI and a web app ([09](09-cli-webapp-and-reports.md)),
the Market Map ([17](17-market-map.md)), the trade journal, and a job that refreshes everything every weekday at
19:30 ([15](15-daily-refresh-and-paper-trading.md)).

## 2. What works (in use)

| Tool | Evidence |
|---|---|
| **GARCH volatility forecasts** → expected move | beat historical volatility out of sample on 31/31 symbols; a pretrained model (Chronos) did not beat it |
| **Market regime** (calm / choppy / stress, HMM) | next-month NIFTY volatility 11.5% calm vs 15.1% choppy (p = 0.026); **not** a direction signal |
| **Measured option costs** | real closing bid/ask spreads ≈ 0.85× the cost model on the strikes that matter |
| **Market Map** | how each law change and event moved NIFTY, VIX and options activity, 2021 → today |

## 3. What did not work

No trading signal has passed its tests (as of 2026-10-24):

- **Direction from public data** — moving-average trend, three LightGBM models with price and NSE derivatives / flow
  features, relative strength: no skill (same-day AUC 0.50–0.51) or no edge after costs.
- **Selling options** — the VRP iron condor looked strong on 2021–26 but lost on 2015–21, years its settings never saw;
  condors on the quietest stocks lost money; the results-day iron butterfly captured a real IV crush but lost it to
  trading costs (−6.5% of risk per trade; break-even needs half the measured spread).

That is the system working: each idea looked good somewhere and was caught before real money was at risk.

## 4. Where it stands

- Progress: see the [tracker](../PROGRESS_TRACKER.md) (bars count only live work).
- Running: the Phase 9 replay — do the agents quote the quant numbers faithfully? ([PA-25](../PA_25-phase9-replay-and-report-wording.md))
- The VRP condor is paper-traded as **observation only** from 2026-10-26.
- **Most promising next step: the user's own trading** — the trade journal measures what works in real trades; a setup
  from it can be written as exact rules and tested like everything else.

## 5. How decisions are made here

Every idea climbs the [proof plan](../plans/PROOF_PLAN.md): frozen spec → backtest gates → stress tests → forward paper
trading → small live size. Rules are pushed to GitHub before testing; every attempt is logged so the bar rises with the
number of tries; nothing is re-tuned on the result. Every change has a PA record ([index](../README.md#3-change-records-pa)).

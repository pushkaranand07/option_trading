# AI forward test: options

> **Status:** Computed 2026-11-01 from the frozen spec. **No trade has counted yet. Your decision; nothing has been changed.**
> **Scope:** dates and power only. Arithmetic, with no LLM call and no market data.

**Asking a NIFTY question on the Plan tab between 09:30 and 15:00 now counts as the first trade**, under the current spec, and the choice below would then no longer be free. Dates are lower bounds: weekdays count as sessions, 2027 and later holidays are not stored, and settling adds up to one expiry. Start assumed 2026-11-02.

## How long 500 trades takes

The spec allows at most 5 questions a week. Your real rate and the share of answers that become trades are **UNVERIFIED**: only 2 AI trades exist, from one date.

| Questions a week | Trades per answer | Trades a week | Weeks to 500 | Earliest date |
|---|---|---|---|---|
| 5 | 100% | 5.0 | 100 | 2028-10-02 |
| 5 | 70% | 3.5 | 143 | 2029-07-30 |
| 5 | 50% | 2.5 | 200 | 2030-09-02 |
| 4 | 100% | 4.0 | 125 | 2029-03-26 |
| 4 | 70% | 2.8 | 179 | 2030-04-08 |
| 4 | 50% | 2.0 | 250 | 2031-08-18 |
| 3 | 100% | 3.0 | 167 | 2030-01-14 |
| 3 | 70% | 2.1 | 239 | 2031-06-02 |
| 3 | 50% | 1.5 | 334 | 2033-03-28 |
| 2 | 100% | 2.0 | 250 | 2031-08-18 |
| 2 | 70% | 1.4 | 358 | 2033-09-12 |
| 2 | 50% | 1.0 | 500 | 2036-06-02 |

## Power at each trade count

Share of simulated runs passing, from the spec. Edge is the extra net return per trade as a share of max risk.

| Trades | 10% edge | 15% edge | 20% edge | 30% edge |
|---|---|---|---|---|
| 50 | 0.04 | 0.06 | 0.13 | 0.32 |
| 100 | 0.05 | 0.12 | 0.22 | 0.59 |
| 200 | 0.09 | 0.20 | 0.48 | 0.92 |
| 300 | 0.12 | 0.35 | 0.66 | 0.97 |
| 500 | 0.19 | 0.55 | 0.85 | 1.00 |
| 1000 | 0.32 | 0.84 | 0.99 | 1.00 |

## What a stop date would allow

Trades reached by each stop date, and the power at that count. Power uses the largest listed count at or below it.

| Stop date | Questions a week | Trades per answer | Trades by then | Power at 20% edge | Power at 30% edge |
|---|---|---|---|---|---|
| 2027-11-01 | 5 | 100% | 260 | 0.48 | 0.92 |
| 2027-11-01 | 5 | 70% | 182 | 0.33 | 0.78 |
| 2027-11-01 | 3 | 70% | 109 | 0.22 | 0.59 |
| 2027-11-01 | 2 | 50% | 52 | 0.13 | 0.32 |
| 2028-11-01 | 5 | 100% | 521 | 0.85 | 1.00 |
| 2028-11-01 | 5 | 70% | 365 | 0.66 | 0.97 |
| 2028-11-01 | 3 | 70% | 218 | 0.48 | 0.92 |
| 2028-11-01 | 2 | 50% | 104 | 0.22 | 0.59 |

## Risks behind the options

- **Provider change:** the spec pins the model's name, API settings and prompt, not the served version. The app does not record the version in each response, so a change behind the same name goes undetected. Whether Azure changes this deployment by itself is UNVERIFIED.
- **Prompt inputs:** the system prompt names: trend, OI walls, FII, implied vol. The word PCR is not in the system prompt, though the option-chain data the model receives includes it. The score was removed because similar inputs showed no edge under the tested conditions. Whether an LLM adds anything on top is what this test would measure.

## Options

| Option | What changes | Verdict date | Power | Main cost |
|---|---|---|---|---|
| **(a) Keep as is** | Nothing | Earliest 2028-10-02; 2031-06-02 at 3 questions a week and 70% | 85% at a 20% edge, if it finishes | Needs about 2 to 5 years of daily questions and the same model throughout |
| **(b) Change the prompt or model, restart the hash** | New prompt, for example without the inputs already found wanting. Free before the first trade | Same as (a) | Same as (a) | Does not shorten anything; the prompt becomes another untested design choice |
| **(c) Stop date and interim look rules** | A fixed end date. Verdict on the trades reached by then | The stop date, for example 2027-11-01 | At 2027-11-01, about 182 trades at 5 and 70%: 0.33 at 20%, 0.78 at 30% | Detects only very large edges. Any interim pass-or-fail look needs its own simulation first: not simulated here |
| **(d) Retire the test** | Remove the hook; AI suggestions stay UNTESTED permanently | None | None | No evidence on the AI, ever. Saves the daily effort and LLM cost |

I have not picked one. **Whichever you choose, the stop date and the action at that date must go in the spec before the first counted trade.** The action needs your words: for example, "retire the test and keep the UNTESTED label" or "report what was reached, with no pass".

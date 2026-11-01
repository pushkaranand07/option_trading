# Root causes of the review's weaknesses

> **Status:** Written 2026-11-01, before any change for these items. Numbers and tables are in the files each item names.
> **Scope:** the eight items of the user's root-cause request. Where evidence does not support the review's claim, this says so.

## Item 1: Cost model unverified

1. **Symptom:** every result carries "cost model unverified".
2. **Root cause:** the rates were copied from web sources on 2026-10-23 and never checked against a broker statement. Statutory rates cite NSE circulars or broker pages (`analytics/costs.py`); slippage (2 and 5 bps) and the Rs 10 lakh order size are written assumptions (`research/gate.py:30-31`). No document from the user's account exists. **The review's "partly assumed" holds; the charges are sourced but unreconciled, and slippage is pure assumption.**
3. **Fix and check:** [cost_parameters_v1.md](cost_parameters_v1.md) tables each parameter with source and date; `scripts/research_cost_sensitivity.py` shows results at 1x to 3x slippage. Reconciling needs the Dhan schedule you paste by hand. Check: read the per-component table; the label stays until then.

## Item 2: "No edge" stated more broadly than proven

1. **Symptom:** the catalog and reports say "no edge found", with the conditions further down or absent.
2. **Root cause:** the headline was written as a verdict string, and its conditions (D-1 timing, futures only, 1.5x costs, h = 1 to 10, public end-of-day features, these 6 specs) sit only in PA-47 and PA-48. **Supported.** `app.js` also says inputs "showed no edge" with no conditions.
3. **Fix and check:** every headline becomes "no edge found under these conditions, 1,532 trials", with the conditions listed. Evening-timing protocol: [nse_publication_protocol_v1.md](nse_publication_protocol_v1.md). Check: a test fails on an unconditioned verdict in those files. Nothing is re-run.

## Item 3: AI forward test likely never finishes

1. **Symptom:** the verdict needs 500 settled trades, from one manual question a session.
2. **Root cause:** the count came from power alone; question rate, no-trade rate and calendar were not part of the design. At most 5 questions a week is 100 weeks, assuming every answer is a trade. The real no-trade rate and question rate are UNVERIFIED: only 2 AI trades exist, from one date. The prompt names trend, OI walls and FII positioning; `build_context` also passes PCR. The spec pins the model name, not its version: `model_settings` reads config, and the served version is not recorded.
3. **Fix and check:** options with dates and power in [ai_test_options_v1.md](ai_test_options_v1.md), from `scripts/ai_test_options.py`. **Your decision.** Check: the stop date and action are in the spec before the first counted trade.

## Item 4: UI behaves like a trading desk

1. **Symptom:** UNTESTED labels sit beside exact tickets, targets and a Take button.
2. **Root cause:** the Plan tab was built to make trades easy to act on, before any test existed. **The review overstated one part: no code here can place an order.** `Dhan.post` is called only for charts and option chains. The Take button is "dummy" and writes a local record. The path to a real order is the user reading a ticket and typing it into Dhan.
3. **Fix and check:** controls and options are listed below. **Your decision;** bug fixes only until then. Check: none yet.

| Control | Where (`webapp/static/app.js`) | What it does | Labelled UNTESTED |
|---|---|---|---|
| "Take this trade (dummy, 1 lot)" button | `stratHtml` | Local record only | Yes |
| Ticket: side, lot, order type, limit price | `.ticket-slot` | Text to type into Dhan | Yes (on the card) |
| Target and stop loss, Super-order instructions | `.ticket-slot`, legs | Text to type into Dhan | Yes (on the card) |
| Ranked table rows, orders, entry, target, stop | Ranked trades | Open a ticket | Yes |
| **Intraday card "Take this trade"** with stop, target, loss a lot, money needed, and past win rate | Rule card | Text to type into Dhan | **No: a gap, not covered by #77's wording** |
| Sizing | Ticket and intraday card | "You choose how many lots"; "pick the quantity" | Partly |

Options, for you to choose:

- **Disable Take for untested tickets.** The button is greyed out with "Untested: not recordable". Tickets stay readable, and the 2-AI-trade track record stops growing through this button. It stops no real order, because the button never placed one.
- **Typed acknowledgement.** Opening a ticket or pressing Take first asks you to type a phrase such as "untested". Target, stop and order text stay hidden until then. This is the only option that adds friction on the real path.
- **Leave.** Labels only. Nothing changes.

Whichever you choose, you also need to decide whether the intraday card gets the same treatment.

## Item 5: Governance overhead

1. **Symptom:** rules are spread across many files.
2. **Root cause:** each decision was frozen as a new file so that no earlier one was edited, which is correct, but nothing states the current result. 12 frozen files were written in 2 days (2026-10-30 to 10-31). **Timing: the review was right on count but all gate changes came before any model fit, except addendum 7, which fixed a bug and changed no rule.**
3. **Fix and check:** [gate_current.md](gate_current.md), read-only, with source hashes. A catalog rule requires a written reason and results seen for any new addendum. Check: a test recomputes each hash.

## Item 6: Whole-pipeline audit

1. **Symptom:** defects were found late (GARCH units, ADANIENT, holiday bars, lot loop, rule-table units).
2. **Root cause:** tests checked timing and logic on synthetic data; nothing checked that real values were physically plausible, or that the harness could catch a planted bug. The review's "nobody audited the whole thing" holds: one read-only review traced the model code only.
3. **Fix and check:** `tradingagents/research/sanity.py` and `tests/test_pipeline_sanity.py`: ranges, planted bugs, and 5 headline numbers recomputed by a second path. Defect table in [pipeline_audit_v1.md](pipeline_audit_v1.md). Check: PASS or FAIL per check.

## Item 7: Volatility finding untested for use

1. **Symptom:** corrected GARCH beat HAR on QLIKE, but no one has measured whether either helps sizing.
2. **Root cause:** spec c was report-only and measured forecasts, not positions. **Supported.**
3. **Fix and check:** [vol_sizing_test_v1.json](vol_sizing_test_v1.json), frozen before it runs, development only, no edge claim. Check: the hash, and its report.

## Item 8: External risks

1. **Symptom:** the review named NSE terms, the Azure endpoint and forward-test dependencies.
2. **Root cause:** these depend on people and contracts outside the code. The NSE question was opened on 2026-10-30, and no answer is recorded. The Azure endpoint is set in `.env`, gitignored; its ownership is UNVERIFIED.
3. **Fix and check:** [external_risks_v1.md](external_risks_v1.md): query drafts and a dependency table. Nothing is sent. The host name goes in the chat report only, not this public repo. Check: your confirmation.

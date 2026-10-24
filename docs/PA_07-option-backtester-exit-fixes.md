# PA-07 — Fix three option_backtester / NSE adapter bugs (early exits, commission, expiry value)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `option_backtester/exits.py`, `option_backtester/simulator.py`, `tradingagents/integrations/optopsy/adapter.py`, `tests/test_option_backtester_fixes.py` |
| **Related** | [PA-01](PA_01-india-market-intelligence-baseline.md) · [PA-06](PA_06-windows-test-portability.md) · [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [architecture/08-option-backtester.md](architecture/08-option-backtester.md) |
| **Pull request** | #6 (branch `fix/option-backtester-exits`); commit `5dbb797` |
| **Date** | 2026-10-23 |

---

## 1. Problem

The options engine moved in from optopsy ([PA-01](PA_01-india-market-intelligence-baseline.md)) could report trades
that a trader would never have had, and overstate profit. Part of the bug-fix list requested on 2026-10-23 (tracker).

## 2. Root cause / findings

1. **Early exits ignored the planned exit.** With `exit_dte > 0` (exit a set number of days before expiry), the
   take-profit / stop-loss scan ran to the contract's last quote, so a threshold crossed *after* the planned exit
   could replace it.
2. **Commission never reached realized P&L.** The simulator's trade log used premiums only.
3. **Expiry-day value used the option's last close, and untraded expiry-day contracts were dropped** — so trades
   with an untraded wing vanished from results.

## 3. Decisions

- Value every expiry-day contract at intrinsic against the underlying close, as NSE settles it, whether it traded or not.
- When commission is set, restate `pct_change` on the currency basis.

## 4. What was built / changed

| File | Change |
|---|---|
| `option_backtester/exits.py` | The scan stops at quotes with more than `exit_dte` days left |
| `option_backtester/simulator.py` | Deducts each trade's commission × quantity from realized P&L |
| `tradingagents/integrations/optopsy/adapter.py` | Expiry-day contracts settle at intrinsic against the underlying close |

4 files, 139 lines added, 9 removed.

## 5. Tests

`tests/test_option_backtester_fixes.py`: a take-profit after the planned exit does not count; one before it still
counts; commission is deducted from realized P&L; expiry-day contracts settle at intrinsic even when untraded.
Each regression test fails without its fix and passes with it (PR body).

## 6. Results

Not recorded beyond the tests.

## 7. Verification

Regression tests only. The quant layer's own condor simulator (`condor.py`, [PA-05](PA_05-garch-volatility-and-vrp-condor.md))
settles expiry at intrinsic in the same way.

## 8. Risks and open items

- `option_backtester/exits.py` still used pandas `drop(inplace=True)`, which pandas is removing; fixed in `8df7ad0`
  ([PA-10](PA_10-relative-strength-model.md)).
- End-of-day close used as both bid and ask remains optimistic (see [PA-23](PA_23-option-quotes-measured-spreads.md)).

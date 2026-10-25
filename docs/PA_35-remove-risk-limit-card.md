# PA-35 — Plan tab: risk-limit card removed, per-lot figures instead

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/static/*` (Plan tab), `webapp/strategist.py`, `webapp/server.py` (`POST /api/strategy` body), `tests/test_strategist.py` |
| **Related** | [PA-33](PA_33-morning-plan.md) (live call sizing), [PA-34](PA_34-ai-strategist-and-nse-option-chain.md) (AI strategist), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/remove-risk-card` |
| **Date** | 2026-10-25 |

## 1. Problem

The user asked for the "Your risk limit" card (capital, max loss %, money for this trade) to be removed from the Plan
tab. Asked what to remove, they chose the whole card.

## 2. Change

- The card and its inputs are gone, along with the browser-stored values they used.
- **Today's call** now shows per-lot figures:
  - options: the lot size, the loss at the stop for one lot, and the premium for one lot;
  - stocks: the loss per share at the stop.

  You choose how many lots or shares to trade.
- **AI strategist:**
  - `POST /api/strategy` takes only `symbol` and `expiry`.
  - The LLM gets no risk input.
  - The result gives per-lot figures (pay or receive, worst case, best case, break-even) and `charges_per_lot`
    (every leg opened and closed).
  - The defined-risk check, bid / ask pricing and warnings are unchanged.
- `strategist.size` is removed. `charges(priced, lots)` stays.

## 3. Tests

`tests/test_strategist.py`:

- The sizing test is replaced by a charges test: four orders for a two-leg trade, and the flat brokerage does not
  double with two lots.
- `recommend` is checked for per-lot pricing, the poor-reward warning and refusal of a naked sell.

Ruff is clean, and `node --check` passes.

## 4. Risks

Without a limit on the page, nothing stops a trade larger than intended. The per-lot worst case is shown so the user
can size by hand.

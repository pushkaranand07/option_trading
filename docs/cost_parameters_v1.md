# Cost parameters: sourced or assumed

> **Status:** Written 2026-11-01 from `tradingagents/analytics/costs.py` and `tradingagents/research/gate.py`. **Cost model unverified: no broker document has been checked.**
> **Scope:** every parameter behind the gate's futures costs and the app's option charges.

The "fetched" date is the one stated in `costs.py`. Nothing was fetched for this file, and the sources were not re-opened.

| Parameter | Value | Source | Date | Status |
|---|---|---|---|---|
| STT, futures | 0.05% sell side | NSE circular NSE/FATAX/73524, Finance Act 2026 | Effective 2026-04-01; fetched 2026-10-23 | Sourced, primary |
| STT, options | 0.15% of premium, sell side | Same | Same | Sourced, primary |
| STT, option exercise | 0.15% of intrinsic | `costs.py` lists no separate citation | Fetched 2026-10-23 | UNVERIFIED source |
| Exchange, futures | Rs 183 per crore, each side | NSE circular NSE/FA/73061, including IPFT | Effective 2026-03-01; fetched 2026-10-23 | Sourced, primary |
| Exchange, options | Rs 3,553 per crore of premium, each side | Same | Same | Sourced, primary |
| SEBI fee | Rs 10 per crore, each side | Zerodha, Upstox, Angel One, Groww and Dhan charge pages | Fetched 2026-10-23 | Sourced, secondary |
| Stamp, futures | 0.002%, buy side | Same broker pages | Fetched 2026-10-23 | Sourced, secondary |
| Stamp, options | 0.003%, buy side | Same broker pages | Fetched 2026-10-23 | Sourced, secondary |
| GST | 18% on brokerage, exchange and SEBI | Same broker pages | Fetched 2026-10-23 | Sourced, secondary |
| Brokerage, F&O | Rs 20 per order | https://dhan.co/pricing/ | Fetched 2026-10-23 | Sourced, not reconciled to your account |
| Order size for brokerage | Rs 10 lakh | `gate.py`: REFERENCE_NOTIONAL | 2026-10-30 | **ASSUMPTION** |
| Slippage, index futures | 2 bps per fill | `gate.py`: SLIPPAGE_BPS | 2026-10-30 | **ASSUMPTION**: no measured historical spread |
| Slippage, stock futures | 5 bps per fill | `gate.py`: SLIPPAGE_BPS | 2026-10-30 | **ASSUMPTION** |
| Slippage, options, app | 1 tick plus 1% of premium | `costs.py`: Slippage | 2026-10-23 | **ASSUMPTION**; a first snapshot of NSE bid and ask is in the tracker. The forward test instead uses quoted bid and ask |

## Limits

- **Today's rates are applied to all history on purpose,** so older trades are charged more than they actually paid. This makes old results harder to pass; it does not show what was really paid.
- **The gate's 1.5x multiplies everything,** statutory rates too. Those don't really vary by 50%; the multiple is a safety margin.

## Reconciliation: blocked on you

Nothing to reconcile yet. Paste Dhan's published charge schedule by hand, and I'll report each component as match or mismatch against this table. A contract note, if you provide one, would check the arithmetic too.

**With neither, still unverified:** every row above against your account, and all slippage. The label stays.

Sensitivity to slippage: [cost_sensitivity_v1.md](cost_sensitivity_v1.md).

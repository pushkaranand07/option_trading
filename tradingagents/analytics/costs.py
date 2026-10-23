"""What a round trip on NSE really costs a retail trader (plan, Phase 1).

Rates as of 2026-10-23, applied to all history on purpose: older trades were
cheaper (F&O STT was raised on 1-Apr-2026), so a strategy that only pays at old
rates is rejected rather than flattered. Every rate lives in :class:`ChargeRates`;
budgets change them, so re-check before relying on the numbers.

Sources (fetched 2026-10-23):
- STT: NSE circular NSE/FATAX/73524 (31-Mar-2026), Finance Act 2026, effective 1-Apr-2026
  https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf
- NSE transaction charges incl. IPFT: NSE circular NSE/FA/73061 (27-Feb-2026), effective 1-Mar-2026
  https://nsearchives.nseindia.com/content/circulars/FA73061.pdf
- SEBI fee Rs 10/crore, stamp duty, GST 18%: Zerodha / Upstox / Angel One / Groww / Dhan charge pages
- Brokerage and DP charge: Dhan (the user's broker), https://dhan.co/pricing/ —
  Rs 0 delivery, lower of Rs 20 or 0.03% intraday, Rs 20 per F&O order,
  DP Rs 12.50 per scrip on a delivery sell (+ GST).

Slippage is not a charge but is modelled here too, since it is paid on every fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DELIVERY, INTRADAY, FUTURES, OPTIONS = "delivery", "intraday", "futures", "options"
SEGMENTS = (DELIVERY, INTRADAY, FUTURES, OPTIONS)
CRORE = 1e7


@dataclass(frozen=True)
class ChargeRates:
    # STT: (buy-side rate, sell-side rate) on turnover; options on premium.
    stt: dict = field(default_factory=lambda: {
        DELIVERY: (0.001, 0.001), INTRADAY: (0.0, 0.00025), FUTURES: (0.0, 0.0005), OPTIONS: (0.0, 0.0015)})
    stt_options_exercise: float = 0.0015        # on intrinsic value, paid by the buyer at ITM expiry
    # NSE transaction charge incl. IPFT, each side, on turnover (options: premium).
    exchange: dict = field(default_factory=lambda: {
        DELIVERY: 307 / CRORE, INTRADAY: 307 / CRORE, FUTURES: 183 / CRORE, OPTIONS: 3553 / CRORE})
    sebi_fee: float = 10 / CRORE                # each side
    # Stamp duty, buy side only.
    stamp: dict = field(default_factory=lambda: {
        DELIVERY: 0.00015, INTRADAY: 0.00003, FUTURES: 0.00002, OPTIONS: 0.00003})
    gst: float = 0.18                           # on brokerage + exchange + SEBI fee + DP charge
    # Brokerage per executed order: flat Rs, capped at a % of the order's value where the broker does.
    brokerage_flat: dict = field(default_factory=lambda: {
        DELIVERY: 0.0, INTRADAY: 20.0, FUTURES: 20.0, OPTIONS: 20.0})
    brokerage_pct_cap: dict = field(default_factory=lambda: {
        DELIVERY: None, INTRADAY: 0.0003, FUTURES: None, OPTIONS: None})
    dp_charge: float = 12.5                     # per scrip on a delivery sell, before GST


@dataclass(frozen=True)
class Slippage:
    equity_bps: float = 5.0                     # 0.05% of price per fill (liquid stocks / futures)
    option_ticks: int = 1                       # plus a share of premium, per fill
    option_tick_size: float = 0.05
    option_premium_pct: float = 0.01


@dataclass
class Breakdown:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi_fee: float = 0.0
    stamp: float = 0.0
    dp_charge: float = 0.0
    gst: float = 0.0
    slippage: float = 0.0

    @property
    def charges(self) -> float:
        """Everything a contract note shows (excludes slippage)."""
        return self.brokerage + self.stt + self.exchange + self.sebi_fee + self.stamp + self.dp_charge + self.gst

    @property
    def total(self) -> float:
        return self.charges + self.slippage


def _brokerage(rates: ChargeRates, segment: str, value: float) -> float:
    flat = rates.brokerage_flat[segment]
    cap = rates.brokerage_pct_cap[segment]
    return min(flat, cap * value) if cap is not None else flat


def round_trip(
    segment: str,
    quantity: float,
    buy_price: float,
    sell_price: float,
    rates: ChargeRates = ChargeRates(),
    slippage: Slippage | None = Slippage(),
    exercised_intrinsic: float = 0.0,
) -> Breakdown:
    """Costs of buying ``quantity`` at ``buy_price`` and selling at ``sell_price``.

    Direction does not matter (a short sale is the same two fills). For options,
    prices are premiums. ``exercised_intrinsic`` is the per-unit intrinsic value
    when a long option is held to ITM expiry instead of sold (``sell_price`` is
    then ignored for STT and brokerage: there is no sell order).
    """
    if segment not in SEGMENTS:
        raise ValueError(f"segment must be one of {SEGMENTS}")
    buy_value, sell_value = quantity * buy_price, quantity * sell_price
    b = Breakdown()
    exercised = segment == OPTIONS and exercised_intrinsic > 0
    orders = [(buy_value, "buy")] + ([] if exercised else [(sell_value, "sell")])
    for value, _side in orders:
        b.brokerage += _brokerage(rates, segment, value)
    stt_buy, stt_sell = rates.stt[segment]
    b.stt = stt_buy * buy_value + (0.0 if exercised else stt_sell * sell_value)
    if exercised:
        b.stt += rates.stt_options_exercise * quantity * exercised_intrinsic
    traded = buy_value + (0.0 if exercised else sell_value)
    b.exchange = rates.exchange[segment] * traded
    b.sebi_fee = rates.sebi_fee * traded
    b.stamp = rates.stamp[segment] * buy_value
    b.dp_charge = rates.dp_charge if segment == DELIVERY else 0.0
    b.gst = rates.gst * (b.brokerage + b.exchange + b.sebi_fee + b.dp_charge)
    if slippage is not None:
        fills = 1 if exercised else 2
        if segment == OPTIONS:
            per_unit = [slippage.option_ticks * slippage.option_tick_size + slippage.option_premium_pct * p
                        for p in (buy_price, sell_price)[:fills]]
            b.slippage = quantity * sum(per_unit)
        else:
            b.slippage = slippage.equity_bps / 1e4 * (buy_value + sell_value)
    return b


def fill_charges(segment: str, quantity: float, price: float, side: str, rates: ChargeRates = ChargeRates()) -> float:
    """Contract-note charges for one executed order (``side`` "buy" or "sell"), slippage excluded.

    For multi-leg option trades, where each leg is its own order on entry and exit.
    """
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    value = quantity * price
    brokerage = _brokerage(rates, segment, value)
    stt_buy, stt_sell = rates.stt[segment]
    stt = (stt_buy if side == "buy" else stt_sell) * value
    exchange = rates.exchange[segment] * value
    sebi = rates.sebi_fee * value
    stamp = rates.stamp[segment] * value if side == "buy" else 0.0
    return brokerage + stt + exchange + sebi + stamp + rates.gst * (brokerage + exchange + sebi)


def cost_fraction(segment: str, price: float, quantity: float = 1.0, rates: ChargeRates = ChargeRates(),
                  slippage: Slippage | None = Slippage()) -> float:
    """Round-trip cost as a fraction of position value, for return-based backtests."""
    value = quantity * price
    return round_trip(segment, quantity, price, price, rates, slippage).total / value if value else 0.0

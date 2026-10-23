"""Run every India real-world fix against live NSE / Yahoo data and print what happened.

    python scripts/india_live_check.py            # all checks
    python scripts/india_live_check.py --skip-optopsy --skip-walkforward

Network is required. Each section is independent: one failing source does not
stop the rest, and failures are printed as failures.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics.swings import (  # noqa: E402
    confirmed_swings,
    double_top_breakdown,
    find_lookahead,
    market_structure,
)
from tradingagents.analytics.validation import walk_forward  # noqa: E402
from tradingagents.compliance import review  # noqa: E402
from tradingagents.dataflows.vendors.nse import NSECalendar, default_client, now_ist  # noqa: E402
from tradingagents.dataflows.vendors.nse.derivatives import (  # noqa: E402
    LotSizeHistory,
    derive_legacy_lot_sizes,
    describe_expiries,
    expiries_from_bhavcopy,
    fo_bhavcopy,
    latest_bhavcopy,
    live_contract_info,
)
from tradingagents.dataflows.vendors.nse.flows import get_fii_dii  # noqa: E402
from tradingagents.dataflows.vendors.nse.indices import ConstituentStore, survivorship_warning  # noqa: E402
from tradingagents.dataflows.vendors.nse.tool_text import index_health_text  # noqa: E402
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv  # noqa: E402


def section(title):
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


def run(name, fn):
    section(name)
    try:
        fn()
    except Exception as exc:   # report and continue: this is a diagnostic
        print(f"FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)


def nifty_daily(years=5) -> pd.DataFrame:
    raw = load_ohlcv("^NSEI", now_ist().date().isoformat(), fill_gaps=False)
    raw["Date"] = pd.to_datetime(raw["Date"])
    df = raw.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    return df[df.index >= df.index.max() - pd.DateOffset(years=years)]


def p01_client():
    client = default_client()
    status = client.get_json("/api/marketStatus", ttl=60)
    cm = next(m for m in status.data["marketState"] if m["market"] == "Capital Market")
    print(f"Market status: {cm['marketStatus']} | {cm['index']} {cm['last']} ({cm['percentChange']}%) "
          f"at {cm['tradeDate']}\n  {status.provenance()}")
    indices = client.get_json("/api/allIndices", ttl=300)
    for row in indices.data["data"]:
        if row["index"] in ("NIFTY 50", "NIFTY BANK", "INDIA VIX"):
            print(f"  {row['index']:<11} last {row['last']:>10} chg {row['percentChange']:>6}%  "
                  f"open {row['open']} high {row['high']} low {row['low']}")
    print(f"Session cookies held: {len(client._session.cookies)}; breaker open: {client.breaker_open}")


def p04_flows():
    cal = NSECalendar.from_nse()
    now = now_ist()
    print(f"Now {now:%d-%b-%Y %H:%M} IST, session state: {cal.session_state(now).value}; "
          f"{len(cal.holidays)} NSE holidays loaded")
    print(get_fii_dii(now.date(), calendar=cal).to_text())
    print("\nAsked for a date never captured locally:")
    print(get_fii_dii(now.date() - timedelta(days=30), calendar=cal).to_text())


def p08_contracts():
    today = now_ist().date()
    bhav = latest_bhavcopy(today)
    day = bhav["trade_date"].iloc[0]
    history = LotSizeHistory()
    n = history.update_from_bhavcopy(bhav)
    legacy = fo_bhavcopy(date(2024, 1, 1))
    history.update_from_bhavcopy(legacy)
    history.save()
    print(f"Latest F&O bhavcopy: {day:%d-%b-%Y} ({len(bhav):,} rows, {n} symbols' lots recorded)")
    for sym in ("NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK"):
        lot = history.lot_size(sym, day)
        print(f"  {sym:<10} lot {lot.lot_size:>5} ({lot.confidence}, {lot.source})")
    print(f"Legacy file 01-Jan-2024, lots derived from turnover: "
          f"NIFTY {derive_legacy_lot_sizes(legacy)['NIFTY']}, BANKNIFTY {derive_legacy_lot_sizes(legacy)['BANKNIFTY']}")
    for sym in ("NIFTY", "BANKNIFTY"):
        print(f"  {sym} expiries (traded): {describe_expiries([e for e in expiries_from_bhavcopy(bhav, sym) if e >= day][:6])}")
    live = live_contract_info("NIFTY")
    print(f"  NIFTY live expiries: {describe_expiries(live['expiries'][:6])}")


def p09_universe():
    store = ConstituentStore()
    today = now_ist().date()
    for index in ("NIFTY 50", "NIFTY BANK"):
        symbols = store.refresh(index, today)
        print(f"{index}: {len(symbols)} members snapshotted on {today} (e.g. {', '.join(symbols[:6])}, ...)")
    m = store.members_as_of("NIFTY 50", today)
    print(f"As of today: method={m.method}, survivorship_safe={m.survivorship_safe}")
    old = store.members_as_of("NIFTY 50", date(2020, 1, 1))
    print(f"As of 2020-01-01: method={old.method}, survivorship_safe={old.survivorship_safe}")
    print("  " + survivorship_warning(old))
    print(f"  Change log file to fill from NSE announcements: {store.changes_path}")


def p02_index_volume():
    end = now_ist().date()
    print(index_health_text("^NSEI", (end - timedelta(days=21)).isoformat(), end.isoformat()))


def p17_lookahead():
    df = nifty_daily(years=1)
    swings = confirmed_swings(df)
    last_high = [s for s in swings if s.kind == "high"][-1]
    last_low = [s for s in swings if s.kind == "low"][-1]
    print(f"^NSEI last confirmed swing high {last_high.price:,.2f} on {last_high.pivot_at:%d-%b-%Y} "
          f"(knowable from {last_high.confirmed_at:%d-%b-%Y})")
    print(f"^NSEI last confirmed swing low  {last_low.price:,.2f} on {last_low.pivot_at:%d-%b-%Y} "
          f"(knowable from {last_low.confirmed_at:%d-%b-%Y})")
    print(f"Market structure today: {market_structure(df).iloc[-1] or 'not enough swings'}")
    recent = df.tail(160)
    leaks = find_lookahead(lambda d: double_top_breakdown(d), recent, start=20)
    print(f"Replay check of double-top detector over {len(recent)} bars: {len(leaks)} look-ahead mismatches")
    naive = find_lookahead(lambda d: d["High"] == d["High"].rolling(7, center=True).max(), recent, start=20)
    print(f"Replay check of a naive centred pivot (the common bug): {len(naive)} mismatches -> repaints")


def p18_walkforward():
    df = nifty_daily(years=5)

    def sma_trend(data, params):
        ret = data["Close"].pct_change().fillna(0)
        pos = (data["Close"] > data["Close"].rolling(params["n"]).mean()).astype(float).shift(1).fillna(0)
        cost = pos.diff().abs().fillna(0) * 0.0005        # ~5 bps per switch
        return pos * ret - cost

    def trades(oos):
        return int((oos != 0).astype(int).diff().eq(1).sum())

    grid = [{"n": n} for n in (10, 20, 50, 100, 150, 200)]
    result = walk_forward(df, sma_trend, grid, train=500, test=126, embargo=5, count_trades=trades)
    print(f"^NSEI long/flat SMA trend, {len(df)} bars, grid {[g['n'] for g in grid]}")
    for f in result.folds:
        print(f"  test {f.test_start:%Y-%m-%d}..{f.test_end:%Y-%m-%d}: chose n={f.params['n']:<3} "
              f"IS Sharpe {f.in_sample_sharpe:5.2f} -> OOS {f.out_of_sample_sharpe:5.2f}")
    print(result.summary())
    for note in result.notes:
        print("  note:", note)


def p15_optopsy():
    from tradingagents.integrations.optopsy import OptopsyBridge, bhavcopy_to_optopsy

    bridge = OptopsyBridge()
    doc = bridge.doctor()
    print(f"options engine healthy={doc['healthy']}: {doc}")
    comps = bridge.list_components()
    print(f"  engine exposes {len(comps['strategies'])} strategies and {len(comps['signals'])} signals")

    cal = NSECalendar.from_nse()
    end = cal.latest_session(now_ist().date() - timedelta(days=1))
    sessions = cal.sessions_between(end - timedelta(days=45), end)
    frames = []
    for day in sessions:
        try:
            frames.append(fo_bhavcopy(day))
        except Exception as exc:
            print(f"  skip {day}: {exc}")
    bhav = pd.concat(frames, ignore_index=True)
    nifty = bhav[(bhav["symbol"] == "NIFTY")]
    spot = nifty.groupby("trade_date")["underlying_price"].first()
    near = nifty[(nifty["strike"] - nifty["trade_date"].map(spot)).abs() <= 1000]
    chain = bhavcopy_to_optopsy(near, "NIFTY")
    print(f"  NIFTY chain from {len(sessions)} bhavcopies: {len(chain):,} rows; approximations:")
    for a in chain.attrs["approximations"]:
        print("   -", a)
    # The engine's vertical-spread default puts BOTH legs at 0.30 delta, so they land on the
    # same strike and every candidate is rejected (empty result). Always pass distinct legs.
    legs = {"leg1_delta": {"target": 0.10, "min": 0.05, "max": 0.20},     # long (protective) put
            "leg2_delta": {"target": 0.30, "min": 0.20, "max": 0.40}}     # short put
    result = bridge.run_strategy("short_put_spread", chain, max_entry_dte=14, exit_dte=0, **legs)
    print("  optopsy short_put_spread (long 0.10Δ / short 0.30Δ, entry <=14 DTE, held to expiry)"
          " on real NIFTY EOD data:")
    print(result.to_string())
    trades = bridge.run_strategy("short_put_spread", chain, max_entry_dte=14, exit_dte=0, raw=True, **legs)
    print(f"  {len(trades)} trades; first five:")
    print(trades.head(5).to_string())


def p25_compliance():
    sample = ("Nifty looks like a sure-shot buy with guaranteed returns.\n"
              "There are no guaranteed returns; stop-loss at 22,550.")
    for f in review(sample):
        print(f"  line {f.line}: '{f.phrase}' -> {f.reason}")
    print("  (line 2 is not flagged: negated)")


def main():
    # Windows consoles default to cp1252, which has no ₹.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-optopsy", action="store_true")
    parser.add_argument("--skip-walkforward", action="store_true")
    args = parser.parse_args()
    run("P-01  NSE blocking automated requests -> session-safe client", p01_client)
    run("P-03/P-04  calendar + FII/DII published only in the evening", p04_flows)
    run("P-08  lot sizes and expiries from NSE files, not constants", p08_contracts)
    run("P-09  survivorship bias -> point-in-time index membership", p09_universe)
    run("P-02  zero/garbage index volume from Yahoo -> constituent proxy + gap check", p02_index_volume)
    run("P-17  patterns that look into the future -> confirmed swings + replay check", p17_lookahead)
    if not args.skip_walkforward:
        run("P-18  overfitting -> walk-forward + deflated Sharpe", p18_walkforward)
    if not args.skip_optopsy:
        run("P-15  options engine inside TradingAgents (+ NSE bhavcopy adapter)", p15_optopsy)
    run("P-25  SEBI advice rules -> report compliance review", p25_compliance)


if __name__ == "__main__":
    main()

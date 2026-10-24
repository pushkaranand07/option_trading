"""Data for the Market Map page: 2021-2026 timeline, event impacts, market network.

    python scripts/market_map.py --out <dir>  [--events events.json]

Everything is measured from the verified NSE store; events come from a JSON list
(date, title, category, kind, source) researched from official sources and news,
plus events detected in the data itself (largest NIFTY days, VIX spikes, lot-size
changes). Writes <out>/market_map.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import SECTOR_OF, STOCKS  # noqa: E402

START = pd.Timestamp("2021-01-01")
WARMUP = pd.Timestamp("2020-09-01")    # measurement windows before the first 2021 events
PERIODS = {"2021-22": ("2021-01-01", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "2026-12-31")}


def wide(prices: pd.DataFrame, column: str) -> pd.DataFrame:
    p = prices.assign(trade_date=pd.to_datetime(prices["trade_date"]))
    return p.pivot(index="trade_date", columns="symbol", values=column).sort_index()


def build_series():
    prices = load_prices()
    close = wide(prices, "close")
    idx = close.index[close.index >= WARMUP]
    fo = ds.load("fo_summary", symbols=["NIFTY", "BANKNIFTY"])
    fo["trade_date"] = pd.to_datetime(fo["trade_date"])
    fo["opt_contracts"] = fo["call_contracts"] + fo["put_contracts"]
    fo_w = {c: fo.pivot(index="trade_date", columns="symbol", values=c) for c in
            ("opt_contracts", "opt_turnover", "pcr_oi", "lot_size", "fut_oi")}
    part = ds.load("participant")
    part["trade_date"] = pd.to_datetime(part["trade_date"])
    share = {}
    for who in ("FII", "Client", "Pro", "DII"):
        g = part[part["category"] == who].set_index("trade_date").sort_index()
        share[who] = g["fut_idx_long"].astype(float) / (g["fut_idx_long"] + g["fut_idx_short"]).astype(float)
    regime = pd.read_parquet(ds.store_root() / "regime" / "regime.parquet")
    regime = pd.Series(regime["regime"].to_numpy(), index=pd.to_datetime(regime["trade_date"]))
    df = pd.DataFrame({
        "nifty": close["NIFTY"], "banknifty": close["BANKNIFTY"], "vix": close["INDIAVIX"],
        "nifty_opt": fo_w["opt_contracts"]["NIFTY"], "bn_opt": fo_w["opt_contracts"]["BANKNIFTY"],
        # Notional value traded (Rs): unlike contract counts it does not jump when the lot size changes.
        "nifty_opt_val": fo_w["opt_turnover"]["NIFTY"], "bn_opt_val": fo_w["opt_turnover"]["BANKNIFTY"],
        "nifty_pcr": fo_w["pcr_oi"]["NIFTY"], "bn_pcr": fo_w["pcr_oi"]["BANKNIFTY"],
        "nifty_lot": fo_w["lot_size"]["NIFTY"], "bn_lot": fo_w["lot_size"]["BANKNIFTY"],
        "fii_long": share["FII"], "client_long": share["Client"], "pro_long": share["Pro"],
        "regime": regime,
    }).reindex(idx)
    return df, close


def detected_events(df: pd.DataFrame) -> list[dict]:
    ev = []
    r = np.log(df["nifty"]).diff()
    for d, v in r.nsmallest(8).items():
        ev.append({"date": d.strftime("%Y-%m-%d"), "title": f"NIFTY {v:+.1%} day", "category": "market",
                   "kind": "detected", "source": "NSE index close"})
    for d, v in r.nlargest(5).items():
        ev.append({"date": d.strftime("%Y-%m-%d"), "title": f"NIFTY {v:+.1%} day", "category": "market",
                   "kind": "detected", "source": "NSE index close"})
    for col, name in (("nifty_lot", "NIFTY"), ("bn_lot", "BANKNIFTY")):
        lot = df[col].ffill()
        ch = lot[lot != lot.shift()].iloc[1:]
        for d, v in ch.items():
            prev = lot.shift().loc[d]
            ev.append({"date": d.strftime("%Y-%m-%d"), "title": f"{name} lot size {prev:.0f} → {v:.0f}",
                       "category": "F&O structure", "kind": "detected", "source": "NSE F&O bhavcopy"})
    return ev


def impact(df: pd.DataFrame, date: str) -> dict | None:
    """Measured before/after around the first session on or after ``date``."""
    idx = df.index
    pos = idx.searchsorted(pd.Timestamp(date))
    if pos >= len(idx) or pos < 21:
        return None
    d = idx[pos]
    n = df["nifty"]

    def ret(a, b):
        a, b = max(a, 0), min(b, len(idx) - 1)
        return float(n.iloc[b] / n.iloc[a] - 1)

    lr = np.log(n).diff()

    def window(col, a, b):
        s = df[col].iloc[max(a, 0): max(min(b, len(idx)), 0)]
        return float(s.mean()) if s.notna().any() else None

    after = min(pos + 20, len(idx))
    out = {
        "session": d.strftime("%Y-%m-%d"),
        "nifty_day": ret(pos - 1, pos),
        "nifty_5d": ret(pos - 1, pos + 4),
        "nifty_20d": ret(pos - 1, pos + 19) if pos + 19 < len(idx) else None,
        "vix_before": float(df["vix"].iloc[pos - 1]) if pd.notna(df["vix"].iloc[pos - 1]) else None,
        "vix_after5": float(df["vix"].iloc[min(pos + 4, len(idx) - 1)]),
        "rv_before": float(lr.iloc[pos - 20:pos].std() * np.sqrt(252)),
        "rv_after": float(lr.iloc[pos:after].std() * np.sqrt(252)) if after - pos > 5 else None,
        "opt_before": window("nifty_opt_val", pos - 20, pos),
        "opt_after": window("nifty_opt_val", pos, after),
        "bn_opt_before": window("bn_opt_val", pos - 20, pos),
        "bn_opt_after": window("bn_opt_val", pos, after),
        "pcr_before": window("nifty_pcr", pos - 5, pos),
        "pcr_after": window("nifty_pcr", pos, pos + 5),
        "fii_before": window("fii_long", pos - 5, pos),
        "fii_after": window("fii_long", pos, pos + 5),
        "regime": df["regime"].iloc[pos] if isinstance(df["regime"].iloc[pos], str) else None,
    }
    return out


def network(close: pd.DataFrame, df: pd.DataFrame) -> dict:
    nodes = [{"id": s, "group": SECTOR_OF[s]} for s in STOCKS]
    nodes += [{"id": "NIFTY", "group": "index"}, {"id": "BANKNIFTY", "group": "index"},
              {"id": "INDIA VIX", "group": "volatility"}, {"id": "FII positioning", "group": "flows"}]
    rets = np.log(close[list(STOCKS) + ["NIFTY", "BANKNIFTY"]]).diff()
    rets["INDIA VIX"] = np.log(close["INDIAVIX"]).diff()
    rets["FII positioning"] = df["fii_long"].diff().reindex(rets.index)
    out = {"nodes": nodes, "periods": {}}
    for name, (a, b) in PERIODS.items():
        c = rets.loc[a:b].corr()
        links = []
        cols = list(c.columns)
        for i, x in enumerate(cols):
            for y in cols[i + 1:]:
                v = c.loc[x, y]
                if pd.notna(v) and abs(v) >= 0.45:
                    links.append({"source": x, "target": y, "r": round(float(v), 3)})
        out["periods"][name] = {
            "links": links,
            "nifty_corr": {s: round(float(c.loc[s, "NIFTY"]), 3) for s in cols if s != "NIFTY"},
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--events", type=Path, help="researched events JSON (list of objects)")
    args = parser.parse_args()
    df, close = build_series()
    events = detected_events(df)
    if args.events and args.events.exists():
        events += json.loads(args.events.read_text(encoding="utf-8"))
    for e in events:
        e["impact"] = impact(df, e["date"])
    # A big day found in the data that a researched event already explains is shown once, as that event.
    explained = {e["impact"]["session"] for e in events if e.get("kind") != "detected" and e["impact"]}
    events = [e for e in events if not (e.get("kind") == "detected" and e["category"] == "market"
                                        and e["impact"] and e["impact"]["session"] in explained)]
    events.sort(key=lambda e: e["date"])
    series = df[df.index >= START].reset_index(names="date")
    series["date"] = series["date"].dt.strftime("%Y-%m-%d")
    payload = {
        "updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "last_session": series["date"].iloc[-1],
        "series": {c: [None if pd.isna(v) else (round(float(v), 4) if not isinstance(v, str) else v)
                       for v in series[c]] for c in series.columns},
        "events": events,
        "network": network(close, df),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "market_map.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"{len(series)} sessions, {len(events)} events, "
          f"{sum(len(p['links']) for p in payload['network']['periods'].values())} network links -> "
          f"{args.out / 'market_map.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

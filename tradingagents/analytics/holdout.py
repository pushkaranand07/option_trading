"""Backward holdout for a frozen strategy (PROOF_PLAN.md, Stage 1 evidence).

The pooled VRP condor's frozen settings are the walk-forward's most frequent
choice over its 2021-04 → 2026 test folds. The years before that never informed
the choice, so running the frozen rules there, unchanged, is a holdout test:
one trial, on data the selection never saw.

Everything is built in memory and kept apart from the production store: the
store, its GARCH forecasts and the paper-trading ledger are not touched (mixing
an extended history into them would subtly change the frozen strategy's inputs).

Inputs before 2018 come from the raw NSE files (F&O bhavcopy, official index
closes); 2018 onwards from the store; index prices for GARCH training from Yahoo
back to 2012 (through the data layer).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tradingagents.analytics import condor as cd, datastore as ds, volatility_model as vm, vrp as vp
from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root
from tradingagents.analytics.implied_vol import atm_iv_table
from tradingagents.analytics.prices import fetch_prices, load_prices

YAHOO_START = date(2012, 1, 1)
RAW_START = date(2015, 1, 1)
STORE_START = date(2018, 1, 1)


def raw_years(symbol: str, start: date = RAW_START, end: date = STORE_START - timedelta(days=1)):
    """Option chain, near-month future closes, lot sizes and official index closes for one
    index, parsed from the raw files between ``start`` and ``end``."""
    raw = raw_root()
    manifest = load_manifest(raw)
    ok = {(d, k): r for (d, k), r in manifest.items() if r.status == "ok" and start <= d <= end}
    days = sorted(d for d, k in ok if k == "fo")
    chains, summaries, closes = [], [], {}
    index_name = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY"}[symbol]
    for day in days:
        r = ok[(day, "fo")]
        fo = ds.parse_fo(raw_path(raw, "fo", day, r.url).read_bytes(), r.url.rsplit("/", 1)[-1])
        fo = fo[fo["symbol"] == symbol]
        summary = ds.fo_summary(fo, [symbol])
        if summary["lot_size"].isna().any():
            summary["lot_size"] = summary["lot_size"].fillna(summary["symbol"].map(ds.lots_from_open_interest(fo)))
        summaries.append(summary)
        chains.append(ds.option_chain(fo, summary, [symbol]))
        if (day, "indices") in ok:
            ri = ok[(day, "indices")]
            ic = ds.parse_index_close(raw_path(raw, "indices", day, ri.url).read_bytes(), day)
            row = ic[ic["symbol"] == index_name]
            if len(row):
                closes[pd.Timestamp(day)] = float(row["close"].iloc[0])
    return (pd.concat(chains, ignore_index=True), pd.concat(summaries, ignore_index=True),
            pd.Series(closes, dtype=float).sort_index())


def build_inputs(symbol: str):
    """Chain, settlement spot, lots and VRP for ``symbol`` from 2015, in memory."""
    chain_old, summary_old, spot_old = raw_years(symbol)
    chain_new = ds.load("option_chain", symbols=[symbol])
    summary_new = ds.load("fo_summary", symbols=[symbol])
    chain = pd.concat([chain_old, chain_new[chain_old.columns]], ignore_index=True)
    summary = pd.concat([summary_old, summary_new[summary_old.columns]], ignore_index=True)
    summary["trade_date"] = pd.to_datetime(summary["trade_date"])
    summary = summary.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    lots = ds.despike_lots(summary.set_index("trade_date")["lot_size"])     # same clean-up as the store
    px_new = load_prices([symbol])
    spot = pd.concat([spot_old, pd.Series(px_new["close"].to_numpy(), index=pd.to_datetime(px_new["trade_date"]))])
    spot = spot[~spot.index.duplicated(keep="last")].sort_index()
    spot = spot.combine_first(summary.set_index("trade_date")["fut_close"])

    # GARCH: Yahoo closes 2012-2017 joined to the store's (NSE-sourced) closes from 2018.
    yahoo = fetch_prices([symbol], YAHOO_START, STORE_START - timedelta(days=1))
    closes = pd.concat([pd.Series(yahoo["close"].to_numpy(), index=pd.to_datetime(yahoo["trade_date"])),
                        pd.Series(px_new["close"].to_numpy(), index=pd.to_datetime(px_new["trade_date"]))])
    closes = closes[~closes.index.duplicated(keep="last")].sort_index()
    garch = vm.garch_forecasts(vm.log_returns(closes), "garch", horizons=(21,))["h21"]
    iv = atm_iv_table(chain)
    iv30 = pd.Series(iv["iv30"].to_numpy(), index=pd.to_datetime(iv["trade_date"]))
    return chain, spot, lots, vp.vrp_series(iv30, garch)


@dataclass
class HoldoutResult:
    symbol_trades: dict
    trades: list
    first_entry: date | None
    end: date
    mean: float
    wins: float
    ci: tuple[float, float]
    always_mean: float
    random_means: np.ndarray
    random_percentile: float

    def summary(self) -> str:
        r = np.array([t.return_on_risk for t in self.trades])
        lines = [f"Backward holdout: frozen rules, entries {self.first_entry} to {self.end} (data the settings never saw)"]
        for s, ts in self.symbol_trades.items():
            rr = np.array([t.return_on_risk for t in ts])
            lines.append(f"  {s}: {len(ts)} trades" + (f", mean {rr.mean():+.2%}, wins {(rr > 0).mean():.0%}"
                                                         if len(ts) else ""))
        if len(r):
            lines += [f"Pooled: {len(r)} trades | mean {self.mean:+.2%} of risk | wins {self.wins:.0%} | "
                      f"worst {r.min():+.0%} | total {r.sum():+.2f}",
                      f"Bootstrap 95% interval of the mean: [{self.ci[0]:+.2%}, {self.ci[1]:+.2%}]",
                      f"Always-enter (same rules, every possible entry) mean {self.always_mean:+.2%}; random entry "
                      f"days: median mean {np.median(self.random_means):+.2%}; frozen rules beat "
                      f"{self.random_percentile:.0%} of {len(self.random_means)} random runs"]
        return "\n".join(lines)


def run(inputs: dict, params_by_symbol: dict, end: date, random_runs: int = 200, seed: int = 0) -> HoldoutResult:
    """Frozen rules on ``inputs`` (symbol -> (chain, spot, lots, vrp)); trades entered up to ``end``."""
    from tradingagents.analytics.stress import block_bootstrap_ci

    rng = np.random.default_rng(seed)
    by_symbol, always, signals, sessions_of = {}, [], {}, {}
    for symbol, p in params_by_symbol.items():
        chain, spot, lots, vrp = inputs[symbol]
        sessions = pd.to_datetime(pd.Index(sorted(set(pd.to_datetime(chain["trade_date"])))))
        signal = vp.vrp_signal(vrp, p["z"], sessions) & (sessions <= pd.Timestamp(end))
        params = replace(cd.CondorParams(), short_delta=p["short_delta"], wing_pct=p["wing_pct"])
        trades, _ = cd.simulate_staggered(chain, spot, lots, signal, params, books=4)
        by_symbol[symbol] = [t for t in trades if t.entry_date <= end]
        valid = vrp.reindex(sessions).notna() & (sessions <= pd.Timestamp(end))
        every, _ = cd.simulate_staggered(chain, spot, lots, valid, params, books=4)
        always += [t for t in every if t.entry_date <= end]
        signals[symbol], sessions_of[symbol] = (signal, valid), sessions
    pooled = [t for ts in by_symbol.values() for t in ts]
    r = np.array([t.return_on_risk for t in pooled])
    rand = []
    for _ in range(random_runs):
        rt = []
        for symbol, p in params_by_symbol.items():
            chain, spot, lots, _ = inputs[symbol]
            signal, valid = signals[symbol]
            rate = signal.sum() / max(valid.sum(), 1)
            rsig = valid & pd.Series(rng.random(len(valid)) < rate, index=valid.index)
            params = replace(cd.CondorParams(), short_delta=p["short_delta"], wing_pct=p["wing_pct"])
            rt += [t.return_on_risk for t in cd.simulate_staggered(chain, spot, lots, rsig, params, books=4)[0]
                   if t.entry_date <= end]
        rand.append(np.mean(rt) if rt else np.nan)
    rand = np.array([x for x in rand if np.isfinite(x)])
    first = min((t.entry_date for t in pooled), default=None)
    ci = block_bootstrap_ci(r) if len(r) >= 10 else (float("nan"), float("nan"))
    am = float(np.mean([t.return_on_risk for t in always])) if always else float("nan")
    return HoldoutResult(by_symbol, pooled, first, end, float(r.mean()) if len(r) else float("nan"),
                         float((r > 0).mean()) if len(r) else float("nan"), ci, am, rand,
                         float((rand < r.mean()).mean()) if len(r) and len(rand) else float("nan"))

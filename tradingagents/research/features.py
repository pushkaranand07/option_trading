"""Point-in-time feature library v1: builders only, no model and no target (docs/features_v1.json, docs/PA_42).

A feature for signal date D reads rows with known_from at or before D. Every builder works on source sessions; ``to_long`` then
stamps each row with the signal date its source became public. Missing stays missing: nothing is carried across sessions,
and a discontinuity (a split, a scheme of arrangement, an OI reset) blanks the values it would distort.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from tradingagents.research import gate as g, loader

SPEC_FILE = g.ROOT / "docs" / "features_v1.json"
SPEC_SHA256 = "971294830a4a7408255e5845231de37b949914b821abac0049e163650cd17090"
ANNUAL = math.sqrt(252)
EXTREME = (-0.40, 0.667)
LIQUID_CONTRACTS = 25
RISK_FREE = 0.065           # ASSUMPTION: the repo's constant
RETURNS = (1, 2, 3, 5, 10, 20, 60)
GARCH_REFIT, GARCH_MIN_RETURNS = 63, 600
GARCH_HORIZONS = (1, 5, 10)
CATEGORIES = ("FII", "DII", "Client", "Pro")
MARKET_FAMILIES = ("d", "f")


def read_spec(path: Path | None = None) -> dict:
    spec = json.loads((path or SPEC_FILE).read_text(encoding="utf-8"))
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != SPEC_SHA256:
        raise ValueError("features_v1.json changed after it was frozen")
    return spec


# ---------------------------------------------------------------- panels

def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s)


def contract_panel(futures: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Contract rows with the same contract's previous session, where that is the session before."""
    f = futures.copy()
    f["t"], f["expiry"] = _ts(f["trade_date"]), _ts(f["expiry"])
    f = f[f["expiry"] >= f["t"]].sort_values(["symbol", "expiry", "t"]).reset_index(drop=True)
    pos = pd.Series(np.arange(len(sessions)), index=sessions)
    f["i"] = f["t"].map(pos)
    by = f.groupby(["symbol", "expiry"], sort=False)
    consecutive = by["i"].diff() == 1
    f["p_close"] = by["close"].shift(1).where(consecutive)
    f["p_oi"] = by["open_interest"].shift(1).where(consecutive)
    return f


def near_rows(f: pd.DataFrame) -> pd.DataFrame:
    return f.sort_values(["symbol", "t", "expiry"]).drop_duplicates(["symbol", "t"]).reset_index(drop=True)


def wide(rows: pd.DataFrame, column: str, sessions: pd.DatetimeIndex, symbols: pd.Index) -> pd.DataFrame:
    """Sessions by symbols; absent stays missing. A repeated (session, symbol) is an error, as in a pivot."""
    i, j = sessions.get_indexer(_ts(rows["t"])), symbols.get_indexer(rows["symbol"])
    hit = (i >= 0) & (j >= 0)
    if pd.DataFrame({"i": i[hit], "j": j[hit]}).duplicated().any():
        raise ValueError(f"{column}: repeated session and symbol")
    out = np.full((len(sessions), len(symbols)), np.nan)
    out[i[hit], j[hit]] = rows[column].to_numpy(dtype=float)[hit]
    return pd.DataFrame(out, index=sessions, columns=symbols)


def discontinuities(f: pd.DataFrame, near: pd.DataFrame, events: pd.DataFrame, sessions: pd.DatetimeIndex, symbols: pd.Index) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(discontinuity, OI reset) per session and symbol. Each uses only that session's data, or an ex-date on that session."""
    reset_rows = f[(f["p_oi"] > 0) & (f["open_interest"] > 0) & (f["oi_change"] == f["open_interest"])]
    reset = np.zeros((len(sessions), len(symbols)), dtype=bool)
    disc = np.zeros_like(reset)

    def mark(frame: np.ndarray, rows: pd.DataFrame) -> None:
        rows = rows[rows["t"].isin(sessions) & rows["symbol"].isin(symbols)]
        if len(rows):
            frame[sessions.get_indexer(rows["t"]), symbols.get_indexer(rows["symbol"])] = True

    mark(reset, reset_rows)
    mark(disc, reset_rows)
    if len(events):
        mark(disc, pd.DataFrame({"t": _ts(events["ex_date"]), "symbol": events["symbol"]}))
    foot = g.split_events(f.assign(trade_date=f["t"]))
    mark(disc, foot.assign(t=_ts(foot["trade_date"])))
    move = near["close"] / near["p_close"] - 1
    mark(disc, near[(move <= EXTREME[0]) | (move >= EXTREME[1])])
    return pd.DataFrame(disc, index=sessions, columns=symbols), pd.DataFrame(reset, index=sessions, columns=symbols)


def in_epochs(values: pd.DataFrame, disc: pd.DataFrame, fn: Callable[[pd.DataFrame], pd.DataFrame]) -> pd.DataFrame:
    """Apply a window function so that no window spans a discontinuity: each stretch between them is its own series. The
    discontinuity session opens the new stretch."""
    plain = [c for c in values.columns if not disc[c].any()]
    out = fn(values[plain])
    pieces = [out]
    for c in values.columns.difference(plain):
        epoch = disc[c].cumsum()
        parts = [fn(values[[c]].where(epoch == e)) for e in epoch.unique()]
        pieces.append(pd.concat(parts, axis=1).bfill(axis=1).iloc[:, [0]].set_axis([c], axis=1))
    return pd.concat(pieces, axis=1).reindex(columns=values.columns)


def source_returns(near: pd.DataFrame, disc: pd.DataFrame, sessions: pd.DatetimeIndex, symbols: pd.Index) -> pd.DataFrame:
    n = near[(near["contracts"] > 0) & (near["close"] > 0) & (near["p_close"] > 0)]
    lr = np.log(n["close"] / n["p_close"])
    return wide(n.assign(lr=lr), "lr", sessions, symbols).where(~disc)


# ---------------------------------------------------------------- family a

def family_a(f: pd.DataFrame, near: pd.DataFrame, disc: pd.DataFrame, lr: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sessions, symbols = disc.index, disc.columns
    out: dict[str, pd.DataFrame] = {}
    for n in RETURNS:
        out[f"ret_{n}"] = lr.rolling(n, min_periods=n).sum()
    for n in (5, 10, 20, 60):
        out[f"rv_{n}"] = lr.rolling(n, min_periods=max(int(n * 0.8), 2)).std() * ANNUAL
    out["rv_ratio_5_60"] = out["rv_5"] / out["rv_60"]
    ok = near[(near["contracts"] > 0) & (near["high"] >= near["low"]) & (near["low"] > 0) & (near["open"] > 0) & (near["close"] > 0)]
    o, h, low, c = (wide(ok, x, sessions, symbols).where(~disc) for x in ("open", "high", "low", "close"))
    hl = np.log(h / low) ** 2
    out["parkinson_20"] = np.sqrt(hl.rolling(20, min_periods=16).mean() / (4 * math.log(2))) * ANNUAL
    gk = 0.5 * hl - (2 * math.log(2) - 1) * np.log(c / o) ** 2
    mean_gk = gk.rolling(20, min_periods=16).mean()
    out["garman_klass_20"] = np.sqrt(mean_gk.where(mean_gk >= 0)) * ANNUAL
    pc = wide(near, "p_close", sessions, symbols)
    out["gap_1"] = np.log(o / pc.where(pc > 0))
    out["range_1"] = (h - low) / c
    out["close_loc_1"] = ((c - low) / (h - low)).where(h > low)
    t = f.groupby(["t", "symbol"])["turnover"].sum().unstack().reindex(index=sessions, columns=symbols)
    t = t.where(t > 0)
    out["turnover_ratio_20"] = t / t.shift(1).rolling(20, min_periods=16).mean()
    out["turnover_ratio_5_60"] = t.rolling(5, min_periods=5).mean() / t.rolling(60, min_periods=48).mean()
    return out


def garch_one(args: tuple[str, pd.Series]) -> pd.DataFrame:
    from tradingagents.analytics import volatility_model as vm

    symbol, r = args
    r = r.dropna()
    if len(r) <= GARCH_MIN_RETURNS:
        return pd.DataFrame()
    try:
        fc = vm.garch_forecasts(r, "garch", horizons=GARCH_HORIZONS, refit_every=GARCH_REFIT)
    except Exception:        # a symbol GARCH cannot fit has no forecast: missing stays missing
        return pd.DataFrame()
    return fc.rename(columns={f"h{h}": f"garch_h{h}" for h in GARCH_HORIZONS}).reset_index(names="t").assign(symbol=symbol)


# ---------------------------------------------------------------- family b

def family_b(f: pd.DataFrame, near: pd.DataFrame, disc: pd.DataFrame, reset: pd.DataFrame, index_close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sessions, symbols = disc.index, disc.columns
    total = f.groupby(["t", "symbol"])["open_interest"].sum().unstack().reindex(index=sessions, columns=symbols)
    both = f[f["p_oi"].notna()]
    change = both.assign(d=both["open_interest"] - both["p_oi"]).groupby(["t", "symbol"])["d"].sum().unstack().reindex(index=sessions, columns=symbols)
    previous = total.shift(1)
    out: dict[str, pd.DataFrame] = {"oi_chg_1": (change / previous.where(previous > 0)).where(~disc)}
    out["oi_chg_5"] = out["oi_chg_1"].rolling(5, min_periods=5).sum()
    log_oi = np.log(total.where(total > 0))

    def z(w: pd.DataFrame) -> pd.DataFrame:
        r = w.rolling(60, min_periods=40)
        return (w - r.mean()) / r.std()

    out["oi_z_60"] = in_epochs(log_oi, disc, z)
    out["oi_rel_252"] = in_epochs(total, disc, lambda w: w.rolling(252, min_periods=126).rank(pct=True))
    out["oi_near_share"] = wide(near, "open_interest", sessions, symbols) / total.where(total > 0)
    ordered = f.sort_values(["symbol", "t", "expiry"])
    second = ordered[ordered.groupby(["symbol", "t"]).cumcount() == 1]
    pair = near.merge(second, on=["symbol", "t"], suffixes=("", "_n"))
    pair = pair[(pair["contracts"] > 0) & (pair["contracts_n"] > 0) & (pair["close"] > 0) & (pair["close_n"] > 0)]
    days = (pair["expiry_n"] - pair["expiry"]).dt.days
    out["basis_term"] = wide(pair.assign(v=np.log(pair["close_n"] / pair["close"]) * 365 / days), "v", sessions, symbols)
    spot = index_close[index_close["symbol"].isin(["NIFTY", "BANKNIFTY"])].assign(t=lambda x: _ts(x["trade_date"]))
    n = near.merge(spot[["t", "symbol", "close"]], on=["t", "symbol"], suffixes=("", "_s"))
    n = n[(n["contracts"] > 0) & ((n["expiry"] - n["t"]).dt.days >= 3)]
    out["basis_spot_index"] = wide(n.assign(v=np.log(n["close"] / n["close_s"]) * 365 / (n["expiry"] - n["t"]).dt.days), "v", sessions, symbols)
    listed = wide(near.assign(v=1.0), "v", sessions, symbols).notna()
    out["oi_reset_flag"] = reset.astype(float).where(listed)
    out["disc_flag"] = disc.astype(float).where(listed)
    last = pd.DataFrame(np.where(disc, np.arange(len(sessions))[:, None], np.nan), index=sessions, columns=symbols).ffill()
    out["sessions_since_disc"] = pd.DataFrame(np.arange(len(sessions))[:, None] - last.to_numpy(), index=sessions, columns=symbols).where(listed)
    return out


# ---------------------------------------------------------------- family c

def black76(F, K, T, r, sigma, is_call):
    s = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    df = np.exp(-r * T)
    return np.where(is_call, df * (F * norm.cdf(d1) - K * norm.cdf(d2)), df * (K * norm.cdf(-d2) - F * norm.cdf(-d1)))


def implied_vol(price, F, K, T, is_call, r: float = RISK_FREE, iterations: int = 40) -> np.ndarray:
    """Black-76 by bisection on [0.5%, 500%]. A price outside the model's range has no IV."""
    price, F, K, T, is_call = map(np.asarray, (price, F, K, T, is_call))
    lo, hi = np.full(len(price), 0.005), np.full(len(price), 5.0)
    bad = (black76(F, K, T, r, lo, is_call) > price) | (black76(F, K, T, r, hi, is_call) < price)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        above = black76(F, K, T, r, mid, is_call) > price
        hi, lo = np.where(above, mid, hi), np.where(above, lo, mid)
    return np.where(bad, np.nan, (lo + hi) / 2)


CHAIN_COLUMNS = ["trade_date", "symbol", "expiry", "strike", "option_type", "close", "contracts", "open_interest", "flag_parity", "flag_below_intrinsic", "exercise_style"]
_KEY = ["t", "symbol", "expiry", "strike"]
_EXPIRY = ["t", "symbol", "expiry"]


def _max_pain(rows: pd.DataFrame) -> pd.Series:
    out = {}
    for key, x in rows.groupby(["t", "symbol"], sort=False):
        k = x["strike"].to_numpy()
        if len(k) < 5:
            continue
        ce, pe = x["oi_c"].fillna(0).to_numpy(), x["oi_p"].fillna(0).to_numpy()
        if ce.sum() + pe.sum() <= 0:
            continue
        pain = (np.maximum(k[:, None] - k, 0) * ce).sum(axis=1) + (np.maximum(k - k[:, None], 0) * pe).sum(axis=1)
        out[key] = k[int(np.argmin(pain))]
    return pd.Series(out, dtype=float)


def options_from_chain(chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(same-session option features per t and symbol, ATM IV per expiry). European rows only; raises on anything else."""
    c = loader.require_european(chain[~chain["symbol"].isin(g.FOREIGN_INDICES)])
    c = c.assign(t=_ts(c["trade_date"]), expiry=_ts(c["expiry"]))
    calls = c[c["option_type"] == "CE"].set_index(_KEY)
    puts = c[c["option_type"] == "PE"].set_index(_KEY)
    cols = ["close", "contracts", "open_interest", "flag_parity", "flag_below_intrinsic"]
    p = calls[cols].add_suffix("_c").join(puts[cols].add_suffix("_p"), how="outer").reset_index()
    p = p.rename(columns={"open_interest_c": "oi_c", "open_interest_p": "oi_p"})
    keys = c[["t", "symbol"]].drop_duplicates()
    flagged = p[["flag_parity_c", "flag_parity_p", "flag_below_intrinsic_c", "flag_below_intrinsic_p"]].fillna(True).astype(bool).any(axis=1)
    liq = p[(p[["contracts_c", "contracts_p"]].min(axis=1, skipna=False) >= LIQUID_CONTRACTS) & (p["close_c"] > 0) & (p["close_p"] > 0) & ~flagged].copy()
    empty = keys.assign(n_liquid_pairs=0.0)
    if not len(liq):
        return empty, pd.DataFrame(columns=[*_EXPIRY, "atm_iv"])
    liq["days"] = (liq["expiry"] - liq["t"]).dt.days
    liq = liq[liq["days"] >= 1].copy()
    liq["T"] = liq["days"] / 365.0
    liq["cp"] = liq["close_c"] - liq["close_p"]
    a = liq.loc[liq.assign(a=liq["cp"].abs()).groupby(_EXPIRY)["a"].idxmin()]
    fwd = a.assign(F=a["strike"] + np.exp(RISK_FREE * a["T"]) * a["cp"])[[*_EXPIRY, "F"]]
    liq = liq.merge(fwd, on=_EXPIRY)
    liq = liq[liq["F"] > 0]
    liq["m"] = liq["strike"] / liq["F"]
    ex = liq[[*_EXPIRY, "days"]].drop_duplicates().sort_values(_EXPIRY)
    ex = ex[ex["days"] >= 7]
    ex["n"] = ex.groupby(["t", "symbol"]).cumcount()
    which = ex[ex["n"] <= 1][[*_EXPIRY, "n"]]

    atm = liq[(liq["m"] - 1).abs() <= 0.025].merge(which, on=_EXPIRY)
    atm = atm.loc[atm.assign(d=(atm["m"] - 1).abs()).groupby(_EXPIRY)["d"].idxmin()]
    iv_c = implied_vol(atm["close_c"], atm["F"], atm["strike"], atm["T"], np.full(len(atm), True))
    iv_p = implied_vol(atm["close_p"], atm["F"], atm["strike"], atm["T"], np.full(len(atm), False))
    atm = atm.assign(atm_iv=(iv_c + iv_p) / 2)[[*_EXPIRY, "n", "atm_iv"]]

    out = keys.merge(liq.groupby(["t", "symbol"]).size().rename("pairs").reset_index(), on=["t", "symbol"], how="left")
    out["n_liquid_pairs"] = np.log1p(out["pairs"].fillna(0))
    out = out.drop(columns="pairs")
    front = atm[atm["n"] == 0].rename(columns={"atm_iv": "atm_iv_front", "expiry": "front_expiry"})[["t", "symbol", "front_expiry", "atm_iv_front"]]
    nxt = atm[atm["n"] == 1].rename(columns={"atm_iv": "atm_iv_next"})[["t", "symbol", "atm_iv_next"]]
    out = out.merge(front, on=["t", "symbol"], how="left").merge(nxt, on=["t", "symbol"], how="left")
    out["iv_term_slope"] = out["atm_iv_next"] - out["atm_iv_front"]
    out["iv_term_ratio"] = out["atm_iv_next"] / out["atm_iv_front"]

    f0 = liq.merge(which[which["n"] == 0][_EXPIRY], on=_EXPIRY)
    wp = f0[f0["m"].between(0.90, 0.98)]
    wp = wp.loc[wp.assign(d=(wp["m"] - 0.95).abs()).groupby(_EXPIRY)["d"].idxmin()]
    wc = f0[f0["m"].between(1.02, 1.10)]
    wc = wc.loc[wc.assign(d=(wc["m"] - 1.05).abs()).groupby(_EXPIRY)["d"].idxmin()]
    wp = wp.assign(iv_p=implied_vol(wp["close_p"], wp["F"], wp["strike"], wp["T"], np.full(len(wp), False)))[["t", "symbol", "iv_p"]]
    wc = wc.assign(iv_c=implied_vol(wc["close_c"], wc["F"], wc["strike"], wc["T"], np.full(len(wc), True)))[["t", "symbol", "iv_c"]]
    skew = wp.merge(wc, on=["t", "symbol"])
    out = out.merge(skew.assign(skew_5=skew["iv_p"] - skew["iv_c"])[["t", "symbol", "skew_5"]], on=["t", "symbol"], how="left")
    out["skew_5_norm"] = out["skew_5"] / out["atm_iv_front"]

    s = liq.groupby(["t", "symbol"])[["contracts_c", "contracts_p", "oi_c", "oi_p"]].sum()
    s["pcr_volume_liquid"] = s["contracts_p"] / s["contracts_c"].where(s["contracts_c"] > 0)
    s["pcr_oi_liquid"] = s["oi_p"] / s["oi_c"].where(s["oi_c"] > 0)
    out = out.merge(s[["pcr_volume_liquid", "pcr_oi_liquid"]].reset_index(), on=["t", "symbol"], how="left")

    fronts = which[which["n"] == 0][_EXPIRY].merge(fwd, on=_EXPIRY)
    chain_front = p.merge(fronts, on=_EXPIRY)
    pain = _max_pain(chain_front)
    if len(pain):
        pm = pain.rename("pain").rename_axis(["t", "symbol"]).reset_index().merge(fronts[["t", "symbol", "F"]], on=["t", "symbol"])
        out = out.merge(pm.assign(max_pain_dist=np.log(pm["pain"] / pm["F"]))[["t", "symbol", "max_pain_dist"]], on=["t", "symbol"], how="left")
    else:
        out["max_pain_dist"] = np.nan
    return out.drop_duplicates(["t", "symbol"]), atm[[*_EXPIRY, "atm_iv"]]


def family_c(options: pd.DataFrame, atm: pd.DataFrame, disc: pd.DataFrame, rv20: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sessions, symbols = disc.index, disc.columns
    options = options.assign(t=_ts(options["t"]), front_expiry=_ts(options["front_expiry"]))
    atm = atm.assign(t=_ts(atm["t"]), expiry=_ts(atm["expiry"]))
    o = options[options["t"].isin(sessions) & options["symbol"].isin(symbols)]
    names = ["atm_iv_front", "atm_iv_next", "iv_term_slope", "iv_term_ratio", "skew_5", "skew_5_norm", "pcr_volume_liquid", "pcr_oi_liquid", "max_pain_dist", "n_liquid_pairs"]
    out = {n: wide(o, n, sessions, symbols) for n in names}
    a = atm[atm["t"].isin(sessions)]
    today =o.dropna(subset=["front_expiry"])[["t", "symbol", "front_expiry", "atm_iv_front"]]
    prior = a.rename(columns={"t": "prev_t", "expiry": "front_expiry", "atm_iv": "iv_prev"})[["prev_t", "symbol", "front_expiry", "iv_prev"]]
    today = today.assign(prev_t=today["t"].map(pd.Series(sessions[:-1], index=sessions[1:]))).merge(prior, on=["prev_t", "symbol", "front_expiry"])
    chg = today.assign(v=today["atm_iv_front"] - today["iv_prev"])
    out["atm_iv_chg_1"] = wide(chg, "v", sessions, symbols).where(~disc)
    out["atm_iv_rel_252"] = out["atm_iv_front"].rolling(252, min_periods=126).rank(pct=True)
    out["iv_minus_rv_20"] = out["atm_iv_front"] - rv20
    return out


# ---------------------------------------------------------------- families d, e, f

def family_d(participant: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict[str, pd.Series]:
    p = participant.assign(t=_ts(participant["trade_date"]))
    out: dict[str, pd.Series] = {}
    for cat in CATEGORIES:
        x = p[p["category"] == cat].set_index("t").reindex(sessions)
        low = cat.lower()

        def net(long_col: str, short_col: str, x=x) -> pd.Series:
            lg, sh = x[long_col].astype(float), x[short_col].astype(float)
            return (lg - sh) / (lg + sh).where(lg + sh > 0)

        for k in ("fut_idx", "fut_stk"):
            out[f"{low}_{k}_net"] = net(f"{k}_long", f"{k}_short")
            out[f"{low}_{k}_net_chg_5"] = out[f"{low}_{k}_net"] - out[f"{low}_{k}_net"].shift(5)
        out[f"{low}_opt_idx_call_net"] = net("opt_idx_call_long", "opt_idx_call_short")
        out[f"{low}_opt_idx_put_net"] = net("opt_idx_put_long", "opt_idx_put_short")
    return out


def family_e(delivery: pd.DataFrame, sessions: pd.DatetimeIndex, symbols: pd.Index) -> dict[str, pd.DataFrame]:
    d = delivery.assign(t=_ts(delivery["trade_date"]))
    pct = wide(d, "deliv_pct", sessions, symbols)
    return {"deliv_pct": pct, "deliv_chg_1": pct - pct.shift(1), "deliv_rel_20": pct - pct.shift(1).rolling(20, min_periods=16).mean()}


def family_f(index_close: pd.DataFrame, a: dict[str, pd.DataFrame], members: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex) -> dict[str, pd.Series]:
    ic = index_close.assign(t=_ts(index_close["trade_date"]))
    close = ic.pivot(index="t", columns="symbol", values="close").reindex(sessions)
    out: dict[str, pd.Series] = {}
    if "INDIAVIX" in close:
        v = close["INDIAVIX"]
        r = v.rolling(60, min_periods=40)
        out |= {"vix": v, "vix_chg_1": np.log(v / v.shift(1)), "vix_chg_5": np.log(v / v.shift(5)), "vix_z_60": (v - r.mean()) / r.std()}
    else:
        out |= {k: pd.Series(np.nan, index=sessions) for k in ("vix", "vix_chg_1", "vix_chg_5", "vix_z_60")}
    n = close["NIFTY"] if "NIFTY" in close else pd.Series(np.nan, index=sessions)
    for w in (5, 20, 60):
        out[f"nifty_ret_{w}"] = np.log(n / n.shift(w))
    for w in (50, 200):
        ma = n.rolling(w, min_periods=w).mean()
        out[f"nifty_above_ma_{w}"] = (n > ma).astype(float).where(ma.notna())
    for sym, name in (("NIFTY", "nifty_fut_ret_20"), ("BANKNIFTY", "banknifty_fut_ret_20")):
        out[name] = a["ret_20"][sym] if sym in a["ret_20"] else pd.Series(np.nan, index=sessions)
    for u, m in members.items():
        for w in (1, 20, 60):
            r = a[f"ret_{w}"].where(m)
            count = r.notna().sum(axis=1)
            out[f"breadth_up_{w}_{u}"] = ((r > 0).sum(axis=1) / count.where(count > 0)).where(count >= 20)
    return out


# ---------------------------------------------------------------- long tables, g, h

def signal_map(summary: pd.DataFrame) -> pd.DataFrame:
    m = summary[["trade_date", "known_from"]].drop_duplicates()
    return pd.DataFrame({"t": _ts(m["trade_date"]), "signal_date": _ts(m["known_from"])}).drop_duplicates("t").sort_values("t").reset_index(drop=True)


def to_long(panels: dict[str, pd.DataFrame], smap: pd.DataFrame, listed: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per source session and symbol that has any value, stamped with its signal date."""
    first = next(iter(panels.values()))
    idx = pd.MultiIndex.from_product([first.index, first.columns], names=["t", "symbol"])
    data = {k: v.reindex(index=first.index, columns=first.columns).to_numpy(dtype=float).ravel() for k, v in panels.items()}
    long = pd.DataFrame(data, index=idx)
    if listed is None:
        keep = long.notna().any(axis=1).to_numpy()
    else:          # a window's value never outlives the symbol's own rows: no row that session, no value
        keep = listed.reindex(index=first.index, columns=first.columns).fillna(False).to_numpy(dtype=bool).ravel()
    long = long[keep].reset_index()
    return _stamp(long, smap)


def _stamp(long: pd.DataFrame, smap: pd.DataFrame) -> pd.DataFrame:
    x = long.merge(smap, on="t", how="inner").rename(columns={"t": "source_trade_date"})
    x["known_from"] = x["signal_date"]
    front = ["signal_date", "source_trade_date", "known_from"]
    return x[front + [c for c in x.columns if c not in front]]


def market_long(series: dict[str, pd.Series], smap: pd.DataFrame) -> pd.DataFrame:
    long = pd.DataFrame(series)
    long = long[long.notna().any(axis=1)].rename_axis("t").reset_index()
    return _stamp(long, smap)


def family_g(f: pd.DataFrame, near: pd.DataFrame, notices: pd.DataFrame, smap: pd.DataFrame) -> pd.DataFrame:
    base = near[["t", "symbol"]].merge(smap, on="t")
    d = base["signal_date"]
    out = base.assign(day_of_week=d.dt.weekday.astype(float), days_since_prev_session=(d - base["t"]).dt.days.astype(float))
    ex = f[["t", "symbol", "expiry"]].merge(smap, on="t")
    ex = ex[ex["expiry"] >= ex["signal_date"]].groupby(["t", "symbol"])["expiry"].min().rename("next_expiry").reset_index()
    out = out.merge(ex, on=["t", "symbol"], how="left")
    out["days_to_expiry"] = (out["next_expiry"] - out["signal_date"]).dt.days.astype(float)
    out["expiry_week"] = (out["days_to_expiry"] <= 7).astype(float).where(out["days_to_expiry"].notna())
    for name in ("board_days_to_next", "board_days_since_last", "results_days_to_next", "results_days_since_last"):
        out[name] = np.nan
    close = pd.Timedelta(hours=15, minutes=30)
    for sym, n in notices.groupby("symbol"):
        rows = out.index[out["symbol"] == sym]
        if not len(rows):
            continue
        days = out.loc[rows, "signal_date"].to_numpy(dtype="datetime64[ns]")
        for prefix, sub in (("board", n), ("results", n[n["results"]])):
            meet = sub["meeting"].to_numpy(dtype="datetime64[ns]")
            note = sub["notice"].to_numpy(dtype="datetime64[ns]")
            if not len(meet):
                continue
            known = note[None, :] < (days + np.timedelta64(close))[:, None]
            gap = (meet[None, :] - days[:, None]) / np.timedelta64(1, "D")
            ahead = np.where(known & (gap >= 0), gap, np.inf).min(axis=1)
            behind = np.where(known & (gap < 0), -gap, np.inf).min(axis=1)
            out.loc[rows, f"{prefix}_days_to_next"] = np.where(np.isfinite(ahead), ahead, np.nan)
            out.loc[rows, f"{prefix}_days_since_last"] = np.where(np.isfinite(behind), behind, np.nan)
    out = out.drop(columns="next_expiry").rename(columns={"t": "source_trade_date"})
    out["known_from"] = out["signal_date"]
    front = ["signal_date", "source_trade_date", "known_from"]
    return out[front + [c for c in out.columns if c not in front]]


def family_h(tables: list[pd.DataFrame], members: dict[str, pd.DataFrame], ranked: list[str]) -> pd.DataFrame:
    """Percentile ranks per signal date among a universe's stock members, ranked on that date's values only."""
    joined = None
    for t in tables:
        cols = ["signal_date", "symbol", *[c for c in ranked if c in t]]
        joined = t[cols] if joined is None else joined.merge(t[cols], on=["signal_date", "symbol"], how="outer")
    src = tables[0][["signal_date", "source_trade_date"]].drop_duplicates("signal_date")
    out = joined[["signal_date", "symbol"]].copy()
    for u, m in members.items():
        stacked = m.stack()
        stacked = stacked[stacked].rename_axis(["signal_date", "symbol"]).reset_index()[["signal_date", "symbol"]].assign(_m=True)
        x = joined.merge(stacked, on=["signal_date", "symbol"], how="left")
        inside = x["_m"].fillna(False).astype(bool).to_numpy()
        for c in ranked:
            v = x[c].where(inside)
            by = v.groupby(x["signal_date"])
            out[f"rank_{u}_{c}"] = by.rank(pct=True).where(by.transform("count") >= 20).to_numpy()
    value_cols = [c for c in out.columns if c.startswith("rank_")]
    out = out[out[value_cols].notna().any(axis=1)].merge(src, on="signal_date")
    out["known_from"] = out["signal_date"]
    return out[["signal_date", "source_trade_date", "known_from", "symbol", *value_cols]]


def stock_members(membership: pd.DataFrame, smap: pd.DataFrame, sessions: pd.DatetimeIndex, symbols: pd.Index, by_signal: bool = False) -> pd.DataFrame:
    """Stock membership per source session (the signal date's membership moved back to its source), or per signal date."""
    m = membership[membership["kind"] == "stock"]
    x = pd.DataFrame({"signal_date": _ts(m["date"]), "symbol": m["symbol"].to_numpy()}).merge(smap, on="signal_date")
    x["v"] = True
    if by_signal:
        return x.pivot(index="signal_date", columns="symbol", values="v").reindex(columns=symbols).fillna(False).astype(bool)
    return x.pivot(index="t", columns="symbol", values="v").reindex(index=sessions, columns=symbols).fillna(False).astype(bool)


def build(inputs: dict, options: pd.DataFrame, atm: pd.DataFrame, garch: pd.DataFrame | None = None) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """All families from loaded inputs; pure. ``inputs``: futures, summary, participant, delivery, index_close, events, notices,
    U1, U2. Returns (tables, returns panel)."""
    f0 = inputs["futures"]
    sessions = pd.DatetimeIndex(sorted(set(_ts(f0["trade_date"])) | {pd.Timestamp(d) for d in inputs.get("holes", ()) if pd.Timestamp(d) <= _ts(f0["trade_date"]).max()}))
    f = contract_panel(f0, sessions)
    near = near_rows(f)
    symbols = pd.Index(sorted(near["symbol"].unique()))
    smap = signal_map(inputs["summary"])
    disc, reset = discontinuities(f, near, inputs["events"], sessions, symbols)
    lr = source_returns(near, disc, sessions, symbols)
    a = family_a(f, near, disc, lr)
    b = family_b(f, near, disc, reset, inputs["index_close"])
    c = family_c(options, atm, disc, a["rv_20"])
    e = family_e(inputs["delivery"], sessions, symbols)
    members = {u: stock_members(inputs[u], smap, sessions, symbols) for u in ("U1", "U2")}
    listed = wide(near.assign(v=True), "v", sessions, symbols)
    ta = to_long(a, smap, listed)
    if garch is not None and len(garch):
        ta = ta.merge(garch.rename(columns={"t": "source_trade_date"}), on=["source_trade_date", "symbol"], how="left")
    else:
        for h in GARCH_HORIZONS:
            ta[f"garch_h{h}"] = np.nan
    tb = to_long(b, smap, listed)
    tc = to_long(c, smap)
    td = market_long(family_d(inputs["participant"], sessions), smap)
    te = to_long(e, smap, listed)      # only symbols with a futures row that session: a later F&O listing must not add earlier rows
    tf = market_long(family_f(inputs["index_close"], a, members, sessions), smap)
    tg = family_g(f, near, inputs["notices"], smap)
    by_signal = {u: stock_members(inputs[u], smap, sessions, symbols, by_signal=True) for u in ("U1", "U2")}
    ranked = ["ret_1", "ret_5", "ret_20", "rv_20", "turnover_ratio_20", "oi_chg_1", "oi_z_60", "atm_iv_front", "iv_minus_rv_20", "skew_5", "pcr_oi_liquid", "deliv_pct"]
    th = family_h([ta, tb, tc, te], by_signal, ranked)
    return {"a": ta, "b": tb, "c": tc, "d": td, "e": te, "f": tf, "g": tg, "h": th}, lr


def load_inputs(end=None, root: Path | None = None, symbols=None) -> dict:
    """Everything except the option chain, through the research loader."""
    from datetime import date

    from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES
    from tradingagents.research import universes as uv

    start = date(2010, 1, 1)
    summary = g.load("base_fo_summary", start=start, end=end, root=root)
    u1, u2 = g.universe_members(summary, pd.read_csv(uv.SYMBOL_MAP))
    return {"futures": g.clean_futures(g.load("base_futures", start=start, end=end, root=root)), "summary": summary,
            "participant": g.load("base_participant", start=start, end=end, root=root), "delivery": g.load("base_delivery", start=start, end=end, root=root),
            "index_close": g.load("base_index", start=start, end=end, root=root), "events": loader.load_price_events(end, root),
            "notices": loader.load_board_notices(end, root), "U1": u1, "U2": u2, "holes": [d for d, k in ARCHIVE_HOLES.items() if "fo" in k]}


# ---------------------------------------------------------------- winsorizing, applied at model time

def fit_limits(values: pd.Series, low: float = 0.5, high: float = 99.5) -> tuple[float, float]:
    v = values.dropna().to_numpy(dtype=float)
    v = v[np.isfinite(v)]
    return (float(np.percentile(v, low)), float(np.percentile(v, high))) if len(v) else (float("nan"), float("nan"))


def apply_limits(frame: pd.DataFrame, limits: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """Clip listed columns; missing stays missing."""
    out = frame.copy()
    for c, (lo, hi) in limits.items():
        if c in out:
            out[c] = out[c].clip(lo, hi)
    return out

"""The quant layer for the web app: risk, measured option spreads, research results, the trade journal.

Everything here reads files the quant layer already wrote (the NSE store, the nightly option quotes, the trial
log, the paper ledger, the daily job's status); nothing is fitted or downloaded on a page view. Personal trade
files stay in ``reports/journal/`` on this computer.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "reports" / "journal"
MARKET_MAP = ROOT / "reports" / "market_map" / "india-market-map.html"
JOURNAL_TYPES = (".csv", ".xlsx", ".xls")
MAX_UPLOAD = 10 * 1024 * 1024

# Web-app symbols -> the quant layer's tickers (only the indices differ).
_TICKER = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}

# What the research has validated for use (from the progress tracker; shown as plain facts).
IN_USE = [
    {"name": "GARCH volatility forecast → expected move", "evidence": "Beat 20-day historical volatility on 31 of 31 symbols, out of sample",
     "use": "Stop distance, strike width, position size"},
    {"name": "Market regime (calm / choppy / stress)", "evidence": "Next-month NIFTY volatility 11.5% in calm vs 15.1% in choppy (p = 0.026)",
     "use": "How much risk to take. Not a direction signal"},
    {"name": "Measured option spreads", "evidence": "NSE closing bid/ask every evening; ≈ 0.85× the cost model on liquid strikes",
     "use": "Which options are too costly to trade"},
]


# Plain names and one-line results for the trial log's ideas (numbers from docs/PROGRESS_TRACKER.md).
# (plain name, what it tested, unit of "tested on", the result in plain words)
IDEA_INFO = {
    "ma_trend": ("Moving-average trend (50/200 day)", "Buy when the 50-day average is above the 200-day", "trades",
                 "Beat random timing only 6% of the time"),
    "lgbm_h10_k1.0": ("AI model: will the stock rise? (price data)", "Machine learning on prices and volumes", "trades",
                      "No skill: as good as a coin flip at ranking stocks (0.505)"),
    "lgbm_h10_k1.0_store": ("AI model: will the stock rise? (+ NSE OI, PCR, FII data)", "Same, with derivatives and flow data",
                            "trades", "No skill: 0.502, a coin flip"),
    "relative_strength": ("Pick the 5 strongest stocks", "Hold the stocks the model ranks best, swap every 2 weeks", "trades",
                          "Lost 1.2% a year vs simply holding all 29, after costs"),
    "relative_strength_keep10": ("Strongest stocks, fewer swaps", "Same, but keep a stock while it stays in the top 10", "trades",
                                 "Fewer costs but still lost 1.0% a year: the picks were no better than average"),
    "move_size_h10_k1": ("AI model: how big will the move be?", "Predict which stocks move a lot in 2 weeks", "predictions",
                         "The AI had no skill (0.503), but plain GARCH did (0.573) — so GARCH is used instead"),
    "vrp_condor_NIFTY": ("NIFTY iron condor when options are expensive", "Sell a monthly NIFTY condor when implied vol beats the forecast",
                         "trades", "Only 19 trades in 5 years: too few to prove anything"),
    "vrp_condor_BANKNIFTY": ("BANKNIFTY iron condor when options are expensive", "Same on BANKNIFTY", "trades",
                             "Only 15 trades in 5 years: too few"),
    "vrp_condor_NIFTY_books4": ("NIFTY condor, a new one every week", "4 overlapping monthly condors for more trades", "trades",
                                "Part of the pooled test below"),
    "vrp_condor_BANKNIFTY_books4": ("BANKNIFTY condor, a new one every week", "Same on BANKNIFTY", "trades",
                                    "Part of the pooled test below"),
    "pooled: vrp_condor_NIFTY_books4 + vrp_condor_BANKNIFTY_books4": (
        "Index condors, NIFTY + BANKNIFTY together", "The best-looking idea: +12.7% of risk per trade on 2021–26", "trades",
        "Looked strong on 2021–26 but just missed the bar; then failed on 2015–21 (below)"),
    "vrp_condor_pooled_holdout": ("Index condors on years they never saw (2015–21)", "The decisive test of the idea above",
                                  "trades", "Lost 5.6% of risk per trade: the 2021–26 result did not hold"),
    "quiet_stock_condor_garch": ("Condors on the 5 calmest stocks", "Sell condors where GARCH expects the least movement",
                                 "trades", "Lost money (Sharpe −0.44); stock options cost too much to trade"),
    "chronos_bolt_vol_chronos": ("Amazon Chronos AI forecast (raw)", "A free pretrained AI model vs GARCH for volatility",
                                 "forecasts", "Worse than GARCH (score 0.449 vs 0.336)"),
    "chronos_bolt_vol_chronos_cal": ("Amazon Chronos AI forecast (adjusted)", "Same, scaled using its own past errors",
                                     "forecasts", "Still worse than GARCH (0.382 vs 0.336)"),
    "results_iron_fly": ("Sell options before company results", "Iron butterfly the day before results, close the day after",
                         "trades", "Option prices do drop after results, but trading costs were bigger: −6.5% per trade"),
    "results_iron_fly_overpriced": ("Same, only when options look overpriced", "Trade only when options price an unusually big move",
                                    "trades", "Better (−4.7%) but still losing after costs"),
}


# ---------------------------------------------------------------- risk & volatility

NIGHTLY = (19, 30)          # the nightly job (Windows task) downloads the day's NSE end-of-day files then
NIGHTLY_DONE = (22, 0)      # by when that day's data should be in (the job takes 10-90 min)


def freshness(as_of: date | str | None, now: datetime | None = None, calendar=None) -> dict:
    """How current a piece of end-of-day data is: the session it covers, the latest session it could cover by now,
    whether it is behind (the nightly job missed a day) and when the next update is due."""
    if calendar is None:
        from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
        calendar = NSECalendar.from_nse()
    now = now or datetime.now()
    today = now.date()
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of[:10])
    done_today = calendar.is_trading_day(today) and (now.hour, now.minute) >= NIGHTLY_DONE
    expected = today if done_today else calendar.previous_session(today)
    if calendar.is_trading_day(today) and (now.hour, now.minute) < NIGHTLY:
        nxt = datetime.combine(today, datetime.min.time()).replace(hour=NIGHTLY[0], minute=NIGHTLY[1])
    else:
        d = today + timedelta(days=1)
        while not calendar.is_trading_day(d):
            d += timedelta(days=1)
        nxt = datetime.combine(d, datetime.min.time()).replace(hour=NIGHTLY[0], minute=NIGHTLY[1])
    stale = as_of is None or as_of < expected
    return {"as_of": str(as_of) if as_of else None, "as_of_label": f"{as_of:%a %d %b}" if as_of else None,
            "expected": str(expected), "stale": stale,
            "next_update": f"{'today' if nxt.date() == today else f'{nxt:%a %d %b}'} {nxt:%I:%M %p}".replace(" 0", " "),
            "today_is_session": calendar.is_trading_day(today)}


def _fresh(as_of) -> dict | None:
    try:
        return freshness(as_of)
    except Exception:                                  # no calendar (offline): the page just skips the line
        return None


RISK_TTL = 60   # built from end-of-day files that change once a night; a minute avoids re-reading them per request


def risk(symbol: str, on: date | None = None, root: Path | None = None) -> dict:
    from webapp import market_data as md

    on = on or date.today()
    return md._cache.get(("risk", symbol.upper(), on, str(root)), RISK_TTL, lambda: _risk(symbol, on, root))


def _risk(symbol: str, on: date, root: Path | None) -> dict:
    from tradingagents.analytics.quant_report import quant_signal_data

    out = quant_signal_data(_TICKER.get(symbol.upper(), symbol.upper()), on, root=root)
    as_of = next((x.get("as_of") for x in (out.get("vol"), out.get("regime"), out.get("iv")) if x and x.get("as_of")), None)
    return out | {"freshness": _fresh(as_of)}


# ---------------------------------------------------------------- measured spreads

def spreads(symbol: str, root: Path | None = None, strikes_each_side: int = 6) -> dict:
    """The latest captured closing bid/ask around the money, nearest monthly-or-weekly expiry first."""
    from tradingagents.analytics import quotes as qt
    from tradingagents.analytics.costs import DEFAULT_SLIPPAGE as slip

    base = qt.quotes_root(root)
    sym = symbol.upper()
    days = sorted((d for d in base.glob("*") if d.is_dir() and any(d.glob(f"{sym}_*.json"))), reverse=True)
    if not days:
        return {"symbol": sym, "available": False,
                "message": "No option quotes captured for this symbol yet (captured nightly for the 29 stocks, NIFTY and BANKNIFTY)."}
    files = sorted(days[0].glob(f"{sym}_*.json"))
    expiries = []
    for f in files:
        q = qt.parse(json.loads(f.read_text(encoding="utf-8")), sym)
        if q.empty:
            continue
        spot = float(q["underlying"].dropna().iloc[0]) if q["underlying"].notna().any() else None
        strikes = sorted(q["strike"].unique())
        if spot:
            atm = min(strikes, key=lambda k: abs(k - spot))
            i = strikes.index(atm)
            keep = set(strikes[max(0, i - strikes_each_side): i + strikes_each_side + 1])
            q = q[q["strike"].isin(keep)]
        else:
            atm = None
        q = q.assign(spread_pct=(q["ask"] - q["bid"]) / q["mid"],
                     model=slip.option_ticks * slip.option_tick_size + slip.option_premium_pct * q["mid"])
        rows = []
        for k, g in q.groupby("strike"):
            row = {"strike": float(k)}
            for _, r in g.iterrows():
                side = "ce" if r["option_type"] == "CE" else "pe"
                row[side] = {"bid": float(r["bid"]), "ask": float(r["ask"]), "spread_pct": float(r["spread_pct"])}
            rows.append(row)
        expiries.append({"expiry": str(q["expiry"].iloc[0]), "spot": spot, "atm": atm,
                         "real_vs_model": float((q["half_spread"] / q["model"]).median()),
                         "median_spread_pct": float(q["spread_pct"].median()), "rows": rows})
    return {"symbol": sym, "available": bool(expiries), "snapshot": days[0].name, "expiries": expiries,
            "freshness": _fresh(days[0].name)}


# ---------------------------------------------------------------- research results

def research(trial_path: Path | None = None, status_file: Path | None = None) -> dict:
    from tradingagents.analytics import trial_log
    from tradingagents.analytics.datastore import store_root
    from tradingagents.analytics.quant_report import BASELINE_IDEAS, VERDICT_TEXT

    latest = {}
    try:
        for t in trial_log.load(path=trial_path):
            latest[t.idea] = t
    except Exception:
        latest = {}
    tested = []
    for idea, t in sorted(latest.items()):
        if idea in BASELINE_IDEAS:
            continue
        verdict = (f"gates {t.gate_verdict}" if t.gate_verdict
                   else VERDICT_TEXT.get(t.verdict, t.verdict or "not judged"))
        passed = t.gate_verdict == "approved" or t.verdict in ("pass", "keep")
        name, what, unit, result = IDEA_INFO.get(idea, (idea.replace("_", " "), "", "trades", ""))
        tested.append({"idea": idea, "name": name, "what": what, "unit": unit, "result": result,
                       "verdict": verdict, "passed": passed, "trades": t.n_oos_trades,
                       "sharpe": None if t.oos_sharpe is None or t.oos_sharpe != t.oos_sharpe else t.oos_sharpe,
                       "when": (t.run_at or "")[:10], "notes": t.notes or ""})
    order = list(IDEA_INFO)
    tested.sort(key=lambda x: (order.index(x["idea"]) if x["idea"] in order else len(order), x["idea"]))
    status_file = status_file or store_root().parent / "daily_status.json"
    daily = None
    if status_file.exists():
        try:
            daily = json.loads(status_file.read_text(encoding="utf-8"))
        except ValueError:
            daily = None
    covered = None                                     # the session the last nightly run brought in
    if daily and daily.get("finished"):
        fin = datetime.fromisoformat(daily["finished"])
        covered = fin.date() if (fin.hour, fin.minute) >= (15, 30) else fin.date() - timedelta(days=1)
    return {"in_use": IN_USE, "tested": tested, "paper": _paper(), "daily_job": daily,
            "approved": [x["idea"] for x in tested if x["verdict"] == "gates approved"],
            "freshness": _fresh(covered) if daily else None}


def _paper() -> list[dict]:
    try:
        from tradingagents.analytics import paper
        from tradingagents.analytics.paper_strategies import STRATEGIES
    except Exception:
        return []
    out = []
    for s in STRATEGIES:
        try:
            r = paper.report(s)
            out.append({"name": s.name, "status": s.status, "note": s.note, "start": str(s.start),
                        "open": r.open_trades, "closed": r.n, "summary": r.summary()})
        except Exception as exc:          # a missing ledger must not break the page
            out.append({"name": s.name, "status": s.status, "note": s.note, "start": str(s.start), "error": str(exc)})
    return out


# ---------------------------------------------------------------- trade journal

def journal_files() -> list[dict]:
    if not JOURNAL_DIR.exists():
        return []
    files = [f for f in JOURNAL_DIR.iterdir() if f.suffix.lower() in JOURNAL_TYPES]
    return [{"name": f.name, "size": f.stat().st_size} for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)]


def safe_name(name: str) -> str:
    """A plain file name inside the journal folder (no paths), with an allowed extension."""
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip() or "tradebook.csv"
    if Path(base).suffix.lower() not in JOURNAL_TYPES:
        raise ValueError("Upload a .csv, .xlsx or .xls file exported from Dhan.")
    return base


def save_upload(name: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD:
        raise ValueError("File is larger than 10 MB.")
    base = safe_name(name)
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    (JOURNAL_DIR / base).write_bytes(data)
    return base


def _table(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for group, r in df.iterrows():
        row = {"group": str(group)}
        for k, v in r.items():
            row[k] = None if pd.isna(v) else (float(v) if v != float("inf") else None)
        out.append(row)
    return out


def journal(name: str, horizon: str = "all") -> dict:
    from tradingagents.analytics import journal as jr

    path = JOURNAL_DIR / safe_name(name)
    if not path.exists():
        raise ValueError(f"{path.name} is not in reports/journal/.")
    trades = jr.read_tradebook(path)
    trips, still_open = jr.round_trips(trades)
    horizons = {"all": "all", "intraday": jr.HORIZONS[0], "week": jr.HORIZONS[1], "month": jr.HORIZONS[2],
                "long": jr.HORIZONS[3]}
    chosen = jr.filter_horizon(trips, horizons.get(horizon, "all"))
    for t in chosen:
        t.entry_hour = f"{t.open_time.hour:02d}:00" if t.open_time.hour or t.open_time.minute else "no time"
        t.weekday = t.open_time.strftime("%a")
        t.tag = t.reason or "(no tag)"
    charges_from_file = "charges" in trades and trades["charges"].notna().any()
    return {
        "file": path.name, "trades": len(trades), "round_trips": len(trips), "still_open": len(still_open),
        "from": f"{trades['datetime'].min():%Y-%m-%d}", "to": f"{trades['datetime'].max():%Y-%m-%d}",
        "charges": "from the file" if charges_from_file else "estimated (Dhan ₹20/order + taxes)",
        "horizon": horizon, "selected": len(chosen),
        "sections": {
            "By holding period": _table(jr.summarize(trips, "horizon")),
            "Overall": _table(jr.summarize(chosen)),
            "By style": _table(jr.summarize(chosen, "style")),
            "By instrument": _table(jr.summarize(chosen, "kind")),
            "By underlying": _table(jr.summarize(chosen, "underlying")),
            "By hour of entry": _table(jr.summarize(chosen, "entry_hour").sort_index() if chosen else None),
            "By day of week": _table(jr.summarize(chosen, "weekday")),
            "By your reason": _table(jr.summarize(chosen, "tag")) if any(t.reason for t in chosen) else [],
        },
    }

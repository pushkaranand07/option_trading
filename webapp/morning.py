"""The morning plan: built before the open (8:30 AM on trading days) for NIFTY and BANKNIFTY.

What it holds, per index: the session's times, the trend and key levels from past sessions, the market regime and
the expected move (validated), implied vol vs forecast, OI / PCR and FII positioning from NSE's files, and the AI
agents' view (news, sentiment, the bull/bear debate). It does **not** decide a trade before the open: the web app's
history-checked rule decides live, after 9:45 AM, and the Plan tab sizes that trade from the user's own capital and
risk limit (kept in the browser on this PC).

Plans are saved in ``reports/morning/<date>.json`` (gitignored).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "reports" / "morning"
INDICES = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
PRE_OPEN, OPEN, CLOSE = time(9, 0), time(9, 15), time(15, 30)
FIRST_SIGNAL = time(9, 45)                 # the live rule waits for the first half hour
# SEBI circular of 2026-10-15 (closing auction session): index derivatives trade until 15:45 from this date.
INDEX_DERIVATIVES_LATE_CLOSE_FROM = date(2026, 12, 7)
INDEX_DERIVATIVES_LATE_CLOSE = time(15, 45)


def session(day: date, calendar=None) -> dict:
    """Is ``day`` a session, and its times (IST)."""
    if calendar is None:
        from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
        calendar = NSECalendar.from_nse()
    trading = calendar.is_trading_day(day)
    muhurat = day in getattr(calendar, "muhurat_days", set())
    deriv_close = INDEX_DERIVATIVES_LATE_CLOSE if day >= INDEX_DERIVATIVES_LATE_CLOSE_FROM else CLOSE
    next_day = day + timedelta(days=1)
    while not calendar.is_trading_day(next_day):
        next_day += timedelta(days=1)
    return {
        "date": str(day), "weekday": day.strftime("%A"), "trading": trading and not muhurat,
        "muhurat": muhurat, "holiday": calendar.holidays.get(day), "next_session": str(next_day),
        "pre_open": "09:00", "open": OPEN.strftime("%H:%M"), "first_signal": FIRST_SIGNAL.strftime("%H:%M"),
        "close": CLOSE.strftime("%H:%M"), "index_derivatives_close": deriv_close.strftime("%H:%M"),
    }


def _store_context(symbol: str, day: date) -> dict:
    """OI / PCR and FII positioning known before ``day`` opens (NSE files of earlier sessions)."""
    from tradingagents.analytics import datastore as ds

    out = {}
    try:
        fo = ds.load("fo_summary", symbols=[symbol], start=day - timedelta(days=20))
        fo = fo[fo["trade_date"].astype(str) < str(day)].sort_values("trade_date")
        if len(fo):
            last = fo.iloc[-1]
            out["pcr"] = {"as_of": str(last["trade_date"]), "value": float(last["pcr_oi"]),
                          "prev": float(fo.iloc[-2]["pcr_oi"]) if len(fo) > 1 else None}
    except Exception as exc:                      # the store may be missing on a new machine
        logger.warning("PCR unavailable: %s", exc)
    try:
        p = ds.load("participant", start=day - timedelta(days=20))
        p = p[(p["category"] == "FII") & (p["trade_date"].astype(str) < str(day))].sort_values("trade_date")
        if len(p):
            share = (p["fut_idx_long"] / (p["fut_idx_long"] + p["fut_idx_short"])).astype(float)
            out["fii_long_share"] = {"as_of": str(p.iloc[-1]["trade_date"]), "value": float(share.iloc[-1]),
                                     "week_ago": float(share.iloc[-6]) if len(share) > 5 else None}
    except Exception as exc:
        logger.warning("FII positioning unavailable: %s", exc)
    return out


def context(symbol: str, day: date) -> dict:
    """Trend, levels, regime, expected move, IV, OI / PCR, FII positioning for one index."""
    from webapp import planner, quant

    out = {"symbol": symbol}
    try:
        p = planner.plan(symbol)
        m = p["mood"]
        last = m["recent"][0] if m.get("recent") else {}
        out["trend"] = {"label": m["label"], "tone": m["tone"], "explain": m["explain"], "returns": m["returns"],
                        "averages": m["averages"], "pos_52w": m["pos_52w"], "low_52w": m["low_52w"],
                        "high_52w": m["high_52w"], "daily_move": m["daily_move"]}
        out["last_session"] = last
    except Exception as exc:
        out["trend_error"] = str(exc)[:300]
    r = quant.risk(symbol, on=day)
    out["regime"], out["iv"] = r.get("regime"), r.get("iv")
    em = r.get("expected_move")
    if em and r.get("vol"):
        one_day = r["vol"]["h5"]["garch"] * np.sqrt(1 / 252)
        close = em["close"]
        out["expected_move"] = {"close": close, "day_pct": float(one_day),
                                "day_low": close * (1 - one_day) if close else None,
                                "day_high": close * (1 + one_day) if close else None,
                                "week_pct": em["h5"]["pct"]}
    out.update(_store_context(symbol, day))
    return out


def ai_view(ticker: str, day: date) -> dict:
    """The full multi-agent analysis for ``day`` (data as of the previous close, overnight news)."""
    from tradingagents.agents.rating import run_rating
    from tradingagents.default_config import build_default_config
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    started = datetime.now()
    state, _ = TradingAgentsGraph(config=build_default_config()).propagate(ticker, str(day))
    return {"rating": run_rating(state), "minutes": round((datetime.now() - started).seconds / 60, 1),
            "decision": state.get("final_trade_decision", ""), "news": state.get("news_report", ""),
            "market": state.get("market_report", ""), "plan": state.get("investment_plan", "")}


def build(day: date | None = None, with_ai: bool = True, calendar=None, keep_ai: bool = True) -> dict:
    day = day or date.today()
    plan = {"built_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "session": session(day, calendar), "indices": {}}
    old = load(day) if keep_ai else None
    with ThreadPoolExecutor(len(INDICES)) as pool:              # the indices' data is independent
        contexts = dict(zip(INDICES, pool.map(lambda s: context(s, day), INDICES), strict=True))
    for symbol, ticker in INDICES.items():
        entry = {"context": contexts[symbol], "ai": None}
        if with_ai and plan["session"]["trading"]:
            try:
                entry["ai"] = ai_view(ticker, day)
            except Exception as exc:
                entry["ai"] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        elif old and old.get("indices", {}).get(symbol, {}).get("ai"):
            entry["ai"] = old["indices"][symbol]["ai"]          # a rules-only refresh keeps the morning's AI view
        plan["indices"][symbol] = entry
    save(plan, day)
    return plan


_ai_job = {"running": False, "started": None, "error": None}


def start_ai_build() -> dict:
    """Rebuild today's plan with the AI view in a background thread (~20 min); one at a time."""
    import threading

    if _ai_job["running"]:
        return dict(_ai_job)
    _ai_job.update(running=True, started=datetime.now().strftime("%H:%M"), error=None)

    def run():
        try:
            build(with_ai=True)
        except Exception as exc:
            _ai_job["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            _ai_job["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return dict(_ai_job)


def ai_status() -> dict:
    return dict(_ai_job)


def path_for(day: date) -> Path:
    return PLAN_DIR / f"{day:%Y-%m-%d}.json"


def save(plan: dict, day: date) -> None:
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path_for(day).with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path_for(day))


def load(day: date | None = None) -> dict | None:
    f = path_for(day or date.today())
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

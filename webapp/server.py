"""Pulse Trader: market data, risk, options, AI analysis and research results, one tab each, in plain English.

Run from the repository root:
    python -m uvicorn webapp.server:app --port 8000
then open http://localhost:8000
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from fastapi import Body, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from webapp import (  # noqa: E402
    ai,
    ai_test,
    build_info,
    latency,
    market_data as md,
    morning,
    option_chain as nse_oc,
    planner,
    quant,
    signals,
    strategist,
    trade_record,
)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Pulse Trader")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
md.start_refresh_ahead()
logger = logging.getLogger(__name__)


@app.middleware("http")
async def time_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    if route is not None and request.url.path.startswith("/api/"):
        latency.observe(f"api {request.method} {route.path}", time.perf_counter() - started)
    return response


# ---------- who may talk to the server (audit H2: DNS rebinding and CSRF) ----------
# The server is for this computer's browser only. A page on another site can make the browser send requests here
# (a form post, or DNS rebinding where attacker.example resolves to 127.0.0.1), so:
#   * only Host 127.0.0.1 / localhost is served (anything else: 400, from TrustedHostMiddleware below);
#   * a request that can change something (not GET / HEAD / OPTIONS) needs the header X-Pulse-Request: 1, which a
#     cross-site form cannot set and a cross-site fetch cannot send without a CORS preflight this server never
#     answers; and when the browser names an Origin (or, without one, a Referer), it must be this computer's.

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
REQUEST_HEADER = "X-Pulse-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost)(:\d{1,5})?")


def local_origin(value: str) -> bool:
    """Is an Origin / Referer value this computer's page (http://127.0.0.1 or http://localhost, any port)?"""
    parts = urlsplit(value)
    return bool(parts.scheme and parts.netloc) and _LOCAL_ORIGIN.fullmatch(f"{parts.scheme}://{parts.netloc}") is not None


def _forbidden(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    if request.method not in SAFE_METHODS:
        if request.headers.get(REQUEST_HEADER) != "1":
            return _forbidden(f"Refused: a request that changes something must carry the header {REQUEST_HEADER}: 1.")
        source = request.headers.get("origin") or request.headers.get("referer")
        if source is not None and not local_origin(source):
            return _forbidden("Refused: this request came from another site.")
    return await call_next(request)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)      # added last, so it runs first


async def _call(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/")
def index():
    """The page, with its script and styles named by their current version (the files' modified time), and itself
    never cached: after an update the browser loads the new app.js instead of running a cached one."""
    from fastapi.responses import HTMLResponse

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        html = html.replace(f'/static/{name}"', f'/static/{name}?v={int((STATIC / name).stat().st_mtime)}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/status")
def status():
    return {
        "dhan": md.dhan.enabled,
        "azure": ai.azure_problem() is None,
        "azure_problem": ai.azure_problem(),
        "market_open": signals.market_open(),
        "muhurat": signals.muhurat_today(),
        "calendar_warning": ("NSE's holiday list could not be loaded and none is saved: only weekends count as closed, "
                             "so a market holiday would show as open." if signals.nse_calendar().source == "weekends only" else None),
        "v2": ai_test.today_status(),
        "code": build_info.status(),
        "indices": [{"symbol": k, "name": v[0]} for k, v in md.INDICES.items()],
    }


def v2_startup_check() -> str | None:
    """At startup: does the code still match the frozen v2 test? A mismatch is logged and shown on every page."""
    why = ai_test.fingerprint_problem()
    if why:
        logger.error("v2 forward test: %s", why)
    return why


@app.get("/api/latency")
def latency_report():
    """p50 / p95 / p99 per API route and per data fetch, over the last requests since the server started."""
    return latency.report()


@app.get("/api/search")
async def search(q: str):
    return await _call(md.search, q)


@app.get("/api/quotes")
async def quotes(symbols: str):
    return await _call(md.quotes, [s for s in symbols.split(",") if s][:30])


@app.get("/api/candles/{symbol}")
async def candles(symbol: str, tf: str = "5m", limit: int = 1500):
    df, source = await _call(md.candles, symbol, tf)
    open_now = signals.market_open()
    age, stale = md.bar_age(df), md.stale_bars(df, tf, open_now)
    df = df.iloc[-limit:]
    bars = [{"time": int(ts.timestamp()), "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "volume": r.volume} for ts, r in zip(df.index, df.itertuples(), strict=True)]
    return {"symbol": symbol.upper(), "tf": tf, "source": source, "bars": bars,
            "data": {"last_bar_age_s": round(age) if age is not None else None, "stale": stale is not None,
                     "live": open_now and source in ("dhan", "yahoo") and stale is None}}


@app.get("/api/plan/{symbol}")
async def plan(symbol: str):
    return await _call(planner.plan, symbol)


@app.get("/api/optionchain/{symbol}")
async def option_chain(symbol: str, expiry: str | None = None):
    chain = await _call(md.option_chain, symbol, expiry)
    chain["view"] = signals.option_view(chain["rows"], chain["spot"])
    return chain


@app.get("/api/expiries/{symbol}")
async def expiries(symbol: str):
    return await _call(md.expiries, symbol)


class AIRequest(BaseModel):
    symbol: str
    analysts: list[str] = ["market", "news", "social", "fundamentals"]


@app.post("/api/ai")
def ai_start(req: AIRequest):
    if problem := ai.azure_problem():
        raise HTTPException(400, problem)
    inst = md.instrument(req.symbol)
    return {"job": ai.start(inst["symbol"], inst["yahoo"], req.analysts)}


@app.get("/api/ai/{job_id}")
def ai_status(job_id: str):
    job = ai.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


# ---------- morning plan ----------

@app.get("/api/morning")
async def morning_plan(date: str | None = None):
    """Today's plan (built at 8:30 AM by the scheduled job); built on the spot, without AI, if missing.
    ``date`` (YYYY-MM-DD) returns that day's saved plan, for the page's preview mode."""
    if date:
        from datetime import date as _date
        try:
            saved = morning.load(_date.fromisoformat(date))
        except ValueError as exc:
            raise HTTPException(400, "date must be YYYY-MM-DD") from exc
        if saved is None:
            raise HTTPException(404, f"No saved plan for {date}")
        return saved | {"ai_job": morning.ai_status()}
    plan = morning.load()
    if plan is None:
        plan = await _call(morning.build, None, False)
    plan["ai_job"] = morning.ai_status()
    return plan


@app.get("/api/morning/context/{symbol}")
async def morning_context(symbol: str):
    """The morning view for any instrument, built now (the 8:30 job covers NIFTY and BANKNIFTY, with AI)."""
    from datetime import date as _date
    return {"context": await _call(morning.context, md.instrument(symbol)["symbol"], _date.today()), "ai": None}


@app.post("/api/morning/refresh")
async def morning_refresh():
    """Rebuild the data part now (seconds); the morning's AI view is kept."""
    plan = await _call(morning.build, None, False)
    plan["ai_job"] = morning.ai_status()
    return plan


@app.post("/api/morning/ai")
def morning_ai():
    if problem := ai.azure_problem():
        raise HTTPException(400, problem)
    return morning.start_ai_build()


# ---------- AI strategist (Plan tab): NSE option chain + one defined-risk strategy, priced per lot ----------

@app.get("/api/chain/{symbol}")
async def nse_chain(symbol: str, expiry: str | None = None):
    try:
        return await run_in_threadpool(nse_oc.chain, md.instrument(symbol)["symbol"], expiry)
    except nse_oc.ChainError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/contract")
async def nse_contract(id: str):
    """One option's intraday premium (NSE ticks), high, low and previous close."""
    try:
        return await run_in_threadpool(nse_oc.contract, id)
    except nse_oc.ChainError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/rank/{symbol}")
async def trade_rank(symbol: str, expiry: str | None = None):
    """Pulse's ranked trades for the instrument: strikes, entry, target and stop for each, best first (no LLM)."""
    try:
        return await run_in_threadpool(strategist.rank, md.instrument(symbol)["symbol"], expiry)
    except nse_oc.ChainError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


class StrategyRequest(BaseModel):
    symbol: str
    expiry: str | None = None
    mode: Literal["full", "quick"] = "full"


@app.post("/api/strategy")
def strategy_start(req: StrategyRequest):
    if problem := ai.azure_problem():
        raise HTTPException(400, problem)
    sym = md.instrument(req.symbol)["symbol"]
    try:
        return {"job": strategist.start(sym, req.expiry, req.mode)}
    except strategist.NoResearch as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/strategy/research/{symbol}")
def strategy_research(symbol: str):
    """Whether today's research exists for a Quick analysis: when, from where, and the agents' call."""
    r = strategist.today_research(md.instrument(symbol)["symbol"]) or {}
    return {k: r.get(k) for k in ("source", "at", "rating", "minutes")} if r else {}


@app.get("/api/strategy/latest/{symbol}")
def strategy_latest(symbol: str):
    """The last AI run for the instrument, fixed until the next run (an empty object if none). ``expired``: it is
    from another day (or older than run ids), so it is shown read-only."""
    run = strategist.latest_run(md.instrument(symbol)["symbol"])
    return run | {"expired": strategist.run_expired(run)} if run else {}


@app.get("/api/strategy/{job_id}")
def strategy_status(job_id: str):
    job = strategist.job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


# ---------- quant layer: risk, spreads, research, market map, trade journal ----------

@app.get("/api/risk/{symbol}")
async def risk(symbol: str):
    return await _call(quant.risk, symbol)


@app.get("/api/spreads/{symbol}")
async def spreads(symbol: str):
    return await _call(quant.spreads, symbol)


@app.get("/api/research")
async def research():
    return await _call(quant.research)


@app.get("/market-map")
def market_map():
    if not quant.MARKET_MAP.exists():
        raise HTTPException(404, "The Market Map has not been built yet: run python scripts/market_map.py")
    return FileResponse(quant.MARKET_MAP)


@app.get("/api/journal/files")
def journal_files():
    return quant.journal_files()


# The page sends the file's bytes as application/octet-stream; text/csv and the .xlsx type are accepted too. Anything
# else (text/plain, a form) is what a cross-site form can send without a preflight, so it is refused (audit M2).
UPLOAD_TYPES = ("application/octet-stream", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/journal/upload")
async def journal_upload(request: Request, name: str):
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in UPLOAD_TYPES:
        raise HTTPException(415, f"Send the file with Content-Type {UPLOAD_TYPES[0]} (or text/csv / the .xlsx type).")
    try:
        return {"name": quant.save_upload(name, await request.body())}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- Trade Record: dummy trades taken from the AI strategist ----------

trade_record.start_monitor()


@app.get("/api/trades")
async def trades():
    return await _call(trade_record.overview)


@app.get("/api/trades.csv")
def trades_csv():
    """Every trade of both views with where it came from (download)."""
    from datetime import date as _date

    from fastapi.responses import Response

    return Response(trade_record.history_csv(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="trade_history_{_date.today()}.csv"'})


@app.post("/api/trades")
def trade_take(body: dict = Body(...)):
    """Take trade ``candidate`` of AI run ``run_id`` as a dummy one-lot trade, priced by the server from a fresh
    chain now. Any price in the body is ignored."""
    try:
        run_id, candidate = str(body.get("run_id") or ""), int(body.get("candidate"))
        return trade_record.take_from_run(run_id, candidate, confirm=bool(body.get("confirm")))
    except trade_record.BetExists as exc:                                  # ask first; nothing written
        raise HTTPException(409, {"message": str(exc), **exc.details}) from exc
    except trade_record.TradeError as exc:
        trade_record.record_refused(run_id, candidate, exc, "you")       # kept under My picks, outside the stats
        raise HTTPException(400, f"Not taken: {exc}") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Not taken: {exc}") from exc


@app.post("/api/trades/{trade_id}/close")
async def trade_close(trade_id: str):
    try:
        return await run_in_threadpool(trade_record.close, trade_id)
    except trade_record.TradeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/trades/{trade_id}")
def trade_delete(trade_id: str):
    try:
        trade_record.delete(trade_id)
    except trade_record.TradeError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/journal")
async def journal(name: str, horizon: str = "all"):
    try:
        return await run_in_threadpool(quant.journal, name, horizon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


v2_startup_check()          # a mismatch is logged at startup and shown on every page (never auto-updated)

"""Pulse Trader: market data, risk, options, AI analysis and research results, one tab each, in plain English.

Run from the repository root:
    python -m uvicorn webapp.server:app --port 8000
then open http://localhost:8000
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import requests

# The package loads the repo's own .env (ROOT/.env, never a parent's; nothing under pytest or with
# TRADINGAGENTS_NO_DOTENV=1, audit H4) when imported; import it first so the keys are there for the modules below.
import tradingagents  # noqa: F401,I001

ROOT = Path(__file__).resolve().parent.parent

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
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
    timeutil,
    trade_record,
)

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start-up work, run when the server starts (not when the module is imported, so tests and scripts that import
    it start no threads): the refresh-ahead thread, the trade monitor, and the v2 fingerprint check.

    On shutdown it calls the stop hooks ``market_data.stop_refresh_ahead`` / ``trade_record.stop_monitor`` when those
    modules have them (other tracks' files; neither has one yet). Without them nothing is left hanging: both threads
    are daemon threads, so they end with the process."""
    for name, start in (("refresh-ahead", lambda: md.start_refresh_ahead()),
                        ("trade monitor", lambda: trade_record.start_monitor()),
                        ("v2 startup check", lambda: v2_startup_check())):
        _step("Start-up", name, start)
    yield
    for name, module, hook in (("refresh-ahead", md, "stop_refresh_ahead"), ("trade monitor", trade_record, "stop_monitor")):
        if stop := getattr(module, hook, None):
            _step("Shutdown", name, stop)


def _step(phase: str, name: str, fn) -> None:
    try:
        fn()
    except Exception:                                 # one failed step must not keep the page down or hang shutdown
        logger.exception("%s step failed: %s", phase, name)


app = FastAPI(title="Pulse Trader", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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


# ---------- errors the page sees (audit L4) ----------
# Bad input: 400 / 422 with a message written here. Known not-found: 404. Upstream data errors (Yahoo, Dhan, NSE)
# carry messages the app wrote for the user, so they stay 502 with that message. Anything else is a bug: the page
# gets 500 {"detail": "Internal error", "error_id"} and the traceback is logged under that id, never sent.

def _upstream_errors() -> tuple[type[BaseException], ...]:
    """The domain errors the data routes reach, all with messages the app writes for the user: the web app's own
    (market_data.DataError, option_chain.ChainError), the package's vendor taxonomy (VendorError: NSE / Yahoo /
    Alpha Vantage failed, throttled, no data or not configured), HTTP clients (requests; curl_cffi, which yfinance
    uses), and the Dhan guard refusing a non-market-data call."""
    from tradingagents.dataflows.errors import VendorError
    from webapp import dhan_guard

    errors: list[type[BaseException]] = [md.DataError, nse_oc.ChainError, VendorError, requests.RequestException]
    try:
        from curl_cffi.requests.exceptions import RequestException as CurlRequestException
        errors.append(CurlRequestException)
    except ImportError:                               # yfinance without curl_cffi
        pass
    if blocked := getattr(dhan_guard, "DhanAccountAccessBlocked", None):
        errors.append(blocked)
    return tuple(errors)


UPSTREAM_ERRORS: tuple[type[BaseException], ...] = _upstream_errors()


def log_error(exc: BaseException) -> str:
    """Log the exception's traceback under a short new id, and return the id (what the page may show)."""
    error_id = uuid.uuid4().hex[:10]
    logger.error("Internal error %s: %s", error_id, type(exc).__name__, exc_info=(type(exc), exc, exc.__traceback__))
    return error_id


def internal_error(exc: BaseException) -> JSONResponse:
    return JSONResponse({"detail": "Internal error", "error_id": log_error(exc)}, status_code=500)


@app.middleware("http")
async def errors_have_an_id(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:                          # an unhandled exception in any endpoint
        return internal_error(exc)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)      # added last, so it runs first


async def _call(fn, *args):
    """Run a blocking data call off the event loop. An upstream data error is a 502 with its own (app-written)
    message; any other exception propagates and becomes a 500 with an error id."""
    try:
        return await run_in_threadpool(fn, *args)
    except UPSTREAM_ERRORS as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _symbol(symbol: str) -> str:
    """The instrument's canonical symbol, looked up off the event loop (md.instrument may parse the scrip master)."""
    return (await _call(md.instrument, symbol))["symbol"]


@app.get("/")
def index():
    """The page, with its script and styles named by their current version (the files' modified time), and itself
    never cached: after an update the browser loads the new app.js instead of running a cached one."""
    from fastapi.responses import HTMLResponse

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        html = html.replace(f'/static/{name}"', f'/static/{name}?v={int((STATIC / name).stat().st_mtime)}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


def _optional(module, name: str):
    """A function another track adds (``trade_record.store_problem`` / ``monitor_status``), or one answering None
    while this server runs code without it."""
    return getattr(module, name, None) or (lambda: None)


@app.get("/api/status")
def status():
    """Everything the page's banners need. Audit M4: each part is checked on its own, so one failing check (say, a
    server running code older than the files on disk) is listed under ``degraded`` instead of making this a 500."""
    degraded: list[dict] = []

    def part(name: str, check, fallback=None):
        try:
            return check()
        except Exception as exc:
            degraded.append({"part": name, "reason": f"could not be checked (error id {log_error(exc)}); "
                                                     "see the server log, or restart the server"})
            return fallback

    azure_problem = part("azure", ai.azure_problem, "The Azure settings could not be checked.")
    source = part("calendar", lambda: getattr(signals.nse_calendar(), "source", None), "unknown")
    if source == "weekends only":
        calendar_warning = ("NSE's holiday list could not be loaded and none is saved: only weekends count as closed, "
                            "so a market holiday would show as open.")
    elif source == "unknown":
        calendar_warning = "The NSE holiday calendar could not be checked: whether the market is open may be wrong."
    else:
        calendar_warning = None
    v2 = part("v2", ai_test.today_status, {"version": getattr(ai_test, "VERSION", None), "state": "ERROR",
                                           "reason": "today's v2 status could not be checked", "fingerprint_problem": None})
    if isinstance(v2, dict) and v2.get("state") == "ERROR" and not any(d["part"] == "v2" for d in degraded):
        degraded.append({"part": "v2", "reason": v2.get("reason") or "today's v2 status could not be checked"})
    return {
        "dhan": part("dhan", lambda: bool(md.dhan.enabled), False),
        "azure": azure_problem is None,
        "azure_problem": azure_problem,
        "market_open": part("market_open", signals.market_open),
        "muhurat": part("muhurat", signals.muhurat_today),
        "calendar_warning": calendar_warning,
        "v2": v2,
        "code": part("code", build_info.status),                           # running commit vs checkout, "stale"
        "store_problem": part("store_problem", _optional(trade_record, "store_problem")),
        "monitor": part("monitor", _optional(trade_record, "monitor_status")),
        "indices": [{"symbol": k, "name": v[0]} for k, v in md.INDICES.items()],
        "degraded": degraded,
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
async def candles(symbol: str, tf: str = "5m", limit: Annotated[int, Query(ge=1, le=5000)] = 1500):
    df, source = await _call(md.candles, symbol, tf)
    open_now = await run_in_threadpool(signals.market_open)            # reads the NSE calendar (may fetch it)
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


def known_expiry(symbol: str, expiry: str | None, listing) -> None:
    """Audit L1: an expiry asked for must be one of the symbol's, or 400 with the valid list (the chain code would
    otherwise answer for another expiry without saying so). Checked here, at the HTTP layer only: option_chain.chain
    stays lenient for the forward test. No expiry means the nearest, unchecked; with no ``listing`` (Track D's
    ``option_chain.valid_expiries`` not present) the route stays lenient as before."""
    if not expiry or listing is None:
        return
    valid = list(listing(symbol))
    if not valid:                                     # the sources answered nothing: not the user's mistake
        raise HTTPException(502, f"The expiry list for {symbol} is unavailable right now (expiry list unavailable): "
                                 "try again in a moment.")
    if expiry not in valid:
        raise HTTPException(400, {"message": f"{expiry} is not an expiry of {symbol}: pick one of {', '.join(valid) or 'none listed'}.",
                                  "valid_expiries": valid})


def _nse_expiries():
    return getattr(nse_oc, "valid_expiries", None)


@app.get("/api/optionchain/{symbol}")
async def option_chain(symbol: str, expiry: str | None = None):
    await _call(known_expiry, symbol, expiry, md.expiries)          # the Dhan chain: Dhan's own expiry list
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
            day = _date.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(400, "date must be YYYY-MM-DD") from exc
        saved = await run_in_threadpool(morning.load, day)
        if saved is None:
            raise HTTPException(404, f"No saved plan for {date}")
        return saved | {"ai_job": morning.ai_status()}
    plan = await run_in_threadpool(morning.load)
    if plan is None:
        plan = await _call(morning.build, None, False)
    plan["ai_job"] = morning.ai_status()
    return plan


@app.get("/api/morning/context/{symbol}")
async def morning_context(symbol: str):
    """The morning view for any instrument, built now (the 8:30 job covers NIFTY and BANKNIFTY, with AI)."""
    return {"context": await _call(morning.context, await _symbol(symbol), timeutil.today_ist()), "ai": None}


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
        sym = await _symbol(symbol)
        await run_in_threadpool(known_expiry, sym, expiry, _nse_expiries())
        return await run_in_threadpool(nse_oc.chain, sym, expiry)
    except nse_oc.ChainError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UPSTREAM_ERRORS as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/contract")
async def nse_contract(id: str):
    """One option's intraday premium (NSE ticks), high, low and previous close."""
    try:
        return await run_in_threadpool(nse_oc.contract, id)
    except nse_oc.ChainError as exc:
        raise HTTPException(400, str(exc)) from exc
    except UPSTREAM_ERRORS as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/rank/{symbol}")
async def trade_rank(symbol: str, expiry: str | None = None):
    """Pulse's ranked trades for the instrument: strikes, entry, target and stop for each, best first (no LLM)."""
    try:
        sym = await _symbol(symbol)
        await run_in_threadpool(known_expiry, sym, expiry, _nse_expiries())
        return await run_in_threadpool(strategist.rank, sym, expiry)
    except nse_oc.ChainError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UPSTREAM_ERRORS as exc:
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


async def _read_capped(request: Request, cap: int) -> bytes:
    """The request body, at most ``cap`` bytes (audit L2). No Content-Length, or one over the cap, is refused before
    a byte is read; while reading, a running total stops a body that is longer than its Content-Length said."""
    too_big = f"File is larger than {cap // (1024 * 1024)} MB." if cap >= 1024 * 1024 else f"File is larger than {cap} bytes."
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(413, "Upload refused: the file's size was not sent (Content-Length).")
    if int(length) > cap:
        raise HTTPException(413, too_big)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cap:
            raise HTTPException(413, too_big)
    return bytes(data)


@app.post("/api/journal/upload")
async def journal_upload(request: Request, name: str):
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in UPLOAD_TYPES:
        raise HTTPException(415, f"Send the file with Content-Type {UPLOAD_TYPES[0]} (or text/csv / the .xlsx type).")
    data = await _read_capped(request, quant.MAX_UPLOAD)
    try:
        return {"name": await run_in_threadpool(quant.save_upload, name, data)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ---------- Trade Record: dummy trades taken from the AI strategist (the monitor starts in the lifespan) ----------


@app.get("/api/trades")
async def trades():
    return await _call(trade_record.overview)


@app.get("/api/trades.csv")
def trades_csv():
    """Every trade of both views with where it came from (download)."""
    from fastapi.responses import Response

    return Response(trade_record.history_csv(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="trade_history_{timeutil.today_ist()}.csv"'})


class _NoStoreCorrupt(Exception):
    """Stands in for trade_record.StoreCorrupt while the loaded trade_record has none (never raised)."""


def _store_corrupt() -> type[Exception]:
    return getattr(trade_record, "StoreCorrupt", None) or _NoStoreCorrupt


def _store_unavailable(exc: Exception) -> HTTPException:
    """Track A raises StoreCorrupt on a write when the trade store can't be read: nothing is saved until it is fixed."""
    return HTTPException(503, f"The trade record can't be saved right now: {exc}")


class TakeRequest(BaseModel):
    """The page sends only which trade of which run; any other field (a price, say) is ignored."""
    run_id: str
    candidate: int = Field(ge=0, strict=True)          # strict: true / 1.5 / "1" are refused, not coerced
    confirm: bool = Field(default=False, strict=True)


@app.post("/api/trades")
def trade_take(req: TakeRequest):
    """Take trade ``candidate`` of AI run ``run_id`` as a dummy one-lot trade, priced by the server from a fresh
    chain now. Any price in the body is ignored."""
    run_id, candidate = req.run_id, req.candidate
    try:
        try:
            return trade_record.take_from_run(run_id, candidate, confirm=req.confirm)
        except _store_corrupt():
            raise
        except trade_record.BetExists as exc:                              # ask first; nothing written
            raise HTTPException(409, {"message": str(exc), **exc.details}) from exc
        except trade_record.TradeError as exc:
            trade_record.record_refused(run_id, candidate, exc, "you")   # kept under My picks, outside the stats
            raise HTTPException(400, f"Not taken: {exc}") from exc
    except _store_corrupt() as exc:
        raise _store_unavailable(exc) from exc


@app.post("/api/trades/{trade_id}/close")
async def trade_close(trade_id: str):
    try:
        return await run_in_threadpool(trade_record.close, trade_id)
    except _store_corrupt() as exc:
        raise _store_unavailable(exc) from exc
    except trade_record.TradeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/trades/{trade_id}")
def trade_delete(trade_id: str):
    try:
        trade_record.delete(trade_id)
    except _store_corrupt() as exc:
        raise _store_unavailable(exc) from exc
    except trade_record.TradeError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.get("/api/journal")
async def journal(name: str, horizon: str = "all"):
    try:
        return await run_in_threadpool(quant.journal, name, horizon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

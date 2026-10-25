"""Pulse Trader: market data, risk, options, AI analysis and research results, one tab each, in plain English.

Run from the repository root:
    python -m uvicorn webapp.server:app --port 8000
then open http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from webapp import (  # noqa: E402
    ai,
    market_data as md,
    morning,
    option_chain as nse_oc,
    planner,
    quant,
    signals,
    strategist,
)

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Pulse Trader")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


async def _call(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {
        "dhan": md.dhan.enabled,
        "azure": ai.azure_problem() is None,
        "azure_problem": ai.azure_problem(),
        "market_open": signals.market_open(),
        "indices": [{"symbol": k, "name": v[0]} for k, v in md.INDICES.items()],
    }


@app.get("/api/search")
async def search(q: str):
    return await _call(md.search, q)


@app.get("/api/quotes")
async def quotes(symbols: str):
    return await _call(md.quotes, [s for s in symbols.split(",") if s][:30])


@app.get("/api/candles/{symbol}")
async def candles(symbol: str, tf: str = "5m", limit: int = 1500):
    df, source = await _call(md.candles, symbol, tf)
    df = df.iloc[-limit:]
    bars = [{"time": int(ts.timestamp()), "open": r.open, "high": r.high, "low": r.low,
             "close": r.close, "volume": r.volume} for ts, r in zip(df.index, df.itertuples(), strict=True)]
    return {"symbol": symbol.upper(), "tf": tf, "source": source, "bars": bars}


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


class StrategyRequest(BaseModel):
    symbol: str
    expiry: str | None = None


@app.post("/api/strategy")
def strategy_start(req: StrategyRequest):
    if problem := ai.azure_problem():
        raise HTTPException(400, problem)
    sym = md.instrument(req.symbol)["symbol"]
    return {"job": strategist.start(sym, req.expiry)}


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


@app.post("/api/journal/upload")
async def journal_upload(request: Request, name: str):
    try:
        return {"name": quant.save_upload(name, await request.body())}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/journal")
async def journal(name: str, horizon: str = "all"):
    try:
        return await run_in_threadpool(quant.journal, name, horizon)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

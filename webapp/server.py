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

from webapp import ai, market_data as md, planner, quant, signals  # noqa: E402

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

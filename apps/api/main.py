"""Orchestration API — dashboard ko sab kuch deta hai.

Endpoints (dashboard ka /api proxy inhe root pe bhejta hai):
  GET  /  /health  /strategies  /instruments  /portfolio  /live/status  /fno/chain
  POST /data/fetch           GET /data/candles
  POST /backtests            GET /backtests
  POST /agent/analyze        GET /agent/runs
  POST /signals/{id}/approve POST /signals/{id}/reject
  POST /paper/start          POST /paper/stop
  POST /live/start           POST /live/stop
  POST /kill-switch          (paper + live dono ko kill karta hai)
  WS   /ws/events

⚠️ LIVE TRADING GATES (mode="live" ke liye):
  LIVE_TRADING_ENABLED=true   env var (default: false)
  LIVE_MAX_CAPITAL            env var (default: ₹50,000)
  confirm phrase: "I UNDERSTAND THIS TRADES REAL MONEY"

Run:  python -m apps.api.main   (port 8000)
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from apps.agent.main import analyze as agent_analyze
from apps.agent.registry import SignalRegistry
from apps.api.auth import AuthMiddleware, allowed_origins, authenticate_websocket
from apps.api.radar import snapshot as radar_snapshot
from apps.data_gateway.main import get_provider
from apps.engine.brokers import available_brokers, get_broker
from apps.engine.live import (
    DhanQuotePriceSource,
    FyersQuotePriceSource,
    KiteQuotePriceSource,
    LiveTrader,
    ReplayPriceSource,
    UpstoxQuotePriceSource,
)
from apps.engine.paper import PaperTrader
from apps.engine.runner import RESULTS_DIR as BACKTESTS_DIR
from apps.engine.runner import run_backtest, save_results
from apps.engine.strategies import STRATEGIES
from libs.risk.engine import RiskEngine, RiskLimits
from libs.storage.execution_journal import ExecutionJournal
from libs.storage.parquet_store import ParquetStore, instrument_from_dir

ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNS_DIR = ROOT / "data" / "agent_runs"

# ⚠️ LIVE TRADING GATES
LIVE_ENABLED = os.environ.get("LIVE_TRADING_ENABLED", "false").lower() == "true"
LIVE_MAX_CAPITAL = float(os.environ.get("LIVE_MAX_CAPITAL", "50000"))
LIVE_CONFIRM_PHRASE = "I UNDERSTAND THIS TRADES REAL MONEY"

app = FastAPI(title="AI Quant — API", version="2.0.0a1")
app.add_middleware(AuthMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(),
                   allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"])

# ---------- shared state ----------
registry = SignalRegistry(AGENT_RUNS_DIR)
journal = ExecutionJournal(os.environ.get("EXECUTION_DB", str(ROOT / "data" / "execution.sqlite3")))


class ConnectionManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, event: dict):
        for ws in list(self.connections):
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()
paper_trader: PaperTrader | None = None
live_trader: LiveTrader | None = None


async def broadcast(event: dict):
    await manager.broadcast(event)


# ---------- request models ----------
class FetchRequest(BaseModel):
    provider: str = "mock"
    symbol: str
    exchange: str = "NSE"
    days: int = Field(default=60, ge=1, le=10000)


class BacktestRequest(BaseModel):
    instrument: str
    strategy: str
    params: dict = {}
    cost_bps: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    start: str | None = None
    end: str | None = None
    capital: float = Field(default=1_000_000, gt=0, le=1_000_000_000, allow_inf_nan=False)


class AnalyzeRequest(BaseModel):
    instrument: str
    llm: str = "auto"
    capital: float = Field(default=1_000_000, gt=0, le=1_000_000_000, allow_inf_nan=False)
    config: dict = {}


class PaperStartRequest(BaseModel):
    instrument: str
    strategy: str = "ema_cross"
    params: dict = {}
    capital: float = Field(default=1_000_000, gt=0, le=1_000_000_000, allow_inf_nan=False)
    speed: float = Field(default=0.5, ge=0, le=3600, allow_inf_nan=False)
    limit: int = Field(default=150, ge=35, le=100000)


class LiveStartRequest(BaseModel):
    instrument: str
    strategy: str = "ema_cross"
    params: dict = {}
    mode: str = "dry_run"        # dry_run | live
    broker: str = "kite"         # kite | dhan (registry se validate hota hai)
    capital: float = Field(default=100_000, gt=0, le=1_000_000_000, allow_inf_nan=False)
    product: str = "CNC"         # CNC (delivery, no leverage) — safe default
    speed: float = Field(default=1.0, ge=0, le=3600, allow_inf_nan=False)           # replay source speed (dry_run without broker creds)
    limit: int = Field(default=150, ge=35, le=100000)
    confirm: str = ""            # live mode ke liye required


# ---------- endpoints ----------
@app.get("/")
def root():
    """API index — preview open karne pe yeh dikhega (404 nahi).

    Version pyproject se padhta hai — hamesha fresh.
    """
    import tomllib
    with open(Path(__file__).parents[2] / "pyproject.toml", "rb") as f:
        version = tomllib.load(f)["project"]["version"]
    return {
        "service": "AI Quant Platform — API",
        "version": version,
        "status": "ok",
        "docs": "/docs  (Swagger UI)",
        "health": "/health",
        "live_trading_enabled": LIVE_ENABLED,
        "endpoints": {
            "data": ["GET /instruments", "POST /data/fetch", "GET /data/candles"],
            "fno": ["GET /fno/underlyings", "GET /fno/chain"],
            "backtests": ["GET /strategies", "POST /backtests", "GET /backtests"],
            "agent": ["POST /agent/analyze", "GET /agent/runs",
                      "POST /signals/{id}/approve", "POST /signals/{id}/reject"],
            "trading": ["GET /portfolio", "POST /paper/start", "POST /paper/stop",
                        "GET /brokers", "POST /live/start", "POST /live/stop",
                        "GET /live/status", "POST /kill-switch"],
            "realtime": ["WS /ws/events"],
        },
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "api",
            "live_trading_enabled": LIVE_ENABLED,
            "live_max_capital": LIVE_MAX_CAPITAL}


@app.get("/strategies")
def strategies():
    return {"strategies": {k: {"description": v["description"], "defaults": v["defaults"]}
                           for k, v in STRATEGIES.items()}}


@app.get("/instruments")
def instruments():
    store = ParquetStore()
    out = []
    for inst in store.list_instruments():
        s = store.summary(instrument_from_dir(inst))
        if s:
            out.append(s)
    return {"instruments": out}


@app.get("/fno/underlyings")
def fno_underlyings():
    """F&O underlyings jo support hote hain (lot size ke saath)."""
    from libs.shared.fno import LOT_SIZES
    return {"underlyings": [{"symbol": s, "lot_size": lot}
                            for s, lot in sorted(LOT_SIZES.items())]}


@app.get("/fno/chain")
def fno_chain(underlying: str, spot: float | None = None, expiry: str | None = None):
    """Option chain — strikes + CE/PE premiums (mock/synthetic data).

    Real broker chain baad mein — same interface.
    """
    from apps.data_gateway.providers.mock_provider import MockProvider, default_fno_spot
    from libs.shared.fno import LOT_SIZES, atm_strike, parse_fno_symbol
    und = underlying.strip().upper()
    if not und:
        raise HTTPException(400, "underlying required hai (e.g. NIFTY)")
    chain = MockProvider().get_option_chain(und, expiry=expiry, spot=spot)
    if not chain:
        raise HTTPException(404, f"Chain nahi mili: {und}")
    spot_used = spot if spot else default_fno_spot(und)
    atm = atm_strike([r["strike"] for r in chain], spot_used)
    fno = parse_fno_symbol(chain[0]["ce"]["symbol"])
    rows = []
    for r in chain:
        rows.append({
            "strike": r["strike"],
            "atm": r["strike"] == atm,
            "ce_itm": r["strike"] < spot_used,
            "pe_itm": r["strike"] > spot_used,
            "ce": {**r["ce"], "instrument": f"NSE:{r['ce']['symbol']}"},
            "pe": {**r["pe"], "instrument": f"NSE:{r['pe']['symbol']}"},
        })
    return {
        "underlying": und,
        "spot": spot_used,
        "expiry": str(fno.expiry) if fno else None,
        "lot_size": LOT_SIZES.get(und, 1),
        "chain": rows,
    }


@app.post("/data/fetch")
async def data_fetch(req: FetchRequest):
    def _do():
        provider = get_provider(req.provider)
        candles = provider.get_historical(req.symbol, days=req.days, exchange=req.exchange)
        if not candles:
            raise ValueError("Provider se koi data nahi mila")
        ParquetStore().write_candles(candles)
        return {"instrument": candles[0].instrument, "candles": len(candles),
                "from": str(candles[0].timestamp.date()),
                "to": str(candles[-1].timestamp.date())}
    try:
        return await run_in_threadpool(_do)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/data/candles")
def data_candles(instrument: str, limit: int = 200):
    candles = ParquetStore().read_candles(instrument)[-limit:]
    return {"instrument": instrument,
            "candles": [json.loads(c.model_dump_json()) for c in candles]}


@app.post("/backtests")
async def backtests(req: BacktestRequest):
    try:
        start = date.fromisoformat(req.start) if req.start else None
        end = date.fromisoformat(req.end) if req.end else None
        results = await run_in_threadpool(
            run_backtest, req.instrument, req.strategy, req.params, start, end, req.capital, req.cost_bps
        )
        save_results(results)
        return results
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/backtests")
def list_backtests():
    out = []
    if BACKTESTS_DIR.exists():
        for p in sorted(BACKTESTS_DIR.glob("*.json"), reverse=True)[:30]:
            r = json.loads(p.read_text())
            out.append({k: r.get(k) for k in (
                "instrument", "strategy", "params", "start", "end",
                "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                "n_trades", "created_at", "run_id", "data_sha256", "kernel_version",
                "net_return_pct", "estimated_cost_inr", "benchmark_return_pct", "validation")})
    return {"backtests": out}


@app.post("/agent/analyze")
async def agent_analyze_endpoint(req: AnalyzeRequest):
    try:
        run = await run_in_threadpool(
            agent_analyze, req.instrument, "ai_agent_v1", req.config, None, req.capital, req.llm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    registry.add(run)
    await broadcast({"type": "signal", "run_id": run.id, "instrument": run.instrument,
                     "direction": run.final_signal.direction.value,
                     "confidence": run.final_signal.confidence,
                     "risk": run.risk_decision.get("decision")})
    return {"run": json.loads(run.model_dump_json())}


@app.get("/agent/runs")
def agent_runs(limit: int = 30):
    return {"runs": registry.list(limit)}


@app.post("/signals/{run_id}/approve")
async def approve_signal(run_id: str):
    try:
        r = registry.approve(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await broadcast({"type": "signal.approved", "run_id": run_id})
    return {"status": "approved", "run": r}


@app.post("/signals/{run_id}/reject")
async def reject_signal(run_id: str):
    try:
        r = registry.reject(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await broadcast({"type": "signal.rejected", "run_id": run_id})
    return {"status": "rejected", "run": r}


# ---------- paper trading ----------
@app.get("/portfolio")
def portfolio():
    if paper_trader:
        return paper_trader.state()
    return {"running": False, "killed": False, "cash": 0, "positions": [],
            "orders": [], "equity_curve": [], "initial_capital": 0,
            "current_equity": 0, "total_pnl": 0, "total_pnl_pct": 0, "n_orders": 0,
            "message": "Paper trader nahi chal raha — start karo"}


@app.post("/paper/start")
async def paper_start(req: PaperStartRequest):
    global paper_trader
    if paper_trader and paper_trader.running:
        raise HTTPException(status_code=400,
                            detail="Paper trader pehle se chal raha hai — pehle stop karo")
    paper_trader = PaperTrader(req.instrument, req.strategy, req.params, req.capital,
                                speed=req.speed, on_event=broadcast,
                                signal_registry=registry, limit=req.limit)
    try:
        await paper_trader.start()
    except ValueError as e:
        paper_trader = None
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "started", "instrument": req.instrument, "strategy": req.strategy}


@app.post("/paper/stop")
async def paper_stop():
    global paper_trader
    if paper_trader:
        paper_trader.stop()
        await broadcast({"type": "paper.stopped"})
    return {"status": "stopped"}


# ---------- live trading (gated, multi-broker) ----------
def _broker_kwargs(broker_name: str) -> dict:
    """Har broker ke live creds (env se) — constructor kwargs."""
    if broker_name == "kite":
        return {"api_key": os.environ.get("KITE_API_KEY"),
                "access_token": os.environ.get("KITE_ACCESS_TOKEN")}
    if broker_name == "dhan":
        return {"client_id": os.environ.get("DHAN_CLIENT_ID"),
                "access_token": os.environ.get("DHAN_ACCESS_TOKEN")}
    if broker_name == "upstox":
        return {"api_key": os.environ.get("UPSTOX_API_KEY"),
                "access_token": os.environ.get("UPSTOX_ACCESS_TOKEN")}
    if broker_name == "fyers":
        return {"client_id": os.environ.get("FYERS_CLIENT_ID"),
                "access_token": os.environ.get("FYERS_ACCESS_TOKEN")}
    return {}


def _price_source(broker_name: str, exchange: str, symbol: str):
    """Har broker ka live quote source (real LTP poll)."""
    if broker_name == "kite":
        return KiteQuotePriceSource(exchange, symbol,
                                    api_key=os.environ.get("KITE_API_KEY"),
                                    access_token=os.environ.get("KITE_ACCESS_TOKEN"))
    if broker_name == "dhan":
        return DhanQuotePriceSource(exchange, symbol,
                                    client_id=os.environ.get("DHAN_CLIENT_ID"),
                                    access_token=os.environ.get("DHAN_ACCESS_TOKEN"))
    if broker_name == "upstox":
        return UpstoxQuotePriceSource(exchange, symbol,
                                      access_token=os.environ.get("UPSTOX_ACCESS_TOKEN"))
    if broker_name == "fyers":
        return FyersQuotePriceSource(exchange, symbol,
                                     client_id=os.environ.get("FYERS_CLIENT_ID"),
                                     access_token=os.environ.get("FYERS_ACCESS_TOKEN"))
    return None


@app.get("/brokers")
def brokers():
    """Available brokers + unke creds present hain ya nahi."""
    return {"brokers": available_brokers(),
            "live_trading_enabled": LIVE_ENABLED,
            "live_max_capital": LIVE_MAX_CAPITAL}


@app.post("/live/start")
async def live_start(req: LiveStartRequest):
    global live_trader
    if live_trader and live_trader.running:
        raise HTTPException(status_code=400,
                            detail="Live trader pehle se chal raha hai — pehle stop karo")
    if req.mode not in ("dry_run", "live"):
        raise HTTPException(status_code=400, detail="mode 'dry_run' ya 'live' hona chahiye")

    # broker validate (registry se)
    known = {b["name"]: b for b in available_brokers()}
    if req.broker not in known:
        raise HTTPException(status_code=400,
                            detail=f"Unknown broker '{req.broker}'. Available: {', '.join(sorted(known))}")
    creds_present = all(os.environ.get(v) for v in known[req.broker]["required_env"])

    # ⚠️ LIVE MODE GATES — real money se pehle sab check
    if req.mode == "live":
        if not LIVE_ENABLED:
            raise HTTPException(
                status_code=400,
                detail="LIVE trading DISABLED hai — enable karne ke liye LIVE_TRADING_ENABLED=true "
                       "set karo (sirf tab jab sach mein taiyaar ho)")
        if req.confirm != LIVE_CONFIRM_PHRASE:
            raise HTTPException(status_code=400,
                                detail=f"confirm phrase galat — exact likho: {LIVE_CONFIRM_PHRASE}")
        if req.capital > LIVE_MAX_CAPITAL:
            raise HTTPException(status_code=400,
                                detail=f"Capital zyada hai — live max ₹{LIVE_MAX_CAPITAL:,.0f}")
        if not creds_present:
            missing = ", ".join(known[req.broker]["required_env"])
            raise HTTPException(status_code=400,
                                detail=f"{req.broker.upper()} creds missing: {missing}")

    exchange, _, symbol = req.instrument.partition(":")

    try:
        if req.mode == "live":
            broker = get_broker(req.broker, dry_run=False, **_broker_kwargs(req.broker))
            source = _price_source(req.broker, exchange, symbol)
        else:
            broker = get_broker(req.broker, dry_run=True)
            # dry_run = real prices (agar creds hain) + fake money, warna replay
            source = (_price_source(req.broker, exchange, symbol) if creds_present
                      else ReplayPriceSource(req.instrument, speed=req.speed, limit=req.limit))
    except Exception:
        raise HTTPException(status_code=400, detail="Broker setup failed; check server credentials and SDK installation") from None

    risk = RiskEngine(RiskLimits(
        max_position_value=min(req.capital * 0.5, 200_000),
        trading_hours_only=(req.mode == "live"),  # replay/simulation mein hours check nahi
    ))
    try:
        run_id = journal.create_run(req.broker, req.instrument, req.mode)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    try:
        live_trader = LiveTrader(req.instrument, req.strategy, req.params,
                                 broker=broker, risk_engine=risk, price_source=source,
                                 on_event=broadcast, signal_registry=registry,
                                 capital=req.capital, product=req.product, journal=journal, run_id=run_id,
                                 trading_hours_only=(req.mode == "live"))
        await live_trader.start()
    except Exception:
        journal.transition(run_id, "startup_failed")
        live_trader = None
        raise HTTPException(status_code=400, detail="Trading startup failed; check broker credentials and price data") from None
    return {"status": "started", "mode": broker.mode, "broker": req.broker,
            "instrument": req.instrument, "run_id": run_id}


@app.post("/live/stop")
async def live_stop():
    global live_trader
    if live_trader:
        live_trader.stop()
        await broadcast({"type": "live.stopped"})
    return {"status": "stopped"}


@app.get("/live/status")
def live_status():
    if live_trader:
        return live_trader.state()
    return {"running": False, "mode": None, "killed": False,
            "message": "Live trader nahi chal raha"}


# ---------- kill switch (sab kuch band karta hai) ----------
@app.post("/kill-switch")
async def kill_switch():
    global paper_trader, live_trader
    if paper_trader:
        paper_trader.kill()
    result = live_trader.kill() if live_trader else {"status": "killed"}
    await broadcast({"type": "kill", **result})
    return result


# ---------- durable operations ----------
class ReconcileRequest(BaseModel):
    confirm: str
    note: str = Field(min_length=20, max_length=1000)


@app.get("/operations")
def operations():
    snapshot = journal.snapshot()
    return {**snapshot, "version": "2.0.0a1", "engine": "NautilusTrader",
            "strategy_kernel": "shared-v2", "live_enabled": LIVE_ENABLED,
            "brokers": available_brokers(), "market": "India",
            "research_mode": "LLM configured" if os.environ.get("LLM_API_KEY") else "Mock / deterministic",
            "data_instruments": len(ParquetStore().list_instruments()),
            "deployment": "single-operator / single-process",
            "limitations": ["Broker fills require reconciliation", "F&O chain is synthetic",
                            "Backtests are in-sample; costs are estimates",
                            "Broker OAuth renewal is manual"]}


@app.post("/operations/runs/{run_id}/reconcile")
def reconcile_run(run_id: str, req: ReconcileRequest):
    if req.confirm != "I VERIFIED BROKER ORDERS AND POSITIONS":
        raise HTTPException(400, "Exact broker-verification confirmation required")
    if live_trader and live_trader.run_id == run_id and live_trader.running:
        raise HTTPException(409, "Stop the active session before reconciliation")
    try:
        journal.reconcile(run_id, req.note)
    except KeyError:
        raise HTTPException(404, "Run not found") from None
    return {"status": "reconciled", "run_id": run_id, "method": "operator_attestation"}


# ---------- websocket ----------
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    if not await authenticate_websocket(ws):
        return
    await manager.connect(ws)
    await ws.send_json({"type": "connection.ready"})
    try:
        while True:
            await ws.receive_text()  # keep-alive; client messages ignored
    except WebSocketDisconnect:
        manager.disconnect(ws)



@app.get("/radar")
def market_radar():
    return radar_snapshot()


def run():
    import uvicorn
    print("🚀 AI Quant API on http://0.0.0.0:8000")
    if LIVE_ENABLED:
        print(f"⚠️  LIVE TRADING ENABLED (max capital ₹{LIVE_MAX_CAPITAL:,.0f})")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()

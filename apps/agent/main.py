"""Agent Service — AI signals with reasoning trace.

Server mode:  python -m apps.agent.main serve --port 8001
CLI mode:     python -m apps.agent.main analyze --instrument NSE:TESTCO
              python -m apps.agent.main runs

Real LLM ke liye env vars:
  export LLM_MODEL="gemini/gemini-2.0-flash"
  export LLM_API_KEY="..."
  (pip install litellm)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from apps.agent.analysis import build_snapshot
from apps.agent.graph.pipeline import run_pipeline
from apps.agent.llm.base import LLMClient
from apps.agent.llm.mock_llm import MockLLMClient
from libs.shared.models import AgentRun, PortfolioState
from libs.storage.parquet_store import ParquetStore

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "agent_runs"

app = FastAPI(title="AI Quant — Agent Service", version="0.1.0")


# ---------- core logic (API aur CLI dono use karte hain) ----------

def get_llm_client(pref: str = "auto") -> LLMClient:
    """mock → hamesha MockLLM. auto → env keys hain toh real LLM, warna mock."""
    if pref == "mock":
        return MockLLMClient()
    model = os.environ.get("LLM_MODEL")
    api_key = os.environ.get("LLM_API_KEY")
    if model and api_key:
        from apps.agent.llm.litellm_client import LiteLLMClient
        return LiteLLMClient(model=model, api_key=api_key,
                             api_base=os.environ.get("LLM_API_BASE"))
    return MockLLMClient()  # dev mode — no keys


def analyze(instrument: str, strategy: str = "ai_agent_v1", config: dict | None = None,
            portfolio: PortfolioState | None = None, capital: float = 1_000_000,
            llm_pref: str = "auto") -> AgentRun:
    candles = ParquetStore().read_candles(instrument)
    if len(candles) < 30:
        raise ValueError(f"{instrument}: kam se kam 30 candles chahiye (mile: {len(candles)})")
    snapshot = build_snapshot(instrument, candles)
    portfolio = portfolio or PortfolioState(cash=capital, total_value=capital)
    llm = get_llm_client(llm_pref)
    run = run_pipeline(snapshot, portfolio, strategy, config or {}, llm)
    save_run(run)
    return run


def save_run(run: AgentRun) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{run.id}.json"
    path.write_text(run.model_dump_json(indent=2))
    return path


# ---------- FastAPI endpoints ----------

class AnalyzeRequest(BaseModel):
    instrument: str
    strategy: str = "ai_agent_v1"
    config: dict = {}
    portfolio: PortfolioState | None = None
    capital: float = 1_000_000
    llm: str = "auto"  # mock | auto


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent"}


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    try:
        run = analyze(req.instrument, req.strategy, req.config,
                      req.portfolio, req.capital, req.llm)
        return {"run": json.loads(run.model_dump_json())}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/runs")
def list_runs():
    runs = []
    if RUNS_DIR.exists():
        for p in sorted(RUNS_DIR.glob("*.json"))[-20:]:
            r = json.loads(p.read_text())
            runs.append({
                "id": r["id"], "instrument": r["instrument"],
                "direction": r["final_signal"]["direction"],
                "confidence": r["final_signal"]["confidence"],
                "risk": r["risk_decision"].get("decision"),
                "cost_inr": r["total_cost_inr"], "created_at": r["created_at"],
            })
    return {"runs": runs}


# ---------- CLI ----------

def print_signal_card(run: AgentRun) -> None:
    sig = run.final_signal
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[sig.direction.value]
    print(f"\n🤖 AI Signal — {run.instrument}  (run {run.id})")
    print(f"   Direction  : {emoji} {sig.direction.value}")
    print(f"   Confidence : {sig.confidence:.2f}")
    if sig.target_price:
        print(f"   Target     : ₹{sig.target_price:,.2f}")
    if sig.stoploss:
        print(f"   Stoploss   : ₹{sig.stoploss:,.2f}")
    if sig.size_hint:
        print(f"   Size hint  : {sig.size_hint} shares")
    print("   " + "─" * 48)
    for step in run.steps:
        out = step.output if len(step.output) <= 260 else step.output[:260] + "..."
        print(f"   [{step.agent:<8}] ({step.model} · {step.tokens} tok · ₹{step.cost_inr:.3f} · {step.duration_ms}ms)")
        for line in out.splitlines()[:5]:
            print(f"      {line}")
        print()
    print(f"   Risk       : {str(run.risk_decision.get('decision', '?')).upper()} — {run.risk_decision.get('reason', '')}")
    print("   " + "─" * 48)
    print(f"   LLM: {run.llm_provider} · Tokens: {run.total_tokens:,} · Cost: ₹{run.total_cost_inr:.3f} · Time: {run.duration_ms}ms")
    print(f"   Status: {run.status.upper()} (human approval — MVP)")


def parse_set(pairs: list[str] | None) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        try:
            out[k] = int(v)
        except ValueError:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
    return out


def cmd_analyze(args) -> None:
    config = parse_set(args.set)
    print(f"⏳ Agent pipeline chala raha hai: {args.instrument} (llm={args.llm}) ...")
    run = analyze(args.instrument, args.strategy, config, capital=args.capital, llm_pref=args.llm)
    print_signal_card(run)
    print(f"\n💾 Saved: {RUNS_DIR / (run.id + '.json')}")


def cmd_serve(args) -> None:
    import uvicorn
    print(f"🚀 Agent Service on http://0.0.0.0:{args.port}  (POST /analyze, GET /runs, GET /health)")
    uvicorn.run("apps.agent.main:app", host="0.0.0.0", port=args.port, reload=False)


def cmd_runs(args) -> None:
    if not RUNS_DIR.exists() or not any(RUNS_DIR.glob("*.json")):
        print("📭 Abhi koi run saved nahi hai.")
        return
    print(f"{'ID':<14} {'INSTRUMENT':<14} {'DIR':<6} {'CONF':>5}  {'RISK':<8} {'COST(₹)':>8}  CREATED")
    for p in sorted(RUNS_DIR.glob("*.json")):
        r = json.loads(p.read_text())
        print(f"{r['id']:<14} {r['instrument']:<14} {r['final_signal']['direction']:<6} "
              f"{r['final_signal']['confidence']:>5.2f}  {str(r['risk_decision'].get('decision')):<8} "
              f"{r['total_cost_inr']:>8.3f}  {r['created_at'][:16]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="AI Quant — Agent Service")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Run agent pipeline for an instrument")
    a.add_argument("--instrument", required=True)
    a.add_argument("--strategy", default="ai_agent_v1")
    a.add_argument("--llm", default="auto", choices=["mock", "auto"],
                   help="mock = no API key (deterministic) · auto = real LLM if env keys set")
    a.add_argument("--capital", type=float, default=1_000_000)
    a.add_argument("--set", action="append", default=None, help="config param, e.g. --set min_confidence=0.7")
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser("serve", help="Run FastAPI server")
    s.add_argument("--port", type=int, default=8001)
    s.set_defaults(func=cmd_serve)

    r = sub.add_parser("runs", help="List saved agent runs")
    r.set_defaults(func=cmd_runs)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

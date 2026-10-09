"""Agent pipeline: Analyst → Trader → Risk (linear, MVP).

Baad mein: LangGraph multi-agent debate (TradingAgents jaisa).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from apps.agent.llm.base import LLMClient
from libs.shared.models import (
    AgentRun,
    AgentStep,
    MarketSnapshot,
    PortfolioState,
    Signal,
    SignalDirection,
)

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "libs" / "prompts" / "v1"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def risk_check(signal: Signal, snapshot: MarketSnapshot,
               portfolio: PortfolioState, config: dict) -> dict:
    """Hard risk rules — inhe koi bypass nahi kar sakta (engine se pehle check)."""
    max_positions = config.get("max_open_positions", 5)
    min_confidence = config.get("min_confidence", 0.6)
    max_position_pct = config.get("max_position_pct", 0.20)
    daily_loss_limit_pct = config.get("daily_loss_limit_pct", 3.0)
    max_drawdown_pct = config.get("max_drawdown_pct", 10.0)

    if signal.direction == SignalDirection.HOLD:
        return {"decision": "approve", "reason": "HOLD signal — koi naya trade nahi",
                "adjusted_size_hint": None}
    if portfolio.daily_pnl_pct <= -daily_loss_limit_pct:
        return {"decision": "veto",
                "reason": f"Daily loss limit hit ({portfolio.daily_pnl_pct:.1f}% ≤ -{daily_loss_limit_pct}%) — sab signals veto",
                "adjusted_size_hint": None}
    if portfolio.current_drawdown_pct <= -max_drawdown_pct:
        return {"decision": "veto",
                "reason": f"Max drawdown ({portfolio.current_drawdown_pct:.1f}%) — kill switch territory",
                "adjusted_size_hint": None}
    if portfolio.open_positions >= max_positions:
        return {"decision": "veto",
                "reason": f"Max open positions ({max_positions}) pahunch gaye",
                "adjusted_size_hint": None}
    if signal.confidence < min_confidence:
        return {"decision": "veto",
                "reason": f"Confidence {signal.confidence:.2f} < minimum {min_confidence}",
                "adjusted_size_hint": None}

    max_rupees = portfolio.total_value * max_position_pct
    affordable = int(max_rupees / snapshot.current_price) if snapshot.current_price > 0 else 0
    if affordable <= 0:
        return {"decision": "veto",
                "reason": "Position afford nahi hota (capital × max_position_pct)",
                "adjusted_size_hint": None}
    size = signal.size_hint or 100
    adjusted = min(size, affordable)
    if adjusted < size:
        return {"decision": "adjust",
                "reason": f"Size {size} → {adjusted} adjust kiya (max {max_position_pct * 100:.0f}% of portfolio)",
                "adjusted_size_hint": adjusted}
    return {"decision": "approve", "reason": "Saare risk checks pass",
            "adjusted_size_hint": adjusted}


def run_pipeline(snapshot: MarketSnapshot, portfolio: PortfolioState,
                 strategy: str, config: dict, llm: LLMClient) -> AgentRun:
    steps: list[AgentStep] = []
    run_id = uuid.uuid4().hex[:12]
    t_start = time.perf_counter()

    # --- Step 1: Analyst (reasoning) ---
    t = time.perf_counter()
    sys_p = load_prompt("analyst")
    user_p = (
        "MARKET SNAPSHOT (JSON):\n```json\n" + snapshot.model_dump_json() + "\n```\n\n"
        "Task: Analyze this snapshot and give your market view with specific reasoning (max 150 words)."
    )
    reasoning, usage = llm.complete(sys_p, user_p, role="analyst")
    steps.append(AgentStep(
        agent="analyst", model=llm.model, output=reasoning,
        tokens=usage["prompt_tokens"] + usage["completion_tokens"],
        cost_inr=usage["cost_inr"], duration_ms=int((time.perf_counter() - t) * 1000),
    ))

    # --- Step 2: Trader (structured Signal) ---
    t = time.perf_counter()
    sys_p = load_prompt("trader")
    user_p = (
        "MARKET SNAPSHOT (JSON):\n```json\n" + snapshot.model_dump_json() + "\n```\n\n"
        "ANALYST REASONING:\n" + reasoning + "\n\n"
        "PORTFOLIO STATE (JSON):\n```json\n" + portfolio.model_dump_json() + "\n```\n\n"
        "STRATEGY CONFIG: " + json.dumps(config)
    )
    raw, usage = llm.complete(sys_p, user_p, response_model=Signal, role="trader")
    try:
        signal = Signal.model_validate_json(raw)
        signal.instrument = snapshot.instrument  # tamper-proof
    except Exception:
        signal = Signal(
            instrument=snapshot.instrument, direction=SignalDirection.HOLD, confidence=0.0,
            reasoning=f"Trader output parse nahi hui — safe fallback HOLD. Raw: {raw[:200]}",
        )
    steps.append(AgentStep(
        agent="trader", model=llm.model, output=signal.model_dump_json(),
        tokens=usage["prompt_tokens"] + usage["completion_tokens"],
        cost_inr=usage["cost_inr"], duration_ms=int((time.perf_counter() - t) * 1000),
    ))

    # --- Step 3: Risk (hard rules + LLM explanation) ---
    t = time.perf_counter()
    decision = risk_check(signal, snapshot, portfolio, config)
    sys_p = load_prompt("risk")
    user_p = (
        "SIGNAL (JSON): " + signal.model_dump_json() + "\n"
        "PORTFOLIO STATE (JSON): " + portfolio.model_dump_json() + "\n"
        "RULE-BASED DECISION (JSON): " + json.dumps(decision) + "\n\n"
        "Task: Explain this risk decision in 1-2 plain sentences with the numbers."
    )
    explanation, usage = llm.complete(sys_p, user_p, role="risk")
    steps.append(AgentStep(
        agent="risk", model=llm.model, output=explanation,
        tokens=usage["prompt_tokens"] + usage["completion_tokens"],
        cost_inr=usage["cost_inr"], duration_ms=int((time.perf_counter() - t) * 1000),
    ))

    return AgentRun(
        id=run_id,
        instrument=snapshot.instrument,
        strategy=strategy,
        steps=steps,
        final_signal=signal,
        risk_decision=decision,
        risk_explanation=explanation,
        total_tokens=sum(s.tokens for s in steps),
        total_cost_inr=round(sum(s.cost_inr for s in steps), 4),
        duration_ms=int((time.perf_counter() - t_start) * 1000),
        llm_provider=llm.name,
        status="pending",  # MVP: human approval
    )

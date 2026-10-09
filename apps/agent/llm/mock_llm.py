"""Mock LLM — bina API key ke pipeline test karne ke liye.

Deterministic, rule-based 'AI'. Real LLM jaisa hi interface:
- user prompt se snapshot JSON parse karta hai
- trader role → structured Signal JSON (real LLM jaisa)
- analyst/risk role → reasoning text

Isse poori pipeline bina paisa kharche test ho jati hai.
"""
from __future__ import annotations

import json
import re

from apps.agent.llm.base import LLMClient
from libs.shared.models import MarketSnapshot, Signal, SignalDirection

SNAPSHOT_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
DECISION_RE = re.compile(r"RULE-BASED DECISION \(JSON\): (\{.*\})")
COST_PER_1K_INR = 0.05  # nominal — real LLM cost compare karne ke liye


class MockLLMClient(LLMClient):
    name = "mock"
    model = "mock-rule-v1"

    def complete(self, system_prompt: str, user_prompt: str,
                 response_model: type | None = None, role: str = "") -> tuple[str, dict]:
        snapshot = self._extract_snapshot(user_prompt)
        if role == "trader":
            text = self._make_signal(snapshot).model_dump_json()
        elif role == "analyst":
            text = self._make_analysis(snapshot)
        elif role == "risk":
            text = self._make_risk_explanation(user_prompt)
        else:
            text = f"[mock] role '{role}' — snapshot for {snapshot.instrument if snapshot else '?'}"

        total_chars = len(system_prompt) + len(user_prompt) + len(text)
        usage = {
            "prompt_tokens": (len(system_prompt) + len(user_prompt)) // 4,
            "completion_tokens": len(text) // 4,
            "cost_inr": round(total_chars / 4 / 1000 * COST_PER_1K_INR, 4),
        }
        return text, usage

    def _extract_snapshot(self, user_prompt: str) -> MarketSnapshot | None:
        m = SNAPSHOT_RE.search(user_prompt)
        if not m:
            return None
        try:
            return MarketSnapshot.model_validate_json(m.group(1))
        except Exception:
            return None

    def _make_signal(self, snapshot: MarketSnapshot | None) -> Signal:
        if snapshot is None:
            return Signal(instrument="UNKNOWN", direction=SignalDirection.HOLD,
                          confidence=0.0, reasoning="mock: snapshot nahi mili")
        price = snapshot.current_price
        rsi = snapshot.rsi_14
        if rsi is not None and rsi < 35:
            conf = min(0.9, 0.5 + (35 - rsi) / 100)
            return Signal(
                instrument=snapshot.instrument, direction=SignalDirection.BUY,
                confidence=round(conf, 2),
                target_price=round(price * 1.03, 2), stoploss=round(price * 0.97, 2),
                size_hint=100,
                reasoning=(f"Mean-reversion setup: RSI(14)={rsi:.1f} oversold (<35), "
                           f"trend {snapshot.trend}. Bounce toward SMA10 expected."),
            )
        if rsi is not None and rsi > 65:
            conf = min(0.9, 0.5 + (rsi - 65) / 100)
            return Signal(
                instrument=snapshot.instrument, direction=SignalDirection.SELL,
                confidence=round(conf, 2),
                target_price=round(price * 0.97, 2), stoploss=round(price * 1.03, 2),
                size_hint=100,
                reasoning=(f"Mean-reversion setup: RSI(14)={rsi:.1f} overbought (>65), "
                           f"trend {snapshot.trend}. Pullback toward SMA10 expected."),
            )
        return Signal(
            instrument=snapshot.instrument, direction=SignalDirection.HOLD,
            confidence=0.5, size_hint=100,
            reasoning=(f"No setup: RSI(14)={rsi if rsi is not None else 'n/a'} neutral zone (35-65), "
                       f"trend {snapshot.trend}. Wait for an extreme."),
        )

    def _make_analysis(self, snapshot: MarketSnapshot | None) -> str:
        if snapshot is None:
            return "[mock analyst] snapshot nahi mili."
        rsi = snapshot.rsi_14 or 50.0
        zone = "oversold" if rsi < 35 else "overbought" if rsi > 65 else "neutral"
        return (
            f"Trend: {snapshot.trend} (SMA10 {snapshot.sma_10:.2f} vs SMA30 {snapshot.sma_30:.2f}). "
            f"RSI(14) = {rsi:.1f} — {zone} zone. "
            f"1D change {snapshot.change_1d_pct:+.2f}%, 5D change {snapshot.change_5d_pct:+.2f}%. "
            f"20D volatility {snapshot.volatility_20d_pct:.2f}%/day. "
            f"Price {snapshot.current_price:.2f} — window range "
            f"{snapshot.window_low:.2f}–{snapshot.window_high:.2f}. "
            f"Avg volume (20D): {snapshot.avg_volume_20:,}."
        )

    def _make_risk_explanation(self, user_prompt: str) -> str:
        m = DECISION_RE.search(user_prompt)
        if m:
            try:
                d = json.loads(m.group(1))
                return f"Risk check result: {str(d.get('decision', '?')).upper()} — {d.get('reason', '')}"
            except Exception:
                pass
        return "[mock risk] decision explain nahi kar paya."

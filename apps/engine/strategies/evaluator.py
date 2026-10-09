"""Strategy logic — pure, broker-agnostic.

PaperTrader aur LiveTrader dono isko use karte hain (ek hi jagah logic).
"""
from __future__ import annotations

from apps.agent.analysis import rsi as rsi_indicator


def ema_update(prev: float | None, price: float, period: int) -> float:
    if prev is None:
        return price
    k = 2 / (period + 1)
    return price * k + prev * (1 - k)


class StrategyEvaluator:
    """Classic strategies — naya price aate hi signal deta hai ({side, qty, reason} ya None)."""

    def __init__(self, name: str, params: dict | None = None):
        self.name = name
        self.params = params or {}
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._prev_diff: float | None = None
        self._closes: list[float] = []

    def on_price(self, price: float, held_qty: int = 0) -> dict | None:
        qty = self.params.get("quantity", 100)
        self._closes.append(price)

        if self.name in ("ema_cross", "atm_call_buy"):  # atm_call_buy = options buyer (same logic)
            self._ema_fast = ema_update(self._ema_fast, price, self.params.get("fast_ema", 10))
            self._ema_slow = ema_update(self._ema_slow, price, self.params.get("slow_ema", 30))
            if self._ema_fast is None or self._ema_slow is None:
                return None
            diff = self._ema_fast - self._ema_slow
            if self._prev_diff is None:
                self._prev_diff = diff
                return None
            crossed_up = self._prev_diff <= 0 < diff
            crossed_down = self._prev_diff >= 0 > diff
            self._prev_diff = diff
            if crossed_up and held_qty == 0:
                return {"side": "BUY", "qty": qty,
                        "reason": f"EMA cross UP (fast {self._ema_fast:.2f} > slow {self._ema_slow:.2f})"}
            if crossed_down and held_qty > 0:
                return {"side": "SELL", "qty": held_qty,
                        "reason": f"EMA cross DOWN (fast {self._ema_fast:.2f} < slow {self._ema_slow:.2f})"}

        elif self.name == "rsi":
            period = self.params.get("period", 14)
            if len(self._closes) < period + 1:
                return None
            r = rsi_indicator(self._closes, period)
            if r is None:
                return None
            if held_qty == 0 and r < self.params.get("oversold", 30):
                return {"side": "BUY", "qty": qty,
                        "reason": f"RSI oversold ({r:.1f} < {self.params.get('oversold', 30)})"}
            if held_qty > 0 and r > self.params.get("overbought", 70):
                return {"side": "SELL", "qty": held_qty,
                        "reason": f"RSI overbought ({r:.1f} > {self.params.get('overbought', 70)})"}

        return None

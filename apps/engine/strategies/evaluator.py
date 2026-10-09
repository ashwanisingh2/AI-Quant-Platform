"""Strategy logic — pure, broker-agnostic.

PaperTrader aur LiveTrader dono isko use karte hain (ek hi jagah logic).
"""
from __future__ import annotations

import math

from apps.agent.analysis import rsi as rsi_indicator


def ema_update(prev: float | None, price: float, period: int) -> float:
    if prev is None:
        return price
    k = 2 / (period + 1)
    return price * k + prev * (1 - k)


class StrategyEvaluator:
    """Classic strategies — naya price aate hi signal deta hai ({side, qty, reason} ya None)."""

    def __init__(self, name: str, params: dict | None = None):
        if name not in ('ema_cross', 'atm_call_buy', 'rsi'):
            raise ValueError('Unknown strategy')
        self.name = name
        self.params = dict(params or {})
        for key in ('quantity', 'period', 'fast_ema', 'slow_ema'):
            value = self.params.get(key, 1)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1 or int(value) != value:
                raise ValueError(f'{key} must be a positive integer')
            if key in self.params:
                self.params[key] = int(value)
        if name != 'rsi' and self.params.get('fast_ema', 10) >= self.params.get('slow_ema', 30):
            raise ValueError('fast_ema must be smaller than slow_ema')
        if name == 'rsi' and not 0 <= self.params.get('oversold', 30) < self.params.get('overbought', 70) <= 100:
            raise ValueError('RSI thresholds must satisfy 0 <= oversold < overbought <= 100')
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._prev_diff: float | None = None
        self._closes: list[float] = []

    def on_price(self, price: float, held_qty: int = 0) -> dict | None:
        if not math.isfinite(price) or price <= 0:
            raise ValueError('Price must be finite and positive')
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

"""Candles → MarketSnapshot (SMA, RSI, volatility, trend — pure Python)."""
from __future__ import annotations

import math

from libs.shared.models import Candle, MarketSnapshot


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Cutler RSI — last `period` moves ka."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def volatility_pct(closes: list[float], period: int = 20) -> float | None:
    """Daily returns ki stddev (% mein)."""
    if len(closes) < period + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(-period, 0)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var) * 100


def detect_trend(closes: list[float]) -> str:
    s10, s30 = sma(closes, 10), sma(closes, 30)
    if s10 is None or s30 is None:
        return "unknown"
    if s10 > s30 * 1.01:
        return "up"
    if s10 < s30 * 0.99:
        return "down"
    return "sideways"


def build_snapshot(instrument: str, candles: list[Candle], news: list[str] | None = None) -> MarketSnapshot:
    if len(candles) < 30:
        raise ValueError(f"Snapshot ke liye kam se kam 30 candles chahiye (mile: {len(candles)})")
    closes = [c.close for c in candles]
    return MarketSnapshot(
        instrument=instrument,
        timestamp=candles[-1].timestamp,
        current_price=closes[-1],
        change_1d_pct=round((closes[-1] / closes[-2] - 1) * 100, 2),
        change_5d_pct=round((closes[-1] / closes[-6] - 1) * 100, 2),
        sma_10=round(sma(closes, 10) or 0, 2),
        sma_30=round(sma(closes, 30) or 0, 2),
        rsi_14=round(rsi(closes, 14) or 50.0, 1),
        volatility_20d_pct=round(volatility_pct(closes, 20) or 0, 2),
        window_high=max(c.high for c in candles),
        window_low=min(c.low for c in candles),
        avg_volume_20=round(sum(c.volume for c in candles[-20:]) / 20),
        trend=detect_trend(closes),
        recent_closes=[round(c, 2) for c in closes[-10:]],
        news=news or [],
    )

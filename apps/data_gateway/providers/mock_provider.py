"""Mock provider — bina internet/credentials ke development ke liye.

Deterministic (seeded) random walk — har run bilkul same data.
Real broker se data aane se pehle pipeline test karne ke liye perfect.
"""
from __future__ import annotations

import random
import zlib
from datetime import date, datetime, timedelta

from apps.data_gateway.providers.base import DataProvider
from libs.shared.models import Candle, instrument_key


class MockProvider(DataProvider):
    name = "mock"

    def __init__(self, seed: int = 42):
        self.seed = seed

    def get_historical(
        self, symbol: str, days: int = 60, exchange: str = "NSE"
    ) -> list[Candle]:
        seed = zlib.crc32(f"{self.seed}:{exchange}:{symbol}".encode())
        rng = random.Random(seed)
        price = 500.0 + (seed % 2000)
        drift = 0.0004  # thoda upward bias — realistic lagta hai

        candles: list[Candle] = []
        d = date.today()
        produced = 0
        while produced < days:
            if d.weekday() < 5:  # Mon–Fri only
                open_ = price
                close = open_ * (1 + rng.gauss(drift, 0.015))
                high = max(open_, close) * (1 + abs(rng.gauss(0, 0.004)))
                low = min(open_, close) * (1 - abs(rng.gauss(0, 0.004)))
                candles.append(Candle(
                    instrument=instrument_key(exchange, symbol),
                    timestamp=datetime(d.year, d.month, d.day),
                    open=round(open_, 2), high=round(high, 2),
                    low=round(low, 2), close=round(close, 2),
                    volume=rng.randint(100_000, 5_000_000),
                ))
                price = close
                produced += 1
            d -= timedelta(days=1)

        candles.reverse()  # oldest → newest
        return candles

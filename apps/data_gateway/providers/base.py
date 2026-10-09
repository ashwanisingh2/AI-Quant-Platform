"""DataProvider interface — har broker / data source isko implement karta hai.

Naya broker add karna = ek nayi class jo isse inherit kare. Bas.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from libs.shared.models import Candle


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_historical(self, symbol: str, days: int = 60, exchange: str = "NSE") -> list[Candle]:
        """Daily candles — last `days` trading days (oldest → newest order)."""
        ...

"""Kite provider — Zerodha Kite Connect (live + historical data).

Requires: Kite Connect account → api_key + access_token
    pip install kiteconnect
    export KITE_API_KEY=...
    export KITE_ACCESS_TOKEN=...   (login flow se milta hai)

Kite historical API ki limits: ek call mein limited candles —
bade ranges ke liye baad mein chunking add karenge.
"""
from __future__ import annotations

from datetime import date, timedelta

from apps.data_gateway.normalize import candle_from_kite_row
from apps.data_gateway.providers.base import DataProvider
from libs.shared.models import Candle


class KiteProvider(DataProvider):
    name = "kite"

    def __init__(self, api_key: str, access_token: str | None = None):
        from kiteconnect import KiteConnect  # lazy import — optional dependency
        self.kite = KiteConnect(api_key=api_key)
        if access_token:
            self.kite.set_access_token(access_token)
        self._token_cache: dict[tuple[str, str], int] = {}

    def get_instruments(self, exchange: str = "NSE") -> list[dict]:
        """Kite ka poora instruments dump (tokens ke liye)."""
        return self.kite.instruments(exchange)

    def _resolve_token(self, symbol: str, exchange: str = "NSE") -> int:
        key = (exchange, symbol)
        if key not in self._token_cache:
            for inst in self.get_instruments(exchange):
                if inst.get("tradingsymbol") == symbol:
                    self._token_cache[key] = inst["instrument_token"]
                    break
            else:
                raise ValueError(f"Instrument nahi mila: {exchange}:{symbol}")
        return self._token_cache[key]

    def get_historical(self, symbol: str, days: int = 60, exchange: str = "NSE") -> list[Candle]:
        token = self._resolve_token(symbol, exchange)
        to = date.today()
        frm = to - timedelta(days=int(days * 1.6))  # calendar days (trading days kam hote hain)
        raw = self.kite.historical_data(token, frm, to, "day")
        return [candle_from_kite_row(r, symbol, exchange) for r in raw]

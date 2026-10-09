"""Raw broker data → unified models (Candle / Instrument).

Har provider raw rows ko in functions se convert karta hai —
naya broker aaya toh yahin add karo.
"""
from __future__ import annotations

from datetime import date, datetime

from libs.shared.models import (
    Candle,
    Exchange,
    Instrument,
    InstrumentType,
    instrument_key,
)


def candle_from_bhavcopy_row(row: dict, day: date, exchange: str = "NSE") -> Candle:
    """NSE bhavcopy CSV row → Candle (EOD candle: timestamp = trading day)."""
    return Candle(
        instrument=instrument_key(exchange, row["SYMBOL"]),
        timestamp=datetime(day.year, day.month, day.day),
        open=float(row["OPEN"]),
        high=float(row["HIGH"]),
        low=float(row["LOW"]),
        close=float(row["CLOSE"]),
        volume=int(float(row.get("TOTTRDQTY") or 0)),
    )


def candle_from_kite_row(row: dict, symbol: str, exchange: str = "NSE") -> Candle:
    """Kite Connect historical row → Candle."""
    d = row["date"]
    ts = d if isinstance(d, datetime) else datetime(d.year, d.month, d.day)
    return Candle(
        instrument=instrument_key(exchange, symbol),
        timestamp=ts,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row.get("volume") or 0),
    )


def instrument_from_bhavcopy_row(row: dict, exchange: str = "NSE") -> Instrument:
    return Instrument(
        exchange=Exchange(exchange),
        symbol=row["SYMBOL"],
        isin=row.get("ISIN") or None,
        instrument_type=InstrumentType.EQ,
    )

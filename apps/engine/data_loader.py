"""Hamare Parquet data → NautilusTrader format (Instrument + Bars).

Phase 0 ka data (ParquetStore) yahin se engine mein jata hai.
Daily candles → 1-DAY-LAST bars, emit time = 15:30 IST (market close).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from nautilus_trader.model.currencies import INR
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Price, Quantity

from libs.shared.models import Candle
from libs.storage.parquet_store import ParquetStore


def parse_instrument(instrument: str) -> tuple[str, str]:
    """'NSE:RELIANCE' → ('NSE', 'RELIANCE')"""
    exchange, _, symbol = instrument.partition(":")
    if not symbol:
        raise ValueError(f"Instrument format galat hai: {instrument!r} (use: EXCHANGE:SYMBOL)")
    return exchange, symbol


def build_instrument(instrument_key: str) -> Equity:
    exchange, symbol = parse_instrument(instrument_key)
    return Equity(
        instrument_id=InstrumentId(Symbol(symbol), Venue(exchange)),
        raw_symbol=Symbol(symbol),
        currency=INR,
        price_precision=2,
        price_increment=Price.from_str("0.05"),
        lot_size=Quantity.from_int(1),
        ts_event=0,
        ts_init=0,
    )


def build_bar_type(instrument: Equity) -> BarType:
    return BarType(
        instrument.id,
        BarSpecification(1, BarAggregation.DAY, PriceType.LAST),
    )


def _ts_ns(dt: datetime) -> int:
    """Naive IST datetime → nanoseconds since epoch."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)


def candle_to_bar(c: Candle, bar_type: BarType) -> Bar:
    emit = c.timestamp.replace(hour=15, minute=30)  # 15:30 IST market close
    ts = _ts_ns(emit)
    return Bar(
        bar_type=bar_type,
        open=Price.from_str(f"{c.open:.2f}"),
        high=Price.from_str(f"{c.high:.2f}"),
        low=Price.from_str(f"{c.low:.2f}"),
        close=Price.from_str(f"{c.close:.2f}"),
        volume=Quantity.from_int(c.volume),
        ts_event=ts,
        ts_init=ts,
    )


def load_bars(
    instrument_key: str,
    start: date | None = None,
    end: date | None = None,
) -> tuple[Equity, BarType, list[Bar]]:
    """ParquetStore se candles lo → Nautilus (instrument, bar_type, bars)."""
    store = ParquetStore()
    candles = store.read_candles(instrument_key, start=start, end=end)
    if not candles:
        raise ValueError(
            f"Data nahi mila: {instrument_key} — pehle fetch karo "
            f"(python -m apps.data_gateway.main fetch ...)"
        )
    instrument = build_instrument(instrument_key)
    bar_type = build_bar_type(instrument)
    bars = [candle_to_bar(c, bar_type) for c in candles]
    return instrument, bar_type, bars

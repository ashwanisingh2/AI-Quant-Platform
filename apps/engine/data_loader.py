"""Hamare Parquet data → NautilusTrader format (Instrument + Bars).

Phase 0 ka data (ParquetStore) yahin se engine mein jata hai.
Daily candles → 1-DAY-LAST bars, emit time = 15:30 IST (market close).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from nautilus_trader.model.currencies import INR
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AssetClass, BarAggregation, OptionKind, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Equity, FuturesContract, Instrument, OptionContract
from nautilus_trader.model.objects import Price, Quantity

from libs.shared.fno import lot_size, monthly_expiry, parse_fno_symbol
from libs.shared.models import Candle
from libs.storage.parquet_store import ParquetStore


def parse_instrument(instrument: str) -> tuple[str, str]:
    """'NSE:RELIANCE' → ('NSE', 'RELIANCE')"""
    exchange, _, symbol = instrument.partition(":")
    if not symbol:
        raise ValueError(f"Instrument format galat hai: {instrument!r} (use: EXCHANGE:SYMBOL)")
    return exchange, symbol


def _fno_expiry_ns(expiry: date) -> int:
    """Expiry date 15:30 ko nanoseconds (IST wall-time as UTC — bars se consistent)."""
    dt = datetime(expiry.year, expiry.month, expiry.day, 15, 30)
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1_000_000_000)


def _fno_live_expiry(fno) -> date:
    """Backtest mein 'contract expired' rejection na ho — expiry future mein rakho.

    Symbol ka expiry agar beet gaya (purana data) toh agla monthly expiry le lo.
    Sirf backtest instrument ke liye — symbol waisa hi rehta hai.
    """
    expiry = fno.expiry
    while expiry <= date.today():
        y, m = expiry.year, expiry.month + 1
        if m > 12:
            y, m = y + 1, 1
        expiry = monthly_expiry(y, m)
    return expiry


def build_instrument(instrument_key: str) -> Instrument:
    """Cash → Equity. F&O → FuturesContract / OptionContract (Phase 8).

    Note: F&O backtest = signal validation. CASH account full notional debit karta hai,
    toh capital kam se kam ek lot ke notional jitna rakho (NIFTY 1 lot ≈ ₹18L at 24000).
    Margin-based accounting = future work.
    """
    exchange, symbol = parse_instrument(instrument_key)
    fno = parse_fno_symbol(symbol)
    if fno is None:
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
    lot = lot_size(fno.underlying)
    expiry = _fno_live_expiry(fno)
    exp_ns = _fno_expiry_ns(expiry)
    act_ns = 0  # hamesha active — backtest data kisi bhi date ka ho (equity jaisa ts=0)
    if fno.is_future:
        return FuturesContract(
            instrument_id=InstrumentId(Symbol(symbol), Venue(exchange)),
            raw_symbol=Symbol(symbol),
            asset_class=AssetClass.INDEX,
            exchange=exchange,
            currency=INR,
            price_precision=2,
            price_increment=Price.from_str("0.05"),
            multiplier=Quantity.from_int(1),      # qty = units; notional = price × qty
            lot_size=Quantity.from_int(lot),
            underlying=fno.underlying,
            activation_ns=act_ns,
            expiration_ns=exp_ns,
            ts_event=act_ns,
            ts_init=act_ns,
        )
    return OptionContract(
        instrument_id=InstrumentId(Symbol(symbol), Venue(exchange)),
        raw_symbol=Symbol(symbol),
        asset_class=AssetClass.INDEX,
        exchange=exchange,
        currency=INR,
        price_precision=2,
        price_increment=Price.from_str("0.05"),
        multiplier=Quantity.from_int(1),
        lot_size=Quantity.from_int(lot),
        underlying=fno.underlying,
        strike_price=Price.from_str(f"{fno.strike:.2f}"),
        option_kind=OptionKind.CALL if fno.kind == "CE" else OptionKind.PUT,
        activation_ns=act_ns,
        expiration_ns=exp_ns,
        ts_event=act_ns,
        ts_init=act_ns,
    )


def build_bar_type(instrument: Instrument) -> BarType:
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

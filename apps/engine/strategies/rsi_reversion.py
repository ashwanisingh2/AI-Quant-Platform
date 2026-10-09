"""Backtest adapter; decisions come from the shared V2 strategy kernel."""
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from apps.engine.strategies.adapter import SharedStrategy


class RSIReversionConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    quantity: int = 100


class RSIReversion(SharedStrategy):
    kernel_name = 'rsi'
    parameter_names = ('period', 'oversold', 'overbought', 'quantity')

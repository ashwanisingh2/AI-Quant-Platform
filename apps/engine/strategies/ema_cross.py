"""Backtest adapter; decisions come from the shared V2 strategy kernel."""
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from apps.engine.strategies.adapter import SharedStrategy


class EMACrossConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    fast_ema: int = 10
    slow_ema: int = 30
    quantity: int = 100


class EMACross(SharedStrategy):
    kernel_name = 'ema_cross'
    parameter_names = ('fast_ema', 'slow_ema', 'quantity')

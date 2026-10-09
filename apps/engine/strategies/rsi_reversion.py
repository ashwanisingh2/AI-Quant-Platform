"""RSI Mean-Reversion strategy.

Rule: RSI oversold (< 30) → BUY
      RSI overbought (> 70) → position band karo
Idea: short-term extremes par price wapas average ki taraf aati hai.
"""
from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import RelativeStrengthIndex
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class RSIReversionConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    quantity: int = 100


class RSIReversion(Strategy):
    def __init__(self, config: RSIReversionConfig):
        super().__init__(config)
        self.rsi = RelativeStrengthIndex(config.period)

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            raise RuntimeError(f"Instrument nahi mila: {self.config.instrument_id}")
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        if not self.rsi.initialized:
            return  # indicator warmup
        if self.portfolio.is_flat(self.config.instrument_id) and self.rsi.value < self.config.oversold:
            self._enter(OrderSide.BUY)
        elif not self.portfolio.is_flat(self.config.instrument_id) and self.rsi.value > self.config.overbought:
            self.close_all_positions(self.config.instrument_id)

    def _enter(self, side: OrderSide):
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=Quantity.from_int(self.config.quantity),
        ))

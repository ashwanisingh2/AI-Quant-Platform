"""EMA Crossover strategy — classic trend-following.

Rule: Fast EMA (default 10) upar cross kare Slow EMA (default 30) ko → BUY
      Fast EMA neeche cross kare Slow EMA ko → position band karo
"""
from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class EMACrossConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    fast_ema: int = 10
    slow_ema: int = 30
    quantity: int = 100


class EMACross(Strategy):
    def __init__(self, config: EMACrossConfig):
        super().__init__(config)
        self.ema_fast = ExponentialMovingAverage(config.fast_ema)
        self.ema_slow = ExponentialMovingAverage(config.slow_ema)
        self._prev_diff: float | None = None

    def on_start(self):
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            raise RuntimeError(f"Instrument nahi mila: {self.config.instrument_id}")
        self.register_indicator_for_bars(self.config.bar_type, self.ema_fast)
        self.register_indicator_for_bars(self.config.bar_type, self.ema_slow)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        if not (self.ema_fast.initialized and self.ema_slow.initialized):
            return  # indicator warmup
        diff = self.ema_fast.value - self.ema_slow.value
        if self._prev_diff is None:
            self._prev_diff = diff
            return
        crossed_up = self._prev_diff <= 0 < diff
        crossed_down = self._prev_diff >= 0 > diff
        self._prev_diff = diff

        if crossed_up and self.portfolio.is_flat(self.config.instrument_id):
            self._enter(OrderSide.BUY)
        elif crossed_down and not self.portfolio.is_flat(self.config.instrument_id):
            self.close_all_positions(self.config.instrument_id)

    def _enter(self, side: OrderSide):
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=Quantity.from_int(self.config.quantity),
        ))

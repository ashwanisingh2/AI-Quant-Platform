"""Nautilus adapter around the same decision kernel used by paper/live trading."""
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from apps.engine.strategies.evaluator import StrategyEvaluator


class SharedStrategy(Strategy):
    kernel_name = 'ema_cross'
    parameter_names = ('fast_ema', 'slow_ema', 'quantity')

    def __init__(self, config):
        super().__init__(config)
        self.evaluator = StrategyEvaluator(self.kernel_name, {
            name: getattr(config, name) for name in self.parameter_names})
        self.signal_trace = []

    def on_start(self):
        if self.cache.instrument(self.config.instrument_id) is None:
            raise RuntimeError('Instrument is not loaded')
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar):
        held = int(self.portfolio.net_position(self.config.instrument_id))
        signal = self.evaluator.on_price(bar.close.as_double(), held)
        self.signal_trace.append({'timestamp_ns': bar.ts_event, 'held_qty': held,
                                  'signal': signal})
        if signal is None:
            return
        if signal['side'] == 'SELL':
            self.close_all_positions(self.config.instrument_id)
        else:
            self.submit_order(self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY, quantity=Quantity.from_int(signal['qty'])))

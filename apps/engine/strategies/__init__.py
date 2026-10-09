"""Strategy registry — naya strategy yahin register karo."""
from apps.engine.strategies.atm_call_buy import ATMCallBuy, ATMCallBuyConfig
from apps.engine.strategies.ema_cross import EMACross, EMACrossConfig
from apps.engine.strategies.rsi_reversion import RSIReversion, RSIReversionConfig

STRATEGIES = {
    "ema_cross": {
        "class": EMACross,
        "config": EMACrossConfig,
        "defaults": {"fast_ema": 10, "slow_ema": 30, "quantity": 100},
        "description": "EMA crossover — trend-following (fast/slow EMA cross)",
    },
    "rsi": {
        "class": RSIReversion,
        "config": RSIReversionConfig,
        "defaults": {"period": 14, "oversold": 30.0, "overbought": 70.0, "quantity": 100},
        "description": "RSI mean-reversion (oversold → buy, overbought → sell)",
    },
    "atm_call_buy": {
        "class": ATMCallBuy,
        "config": ATMCallBuyConfig,
        "defaults": {"fast_ema": 10, "slow_ema": 30, "quantity": 75},
        "description": "ATM call buyer — F&O options BUY only (EMA cross on premium, long exit)",
    },
}

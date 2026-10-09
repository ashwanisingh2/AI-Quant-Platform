"""Shared data models — poori platform yeh models use karegi.

Sab timestamps: IST, naive (timezone-naive datetime, IST wall time).
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"          # NSE derivatives (F&O)
    BINANCE = "BINANCE"  # crypto (baad mein)


class InstrumentType(str, Enum):
    EQ = "EQ"    # equity
    FUT = "FUT"  # futures
    CE = "CE"    # call option
    PE = "PE"    # put option


class Instrument(BaseModel):
    exchange: Exchange
    symbol: str
    isin: str | None = None
    instrument_type: InstrumentType = InstrumentType.EQ
    lot_size: int = 1
    tick_size: float = 0.05
    expiry: date | None = None  # F&O ke liye

    @property
    def key(self) -> str:
        return f"{self.exchange.value}:{self.symbol}"


class Candle(BaseModel):
    """OHLCV candle. timestamp = candle ki shuruaat (IST)."""
    instrument: str   # key format: "NSE:RELIANCE"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    @model_validator(mode="after")
    def _check_ohlc(self) -> "Candle":
        lo, hi = min(self.open, self.close), max(self.open, self.close)
        if not (self.low <= lo and hi <= self.high):
            raise ValueError(
                f"Invalid OHLC: low={self.low} open={self.open} "
                f"close={self.close} high={self.high}"
            )
        if self.low <= 0:
            raise ValueError("Prices must be positive")
        return self


class Tick(BaseModel):
    """Live tick — Phase 3 (live data) mein use hoga."""
    instrument: str
    timestamp: datetime
    last_price: float
    volume: int = 0


def instrument_key(exchange: str | Exchange, symbol: str) -> str:
    """'NSE', 'RELIANCE' → 'NSE:RELIANCE'"""
    ex = exchange.value if isinstance(exchange, Exchange) else exchange
    return f"{ex}:{symbol}"


# ============================================================
# 🤖 Phase 2 — AI Agent models
# ============================================================

class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"   # exit long / go short
    HOLD = "HOLD"


class Signal(BaseModel):
    """AI/strategy se nikla trading signal."""
    instrument: str
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0)
    target_price: float | None = None
    stoploss: float | None = None
    size_hint: int | None = None
    reasoning: str = ""
    status: str = "pending"  # pending | approved | rejected | executed | expired
    created_at: datetime = Field(default_factory=datetime.now)


class MarketSnapshot(BaseModel):
    """Analyst agent ko diya jane wala market ka summary."""
    instrument: str
    timestamp: datetime
    current_price: float
    change_1d_pct: float | None = None
    change_5d_pct: float | None = None
    sma_10: float | None = None
    sma_30: float | None = None
    rsi_14: float | None = None
    volatility_20d_pct: float | None = None
    window_high: float
    window_low: float
    avg_volume_20: int | None = None
    trend: str = "unknown"  # up | down | sideways | unknown
    recent_closes: list[float] = []
    news: list[str] = []


class PortfolioState(BaseModel):
    """Risk agent ko diya jane wala portfolio state."""
    cash: float
    total_value: float
    positions_value: float = 0.0
    open_positions: int = 0
    current_drawdown_pct: float = 0.0
    daily_pnl_pct: float = 0.0


class AgentStep(BaseModel):
    """Pipeline ka ek step — kis agent ne kya kiya, kitna token/kharcha."""
    agent: str  # analyst | trader | risk
    model: str
    output: str
    tokens: int
    cost_inr: float
    duration_ms: int


class AgentRun(BaseModel):
    """Poora agent run — reasoning trace + final signal."""
    id: str
    instrument: str
    strategy: str
    steps: list[AgentStep]
    final_signal: Signal
    risk_decision: dict
    risk_explanation: str
    total_tokens: int
    total_cost_inr: float
    duration_ms: int
    llm_provider: str
    status: str = "pending"  # MVP: human approval
    created_at: datetime = Field(default_factory=datetime.now)

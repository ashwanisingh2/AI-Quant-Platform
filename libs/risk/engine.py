"""Risk Engine — har order iske bina broker nahi pahunch sakta. 🛡️

Sab rules yahin, audit trail ke saath. Live trading se pehle yeh MANDATORY hai.

Checks (har order pe):
  1. kill switch        7. max open positions
  2. trading hours      8. daily loss limit
  3. instrument whitelist  9. max drawdown
  4. strategy whitelist 10. AI min confidence
  5. price deviation    11. order rate limit
  6. position value cap
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone


@dataclass
class RiskLimits:
    max_position_pct: float = 0.20          # ek instrument: max % of capital
    max_open_positions: int = 5
    max_position_value: float = 200_000.0   # ek instrument: absolute cap (₹)
    daily_loss_limit_pct: float = 3.0       # din mein max loss %
    max_drawdown_pct: float = 10.0          # overall drawdown → kill
    min_confidence: float = 0.6             # AI signals ke liye
    max_orders_per_minute: int = 5
    max_price_deviation_pct: float = 10.0   # reference price se deviation (circuit sanity)
    allowed_instruments: list[str] | None = None   # whitelist (None = sab allowed)
    allowed_strategies: list[str] | None = None
    trading_hours_only: bool = True
    market_open: str = "09:15"
    market_close: str = "15:30"


@dataclass
class RiskContext:
    capital: float
    cash: float
    positions_value: float          # is instrument mein current exposure (₹)
    open_positions: int
    daily_pnl_pct: float
    current_drawdown_pct: float
    reference_price: float
    instrument: str
    now: datetime | None = None     # IST; None → abhi


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    checks: list[dict] = field(default_factory=list)  # audit trail

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "checks": self.checks}


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.killed = False
        self._order_times: list[datetime] = []

    def kill(self):
        self.killed = True

    def reset_kill(self):
        self.killed = False

    @staticmethod
    def _now_ist() -> datetime:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))

    def check_order(self, side: str, qty: int, price: float, ctx: RiskContext,
                    strategy: str = "", confidence: float | None = None) -> RiskDecision:
        checks: list[dict] = []

        def add(name: str, passed: bool, detail: str) -> bool:
            checks.append({"check": name, "passed": bool(passed), "detail": detail})
            return bool(passed)

        # 1. kill switch
        if not add("kill_switch", not self.killed, "KILLED" if self.killed else "active"):
            return self._deny("🚨 Kill switch active", checks)

        # 2. trading hours (IST, Mon-Fri)
        if self.limits.trading_hours_only:
            now = ctx.now or self._now_ist()
            oh, om = map(int, self.limits.market_open.split(":"))
            ch, cm = map(int, self.limits.market_close.split(":"))
            t = now.time()
            in_hours = time(oh, om) <= t <= time(ch, cm) and now.weekday() < 5
            if not add("trading_hours", in_hours,
                       f"{now.strftime('%a %H:%M')} — market {'open' if in_hours else 'BAND'}"):
                return self._deny("Market band hai (trading hours ke bahar)", checks)

        # 3. instrument whitelist
        if self.limits.allowed_instruments is not None:
            ok = ctx.instrument in self.limits.allowed_instruments
            if not add("instrument_whitelist", ok, ctx.instrument):
                return self._deny(f"Instrument allowed nahi hai: {ctx.instrument}", checks)

        # 4. strategy whitelist
        if self.limits.allowed_strategies is not None and strategy:
            ok = strategy in self.limits.allowed_strategies
            if not add("strategy_whitelist", ok, strategy):
                return self._deny(f"Strategy allowed nahi hai: {strategy}", checks)

        # 5. price deviation (circuit sanity)
        if ctx.reference_price > 0:
            dev = abs(price - ctx.reference_price) / ctx.reference_price * 100
            ok = dev <= self.limits.max_price_deviation_pct
            if not add("price_deviation", ok,
                       f"{dev:.2f}% (max {self.limits.max_price_deviation_pct}%)"):
                return self._deny(f"Price deviation zyada hai: {dev:.2f}%", checks)

        # 6. position value cap (pct of capital + absolute)
        new_value = qty * price if side == "BUY" else 0.0
        total_value = ctx.positions_value + new_value
        ok = (total_value <= ctx.capital * self.limits.max_position_pct
              and total_value <= self.limits.max_position_value)
        if not add("position_value_cap", ok,
                   f"₹{total_value:,.0f} (max {self.limits.max_position_pct * 100:.0f}% / ₹{self.limits.max_position_value:,.0f})"):
            return self._deny("Position size limit cross ho gaya", checks)

        # 7. max open positions (nayi position ke liye)
        if side == "BUY" and ctx.open_positions >= self.limits.max_open_positions:
            if not add("max_open_positions", False, f"{ctx.open_positions} open"):
                return self._deny("Max open positions pahunch gaye", checks)
        else:
            add("max_open_positions", True, f"{ctx.open_positions} open")

        # 8. daily loss limit
        if ctx.daily_pnl_pct <= -self.limits.daily_loss_limit_pct:
            if not add("daily_loss_limit", False, f"{ctx.daily_pnl_pct:.2f}%"):
                return self._deny("Daily loss limit hit — aaj ke liye band", checks)
        else:
            add("daily_loss_limit", True, f"{ctx.daily_pnl_pct:.2f}%")

        # 9. max drawdown
        if ctx.current_drawdown_pct <= -self.limits.max_drawdown_pct:
            if not add("max_drawdown", False, f"{ctx.current_drawdown_pct:.2f}%"):
                return self._deny("Max drawdown hit — kill switch territory", checks)
        else:
            add("max_drawdown", True, f"{ctx.current_drawdown_pct:.2f}%")

        # 10. AI confidence (agar diya ho)
        if confidence is not None:
            ok = confidence >= self.limits.min_confidence
            if not add("min_confidence", ok,
                       f"{confidence:.2f} (min {self.limits.min_confidence})"):
                return self._deny(f"Confidence kam hai: {confidence:.2f}", checks)

        # 11. order rate limit
        now = ctx.now or self._now_ist()
        cutoff = now.timestamp() - 60
        self._order_times = [t for t in self._order_times if t.timestamp() > cutoff]
        ok = len(self._order_times) < self.limits.max_orders_per_minute
        if not add("rate_limit", ok,
                   f"{len(self._order_times)}/{self.limits.max_orders_per_minute} per min"):
            return self._deny("Order rate limit hit", checks)
        self._order_times.append(now)

        return RiskDecision(allowed=True, reason="Saare checks pass", checks=checks)

    def _deny(self, reason: str, checks: list[dict]) -> RiskDecision:
        return RiskDecision(allowed=False, reason=reason, checks=checks)

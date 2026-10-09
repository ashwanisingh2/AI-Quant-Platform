"""Live Trader — live data + broker. Default: dry_run (simulated orders).

Modes:
  dry_run → Kite data (ya replay) + simulated broker — bina paisa lagaye live jaisa
  live    → REAL Kite orders — real money! (gated: env + confirm + max capital)

Har order RiskEngine se guzarta hai — bina check ke broker nahi pahunch sakta.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from apps.engine.brokers.kite_broker import KiteBroker
from apps.engine.strategies.evaluator import StrategyEvaluator
from libs.risk.engine import RiskContext, RiskEngine, RiskLimits
from libs.shared.models import Candle
from libs.storage.parquet_store import ParquetStore


# ---------- price sources ----------
class ReplayPriceSource:
    """Stored candles ko live feed ki tarah (dry-run testing ke liye)."""

    def __init__(self, instrument: str, speed: float = 1.0, limit: int = 150):
        self.instrument = instrument
        self.speed = speed
        self.limit = limit
        self._candles: list[Candle] = []
        self._idx = 0
        self.exhausted = False

    def load(self):
        self._candles = ParquetStore().read_candles(self.instrument)[-self.limit:]
        if len(self._candles) < 35:
            raise ValueError(f"{self.instrument}: kam se kam 35 candles chahiye")

    async def get_price(self) -> tuple[float, str] | None:
        if self._idx >= len(self._candles):
            self.exhausted = True
            return None
        c = self._candles[self._idx]
        self._idx += 1
        await asyncio.sleep(self.speed)
        return c.close, str(c.timestamp.date())


class KiteQuotePriceSource:
    """Kite se live LTP poll karta hai (REST quote API)."""

    def __init__(self, exchange: str, symbol: str, api_key: str | None = None,
                 access_token: str | None = None, poll_interval: float = 2.0):
        self.exchange = exchange
        self.symbol = symbol
        self.poll_interval = poll_interval
        self.last_error: str | None = None
        self._kite = None
        if api_key:
            from kiteconnect import KiteConnect  # lazy — optional dependency
            self._kite = KiteConnect(api_key=api_key)
            if access_token:
                self._kite.set_access_token(access_token)

    async def get_price(self) -> tuple[float, str] | None:
        if self._kite is None:
            return None
        try:
            q = await asyncio.to_thread(self._kite.quote, f"{self.exchange}:{self.symbol}")
            data = q[f"{self.exchange}:{self.symbol}"]
            lp = data.get("last_price")
            if lp:
                return lp, datetime.now(timezone.utc).isoformat()
        except Exception as e:
            self.last_error = str(e)
        return None


class DhanQuotePriceSource:
    """Dhan se live LTP poll karta hai (dhanhq ticker_data REST)."""

    SEGMENTS = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}

    def __init__(self, exchange: str, symbol: str, client_id: str | None = None,
                 access_token: str | None = None, poll_interval: float = 2.0):
        self.exchange = exchange
        self.symbol = symbol
        self.poll_interval = poll_interval
        self.last_error: str | None = None
        self._dhan = None
        self._token: str | None = None
        if client_id:
            from dhanhq import DhanContext, dhanhq  # lazy — optional dependency
            self._dhan = dhanhq(DhanContext(client_id, access_token))

    async def get_price(self) -> tuple[float, str] | None:
        if self._dhan is None:
            return None
        try:
            if self._token is None:
                # security_id resolve (scrip master se — pehli baar slow, cache ho jata hai)
                from apps.engine.brokers.dhan_broker import resolve_security_id
                self._token = await asyncio.to_thread(
                    resolve_security_id, self._dhan, self.exchange, self.symbol)
            seg = self.SEGMENTS.get(self.exchange, "NSE_EQ")
            df = await asyncio.to_thread(
                self._dhan.ticker_data, {"securities": {seg: [int(self._token)]}}
            )
            rows = df.to_dict("records") if hasattr(df, "to_dict") else list(df or [])
            if rows:
                row = rows[0]
                lp = row.get("last_price") or row.get("LTP") or row.get("ltp")
                if lp:
                    return float(lp), datetime.now(timezone.utc).isoformat()
        except Exception as e:
            self.last_error = str(e)
        return None


class UpstoxQuotePriceSource:
    """Upstox se live LTP poll karta hai (upstox_client MarketQuoteApi)."""

    def __init__(self, exchange: str, symbol: str, access_token: str | None = None,
                 poll_interval: float = 2.0):
        self.exchange = exchange
        self.symbol = symbol
        self.poll_interval = poll_interval
        self.last_error: str | None = None
        self._api = None
        self._token: str | None = None
        if access_token:
            import upstox_client  # lazy — optional dependency
            configuration = upstox_client.Configuration()
            configuration.access_token = access_token
            self._api = upstox_client.MarketQuoteApi(upstox_client.ApiClient(configuration))

    async def get_price(self) -> tuple[float, str] | None:
        if self._api is None:
            return None
        try:
            if self._token is None:
                seg = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}.get(self.exchange, "NSE_EQ")
                self._token = f"{seg}|{self.symbol}"
            resp = await asyncio.to_thread(
                self._api.get_ltp, instrument_key=self._token, api_version="2.0")
            data = getattr(resp, "data", None)
            if isinstance(data, dict) and data:
                row = data.get(self._token) or next(iter(data.values()))
                lp = row.get("last_price") or row.get("lastPrice") if isinstance(row, dict) else None
                if lp:
                    return float(lp), datetime.now(timezone.utc).isoformat()
        except Exception as e:
            self.last_error = str(e)
        return None


class FyersQuotePriceSource:
    """Fyers se live LTP poll karta hai (fyersModel.quotes)."""

    def __init__(self, exchange: str, symbol: str, client_id: str | None = None,
                 access_token: str | None = None, poll_interval: float = 2.0):
        self.exchange = exchange
        self.symbol = symbol
        self.poll_interval = poll_interval
        self.last_error: str | None = None
        self._fyers = None
        if client_id and access_token:
            from fyers_apiv3 import fyersModel  # lazy — optional dependency
            self._fyers = fyersModel.fyersModel(
                client_id=client_id, token=access_token, is_async=False, log_path="")

    async def get_price(self) -> tuple[float, str] | None:
        if self._fyers is None:
            return None
        try:
            fsym = f"{self.exchange}:{self.symbol}-EQ"
            resp = await asyncio.to_thread(self._fyers.quotes, {"symbols": fsym})
            for row in resp.get("d", []):
                if row.get("n") == fsym and isinstance(row.get("v"), dict):
                    lp = row["v"].get("lp")
                    if lp:
                        return float(lp), datetime.now(timezone.utc).isoformat()
        except Exception as e:
            self.last_error = str(e)
        return None


# ---------- live trader ----------
class LiveTrader:
    def __init__(self, instrument: str, strategy: str = "ema_cross",
                 params: dict | None = None, broker: KiteBroker | None = None,
                 risk_engine: RiskEngine | None = None, price_source=None,
                 on_event=None, signal_registry=None, capital: float = 100_000,
                 product: str = "CNC", trading_hours_only: bool = True):
        self.instrument = instrument  # "NSE:TESTCO"
        self.exchange, _, self.symbol = instrument.partition(":")
        self.strategy = strategy
        self.params = params or {}
        self.broker = broker or KiteBroker(dry_run=True)
        self.risk = risk_engine or RiskEngine(
            RiskLimits(trading_hours_only=trading_hours_only))
        self.price_source = price_source
        self.on_event = on_event
        self.signal_registry = signal_registry
        self.capital = capital
        self.product = product

        self._evaluator = (StrategyEvaluator(strategy, self.params)
                           if strategy != "ai_agent" else None)
        self.running = False
        self.killed = False
        self._task: asyncio.Task | None = None
        self._last_price: float | None = None
        self.equity_curve: list[float] = []
        self._day_start_equity = capital
        self._peak_equity = capital
        self._executed_signals: set[str] = set()

    async def start(self):
        if isinstance(self.price_source, ReplayPriceSource):
            self.price_source.load()
        conn = await asyncio.to_thread(self.broker.connect)
        self.running = True
        self._task = asyncio.create_task(self._loop())
        await self._emit({"type": "live.started", "mode": self.broker.mode,
                          "instrument": self.instrument, "connection": conn})

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()

    def kill(self):
        """🚨 Kill switch — open orders cancel + saari positions square off."""
        self.killed = True
        self.running = False
        self.risk.kill()
        try:
            cancelled = [self.broker.cancel_order(o["order_id"])
                         for o in self.broker.open_orders()]
            squared = self.broker.square_off_all()
        except Exception as e:
            cancelled, squared = [], [{"error": str(e)}]
        if self._task:
            self._task.cancel()
        self._emit_soon({"type": "kill", "cancelled_orders": len(cancelled),
                         "squared_off": len(squared)})

    async def _loop(self):
        try:
            while self.running and not self.killed:
                tick = await self.price_source.get_price()
                if tick is None:
                    if getattr(self.price_source, "exhausted", False):
                        # replay data khatam → live feed ki tarah band
                        self.running = False
                        await self._emit({"type": "live.finished",
                                          "reason": "data khatam ho gaya"})
                        break
                    await asyncio.sleep(1)
                    continue
                price, ts = tick
                await self._on_price(price, ts)
        except asyncio.CancelledError:
            pass

    async def _on_price(self, price: float, ts: str):
        self._last_price = price
        self.broker.set_price(price)

        self._check_ai_signals(price)
        if self._evaluator is not None:
            sig = self._evaluator.on_price(price, self._held_qty())
            if sig:
                self._maybe_execute(sig["side"], sig["qty"], price,
                                    sig["reason"], strategy=self.strategy)

        eq = self.equity()
        self.equity_curve.append(round(eq, 2))
        self._peak_equity = max(self._peak_equity, eq)
        await self._emit({"type": "live.tick", "mode": self.broker.mode,
                          "price": price, "time": ts, "equity": round(eq, 2)})

    def _check_ai_signals(self, price: float):
        if self.signal_registry is None:
            return
        for sig in self.signal_registry.approved(self.instrument):
            run_id = sig.get("run_id")
            if run_id in self._executed_signals:
                continue
            self._executed_signals.add(run_id)
            if sig.get("direction") == "BUY":
                self._maybe_execute("BUY", sig.get("size_hint") or 100, price,
                                    f"AI signal approved (run {run_id})",
                                    strategy="ai_agent",
                                    confidence=sig.get("confidence"))
            elif sig.get("direction") == "SELL" and self._held_qty() > 0:
                self._maybe_execute("SELL", self._held_qty(), price,
                                    f"AI signal approved (run {run_id})",
                                    strategy="ai_agent",
                                    confidence=sig.get("confidence"))

    def _held_qty(self) -> int:
        for p in self.broker.positions():
            if p["symbol"] == self.symbol:
                return p["qty"]
        return 0

    def _maybe_execute(self, side: str, qty: int, price: float, reason: str,
                       strategy: str = "", confidence: float | None = None):
        eq = self.equity()
        ctx = RiskContext(
            capital=self.capital,
            cash=self._cash(),
            positions_value=abs(self._held_qty()) * price,
            open_positions=len([p for p in self.broker.positions() if p["qty"] != 0]),
            daily_pnl_pct=(eq / self._day_start_equity - 1) * 100,
            current_drawdown_pct=(eq / self._peak_equity - 1) * 100,
            reference_price=price,
            instrument=self.instrument,
            held_qty=self._held_qty(),   # F&O: exit vs naked short pata chale
        )
        decision = self.risk.check_order(side, int(qty), price, ctx,
                                         strategy=strategy, confidence=confidence)
        if not decision.allowed:
            self._emit_soon({"type": "live.rejected", "reason": decision.reason,
                             "checks": decision.checks})
            return None
        order = self.broker.place_market_order(
            self.exchange, self.symbol, side, int(qty), product=self.product)
        self._emit_soon({"type": "live.order", "order": order,
                         "risk": decision.as_dict()})
        return order

    def _cash(self) -> float:
        if self.broker.dry_run:
            cash = float(self.capital)
            for o in self.broker.all_orders():
                if o["status"] == "COMPLETE":
                    if o["side"] == "BUY":
                        cash -= o["qty"] * o["price"]
                    else:
                        cash += o["qty"] * o["price"]
            return cash
        return self.broker.margins().get("available_cash") or 0.0

    def equity(self) -> float:
        return self._cash() + sum(
            p["qty"] * (self._last_price or 0) for p in self.broker.positions())

    def state(self) -> dict:
        return {
            "running": self.running,
            "killed": self.killed,
            "mode": self.broker.mode,
            "instrument": self.instrument,
            "strategy": self.strategy,
            "product": self.product,
            "cash": round(self._cash(), 2),
            "positions": self.broker.positions(),
            "open_orders": self.broker.open_orders(),
            "equity_curve": self.equity_curve,
            "initial_capital": self.capital,
            "current_equity": round(self.equity(), 2),
            "total_pnl_pct": round((self.equity() / self.capital - 1) * 100, 2),
            "risk_killed": self.risk.killed,
        }

    async def _emit(self, event: dict):
        if not self.on_event:
            return
        try:
            res = self.on_event(event)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass

    def _emit_soon(self, event: dict):
        try:
            asyncio.get_running_loop().create_task(self._emit(event))
        except RuntimeError:
            pass

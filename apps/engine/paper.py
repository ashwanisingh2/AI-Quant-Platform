"""Paper Trader — real prices (replay ya Kite live), fake money. 📄💰

MVP: lightweight paper broker. Strategy logic shared evaluator mein hai
(apps/engine/strategies/evaluator.py) — LiveTrader wohi use karta hai.
- Replay mode: stored candles ko live ki tarah ek-ek feed karta hai
- Classic strategy (ema_cross/rsi) ya approved AI signals se trade karta hai
- Kill switch: sab kuch band + saari positions close
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from apps.engine.strategies.evaluator import StrategyEvaluator
from libs.shared.models import Candle
from libs.storage.parquet_store import ParquetStore


class PaperTrader:
    def __init__(self, instrument: str, strategy: str = "ema_cross",
                 params: dict | None = None, capital: float = 1_000_000,
                 speed: float = 0.5, on_event=None, signal_registry=None,
                 limit: int = 150):
        self.instrument = instrument
        self.strategy = strategy
        self.params = params or {}
        self.capital = capital
        self.speed = speed
        self.on_event = on_event
        self.signal_registry = signal_registry
        self.limit = limit

        self.cash = capital
        self.positions: dict[str, dict] = {}   # instrument -> {qty, avg_price}
        self.orders: list[dict] = []
        self.equity_curve: list[float] = []
        self.running = False
        self.killed = False
        self._task: asyncio.Task | None = None
        self._candles: list[Candle] = []
        self._idx = 0
        self._last_price: float | None = None
        self._last_time: str = ""
        self._evaluator = (StrategyEvaluator(strategy, self.params)
                           if strategy != "ai_agent" else None)
        self._executed_signals: set[str] = set()

    # ---------- lifecycle ----------
    def load(self):
        self._candles = ParquetStore().read_candles(self.instrument)[-self.limit:]
        if len(self._candles) < 35:
            raise ValueError(
                f"{self.instrument}: kam se kam 35 candles chahiye (mile: {len(self._candles)})"
            )

    async def start(self):
        self.load()
        self.running = True
        self._task = asyncio.create_task(self._loop())
        await self._emit({"type": "paper.started", "instrument": self.instrument,
                          "strategy": self.strategy, "capital": self.capital})

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()

    def kill(self):
        """🚨 Kill switch — sab band, saari positions close."""
        self.killed = True
        self.running = False
        if self._last_price is not None:
            for inst, pos in list(self.positions.items()):
                if pos["qty"] > 0:
                    self._execute({"side": "SELL", "qty": pos["qty"],
                                   "reason": "KILL SWITCH — position close"}, self._last_price)
            self.positions.clear()
        if self._task:
            self._task.cancel()
        self._emit_soon({"type": "kill", "message": "KILL SWITCH — sab band, positions close"})

    # ---------- main loop ----------
    async def _loop(self):
        try:
            while self.running and not self.killed and self._idx < len(self._candles):
                c = self._candles[self._idx]
                self._idx += 1
                await self._on_candle(c)
                await asyncio.sleep(self.speed)
            if not self.killed and self.running:
                await self._emit({"type": "paper.finished", "reason": "data khatam ho gaya"})
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False

    async def _on_candle(self, c: Candle):
        price = c.close
        self._last_price = price
        self._last_time = str(c.timestamp.date())

        self._check_ai_signals(price)
        sig = self._eval_strategy(price)
        if sig:
            self._execute(sig, price)

        eq = self.equity()
        self.equity_curve.append(round(eq, 2))
        await self._emit({"type": "paper.tick", "instrument": self.instrument,
                          "price": price, "time": self._last_time, "equity": round(eq, 2)})

    # ---------- AI signals (approved) ----------
    def _check_ai_signals(self, price: float):
        if self.signal_registry is None:
            return
        for sig in self.signal_registry.approved(self.instrument):
            run_id = sig.get("run_id")
            if run_id in self._executed_signals:
                continue
            direction = sig.get("direction")
            qty = sig.get("size_hint") or 100
            if direction == "BUY":
                self._execute({"side": "BUY", "qty": qty,
                               "reason": f"AI signal approved (run {run_id})"}, price)
            elif direction == "SELL":
                pos = self.positions.get(self.instrument, {})
                if pos.get("qty", 0) > 0:
                    self._execute({"side": "SELL", "qty": pos["qty"],
                                   "reason": f"AI signal approved (run {run_id})"}, price)
            self._executed_signals.add(run_id)

    # ---------- classic strategies (shared evaluator) ----------
    def _eval_strategy(self, price: float) -> dict | None:
        if self._evaluator is None:
            return None
        pos = self.positions.get(self.instrument, {"qty": 0})
        return self._evaluator.on_price(price, pos.get("qty", 0))

    # ---------- paper broker ----------
    def _execute(self, sig: dict, price: float):
        side, qty = sig["side"], int(sig["qty"])
        pos = self.positions.get(self.instrument, {"qty": 0, "avg_price": 0.0})

        if side == "BUY":
            cost = qty * price
            max_rupees = self.capital * self.params.get("max_position_pct", 0.5)
            if cost > self.cash or cost > max_rupees:
                self._emit_soon({"type": "paper.rejected",
                                 "reason": f"Cash/position limit — need ₹{cost:,.0f}, have ₹{self.cash:,.0f}"})
                return
            new_qty = pos["qty"] + qty
            avg = (pos["qty"] * pos["avg_price"] + qty * price) / new_qty
            self.positions[self.instrument] = {"qty": new_qty, "avg_price": avg}
            self.cash -= cost
        else:  # SELL
            if pos["qty"] <= 0:
                return
            qty = min(qty, pos["qty"])
            self.cash += qty * price
            pos["qty"] -= qty
            if pos["qty"] == 0:
                self.positions[self.instrument] = {"qty": 0, "avg_price": 0.0}

        order = {
            "id": uuid.uuid4().hex[:10],
            "instrument": self.instrument,
            "side": side,
            "qty": qty,
            "price": round(price, 2),
            "time": datetime.now(timezone.utc).isoformat(),
            "status": "filled",
            "reason": sig.get("reason", ""),
        }
        self.orders.append(order)
        self._emit_soon({"type": "paper.order", "order": order})

    # ---------- state ----------
    def equity(self) -> float:
        return self.cash + sum(
            p["qty"] * (self._last_price or 0) for p in self.positions.values()
        )

    def state(self) -> dict:
        eq = self.equity()
        return {
            "running": self.running,
            "killed": self.killed,
            "instrument": self.instrument,
            "strategy": self.strategy,
            "cash": round(self.cash, 2),
            "positions": [{"instrument": k, **v} for k, v in self.positions.items()],
            "orders": self.orders[-50:],
            "n_orders": len(self.orders),
            "equity_curve": self.equity_curve,
            "initial_capital": self.capital,
            "current_equity": round(eq, 2),
            "total_pnl": round(eq - self.capital, 2),
            "total_pnl_pct": round((eq / self.capital - 1) * 100, 2),
        }

    # ---------- events ----------
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
            pass  # no running loop

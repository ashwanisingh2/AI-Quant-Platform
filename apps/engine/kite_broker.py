"""Kite Broker — Zerodha se orders. Dry-run (simulation) ya LIVE (real money!).

⚠️ dry_run=False → REAL MONEY. Sirf tab use karo jab:
  - KITE_API_KEY + KITE_ACCESS_TOKEN set hon
  - LIVE_TRADING_ENABLED=true set ho
  - Kam se kam 2-3 mahine paper trading ho chuka ho

Kite Connect API: pip install kiteconnect
"""
from __future__ import annotations

import uuid
import zlib
from datetime import datetime, timezone


class KiteBroker:
    def __init__(self, api_key: str | None = None, access_token: str | None = None,
                 dry_run: bool = True):
        self.dry_run = dry_run
        self.api_key = api_key
        self._kite = None
        self._last_price: float | None = None
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}   # symbol → {exchange, qty, avg_price}
        self._token_cache: dict[tuple[str, str], int] = {}
        if not dry_run:
            from kiteconnect import KiteConnect  # lazy — optional dependency
            if not api_key:
                raise ValueError("KITE_API_KEY missing (live mode)")
            self._kite = KiteConnect(api_key=api_key)
            if access_token:
                self._kite.set_access_token(access_token)

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "LIVE ⚠️ REAL MONEY"

    # ---------- connection ----------
    def connect(self) -> dict:
        """Connection test + reconciliation (real positions/orders sync — startup pe zaroori)."""
        if self.dry_run:
            return {"mode": "dry_run", "status": "connected (simulated)"}
        profile = self._kite.profile()  # token invalid → yahin fail hoga
        self._reconcile()
        return {"mode": "live", "status": "connected", "user": profile.get("user_name")}

    def _reconcile(self):
        """Broker pe maujood positions/orders ko local state mein sync karo."""
        if self.dry_run:
            return
        for pos in self._kite.positions().get("net", []):
            if pos["quantity"] != 0:
                self._positions[pos["tradingsymbol"]] = {
                    "exchange": pos.get("exchange", "NSE"),
                    "qty": pos["quantity"],
                    "avg_price": pos["average_price"],
                }
        for o in self._kite.orders():
            if o["status"] in ("OPEN", "TRIGGER PENDING"):
                self._orders[o["order_id"]] = self._to_local_order(o)

    # ---------- instruments ----------
    def resolve_token(self, exchange: str, symbol: str) -> int:
        key = (exchange, symbol)
        if key not in self._token_cache:
            if self.dry_run:
                self._token_cache[key] = zlib.crc32(f"{exchange}:{symbol}".encode()) % 900_000 + 100_000
            else:
                for inst in self._kite.instruments(exchange):
                    if inst.get("tradingsymbol") == symbol:
                        self._token_cache[key] = inst["instrument_token"]
                        break
                else:
                    raise ValueError(f"Instrument nahi mila: {exchange}:{symbol}")
        return self._token_cache[key]

    # ---------- pricing ----------
    def set_price(self, price: float):
        self._last_price = price

    def quote(self, exchange: str, symbol: str) -> dict:
        if self.dry_run:
            return {"instrument": f"{exchange}:{symbol}",
                    "last_price": self._last_price, "source": "dry_run"}
        data = self._kite.quote(f"{exchange}:{symbol}")[f"{exchange}:{symbol}"]
        return {"instrument": f"{exchange}:{symbol}", "last_price": data["last_price"],
                "ohlc": data.get("ohlc"), "source": "kite"}

    # ---------- orders ----------
    def place_market_order(self, exchange: str, symbol: str, side: str,
                           qty: int, product: str = "CNC") -> dict:
        """side: BUY|SELL → local order dict."""
        if self.dry_run:
            price = self._last_price
            if price is None:
                raise ValueError("dry_run: pehle set_price() karo")
            order = {
                "order_id": f"DRY-{uuid.uuid4().hex[:10]}",
                "exchange": exchange, "symbol": symbol, "side": side,
                "qty": qty, "product": product, "order_type": "MARKET",
                "price": price, "status": "COMPLETE", "filled_qty": qty,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._orders[order["order_id"]] = order
            self._apply_fill(order)
            return order

        resp = self._kite.place_order(
            variety="regular", exchange=exchange, tradingsymbol=symbol,
            transaction_type=side, quantity=qty, product=product, order_type="MARKET",
        )
        order_id = resp["order_id"]
        for o in self._kite.orders():
            if o["order_id"] == order_id:
                order = self._to_local_order(o)
                self._orders[order_id] = order
                if order["status"] == "COMPLETE":
                    self._apply_fill(order)
                return order
        return {"order_id": order_id, "status": "OPEN", "symbol": symbol,
                "side": side, "qty": qty, "exchange": exchange}

    @staticmethod
    def _to_local_order(o: dict) -> dict:
        return {
            "order_id": o["order_id"], "exchange": o.get("exchange"),
            "symbol": o.get("tradingsymbol"), "side": o.get("transaction_type"),
            "qty": o.get("quantity"), "product": o.get("product"),
            "order_type": o.get("order_type"),
            "price": o.get("average_price") or o.get("price"),
            "status": o.get("status"), "filled_qty": o.get("filled_quantity", 0),
            "ts": o.get("order_timestamp"),
        }

    def _apply_fill(self, order: dict):
        symbol = order["symbol"]
        pos = self._positions.setdefault(
            symbol, {"exchange": order.get("exchange", "NSE"), "qty": 0, "avg_price": 0.0}
        )
        if order["side"] == "BUY":
            new_qty = pos["qty"] + order["qty"]
            if new_qty > 0:
                pos["avg_price"] = (pos["qty"] * pos["avg_price"] + order["qty"] * order["price"]) / new_qty
            pos["qty"] = new_qty
        else:
            pos["qty"] -= order["qty"]
            if pos["qty"] <= 0:
                pos["qty"] = 0
                pos["avg_price"] = 0.0

    def cancel_order(self, order_id: str) -> dict:
        if self.dry_run:
            o = self._orders.get(order_id)
            if o and o["status"] in ("OPEN", "TRIGGER PENDING"):
                o["status"] = "CANCELLED"
                return o
            return {"order_id": order_id, "status": "NOT_FOUND"}
        self._kite.cancel_order(variety="regular", order_id=order_id)
        o = self._orders.get(order_id)
        if o:
            o["status"] = "CANCELLED"
        return o or {"order_id": order_id, "status": "CANCELLED"}

    def open_orders(self) -> list[dict]:
        if self.dry_run:
            return [o for o in self._orders.values()
                    if o["status"] in ("OPEN", "TRIGGER PENDING")]
        return [self._to_local_order(o) for o in self._kite.orders()
                if o["status"] in ("OPEN", "TRIGGER PENDING")]

    def all_orders(self) -> list[dict]:
        if self.dry_run:
            return list(self._orders.values())
        return [self._to_local_order(o) for o in self._kite.orders()]

    def positions(self) -> list[dict]:
        if self.dry_run:
            return [{"symbol": k, **v} for k, v in self._positions.items()]
        return [{"symbol": p["tradingsymbol"], "exchange": p.get("exchange"),
                 "qty": p["quantity"], "avg_price": p["average_price"],
                 "pnl": p.get("pnl", 0)}
                for p in self._kite.positions().get("net", [])]

    def margins(self) -> dict:
        if self.dry_run:
            return {"available_cash": None, "source": "dry_run"}
        return {"available_cash": self._kite.margins().get("available", {}).get("cash"),
                "source": "kite"}

    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (opposite market orders)."""
        results = []
        for pos in self.positions():
            if pos["qty"] != 0:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                results.append(self.place_market_order(
                    pos.get("exchange", "NSE"), pos["symbol"], side, abs(pos["qty"])))
        return results

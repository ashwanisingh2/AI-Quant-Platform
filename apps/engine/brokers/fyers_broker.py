"""Fyers Broker — brokers registry mein 'fyers'. 🟢

Fyers se orders via official fyers-apiv3 (fyers_apiv3.fyersModel).
Dry-run (simulation) ya LIVE (real money!).

⚠️ dry_run=False → REAL MONEY. Sirf tab use karo jab:
  - FYERS_CLIENT_ID + FYERS_ACCESS_TOKEN set hon
  - LIVE_TRADING_ENABLED=true set ho
  - Kam se kam 2-3 mahine paper trading ho chuka ho

Fyers SDK: pip install fyers-apiv3  (ya: pip install .[fyers])

Fyers ki alag baatein yaad rakho:
  - symbol format = "NSE:SBIN-EQ" (exchange:tradingsymbol-EQ) — seedha "NSE:SBIN" nahi
  - order type: 2 = MARKET · side: 1 = BUY, -1 = SELL (numbers, not strings!)
  - product: "CNC" (delivery), "INTRADAY" (MIS)
  - order status (int): 1=cancelled, 2=traded, 4=transit, 5=rejected, 6=pending, 7=expired
  - position symbol mein product suffix hota hai: "NSE:SBIN-EQ-CNC"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apps.engine.brokers import register_broker
from apps.engine.brokers.base import BrokerBase


@register_broker
class FyersBroker(BrokerBase):
    name = "fyers"
    required_env = ("FYERS_CLIENT_ID", "FYERS_ACCESS_TOKEN")

    #: hamara product → Fyers ka productType
    PRODUCTS = {"CNC": "CNC", "MIS": "INTRADAY"}
    #: hamara side → Fyers ka side (number)
    SIDES = {"BUY": 1, "SELL": -1}
    #: Fyers order status (int) → hamara status
    STATUS_MAP = {
        1: "CANCELLED",   # cancelled
        2: "COMPLETE",    # traded
        4: "OPEN",        # transit
        5: "REJECTED",    # rejected
        6: "OPEN",        # pending
        7: "CANCELLED",   # expired
    }
    ORDER_TYPE_MARKET = 2

    def __init__(self, client_id: str | None = None, access_token: str | None = None,
                 dry_run: bool = True):
        super().__init__(dry_run)
        self.client_id = client_id
        self._fyers = None
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}   # symbol → {exchange, qty, avg_price}
        if not dry_run:
            from fyers_apiv3 import fyersModel  # lazy — optional dependency
            if not client_id or not access_token:
                raise ValueError("FYERS_CLIENT_ID / FYERS_ACCESS_TOKEN missing (live mode)")
            self._fyers = fyersModel.fyersModel(
                client_id=client_id, token=access_token, is_async=False, log_path="")

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "LIVE ⚠️ REAL MONEY (Fyers)"

    @staticmethod
    def fyers_symbol(exchange: str, symbol: str) -> str:
        """Hamara "NSE:SBIN" → Fyers ka "NSE:SBIN-EQ"."""
        if exchange not in ("NSE", "BSE"):
            raise ValueError(f"Fyers pe exchange nahi hai: {exchange} (supported: NSE, BSE)")
        return f"{exchange}:{symbol}-EQ"

    @staticmethod
    def _product(product: str) -> str:
        p = FyersBroker.PRODUCTS.get(product)
        if p is None:
            raise ValueError(f"Fyers pe product nahi hai: {product} (supported: {sorted(FyersBroker.PRODUCTS)})")
        return p

    # ---------- connection ----------
    def connect(self) -> dict:
        """Connection test + reconciliation (real positions/orders sync — startup pe zaroori)."""
        if self.dry_run:
            return {"mode": "dry_run", "status": "connected (simulated)"}
        self._fyers.funds()  # token invalid → yahin fail hoga
        self._reconcile()
        return {"mode": "live", "status": "connected"}

    def _reconcile(self):
        """Broker pe maujood positions/orders ko local state mein sync karo."""
        if self.dry_run:
            return
        for pos in self._fyers.positions().get("netPositions", []):
            qty = int(pos.get("netQty") or 0)
            if qty != 0:
                self._positions[self._strip_suffix(pos.get("symbol", ""))] = {
                    "exchange": "NSE",
                    "qty": qty,
                    "avg_price": float(pos.get("avgPrice") or pos.get("buyAvg") or 0.0),
                }
        for o in self._fyers.orderbook().get("d", []):
            if self.STATUS_MAP.get(int(o.get("status", 0)), "OPEN") == "OPEN":
                self._orders[str(o.get("id", ""))] = self._to_local_order(o)

    @staticmethod
    def _strip_suffix(fyers_symbol: str) -> str:
        """"NSE:SBIN-EQ-CNC" → "SBIN" (product + EQ suffix hatao)."""
        sym = fyers_symbol.split(":", 1)[-1] if ":" in fyers_symbol else fyers_symbol
        for suffix in ("-CNC", "-INTRADAY", "-MARGIN", "-CO", "-BO"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
                break
        if sym.endswith("-EQ"):
            sym = sym[: -len("-EQ")]
        return sym

    # ---------- instruments ----------
    def resolve_token(self, exchange: str, symbol: str) -> str:
        """Fyers mein symbol hi key hai ("NSE:SBIN-EQ") — token resolve ki zaroorat nahi."""
        return self.fyers_symbol(exchange, symbol)

    # ---------- pricing ----------
    def quote(self, exchange: str, symbol: str) -> dict:
        if self.dry_run:
            return {"instrument": f"{exchange}:{symbol}",
                    "last_price": self._last_price, "source": "dry_run"}
        fsym = self.fyers_symbol(exchange, symbol)
        resp = self._fyers.quotes({"symbols": fsym})
        ltp = None
        for row in resp.get("d", []):
            if row.get("n") == fsym and isinstance(row.get("v"), dict):
                ltp = row["v"].get("lp")
                break
        return {"instrument": f"{exchange}:{symbol}", "last_price": ltp, "source": "fyers"}

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

        fsym = self.fyers_symbol(exchange, symbol)
        resp = self._fyers.place_order(data={
            "symbol": fsym,
            "qty": int(qty),
            "type": self.ORDER_TYPE_MARKET,   # 2 = MARKET
            "side": self.SIDES[side],         # 1 = BUY, -1 = SELL
            "productType": self._product(product),
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        })
        order_id = str(resp.get("id", ""))
        # latest status le aao
        order = {"order_id": order_id, "symbol": symbol, "exchange": exchange,
                 "side": side, "qty": qty, "status": "OPEN"}
        try:
            for o in self._fyers.orderbook().get("d", []):
                if str(o.get("id", "")) == order_id:
                    order = self._to_local_order(o)
                    break
        except Exception:
            pass
        self._orders[order_id] = order
        if order["status"] == "COMPLETE":
            self._apply_fill(order)
        return order

    def _to_local_order(self, o: dict) -> dict:
        side = "BUY" if int(o.get("side", 1)) == 1 else "SELL"
        return {
            "order_id": str(o.get("id", "")),
            "exchange": "NSE",
            "symbol": self._strip_suffix(str(o.get("symbol", ""))),
            "side": side,
            "qty": int(o.get("qty", 0) or 0),
            "product": o.get("productType", ""),
            "order_type": "MARKET" if int(o.get("type", 2)) == 2 else "LIMIT",
            "price": float(o.get("tradedPrice") or o.get("limitPrice") or 0.0),
            "status": self.STATUS_MAP.get(int(o.get("status", 0)), "OPEN"),
            "filled_qty": int(o.get("filledQty", 0) or 0),
            "ts": o.get("orderTimestamp") or o.get("tradeTime"),
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
        self._fyers.cancel_order({"id": order_id})
        o = self._orders.get(order_id)
        if o:
            o["status"] = "CANCELLED"
        return o or {"order_id": order_id, "status": "CANCELLED"}

    def open_orders(self) -> list[dict]:
        if self.dry_run:
            return [o for o in self._orders.values() if o["status"] == "OPEN"]
        return [self._to_local_order(o) for o in self._fyers.orderbook().get("d", [])
                if self.STATUS_MAP.get(int(o.get("status", 0)), "OPEN") == "OPEN"]

    def all_orders(self) -> list[dict]:
        if self.dry_run:
            return list(self._orders.values())
        return [self._to_local_order(o) for o in self._fyers.orderbook().get("d", [])]

    def positions(self) -> list[dict]:
        if self.dry_run:
            return [{"symbol": k, **v} for k, v in self._positions.items()]
        out = []
        for pos in self._fyers.positions().get("netPositions", []):
            qty = int(pos.get("netQty") or 0)
            out.append({
                "symbol": self._strip_suffix(pos.get("symbol", "")),
                "exchange": "NSE",
                "qty": qty,
                "avg_price": float(pos.get("avgPrice") or pos.get("buyAvg") or 0.0),
                "pnl": float(pos.get("pnl") or pos.get("pl") or 0.0),
            })
        return out

    def margins(self) -> dict:
        if self.dry_run:
            return {"available_cash": None, "source": "dry_run"}
        cash = None
        try:
            for entry in self._fyers.funds().get("fund_limit", []):
                cash = entry.get("available_balance") or entry.get("availableBalance")
                if cash is not None:
                    break
        except Exception:
            pass
        return {"available_cash": cash, "source": "fyers"}

    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (opposite market orders)."""
        results = []
        for pos in self.positions():
            if pos["qty"] != 0:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                results.append(self.place_market_order(
                    pos.get("exchange", "NSE"), pos["symbol"], side, abs(pos["qty"])))
        return results

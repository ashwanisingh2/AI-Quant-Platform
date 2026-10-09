"""Dhan Broker — brokers registry mein 'dhan'. 🟠

Dhan (India ka #2 broker) se orders via official dhanhq library.
Dry-run (simulation) ya LIVE (real money!).

⚠️ dry_run=False → REAL MONEY. Sirf tab use karo jab:
  - DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN set hon
  - LIVE_TRADING_ENABLED=true set ho
  - Kam se kam 2-3 mahine paper trading ho chuka ho

Dhan API: pip install dhanhq  (ya: pip install .[dhan])

Dhan vs Kite — alag baatein yaad rakho:
  - instrument id = security_id (string, e.g. "1333" HDFC Bank) — kite jaisa int token nahi
  - exchange segment = "NSE_EQ" (equity) — seedha "NSE" nahi
  - product: CNC (delivery) ya INTRA (intraday) — kite ke MIS ka naam INTRA hai
  - order status: TRADED / PENDING / CANCELLED / REJECTED — kite ke COMPLETE ka naam TRADED
"""
from __future__ import annotations

import uuid
import zlib
from datetime import datetime, timezone

from apps.engine.brokers import register_broker
from apps.engine.brokers.base import BrokerBase


@register_broker
class DhanBroker(BrokerBase):
    name = "dhan"
    required_env = ("DHAN_CLIENT_ID",)

    #: hamara exchange → Dhan ka exchange segment (equity cash)
    SEGMENTS = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}
    #: hamara product → Dhan ka product type
    PRODUCTS = {"CNC": "CNC", "MIS": "INTRA"}
    #: Dhan order status → hamara status
    STATUS_MAP = {
        "TRADED": "COMPLETE", "PENDING": "OPEN", "OPEN": "OPEN",
        "CANCELLED": "CANCELLED", "REJECTED": "REJECTED", "PART_TRADED": "OPEN",
    }

    def __init__(self, client_id: str | None = None, access_token: str | None = None,
                 dry_run: bool = True):
        super().__init__(dry_run)
        self.client_id = client_id
        self._dhan = None
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}   # symbol → {exchange, qty, avg_price}
        self._token_cache: dict[tuple[str, str], str] = {}
        if not dry_run:
            from dhanhq import DhanContext, dhanhq  # lazy — optional dependency
            if not client_id:
                raise ValueError("DHAN_CLIENT_ID missing (live mode)")
            self._dhan = dhanhq(DhanContext(client_id, access_token))

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "LIVE ⚠️ REAL MONEY (Dhan)"

    def _segment(self, exchange: str) -> str:
        seg = self.SEGMENTS.get(exchange)
        if seg is None:
            raise ValueError(f"Dhan pe exchange nahi hai: {exchange} (supported: {sorted(self.SEGMENTS)})")
        return seg

    def _product(self, product: str) -> str:
        p = self.PRODUCTS.get(product)
        if p is None:
            raise ValueError(f"Dhan pe product nahi hai: {product} (supported: {sorted(self.PRODUCTS)})")
        return p

    # ---------- connection ----------
    def connect(self) -> dict:
        """Connection test + reconciliation (real positions/orders sync — startup pe zaroori)."""
        if self.dry_run:
            return {"mode": "dry_run", "status": "connected (simulated)"}
        limits = self._dhan.get_fund_limits()  # token invalid → yahin fail hoga
        self._reconcile()
        cash = None
        try:
            cash = limits.get("availabelBalance") or limits.get("availableBalance")
        except Exception:
            pass
        return {"mode": "live", "status": "connected", "available_cash": cash}

    def _reconcile(self):
        """Broker pe maujood positions/orders ko local state mein sync karo."""
        if self.dry_run:
            return
        for rec in self._records(self._dhan.get_positions()):
            qty = int(rec.get("netQty") or 0)
            if qty != 0:
                self._positions[str(rec.get("tradingSymbol") or rec.get("securityId"))] = {
                    "exchange": "NSE",
                    "qty": qty,
                    "avg_price": float(rec.get("buyAvg") or rec.get("costPrice") or 0.0),
                }
        for rec in self._records(self._dhan.get_order_list()):
            status = self.STATUS_MAP.get(str(rec.get("orderStatus", "")), "OPEN")
            if status in ("OPEN",):
                self._orders[str(rec.get("orderId"))] = self._to_local_order(rec)

    @staticmethod
    def _records(df) -> list[dict]:
        """dhanhq DataFrame → list[dict] (DataFrame ya list dono chalega)."""
        if df is None:
            return []
        if hasattr(df, "to_dict"):
            try:
                return df.to_dict("records")
            except Exception:
                return []
        return list(df)

    # ---------- instruments ----------
    def resolve_token(self, exchange: str, symbol: str) -> str:
        """Dhan security_id (string). Live: scrip-master CSV se. Dry-run: stable hash."""
        key = (exchange, symbol)
        if key not in self._token_cache:
            if self.dry_run:
                self._token_cache[key] = str(zlib.crc32(f"{exchange}:{symbol}".encode()) % 900_000 + 100_000)
            else:
                self._token_cache[key] = self._lookup_security_id(exchange, symbol)
        return self._token_cache[key]

    def _lookup_security_id(self, exchange: str, symbol: str) -> str:
        """Scrip master CSV (dhanhq) se trading symbol → security id."""
        return resolve_security_id(self._dhan, exchange, symbol)

    # ---------- pricing ----------
    def quote(self, exchange: str, symbol: str) -> dict:
        if self.dry_run:
            return {"instrument": f"{exchange}:{symbol}",
                    "last_price": self._last_price, "source": "dry_run"}
        seg = self._segment(exchange)
        token = self.resolve_token(exchange, symbol)
        df = self._dhan.ticker_data(securities={seg: [int(token)]})
        rows = self._records(df)
        ltp = None
        if rows:
            row = rows[0]
            ltp = row.get("last_price") or row.get("LTP") or row.get("ltp")
        return {"instrument": f"{exchange}:{symbol}", "last_price": ltp, "source": "dhan"}

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

        seg = self._segment(exchange)
        token = self.resolve_token(exchange, symbol)
        resp = self._dhan.place_order(
            security_id=str(token),
            exchange_segment=seg,
            transaction_type=side,          # "BUY" / "SELL"
            quantity=int(qty),
            order_type=self._dhan.MARKET,
            product_type=self._product(product),
            price=0,
        )
        order_id = str(resp.get("orderId") if isinstance(resp, dict) else resp)
        # latest status le aao
        try:
            cur = self._records(self._dhan.get_order_by_id(order_id))
            order = self._to_local_order(cur[0]) if cur else {
                "order_id": order_id, "symbol": symbol, "exchange": exchange,
                "side": side, "qty": qty, "status": "OPEN",
            }
        except Exception:
            order = {"order_id": order_id, "symbol": symbol, "exchange": exchange,
                     "side": side, "qty": qty, "status": "OPEN"}
        self._orders[order_id] = order
        if order["status"] == "COMPLETE":
            self._apply_fill(order)
        return order

    def _to_local_order(self, rec: dict) -> dict:
        return {
            "order_id": str(rec.get("orderId")),
            "exchange": "NSE",
            "symbol": str(rec.get("tradingSymbol") or rec.get("securityId")),
            "side": rec.get("transactionType"),
            "qty": int(rec.get("quantity") or 0),
            "product": rec.get("productType"),
            "order_type": rec.get("orderType"),
            "price": float(rec.get("price") or rec.get("averagePrice") or 0.0),
            "status": self.STATUS_MAP.get(str(rec.get("orderStatus", "")), "OPEN"),
            "filled_qty": int(rec.get("filled_qty") or rec.get("filledQty") or 0),
            "ts": rec.get("createTime") or rec.get("updateTime"),
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
        self._dhan.cancel_order(order_id)
        o = self._orders.get(order_id)
        if o:
            o["status"] = "CANCELLED"
        return o or {"order_id": order_id, "status": "CANCELLED"}

    def open_orders(self) -> list[dict]:
        if self.dry_run:
            return [o for o in self._orders.values() if o["status"] == "OPEN"]
        return [self._to_local_order(r) for r in self._records(self._dhan.get_order_list())
                if self.STATUS_MAP.get(str(r.get("orderStatus", "")), "OPEN") == "OPEN"]

    def all_orders(self) -> list[dict]:
        if self.dry_run:
            return list(self._orders.values())
        return [self._to_local_order(r) for r in self._records(self._dhan.get_order_list())]

    def positions(self) -> list[dict]:
        if self.dry_run:
            return [{"symbol": k, **v} for k, v in self._positions.items()]
        out = []
        for rec in self._records(self._dhan.get_positions()):
            qty = int(rec.get("netQty") or 0)
            out.append({
                "symbol": str(rec.get("tradingSymbol") or rec.get("securityId")),
                "exchange": "NSE",
                "qty": qty,
                "avg_price": float(rec.get("buyAvg") or rec.get("costPrice") or 0.0),
                "pnl": float(rec.get("pnl") or rec.get("dayBuyValue") or 0.0) if qty else 0.0,
            })
        return out

    def margins(self) -> dict:
        if self.dry_run:
            return {"available_cash": None, "source": "dry_run"}
        limits = self._dhan.get_fund_limits()
        # Dhan ka field ka typo hai — dono spelling check karo
        cash = None
        if isinstance(limits, dict):
            cash = limits.get("availabelBalance") or limits.get("availableBalance")
        return {"available_cash": cash, "source": "dhan"}

    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (opposite market orders)."""
        results = []
        for pos in self.positions():
            if pos["qty"] != 0:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                results.append(self.place_market_order(
                    pos.get("exchange", "NSE"), pos["symbol"], side, abs(pos["qty"])))
        return results


def resolve_security_id(dhan, exchange: str, symbol: str) -> str:
    """Module-level helper — scrip master CSV se trading symbol → security id.

    DhanQuotePriceSource bhi isi ko use karta hai (real LTP ke liye real id chahiye).
    """
    df = dhan.fetch_security_list("compact")
    rows = DhanBroker._records(df)
    # column names version ke hisaab se alag ho sakte hain — dono try karo
    id_cols = ["EXCH_ID", "SEM_EXM_EXCH_ID", "SECURITY_ID"]
    sym_cols = ["SEM_TRADING_SYMBOL", "SM_SYMBOL_NAME", "SYMBOL_NAME", "INSTRUMENT"]
    seg_cols = ["SEM_SEGMENT", "SEGMENT"]
    for row in rows:
        sym = next((str(row[c]) for c in sym_cols if row.get(c)), "")
        exid = next((row[c] for c in id_cols if row.get(c) is not None), None)
        segment = next((str(row[c]) for c in seg_cols if row.get(c)), "")
        # equity segment 'E' hai
        is_equity = segment in ("E", "EQ", "EQUITY")
        exch = str(row.get("SEM_EXM_EXCH_ID") or row.get("EXCH") or "")
        if sym.upper() == symbol.upper() and exid is not None and (is_equity or not segment):
            if exchange == "NSE" and exch and "BSE" in exch.upper():
                continue
            return str(exid)
    raise ValueError(f"Security nahi mili: {exchange}:{symbol} (scrip master mein dhoondo)")

"""Upstox Broker — brokers registry mein 'upstox'. 🟣

Upstox se orders via official upstox-python-sdk (upstox_client).
Dry-run (simulation) ya LIVE (real money!).

⚠️ dry_run=False → REAL MONEY. Sirf tab use karo jab:
  - UPSTOX_ACCESS_TOKEN set ho (api_key se login flow ke baad milta hai)
  - LIVE_TRADING_ENABLED=true set ho
  - Kam se kam 2-3 mahine paper trading ho chuka ho

Upstox SDK: pip install upstox-python-sdk  (ya: pip install .[upstox])

Upstox ki alag baatein yaad rakho:
  - instrument_key format = "NSE_EQ|INE002A01018" (exchange|ISIN)
  - exchange segment = "NSE_EQ" (equity)
  - product: "D" (delivery/CNC), "I" (intraday/MIS)
  - order status: "complete" / "open" / "cancelled" / "rejected" (lowercase strings)
"""
from __future__ import annotations

import uuid
import zlib
from datetime import datetime, timezone

from apps.engine.brokers import register_broker
from apps.engine.brokers.base import BrokerBase


@register_broker
class UpstoxBroker(BrokerBase):
    name = "upstox"
    required_env = ("UPSTOX_ACCESS_TOKEN",)

    #: hamara exchange → Upstox ka segment (equity + F&O)
    SEGMENTS = {"NSE": "NSE_EQ", "BSE": "BSE_EQ", "NFO": "NFO", "BFO": "BFO"}
    #: hamara product → Upstox ka product code
    PRODUCTS = {"CNC": "D", "MIS": "I"}
    #: Upstox order status (lowercase) → hamara status
    STATUS_MAP = {
        "complete": "COMPLETE",
        "open": "OPEN",
        "trigger pending": "OPEN",
        "after market order req received": "OPEN",
        "cancelled": "CANCELLED",
        "rejected": "REJECTED",
    }
    API_VERSION = "2.0"

    def __init__(self, api_key: str | None = None, access_token: str | None = None,
                 dry_run: bool = True):
        super().__init__(dry_run)
        self.api_key = api_key
        self._client = None
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}   # symbol → {exchange, qty, avg_price}
        self._token_cache: dict[tuple[str, str], str] = {}
        if not dry_run:
            import upstox_client  # lazy — optional dependency
            if not access_token:
                raise ValueError("UPSTOX_ACCESS_TOKEN missing (live mode)")
            configuration = upstox_client.Configuration()
            configuration.access_token = access_token
            self._client = upstox_client.ApiClient(configuration)

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "LIVE ⚠️ REAL MONEY (Upstox)"

    def _segment(self, exchange: str) -> str:
        seg = self.SEGMENTS.get(exchange)
        if seg is None:
            raise ValueError(f"Upstox pe exchange nahi hai: {exchange} (supported: {sorted(self.SEGMENTS)})")
        return seg

    def _product(self, product: str) -> str:
        p = self.PRODUCTS.get(product)
        if p is None:
            raise ValueError(f"Upstox pe product nahi hai: {product} (supported: {sorted(self.PRODUCTS)})")
        return p

    def _api(self, name: str):
        """upstox_client ka API instance (OrderApiV3, PortfolioApi, ...)."""
        import upstox_client
        return getattr(upstox_client, name)(self._client)

    def to_broker_instrument(self, exchange: str, symbol: str) -> tuple[str, str]:
        """F&O: NSE:NIFTY-23OCT25-FUT → NFO:NIFTY25OCTFUT (upstox ka compact format)."""
        from libs.shared.fno import parse_fno_symbol, to_compact_fno
        fno = parse_fno_symbol(symbol)
        if fno is not None:
            return "NFO", to_compact_fno(fno)
        return exchange, symbol

    # ---------- connection ----------
    def connect(self) -> dict:
        """Connection test + reconciliation (real positions/orders sync — startup pe zaroori)."""
        if self.dry_run:
            return {"mode": "dry_run", "status": "connected (simulated)"}
        funds = self._api("UserApi").get_user_fund_margin(self.API_VERSION)  # token invalid → yahin fail
        self._reconcile()
        cash = None
        try:
            cash = funds.data.equity.available_margin
        except Exception:
            pass
        return {"mode": "live", "status": "connected", "available_cash": cash}

    def _reconcile(self):
        """Broker pe maujood positions/orders ko local state mein sync karo."""
        if self.dry_run:
            return
        for pos in self._api("PortfolioApi").get_positions(self.API_VERSION).data or []:
            qty = int(getattr(pos, "quantity", 0) or 0)
            if qty != 0:
                self._positions[getattr(pos, "tradingsymbol", "")] = {
                    "exchange": getattr(pos, "exchange", "NSE"),
                    "qty": qty,
                    "avg_price": float(getattr(pos, "buy_price", 0) or 0),
                }
        for o in self._api("OrderApi").get_order_book(self.API_VERSION).data or []:
            status = self.STATUS_MAP.get(str(getattr(o, "status", "")).lower(), "OPEN")
            if status == "OPEN":
                self._orders[str(getattr(o, "order_id", ""))] = self._to_local_order(o)

    # ---------- instruments ----------
    def resolve_token(self, exchange: str, symbol: str) -> str:
        """Upstox instrument_key ("NSE_EQ|INE002A01018"). Dry-run: stable fake key."""
        key = (exchange, symbol)
        if key not in self._token_cache:
            if self.dry_run:
                seg = self._segment(exchange)
                fake_isin = f"INE{zlib.crc32(f'{exchange}:{symbol}'.encode()) % 10**9:09d}"
                self._token_cache[key] = f"{seg}|{fake_isin}"
            else:
                bex, bsym = self.to_broker_instrument(exchange, symbol)
                self._token_cache[key] = self._lookup_instrument_key(self._segment(bex), bsym)
        return self._token_cache[key]

    def _lookup_instrument_key(self, segment: str, symbol: str) -> str:
        """Instruments list se tradingsymbol → instrument_key (dashes/spaces normalize)."""
        wanted = symbol.upper().replace("-", "").replace(" ", "")
        instruments = self._api("InstrumentApi").get_instruments(segment, api_version=self.API_VERSION)
        for inst in instruments.data or []:
            tsym = str(getattr(inst, "trading_symbol", "")).upper().replace("-", "").replace(" ", "")
            if tsym == wanted:
                return str(getattr(inst, "instrument_key"))
        raise ValueError(f"Instrument nahi mila: {segment}:{symbol} (instrument master mein dhoondo)")

    # ---------- pricing ----------
    def quote(self, exchange: str, symbol: str) -> dict:
        if self.dry_run:
            return {"instrument": f"{exchange}:{symbol}",
                    "last_price": self._last_price, "source": "dry_run"}
        exchange, symbol = self.to_broker_instrument(exchange, symbol)
        token = self.resolve_token(exchange, symbol)
        resp = self._api("MarketQuoteApi").get_ltp(
            instrument_key=token, api_version=self.API_VERSION)
        ltp = None
        data = getattr(resp, "data", None)
        if isinstance(data, dict):
            row = data.get(token) or (next(iter(data.values()), None) if data else None)
            if isinstance(row, dict):
                ltp = row.get("last_price") or row.get("lastPrice")
        return {"instrument": f"{exchange}:{symbol}", "last_price": ltp, "source": "upstox"}

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

        import upstox_client
        exchange, symbol = self.to_broker_instrument(exchange, symbol)
        token = self.resolve_token(exchange, symbol)
        body = upstox_client.PlaceOrderV3Request(
            quantity=int(qty),
            product=self._product(product),
            validity="DAY",
            price=0,
            instrument_token=token,
            order_type="MARKET",
            transaction_type=side,   # "BUY" / "SELL"
            disclosed_quantity=0,
            trigger_price=0.0,
            is_amo=False,
        )
        resp = self._api("OrderApiV3").place_order(body)
        order_id = str(resp.data.order_id)
        # latest status le aao
        order = {"order_id": order_id, "symbol": symbol, "exchange": exchange,
                 "side": side, "qty": qty, "status": "OPEN"}
        try:
            for o in self._api("OrderApi").get_order_book(self.API_VERSION).data or []:
                if str(getattr(o, "order_id", "")) == order_id:
                    order = self._to_local_order(o)
                    break
        except Exception:
            pass
        self._orders[order_id] = order
        if order["status"] == "COMPLETE":
            self._apply_fill(order)
        return order

    def _to_local_order(self, o) -> dict:
        return {
            "order_id": str(getattr(o, "order_id", "")),
            "exchange": getattr(o, "exchange", "NSE"),
            "symbol": getattr(o, "trading_symbol", "") or getattr(o, "instrument_token", ""),
            "side": getattr(o, "transaction_type", ""),
            "qty": int(getattr(o, "quantity", 0) or 0),
            "product": getattr(o, "product", ""),
            "order_type": getattr(o, "order_type", ""),
            "price": float(getattr(o, "average_price", 0) or getattr(o, "price", 0) or 0),
            "status": self.STATUS_MAP.get(str(getattr(o, "status", "")).lower(), "OPEN"),
            "filled_qty": int(getattr(o, "filled_quantity", 0) or 0),
            "ts": getattr(o, "order_timestamp", None),
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
        self._api("OrderApiV3").cancel_order(order_id)
        o = self._orders.get(order_id)
        if o:
            o["status"] = "CANCELLED"
        return o or {"order_id": order_id, "status": "CANCELLED"}

    def open_orders(self) -> list[dict]:
        if self.dry_run:
            return [o for o in self._orders.values() if o["status"] == "OPEN"]
        out = []
        for o in self._api("OrderApi").get_order_book(self.API_VERSION).data or []:
            local = self._to_local_order(o)
            if local["status"] == "OPEN":
                out.append(local)
        return out

    def all_orders(self) -> list[dict]:
        if self.dry_run:
            return list(self._orders.values())
        return [self._to_local_order(o)
                for o in self._api("OrderApi").get_order_book(self.API_VERSION).data or []]

    def positions(self) -> list[dict]:
        if self.dry_run:
            return [{"symbol": k, **v} for k, v in self._positions.items()]
        out = []
        for pos in self._api("PortfolioApi").get_positions(self.API_VERSION).data or []:
            qty = int(getattr(pos, "quantity", 0) or 0)
            out.append({
                "symbol": getattr(pos, "tradingsymbol", ""),
                "exchange": getattr(pos, "exchange", "NSE"),
                "qty": qty,
                "avg_price": float(getattr(pos, "buy_price", 0) or 0),
                "pnl": float(getattr(pos, "unrealised", 0) or 0) + float(getattr(pos, "realised", 0) or 0),
            })
        return out

    def margins(self) -> dict:
        if self.dry_run:
            return {"available_cash": None, "source": "dry_run"}
        funds = self._api("UserApi").get_user_fund_margin(self.API_VERSION)
        cash = None
        try:
            cash = funds.data.equity.available_margin
        except Exception:
            pass
        return {"available_cash": cash, "source": "upstox"}

    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (opposite market orders)."""
        results = []
        for pos in self.positions():
            if pos["qty"] != 0:
                side = "SELL" if pos["qty"] > 0 else "BUY"
                results.append(self.place_market_order(
                    pos.get("exchange", "NSE"), pos["symbol"], side, abs(pos["qty"])))
        return results

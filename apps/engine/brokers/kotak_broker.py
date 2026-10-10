"""Kotak Neo Broker — brokers registry mein 'kotak'. 🟣

Official SDK: pip install "kotakneoapi>=3.0"  (import name: neo_api_client)

Scope (personal use, cash equity):
  - NSE/BSE equity, product CNC (delivery) ya MIS (intraday).
  - Sirf LIMIT orders. Market order nahi bheja jata. Limit price = LTP se
    thoda upar (BUY) / neeche (SELL), tick size par round — marketable limit.
  - F&O live abhi band hai. Kotak ka trading symbol format alag hai; verify
    karne ke baad hi add karenge.

Daily login: session roz expire hota hai. TOTP (authenticator ka 6-digit code,
30 sec) har live start par chahiye. TOTP / MPIN kabhi logs, repo ya DB mein nahi jaate.

Static IP: broker par whitelisted IP se hi order accept hote hain. KOTAK_STATIC_IP
set ho to connect() pe mismatch par session band karke refuse karta hai.

Order rate: SEBI retail API threshold 10 orders/second per exchange. Placement,
cancel dono isme count hote hain. Limit local guard se enforce hoti hai — exceed
hone par order bheja hi nahi jata.

Outcomes (journal ke liye):
  - Broker ne explicitly reject kiya (stat Not_Ok, session error nahi) → REJECTED.
  - Session expire (stCode 403) → KotakSessionExpired, naye TOTP ke saath restart.
  - SDK exception / timeout / order number missing → exception (UNKNOWN). Automatic
    retry nahi hota; broker order book se reconcile karo.

⚠️ dry_run=False → REAL MONEY. Sirf tab use karo jab LIVE_TRADING_ENABLED=true ho.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from apps.engine.brokers import register_broker
from apps.engine.brokers.base import BrokerBase
from libs.shared.fno import is_fno

TICK_SIZE = 0.05
#: NSE/BSE trading symbol ke series suffix (RELIANCE-EQ, BAJAJ-AUTO-BE ...)
EQUITY_SERIES = {"EQ", "BE", "BL", "BZ", "SM", "ST", "T0"}
#: Kotak exchange segments jo F&O hain (positions mein lot size divide hota hai)
FNO_SEGMENTS = {"nse_fo", "bse_fo", "mcx_fo"}
#: SEBI retail algo/API threshold (orders per second, per exchange)
SEBI_OPS_LIMIT = 10
SESSION_EXPIRED_CODE = 403

#: Per-order tag (SDK `tag` -> payload `ig` -> echoed as GuiOrdId): 15 chars, alnum only,
#: har order ke liye unique. Kotak Algo ID khud append karta hai; ye hamara order-level audit tag hai.
ORDER_TAG_PREFIX = "AIQ"


def new_order_tag() -> str:
    return ORDER_TAG_PREFIX + uuid.uuid4().hex[:12].upper()


class KotakSessionExpired(RuntimeError):
    """Kotak session expire ho gaya — naye TOTP ke saath live session restart karo."""


class OrderRateLimitExceeded(RuntimeError):
    """Local OPS guard ne order rok diya — broker tak request nahi gayi."""


class OrderRateGuard:
    """Sliding-window OPS guard, exchange-wise. Clock injectable (tests ke liye)."""

    def __init__(self, max_per_second: int = SEBI_OPS_LIMIT, clock=time.monotonic):
        if not 1 <= max_per_second <= SEBI_OPS_LIMIT:
            raise ValueError(f"OPS limit 1 se {SEBI_OPS_LIMIT} ke beech hona chahiye")
        self.max_per_second = max_per_second
        self._clock = clock
        self._sent: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, exchange: str) -> None:
        """Request ko slot do, ya OrderRateLimitExceeded. Failed attempts bhi count hote hain."""
        now = self._clock()
        with self._lock:
            window = self._sent.setdefault(exchange, deque())
            while window and now - window[0] >= 1.0:
                window.popleft()
            if len(window) >= self.max_per_second:
                raise OrderRateLimitExceeded(
                    f"{exchange}: {self.max_per_second} orders/second limit pahunch gaya")
            window.append(now)


#: Field-name fragments whose values are always fully masked. Mirrors the SDK's own
#: censor list (kotakneoapi 3.0.x `censor_sensitive_data`), which only partially masks
#: (`65***21`) — that still leaks 4 of 6 MPIN/TOTP digits on failed-login ERROR logs.
_SENSITIVE_KEY_PARTS = ("password", "secret", "auth", "api_key", "consumer_key",
                        "consumer_secret", "otp", "mpin", "sid")
#: Exact field names (case-insensitive) the SDK leaves uncensored: session token (JWT),
#: request id, PAN (`kId`), account name and login identity.
_SENSITIVE_KEYS = {"token", "rid", "kid", "greetingname", "hsserverid",
                   "mobilenumber", "mobile_number", "ucc"}
#: `"key": "value"` pairs inside raw text, e.g. a truncated response-body preview.
_JSON_PAIR = re.compile(r'"([A-Za-z0-9_\-]+)"(\s*:\s*)"[^"]*"?')


def _is_sensitive_key(key) -> bool:
    lower = str(key).lower()
    return lower in _SENSITIVE_KEYS or any(part in lower for part in _SENSITIVE_KEY_PARTS)


def _mask_json_pair(match: re.Match) -> str:
    if not _is_sensitive_key(match.group(1)):
        return match.group(0)
    return f'"{match.group(1)}"{match.group(2)}"***"'


def _scrub(value, secrets: list[str]):
    """Secrets aur sensitive fields ko *** se badal do (structlog event dict, nested bhi).

    Teen layer: sensitive key ki value poori mask, known secret values (aur SDK ka
    partial `ab***yz` form) replace, raw JSON text ke andar sensitive pairs mask.
    """
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "***")
            if len(secret) > 4:
                value = value.replace(f"{secret[:2]}***{secret[-2:]}", "***")
        return _JSON_PAIR.sub(_mask_json_pair, value) if '"' in value else value
    if isinstance(value, dict):
        return {k: "***" if _is_sensitive_key(k) else _scrub(v, secrets)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v, secrets) for v in value)
    return value


class SecretRedactor(logging.Filter):
    """SDK log record se mobile / UCC / MPIN / key jaise values hata deta hai.

    Handler-level filter hona chahiye: SDK ke records structlog se aate hain (msg = dict),
    aur child loggers ke records parent logger ke filter se nahi guzarte.
    """

    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 2]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _scrub(record.msg, self._secrets)
        record.args = _scrub(record.args, self._secrets) if record.args else record.args
        return True


def redact_sdk_logs(secrets: list[str]) -> None:
    """SDK ke handlers (console + file) aur loggers par redaction filter lagao (idempotent)."""
    sdk_root = logging.getLogger("neo_api_client")
    for handler in sdk_root.handlers:
        if not any(isinstance(f, SecretRedactor) for f in handler.filters):
            handler.addFilter(SecretRedactor(secrets))
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(logger, logging.Logger) and (name == "neo_api_client" or name.startswith("neo_api_client.")):
            if not any(isinstance(f, SecretRedactor) for f in logger.filters):
                logger.addFilter(SecretRedactor(secrets))


def _ensure_ok(resp, action: str) -> dict:
    """SDK response ko check karo. Error ho to sanitized exception — raw response/creds nahi."""
    if not isinstance(resp, dict):
        raise RuntimeError(f"Kotak {action} failed (unexpected response)")
    if any(k in resp for k in ("error", "Error", "Error Message")):
        raise RuntimeError(f"Kotak {action} failed (sdk error)")
    if resp.get("stCode") == SESSION_EXPIRED_CODE:
        raise KotakSessionExpired("Kotak session expired — naye TOTP ke saath live start karo")
    if "stat" in resp and str(resp.get("stat", "")).lower() != "ok":
        raise RuntimeError(f"Kotak {action} failed (stCode={resp.get('stCode')})")
    return resp


def _is_explicit_reject(resp) -> bool:
    """Broker ka clear 'Not_Ok' (exception nahi, session error nahi) → order reject hua."""
    if not isinstance(resp, dict) or any(k in resp for k in ("error", "Error", "Error Message")):
        return False
    if resp.get("stCode") == SESSION_EXPIRED_CODE:
        return False
    return "stat" in resp and str(resp.get("stat", "")).lower() != "ok"


def _rows(resp) -> list[dict]:
    """Kotak list response → list[dict]. data key ya seedha list dono chalega."""
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    _ensure_ok(resp, "list")
    data = resp.get("data") or []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _num(rec: dict, key: str) -> float:
    try:
        return float(rec.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _marketable_limit(ltp: float, side: str, buffer: float) -> float:
    """BUY → ceil(LTP*(1+buffer)), SELL → floor(LTP*(1-buffer)) on TICK_SIZE grid."""
    raw = ltp * (1 + buffer) if side == "BUY" else ltp * (1 - buffer)
    ticks = math.ceil(round(raw / TICK_SIZE, 6)) if side == "BUY" else math.floor(round(raw / TICK_SIZE, 6))
    return round(ticks * TICK_SIZE, 2)


@register_broker
class KotakBroker(BrokerBase):
    name = "kotak"
    required_env = ("KOTAK_CONSUMER_KEY", "KOTAK_MOBILE", "KOTAK_UCC", "KOTAK_MPIN")

    SEGMENTS = {"NSE": "nse_cm", "BSE": "bse_cm"}
    PRODUCTS = {"CNC": "CNC", "MIS": "MIS"}
    SIDES = {"BUY": "B", "SELL": "S"}
    #: Kotak ordSt → hamara status. Jo state samajh na aaye woh UNKNOWN (reconcile karo).
    STATUS_MAP = {
        "open": "OPEN",
        "open pending": "OPEN",
        "trigger pending": "OPEN",
        "complete": "COMPLETE",
        "rejected": "REJECTED",
        "cancelled": "CANCELLED",
        "canceled": "CANCELLED",
    }

    def __init__(self, consumer_key: str | None = None, mobile: str | None = None,
                 ucc: str | None = None, mpin: str | None = None, totp: str | None = None,
                 static_ip: str | None = None, limit_buffer: float = 0.005,
                 dry_run: bool = True, client=None):
        super().__init__(dry_run)
        self._mobile = mobile
        self._ucc = ucc
        self._mpin = mpin
        self._totp = totp           # one-time: connect() ke baad memory se hata diya jata hai
        self.static_ip = static_ip
        self.limit_buffer = limit_buffer
        self._client = client
        self._logged_in = False
        self._rate = OrderRateGuard()
        self._orders: dict[str, dict] = {}
        self._positions: dict[str, dict] = {}
        self._token_cache: dict[tuple[str, str], str] = {}
        if not dry_run and client is None:
            missing = [name for name, val in (
                ("KOTAK_CONSUMER_KEY", consumer_key), ("KOTAK_MOBILE", mobile),
                ("KOTAK_UCC", ucc), ("KOTAK_MPIN", mpin)) if not val]
            if missing:
                raise ValueError(f"Kotak creds missing: {', '.join(missing)}")
            if not 0 < limit_buffer < 0.05:
                raise ValueError("limit_buffer 0 aur 5% ke beech hona chahiye")
            from neo_api_client import NeoAPI  # lazy — optional dependency
            self._client = NeoAPI(consumer_key=consumer_key, environment="prod")
            redact_sdk_logs([consumer_key, mobile, ucc, mpin])

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "LIVE ⚠️ REAL MONEY (Kotak Neo)"

    # ---------- helpers ----------
    def _api(self):
        if self._client is None or not self._logged_in:
            raise RuntimeError("Kotak session active nahi hai — pehle connect() chalao")
        return self._client

    def _segment(self, exchange: str) -> str:
        seg = self.SEGMENTS.get(exchange)
        if seg is None:
            raise ValueError(f"Kotak pe exchange nahi hai: {exchange} (supported: {sorted(self.SEGMENTS)})")
        return seg

    def _product(self, product: str) -> str:
        p = self.PRODUCTS.get(product)
        if p is None:
            raise ValueError(f"Kotak pe product nahi hai: {product} (supported: {sorted(self.PRODUCTS)})")
        return p

    @staticmethod
    def _trading_symbol(symbol: str) -> str:
        """RELIANCE → RELIANCE-EQ. Series suffix pehle se ho to waise hi rehne do."""
        if is_fno(symbol):
            raise ValueError("Kotak pe F&O live abhi support nahi — sirf cash equity")
        base, _, series = symbol.upper().rpartition("-")
        if base and series in EQUITY_SERIES:
            return symbol.upper()
        return f"{symbol.upper()}-EQ"

    # ---------- connection ----------
    def connect(self) -> dict:
        """Login (TOTP → MPIN), static IP check, limits aur orders/positions sync."""
        if self.dry_run:
            return {"mode": "dry_run", "status": "connected (simulated)"}
        totp, self._totp = self._totp, None
        if not totp:
            raise ValueError("Kotak TOTP missing — authenticator app ka current 6-digit code do")
        client = self._client
        _ensure_ok(client.totp_login(mobile_number=self._mobile, ucc=self._ucc, totp=totp), "totp_login")
        _ensure_ok(client.totp_validate(mpin=self._mpin), "totp_validate")
        self._logged_in = True
        ip = self._current_ip()
        if self.static_ip and ip != self.static_ip:
            self._logged_in = False
            try:
                client.logout()
            except Exception:
                pass
            raise ValueError("Current IP registered static IP se match nahi karta — broker whitelist check karo")
        cash = self._available_cash()
        self._reconcile()
        return {"mode": "live", "status": "connected", "available_cash": cash, "ip": ip}

    def _current_ip(self) -> str | None:
        resp = self._client.whatsmyip()
        rows = _rows(resp.get("data") if isinstance(resp, dict) and "data" in resp else resp)
        return str(rows[0].get("ip")) if rows and rows[0].get("ip") else None

    def _available_cash(self) -> float | None:
        rec = _ensure_ok(self._api().limits(), "limits")
        return _num(rec, "Net") if "Net" in rec else None

    def _reconcile(self):
        """Broker pe maujood open orders aur positions ko local state mein sync karo."""
        for rec in _rows(self._api().order_report()):
            local = self._to_local_order(rec)
            if local["status"] == "OPEN":
                self._orders[local["order_id"]] = local
        for pos in self.positions():
            self._positions[pos["symbol"]] = {"exchange": pos["exchange"], "qty": pos["qty"],
                                              "avg_price": pos["avg_price"]}

    # ---------- instruments / pricing ----------
    def resolve_token(self, exchange: str, symbol: str) -> str:
        """Kotak pSymbol (instrument token). Dry-run mein use nahi hota."""
        key = (exchange, symbol)
        if key not in self._token_cache:
            seg = self._segment(exchange)
            trd = self._trading_symbol(symbol)
            resp = self._api().search_scrip(exchange_segment=seg, symbol=trd.rsplit("-", 1)[0])
            match = next((r for r in _rows(resp) if str(r.get("pTrdSymbol", "")).upper() == trd), None)
            if not match or not match.get("pSymbol"):
                raise ValueError(f"Kotak scrip nahi mila: {trd}")
            self._token_cache[key] = str(match["pSymbol"])
        return self._token_cache[key]

    def quote(self, exchange: str, symbol: str) -> dict:
        if self.dry_run:
            return {"instrument": f"{exchange}:{symbol}",
                    "last_price": self._last_price, "source": "dry_run"}
        seg = self._segment(exchange)
        token = self.resolve_token(exchange, symbol)
        resp = _ensure_ok(self._api().quotes(
            instrument_tokens=[{"instrument_token": token, "exchange_segment": seg}],
            quote_type="ltp"), "quotes")
        ltp = None
        data = resp.get("data") or []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            raw = data[0].get("ltp") or data[0].get("last_traded_price")
            ltp = float(raw) if raw and float(raw) > 0 else None
        return {"instrument": f"{exchange}:{symbol}", "last_price": ltp, "source": "kotak"}

    # ---------- orders ----------
    def place_market_order(self, exchange: str, symbol: str, side: str,
                           qty: int, product: str = "CNC") -> dict:
        """Naam base interface ke liye hai. Live mein yeh LIMIT (marketable) order hai — market nahi."""
        if side not in self.SIDES:
            raise ValueError("side BUY ya SELL hona chahiye")
        if int(qty) <= 0:
            raise ValueError("qty positive hona chahiye")
        if self.dry_run:
            price = self._last_price
            if price is None:
                raise ValueError("dry_run: pehle set_price() karo")
            order = {
                "order_id": f"DRY-{uuid.uuid4().hex[:10]}",
                "exchange": exchange, "symbol": symbol, "side": side,
                "qty": qty, "product": product, "order_type": "LIMIT",
                "price": price, "status": "COMPLETE", "filled_qty": qty,
                "order_tag": new_order_tag(),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._orders[order["order_id"]] = order
            self._apply_fill(order)
            return order

        seg = self._segment(exchange)
        prod = self._product(product)
        trd = self._trading_symbol(symbol)
        ltp = self.quote(exchange, symbol)["last_price"]
        if not ltp:
            raise ValueError("Kotak LTP nahi mila — order nahi bheja")
        limit = _marketable_limit(float(ltp), side, self.limit_buffer)
        self._rate.acquire(exchange)  # OPS guard: exceed ho to request hi nahi jati
        tag = new_order_tag()
        resp = self._api().place_order(
            exchange_segment=seg,
            product=prod,
            price=f"{limit:.2f}",
            order_type="L",
            quantity=str(int(qty)),
            validity="DAY",
            trading_symbol=trd,
            transaction_type=self.SIDES[side],
            tag=tag,
        )
        base = {"exchange": exchange, "symbol": symbol, "side": side, "qty": int(qty),
                "product": product, "order_type": "LIMIT", "price": limit, "filled_qty": 0,
                "order_tag": tag}
        if _is_explicit_reject(resp):
            return {**base, "order_id": "", "status": "REJECTED", "reason_code": resp.get("stCode")}
        _ensure_ok(resp, "place_order")
        order_id = str(resp.get("nOrdNo") or "")
        if not order_id:
            raise RuntimeError("Kotak place_order: order number nahi mila — broker order book check karo")
        order = {**base, "order_id": order_id, "status": "OPEN"}
        self._orders[order_id] = order
        return order

    def _to_local_order(self, rec: dict) -> dict:
        raw = str(rec.get("ordSt") or "").lower()
        return {
            "order_id": str(rec.get("nOrdNo") or ""),
            "exchange": "BSE" if str(rec.get("exSeg", "")).startswith("bse") else "NSE",
            "symbol": str(rec.get("trdSym") or ""),
            "side": "BUY" if rec.get("trnsTp") == "B" else "SELL",
            "qty": int(_num(rec, "qty")),
            "product": rec.get("prod"),
            "order_type": rec.get("prcTp"),
            "order_tag": str(rec.get("GuiOrdId") or ""),
            "price": _num(rec, "prc") or _num(rec, "avgPrc"),
            "status": self.STATUS_MAP.get(raw, "UNKNOWN"),
            "filled_qty": int(_num(rec, "fldQty")),
            "ts": rec.get("ordDtTm"),
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
            if o and o["status"] == "OPEN":
                o["status"] = "CANCELLED"
                return o
            return {"order_id": order_id, "status": "NOT_FOUND"}
        o = self._orders.get(order_id)
        self._rate.acquire((o or {}).get("exchange", "NSE"))  # cancel bhi OPS mein count hota hai
        _ensure_ok(self._api().cancel_order(order_id=order_id), "cancel_order")
        # Cancel accepted ≠ cancelled. Final state broker order book se reconcile karo.
        if o:
            o["status"] = "CANCEL_REQUESTED"
        return o or {"order_id": order_id, "status": "CANCEL_REQUESTED"}

    def open_orders(self) -> list[dict]:
        if self.dry_run:
            return [o for o in self._orders.values() if o["status"] == "OPEN"]
        return [o for o in (self._to_local_order(r) for r in _rows(self._api().order_report()))
                if o["status"] == "OPEN"]

    def all_orders(self) -> list[dict]:
        if self.dry_run:
            return list(self._orders.values())
        return [self._to_local_order(r) for r in _rows(self._api().order_report())]

    # ---------- portfolio ----------
    def positions(self) -> list[dict]:
        if self.dry_run:
            return [{"symbol": k, **v} for k, v in self._positions.items()]
        out = []
        for rec in _rows(self._api().positions()):
            seg = str(rec.get("exSeg", ""))
            divisor = (_num(rec, "lotSz") or 1) if seg in FNO_SEGMENTS else 1
            buy = _num(rec, "cfBuyQty") + _num(rec, "flBuyQty")
            sell = _num(rec, "cfSellQty") + _num(rec, "flSellQty")
            qty = int(round((buy - sell) / divisor))
            if qty == 0:
                continue
            out.append({
                "symbol": str(rec.get("trdSym") or ""),
                "exchange": "BSE" if seg.startswith("bse") else "NSE",
                "qty": qty,
                "avg_price": self._avg_price(rec, qty),
            })
        return out

    @staticmethod
    def _avg_price(rec: dict, qty: int) -> float:
        """Kotak docs ke formula par: amount / (qty × multiplier × genNum/genDen × prcNum/prcDen)."""
        scale = ((_num(rec, "multiplier") or 1)
                 * ((_num(rec, "genNum") or 1) / (_num(rec, "genDen") or 1))
                 * ((_num(rec, "prcNum") or 1) / (_num(rec, "prcDen") or 1)))
        if qty > 0:
            amt, units = _num(rec, "cfBuyAmt") + _num(rec, "buyAmt"), _num(rec, "cfBuyQty") + _num(rec, "flBuyQty")
        else:
            amt, units = _num(rec, "cfSellAmt") + _num(rec, "sellAmt"), _num(rec, "cfSellQty") + _num(rec, "flSellQty")
        if units <= 0 or scale <= 0:
            return 0.0
        return round(amt / (units * scale), 2)

    def margins(self) -> dict:
        if self.dry_run:
            return {"available_cash": None, "source": "dry_run"}
        rec = _ensure_ok(self._api().limits(), "limits")
        return {"available_cash": _num(rec, "Net"), "source": "kotak"}

    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (marketable limit exits)."""
        results = []
        for pos in self.positions():
            if pos["qty"] == 0:
                continue
            side = "SELL" if pos["qty"] > 0 else "BUY"
            exchange = pos.get("exchange", "NSE")
            try:
                results.append(self.place_market_order(exchange, pos["symbol"], side, abs(pos["qty"])))
            except Exception as exc:
                # Har exit alag se try hota hai. Fail hone wali exit manual review ke liye visible rehti hai.
                results.append({"exchange": exchange, "symbol": pos["symbol"], "side": side,
                                "qty": abs(pos["qty"]), "status": "NOT_SENT",
                                "error": type(exc).__name__})
        return results

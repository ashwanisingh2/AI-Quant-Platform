"""Broker abstraction — har broker ka same interface. 📡

Ye wohi hai jo vnpy/ccxt karte hain: ek interface, kai brokers.
Kite (Zerodha), Dhan, aur aage Upstox/Fyers — sab ek jaise.

Interface (har broker implement karta hai):
  connect() · resolve_token() · quote() · place_market_order() ·
  cancel_order() · open_orders() · all_orders() · positions() ·
  margins() · square_off_all()

⚠️ dry_run=True (default) = simulated orders, real prices. Real money nahi.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerBase(ABC):
    """Har broker iska subclass banata hai. Dry-run default — safe."""

    name: str = "base"
    #: live mode ke liye zaroori env vars (credentials check ke liye)
    required_env: tuple[str, ...] = ()

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._last_price: float | None = None

    # ---------- identity ----------
    @property
    @abstractmethod
    def mode(self) -> str:
        """'dry_run' ya 'LIVE ⚠️ REAL MONEY'"""

    @property
    def is_live(self) -> bool:
        return not self.dry_run

    # ---------- connection ----------
    @abstractmethod
    def connect(self) -> dict:
        """Connection test + reconciliation (startup pe real state sync)."""

    # ---------- instruments / pricing ----------
    def to_broker_instrument(self, exchange: str, symbol: str) -> tuple[str, str]:
        """Broker-specific exchange/symbol mapping.

        F&O formats har broker mein alag hote hain (kite: NFO:NIFTY25OCTFUT,
        fyers: NSE:NIFTY25OCTFUT...). Default: passthrough.
        Sirf LIVE paths mein use hota hai — dry-run original symbol rakhta hai.
        """
        return exchange, symbol

    @abstractmethod
    def resolve_token(self, exchange: str, symbol: str):
        """Broker ka internal instrument id (kite: int token, dhan: security_id)."""

    def set_price(self, price: float):
        """Dry-run mein last price set karta hai (fills isi price pe hote hain)."""
        self._last_price = price

    @abstractmethod
    def quote(self, exchange: str, symbol: str) -> dict:
        """{'instrument', 'last_price', 'source'}"""

    # ---------- orders ----------
    @abstractmethod
    def place_market_order(self, exchange: str, symbol: str, side: str,
                           qty: int, product: str = "CNC") -> dict:
        """side: BUY|SELL → local order dict {order_id, side, qty, price, status, ...}"""

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        ...

    @abstractmethod
    def open_orders(self) -> list[dict]:
        ...

    @abstractmethod
    def all_orders(self) -> list[dict]:
        ...

    # ---------- portfolio ----------
    @abstractmethod
    def positions(self) -> list[dict]:
        """[{'symbol', 'exchange', 'qty', 'avg_price'}]"""

    @abstractmethod
    def margins(self) -> dict:
        ...

    @abstractmethod
    def square_off_all(self) -> list[dict]:
        """🚨 Kill switch — saari open positions band karo (opposite market orders)."""

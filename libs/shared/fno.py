"""F&O (Futures & Options) support — symbols, lot sizes, margin. 📊⚠️

Canonical symbol format (hamara):
  Futures:  NIFTY-23OCT25-FUT          → NSE:NIFTY-23OCT25-FUT
  Options:  NIFTY-23OCT25-24000-CE     → NSE:NIFTY-23OCT25-24000-CE
            NIFTY-23OCT25-24000-PE     → NSE:NIFTY-23OCT25-24000-PE

⚠️ F&O = LEVERAGE = high risk. MVP safety rules:
  - lot size enforce hota hai (qty lot ka multiple hona chahiye)
  - F&O notional cap (default: 100% of capital)
  - naked option SELL allowed nahi hai (sirf options BUY — buying is safe direction)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# ---------- lot sizes (NSE, 2026) ----------
LOT_SIZES: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 35,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 140,
    "NIFTYNXT50": 50,
    "SENSEX": 20,
    "BANKEX": 30,
}
DEFAULT_LOT_SIZE = 1  # stock F&O jab tak exact lot na pata ho — conservative

#: F&O margin assumption (SPAN ~20% for overnight futures)
FNO_MARGIN_PCT = 0.20


@dataclass
class FnoInstrument:
    """Parsed F&O instrument."""
    underlying: str          # NIFTY, BANKNIFTY, SBIN...
    kind: str                # FUT | CE | PE
    expiry: date             # expiry date (Thursday)
    strike: float | None = None   # options ke liye

    @property
    def is_option(self) -> bool:
        return self.kind in ("CE", "PE")

    @property
    def is_future(self) -> bool:
        return self.kind == "FUT"


_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# NIFTY-23OCT25-FUT  |  NIFTY-23OCT25-24000-CE
_RE_FUT = re.compile(r"^([A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})-FUT$")
_RE_OPT = re.compile(r"^([A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})-(\d+(?:\.\d+)?)-(CE|PE)$")


def parse_fno_symbol(symbol: str) -> FnoInstrument | None:
    """F&O symbol parse karo. Agar F&O nahi hai toh None.

    >>> parse_fno_symbol("NIFTY-23OCT25-FUT")
    FnoInstrument(underlying='NIFTY', kind='FUT', expiry=datetime.date(2025, 10, 23))
    """
    symbol = symbol.strip().upper()
    m = _RE_OPT.match(symbol)
    if m:
        und, dd, mon, yy, strike, kind = m.groups()
        return FnoInstrument(
            underlying=und, kind=kind,
            expiry=_make_date(int(dd), mon, int(yy)),
            strike=float(strike),
        )
    m = _RE_FUT.match(symbol)
    if m:
        und, dd, mon, yy = m.groups()
        return FnoInstrument(
            underlying=und, kind="FUT",
            expiry=_make_date(int(dd), mon, int(yy)),
        )
    return None


def _make_date(dd: int, mon: str, yy: int) -> date:
    """Symbol ka day = exact expiry date (weekly bhi ho sakta hai — Thursday adjust nahi)."""
    import calendar
    month = _MONTHS.index(mon) + 1
    year = 2000 + yy
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(dd, last))


def format_fno_symbol(fno: FnoInstrument) -> str:
    """FnoInstrument → canonical symbol."""
    exp = f"{fno.expiry.day:02d}{_MONTHS[fno.expiry.month - 1]}{fno.expiry.year % 100:02d}"
    if fno.is_option:
        strike = f"{fno.strike:.0f}" if fno.strike == int(fno.strike) else f"{fno.strike}"
        return f"{fno.underlying}-{exp}-{strike}-{fno.kind}"
    return f"{fno.underlying}-{exp}-FUT"


def to_compact_fno(fno: FnoInstrument) -> str:
    """Broker-style compact symbol (kite/upstox/fyers): 2-digit year, no day.

    NIFTY-23OCT25-FUT → NIFTY25OCTFUT · NIFTY-23OCT25-24000-CE → NIFTY25OCT24000CE
    """
    exp = f"{fno.expiry.year % 100:02d}{_MONTHS[fno.expiry.month - 1]}"
    if fno.is_option:
        strike = f"{fno.strike:.0f}" if fno.strike == int(fno.strike) else f"{fno.strike}"
        return f"{fno.underlying}{exp}{strike}{fno.kind}"
    return f"{fno.underlying}{exp}FUT"


def is_fno(symbol: str) -> bool:
    return parse_fno_symbol(symbol) is not None


def underlying_of(symbol: str) -> str | None:
    """"NIFTY-23OCT25-24000-CE" → "NIFTY". Agar F&O nahi toh None."""
    fno = parse_fno_symbol(symbol)
    return fno.underlying if fno else None


def lot_size(underlying: str) -> int:
    """Lot size by underlying. Unknown → DEFAULT_LOT_SIZE (1, conservative)."""
    return LOT_SIZES.get(underlying.strip().upper(), DEFAULT_LOT_SIZE)


def fno_margin(notional: float, margin_pct: float = FNO_MARGIN_PCT) -> float:
    """F&O notional ka approx margin (SPAN ~20%)."""
    return notional * margin_pct


def monthly_expiry(year: int, month: int) -> date:
    """Mahine ka last Thursday (monthly expiry)."""
    # mahine ka last din
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    while last.weekday() != 3:  # Thursday
        last -= timedelta(days=1)
    return last


def atm_strike(strikes: list[float], spot: float) -> float:
    """Spot ke sabse kareeb wala strike (ATM)."""
    return min(strikes, key=lambda s: abs(s - spot))

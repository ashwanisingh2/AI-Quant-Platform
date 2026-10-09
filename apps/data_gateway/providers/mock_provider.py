"""Mock provider — bina internet/credentials ke development ke liye.

Deterministic (seeded) random walk — har run bilkul same data.
Real broker se data aane se pehle pipeline test karne ke liye perfect.

Phase 8: F&O support — synthetic futures/options candles + option chain.
"""
from __future__ import annotations

import random
import zlib
from datetime import date, datetime, timedelta

from apps.data_gateway.providers.base import DataProvider
from libs.shared.fno import FnoInstrument, monthly_expiry, parse_fno_symbol
from libs.shared.models import Candle, instrument_key

#: synthetic spot base by underlying (F&O data ke liye)
_FNO_SPOT = {"NIFTY": 24000.0, "BANKNIFTY": 52000.0, "FINNIFTY": 22000.0,
             "MIDCPNIFTY": 18000.0, "SENSEX": 78000.0, "BANKEX": 58000.0}
_FNO_STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
                    "MIDCPNIFTY": 25, "SENSEX": 100, "BANKEX": 100}


class MockProvider(DataProvider):
    name = "mock"

    def __init__(self, seed: int = 42):
        self.seed = seed

    def get_historical(
        self, symbol: str, days: int = 60, exchange: str = "NSE"
    ) -> list[Candle]:
        fno = parse_fno_symbol(symbol)
        if fno is not None:
            return self._fno_candles(fno, days, exchange)

        seed = zlib.crc32(f"{self.seed}:{exchange}:{symbol}".encode())
        rng = random.Random(seed)
        price = 500.0 + (seed % 2000)
        drift = 0.0004  # thoda upward bias — realistic lagta hai

        candles: list[Candle] = []
        d = date.today()
        produced = 0
        while produced < days:
            if d.weekday() < 5:  # Mon–Fri only
                open_ = price
                close = open_ * (1 + rng.gauss(drift, 0.015))
                high = max(open_, close) * (1 + abs(rng.gauss(0, 0.004)))
                low = min(open_, close) * (1 - abs(rng.gauss(0, 0.004)))
                candles.append(Candle(
                    instrument=instrument_key(exchange, symbol),
                    timestamp=datetime(d.year, d.month, d.day),
                    open=round(open_, 2), high=round(high, 2),
                    low=round(low, 2), close=round(close, 2),
                    volume=rng.randint(100_000, 5_000_000),
                ))
                price = close
                produced += 1
            d -= timedelta(days=1)

        candles.reverse()  # oldest → newest
        return candles

    # ---------- F&O (Phase 8) ----------
    def _fno_candles(self, fno: FnoInstrument, days: int, exchange: str) -> list[Candle]:
        """Synthetic F&O candles — underlying-seeded random walk.

        FUT ≈ spot (chhota basis) · CE/PE premium = intrinsic×0.5 + time value (decaying).
        """
        seed = zlib.crc32(f"{self.seed}:{exchange}:{fno.underlying}".encode())
        rng = random.Random(seed)
        spot0 = _FNO_SPOT.get(fno.underlying, 2000.0)

        # underlying ka daily path
        spots = [spot0]
        for _ in range(days):
            spots.append(spots[-1] * (1 + rng.gauss(0.0004, 0.012)))

        symbol = f"{fno.underlying}-{fno.expiry.day:02d}{fno.expiry.strftime('%b').upper()}{fno.expiry.year % 100:02d}"
        if fno.is_future:
            symbol = f"{symbol}-FUT"
        else:
            symbol = f"{symbol}-{int(fno.strike)}-{fno.kind}"

        candles: list[Candle] = []
        d = date.today()
        produced = 0
        while produced < days:
            if d.weekday() < 5:  # Mon–Fri only
                spot = spots[produced]
                days_left = max((fno.expiry - d).days, 1)
                if fno.is_future:
                    open_ = spot * 0.999
                    close = spot * (1 + rng.gauss(0, 0.003))
                else:
                    if fno.kind == "CE":
                        intrinsic = max(spot - fno.strike, 0.0)
                    else:
                        intrinsic = max(fno.strike - spot, 0.0)
                    time_value = 120.0 * (days_left / 30.0) + 15.0
                    premium = intrinsic * 0.5 + time_value
                    open_ = premium
                    close = premium * (1 + rng.gauss(0, 0.03))
                high = max(open_, close) * (1 + abs(rng.gauss(0, 0.004)))
                low = max(min(open_, close) * (1 - abs(rng.gauss(0, 0.004))), 0.05)
                candles.append(Candle(
                    instrument=instrument_key(exchange, symbol),
                    timestamp=datetime(d.year, d.month, d.day),
                    open=round(open_, 2), high=round(high, 2),
                    low=round(low, 2), close=round(max(close, 0.05), 2),
                    volume=rng.randint(50_000, 2_000_000),
                ))
                produced += 1
            d -= timedelta(days=1)

        candles.reverse()  # oldest → newest
        return candles

    def get_option_chain(self, underlying: str, expiry: str | None = None,
                         spot: float | None = None) -> list[dict]:
        """Synthetic option chain — strikes around spot, CE/PE premiums ke saath.

        expiry: "23OCT25" format (None → current month ki monthly expiry).
        Returns: [{strike, ce: {symbol, premium}, pe: {symbol, premium}}]
        """
        und = underlying.strip().upper()
        spot = spot or _FNO_SPOT.get(und, 2000.0)
        step = _FNO_STRIKE_STEP.get(und, 50)
        if expiry:
            fno_date = parse_fno_symbol(f"{und}-{expiry}-FUT")
            exp = fno_date.expiry if fno_date else monthly_expiry(date.today().year, date.today().month)
        else:
            exp = monthly_expiry(date.today().year, date.today().month)
        days_left = max((exp - date.today()).days, 1)
        time_value = 120.0 * (days_left / 30.0) + 15.0
        exp_str = f"{exp.day:02d}{exp.strftime('%b').upper()}{exp.year % 100:02d}"

        rows = []
        for i in range(-10, 11):  # ±10 strikes around spot
            strike = round(spot + i * step, 2)
            ce_prem = max(spot - strike, 0.0) * 0.5 + time_value
            pe_prem = max(strike - spot, 0.0) * 0.5 + time_value
            rows.append({
                "strike": strike,
                "ce": {"symbol": f"{und}-{exp_str}-{int(strike)}-CE",
                       "premium": round(ce_prem, 2)},
                "pe": {"symbol": f"{und}-{exp_str}-{int(strike)}-PE",
                       "premium": round(pe_prem, 2)},
            })
        return rows

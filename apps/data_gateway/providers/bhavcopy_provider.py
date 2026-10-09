"""Bhavcopy provider — REAL NSE EOD data, no API key needed! 🇮🇳

Source: NSE archives (daily "bhavcopy" files).
Yeh wohi data hai jo NSE apni website pe daily publish karta hai.

Note: NSE kabhi-kabhi datacenter IPs ko block karta hai (403).
Agar block mile toh thodi der baad try karo ya VPN/phone hotspot se.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta

import requests

from apps.data_gateway.normalize import candle_from_bhavcopy_row
from apps.data_gateway.providers.base import DataProvider
from libs.shared.models import Candle


class BhavcopyProvider(DataProvider):
    name = "bhavcopy"

    BASE_URLS = [
        "https://archives.nseindia.com/content/historical/EQUITIES",
        "https://www.nseindia.com/content/historical/EQUITIES",
    ]
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def _candidate_urls(self, d: date) -> list[str]:
        dd = f"{d.day:02d}"
        mon = d.strftime("%b").upper()
        yy = f"{d.year % 100:02d}"
        fname = f"cm{dd}{mon}{yy}bhav.csv.zip"
        urls = []
        for base in self.BASE_URLS:
            urls.append(f"{base}/{d.year}/{d.strftime('%b').upper()}/{fname}")
            urls.append(f"{base}/{d.year}/{d.month:02d}/{fname}")
        return urls

    def fetch_eod(self, symbol: str, day: date, exchange: str = "NSE") -> list[Candle]:
        """Ek din ka bhavcopy download karke ek symbol ka candle banata hai."""
        for url in self._candidate_urls(day):
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
                text = io.TextIOWrapper(zf.open(csv_name), encoding="utf-8")
                for row in csv.DictReader(text):
                    if row.get("SYMBOL") == symbol and row.get("SERIES") == "EQ":
                        return [candle_from_bhavcopy_row(row, day, exchange)]
                return []  # file mili, symbol nahi — aage try mat karo
            except Exception:
                continue
        return []

    def get_historical(self, symbol: str, days: int = 60, exchange: str = "NSE") -> list[Candle]:
        """Last N trading days — recent se peeche jaate hue (weekends skip)."""
        candles: list[Candle] = []
        d = date.today()
        found = 0
        tried = 0
        while found < days and tried < days * 2 + 30:
            tried += 1
            if d.weekday() < 5:
                c = self.fetch_eod(symbol, d, exchange)
                if c:
                    candles.extend(c)
                    found += 1
            d -= timedelta(days=1)
        candles.reverse()  # oldest → newest
        return candles

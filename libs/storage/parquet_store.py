"""Parquet + DuckDB OHLCV storage.

Layout:  data/ohlcv/{INSTRUMENT_KEY}/{YYYY-MM}.parquet
Example: data/ohlcv/NSE_RELIANCE/2026-10.parquet

- write_candles(): existing data mein MERGE karta hai (incremental fetch, idempotent)
- read_candles():  DuckDB se direct Parquet pe SQL — fast, no loading
All timestamps: IST, naive.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from libs.shared.models import Candle

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "ohlcv"


def instrument_key(instrument: str) -> str:
    """'NSE:RELIANCE' → 'NSE_RELIANCE' (filesystem-safe)"""
    return instrument.replace(":", "_").replace("/", "_")


def instrument_from_dir(dir_name: str) -> str:
    """'NSE_RELIANCE' → 'NSE:RELIANCE' (list_instruments ke output ke liye)"""
    return dir_name.replace("_", ":", 1)


class ParquetStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- write ----------
    def write_candles(self, candles: list[Candle]) -> int:
        """Candles ko month-wise Parquet mein likho. Existing se merge + dedupe."""
        if not candles:
            return 0
        groups: dict[tuple[str, date], list[Candle]] = {}
        for c in candles:
            month = date(c.timestamp.year, c.timestamp.month, 1)
            groups.setdefault((c.instrument, month), []).append(c)

        total = 0
        for (instrument, month), group in sorted(groups.items()):
            path = self.root / instrument_key(instrument) / f"{month.year}-{month.month:02d}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)

            rows: list[dict] = []
            if path.exists():
                rows = pq.read_table(path).to_pylist()
            rows += [c.model_dump() for c in group]

            dedup: dict[datetime, dict] = {}
            for r in rows:
                dedup[r["timestamp"]] = r  # last write wins
            rows = sorted(dedup.values(), key=lambda r: r["timestamp"])

            pq.write_table(pa.Table.from_pylist(rows), path)
            total += len(group)
        return total

    # ---------- read ----------
    def read_candles(
        self,
        instrument: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Candle]:
        """Stored candles wapas lo (optionally date range mein)."""
        d = self.root / instrument_key(instrument)
        if not d.is_dir() or not any(d.glob("*.parquet")):
            return []
        q = (
            "SELECT instrument, timestamp, open, high, low, close, volume "
            "FROM read_parquet(?) WHERE instrument = ?"
        )
        params: list = [str(d / "*.parquet"), instrument]
        if start:
            q += " AND timestamp >= ?"
            params.append(datetime(start.year, start.month, start.day))
        if end:
            q += " AND timestamp <= ?"
            params.append(datetime(end.year, end.month, end.day, 23, 59, 59))
        q += " ORDER BY timestamp"
        rows = duckdb.connect().execute(q, params).fetchall()
        return [
            Candle(instrument=r[0], timestamp=r[1], open=r[2],
                   high=r[3], low=r[4], close=r[5], volume=r[6])
            for r in rows
        ]

    # ---------- meta ----------
    def list_instruments(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def summary(self, instrument: str) -> dict | None:
        rows = self.read_candles(instrument)
        if not rows:
            return None
        return {
            "instrument": instrument,
            "candles": len(rows),
            "from": str(rows[0].timestamp.date()),
            "to": str(rows[-1].timestamp.date()),
            "last_close": rows[-1].close,
            "high": max(r.high for r in rows),
            "low": min(r.low for r in rows),
        }

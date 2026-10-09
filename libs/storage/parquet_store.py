"""Parquet + DuckDB OHLCV storage.

Layout:  data/ohlcv/{INSTRUMENT_KEY}/{YYYY-MM}.parquet
Example: data/ohlcv/NSE_RELIANCE/2026-10.parquet

- write_candles(): existing data mein MERGE karta hai (incremental fetch, idempotent)
- read_candles():  DuckDB se direct Parquet pe SQL — fast, no loading
All timestamps: IST, naive.
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from threading import RLock

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from libs.shared.models import Candle

WRITE_LOCK = RLock()
KNOWN_SOURCES = frozenset({"unknown", "mock", "kite", "bhavcopy"})

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "ohlcv"


def instrument_key(instrument: str) -> str:
    """'NSE:RELIANCE' → 'NSE_RELIANCE' (filesystem-safe)"""
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,15}:[A-Z0-9][A-Z0-9&_.-]{0,79}", instrument):
        raise ValueError("Invalid instrument identifier")
    return instrument.replace(":", "_", 1)


def instrument_from_dir(dir_name: str) -> str:
    """'NSE_RELIANCE' → 'NSE:RELIANCE' (list_instruments ke output ke liye)"""
    return dir_name.replace("_", ":", 1)


class ParquetStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _instrument_directory(self, instrument: str) -> Path:
        directory = self.root / instrument_key(instrument)
        if not directory.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Instrument directory escapes storage root")
        return directory

    # ---------- write ----------
    def write_candles(self, candles: list[Candle], source: str = "unknown") -> int:
        if source not in KNOWN_SOURCES:
            raise ValueError("Unsupported data source")
        with WRITE_LOCK:
            return self._write_candles(candles, source)

    def _write_candles(self, candles: list[Candle], source: str) -> int:
        """Candles ko month-wise Parquet mein likho. Existing se merge + dedupe."""
        if not candles:
            return 0
        groups: dict[tuple[str, date], list[Candle]] = {}
        for c in candles:
            month = date(c.timestamp.year, c.timestamp.month, 1)
            groups.setdefault((c.instrument, month), []).append(c)

        total = 0
        for (instrument, month), group in sorted(groups.items()):
            path = self._instrument_directory(instrument) / f"{month.year}-{month.month:02d}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)

            rows: list[dict] = []
            if path.exists():
                rows = pq.read_table(path).to_pylist()
            rows = [{**row, "data_source": row.get("data_source") or "unknown"} for row in rows]
            rows += [{**c.model_dump(), "data_source": source} for c in group]

            dedup: dict[datetime, dict] = {}
            for r in rows:
                dedup[r["timestamp"]] = r  # last write wins
            rows = sorted(dedup.values(), key=lambda r: r["timestamp"])

            if path.is_symlink():
                raise ValueError("Symlink data files are not supported")
            descriptor, temporary_name = tempfile.mkstemp(prefix=".candles-", suffix=".tmp", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    pq.write_table(pa.Table.from_pylist(rows), output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary_name, path)
            finally:
                Path(temporary_name).unlink(missing_ok=True)
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
        d = self._instrument_directory(instrument)
        if any(path.is_symlink() for path in d.glob("*.parquet")):
            raise ValueError("Symlink data files are not supported")
        if not d.is_dir() or not any(d.glob("*.parquet")):
            return []
        q = (
            "SELECT instrument, timestamp, open, high, low, close, volume "
            "FROM read_parquet(?, union_by_name=true) WHERE instrument = ?"
        )
        params: list = [str(d / "*.parquet"), instrument]
        if start:
            q += " AND timestamp >= ?"
            params.append(datetime(start.year, start.month, start.day))
        if end:
            q += " AND timestamp <= ?"
            params.append(datetime(end.year, end.month, end.day, 23, 59, 59))
        q += " ORDER BY timestamp"
        with duckdb.connect() as connection:
            rows = connection.execute(q, params).fetchall()
        return [
            Candle(instrument=r[0], timestamp=r[1], open=r[2],
                   high=r[3], low=r[4], close=r[5], volume=r[6])
            for r in rows
        ]

    def provenance(self, instrument: str) -> dict:
        sources = set()
        for path in self._instrument_directory(instrument).glob("*.parquet"):
            if path.is_symlink():
                raise ValueError("Symlink data files are not supported")
            schema = pq.read_schema(path)
            if "data_source" not in schema.names:
                sources.add("unknown")
                continue
            sources.update(value or "unknown" for value in pq.read_table(path, columns=["data_source"]).column(0).to_pylist())
        status = "unknown" if not sources or "unknown" in sources else "mock" if sources == {"mock"} else "mixed" if "mock" in sources else "recorded_provider"
        return {"status": status, "sources": sorted(sources)}

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

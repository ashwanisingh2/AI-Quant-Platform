"""Explainable daily radar. No broker calls or execution side effects."""
from collections import Counter, defaultdict
from datetime import date, datetime
from math import isfinite
from statistics import mean
from zoneinfo import ZoneInfo

import duckdb
import pyarrow

from libs.storage.parquet_store import ParquetStore, instrument_from_dir

# Small display taxonomy, NOT an exchange-maintained F&O universe.
SECTORS = {
    'RELIANCE': 'Energy', 'ONGC': 'Energy', 'BPCL': 'Energy',
    'TCS': 'IT', 'INFY': 'IT', 'WIPRO': 'IT', 'HCLTECH': 'IT',
    'HDFCBANK': 'Banks', 'ICICIBANK': 'Banks', 'SBIN': 'Banks', 'AXISBANK': 'Banks',
    'TATAMOTORS': 'Auto', 'MARUTI': 'Auto', 'M&M': 'Auto',
    'SUNPHARMA': 'Healthcare', 'CIPLA': 'Healthcare',
}


def score_daily(candles):
    if len(candles) < 21:
        raise ValueError('Need 21 daily candles')
    rows = sorted(candles, key=lambda c: c.timestamp)[-61:]
    if len({c.timestamp.date() for c in rows}) != len(rows):
        raise ValueError('Daily candles required')
    for c in rows:
        if not all(isfinite(v) for v in (c.open, c.high, c.low, c.close, c.volume)):
            raise ValueError('Non-finite candle')
        if c.low <= 0 or c.low > min(c.open, c.close) or c.high < max(c.open, c.close) or c.volume < 0:
            raise ValueError('Invalid candle')
    previous, last = rows[:-1], rows[-1]
    adr = mean(c.high - c.low for c in previous[-20:])
    if adr <= 0:
        raise ValueError('Zero historical range')
    up, down = last.high - last.open, last.open - last.low
    clean = max(up, down) > 2 * min(up, down)
    score = (last.close - last.open) / adr if clean else 0.0
    direction = 'bullish' if score > 0 else 'bearish' if score < 0 else 'neutral'
    change = (last.close / previous[-1].close - 1) * 100
    return {
        'instrument': last.instrument, 'session': last.timestamp.date().isoformat(),
        'sector': SECTORS.get(last.instrument.split(':')[-1], 'Unclassified'),
        'close': last.close, 'change_pct': round(change, 3), 'score': round(score, 4),
        'direction': direction, 'adr': round(adr, 4),
        'support': min(c.low for c in previous[-20:]),
        'resistance': max(c.high for c in previous[-20:]),
        'reason': f'Close minus open / prior 20-session average range ({adr:.2f}). '
                  + ('Directional range passed 2:1 filter.' if clean else 'Two-sided range: score suppressed to zero.'),
        'candles': [{'date': c.timestamp.date().isoformat(), 'close': c.close} for c in rows],
    }


def snapshot(store=None, now=None):
    store = store or ParquetStore()
    today = (now or datetime.now(ZoneInfo('Asia/Kolkata'))).date().isoformat()
    rows, excluded = [], []
    instruments = store.list_instruments()
    for key in instruments[:300]:
        instrument = instrument_from_dir(key)
        if not instrument.startswith(('NSE:', 'BSE:')):
            excluded.append({'instrument': instrument, 'reason': 'Unsupported exchange'})
            continue
        try:
            history = store.read_candles(instrument)
            completed_history = [candle for candle in history if candle.timestamp.date().isoformat() < today]
            row = score_daily(completed_history)
            row["provenance"] = store.provenance(instrument)
            row["age_calendar_days"] = (date.fromisoformat(today) - date.fromisoformat(row["session"])).days
            row["freshness"] = "stale" if row["age_calendar_days"] > 7 else "historical"
            if row['session'] > today:
                raise ValueError('Future session')
            rows.append(row)
        except (ValueError, OSError, duckdb.Error, pyarrow.ArrowException):
            excluded.append({'instrument': instrument, 'reason': 'Unreadable or invalid daily history; need 21 sessions'})
    session = max((r['session'] for r in rows), default=None)
    eligible = [r for r in rows if r['session'] == session]
    for row in rows:
        if row['session'] != session:
            excluded.append({'instrument': row['instrument'], 'reason': 'Older than snapshot session'})
    eligible.sort(key=lambda r: (-abs(r['score']), r['instrument']))
    groups = defaultdict(list)
    for rank, row in enumerate(eligible, 1):
        row['rank'] = rank
        groups[row['sector']].append(row)
    breadth = Counter('advancing' if r['change_pct'] > 0 else 'declining' if r['change_pct'] < 0 else 'unchanged' for r in eligible)
    return {
        'mode': 'stored_daily', 'provenance': 'unverified', 'session': session,
        'notice': 'Historical daily data, not live. Today’s candles are excluded as potentially incomplete. Provider labels record origin, not independent verification.',
        'rows': eligible, 'breadth': {k: breadth[k] for k in ('advancing', 'declining', 'unchanged')},
        'sectors': sorted([{'sector': k, 'count': len(v), 'score': round(mean(r['score'] for r in v), 4)} for k, v in groups.items()], key=lambda s: -s['score']),
        'excluded': excluded, 'truncated': len(instruments) > 300,
        'coverage': len(eligible), 'universe': 'Loaded instruments only; not the full market or verified F&O universe',
    }

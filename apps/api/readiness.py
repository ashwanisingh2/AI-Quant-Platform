"""Dependency readiness, separate from process liveness and trading admission."""
import os
import sqlite3
import tempfile
from pathlib import Path

from apps.api.auth import configured_token


def check_readiness(storage_root: Path, journal) -> dict:
    checks = {'authentication': configured_token() is not None, 'storage': False, 'journal': False}
    try:
        with tempfile.TemporaryFile(dir=storage_root) as probe:
            probe.write(b'readiness')
            probe.flush()
            os.fsync(probe.fileno())
        checks['storage'] = True
    except OSError:
        pass
    try:
        with journal.connect() as connection:
            checks['journal'] = connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    except (sqlite3.Error, OSError):
        pass
    return {'status': 'ready' if all(checks.values()) else 'unavailable', 'checks': checks,
            'scope': 'service dependencies only; does not certify live trading or data freshness'}

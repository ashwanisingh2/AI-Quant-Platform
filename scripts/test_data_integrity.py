import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from apps.api.radar import snapshot
from apps.data_gateway.main import get_provider
from libs.storage.parquet_store import ParquetStore
from scripts.test_radar import candles


class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ParquetStore(self.directory.name)

    def test_provider_identity_and_mixed_history(self):
        history = candles()
        self.store.write_candles(history, source='mock')
        self.assertEqual(self.store.provenance('NSE:INFY')['status'], 'mock')
        self.store.write_candles(history[-1:], source='kite')
        self.assertEqual(self.store.provenance('NSE:INFY')['status'], 'mixed')
        self.assertEqual(len(self.store.read_candles('NSE:INFY')), 21)

    def test_unknown_history_never_promoted_by_partial_fetch(self):
        history = candles()
        self.store.write_candles(history)
        self.store.write_candles(history[-1:], source='kite')
        self.assertEqual(self.store.provenance('NSE:INFY')['status'], 'unknown')

    def test_interrupted_write_preserves_existing_file(self):
        self.store.write_candles(candles(), source='mock')
        with patch('libs.storage.parquet_store.pq.write_table', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.write_candles(candles(), source='kite')
        self.assertEqual(self.store.provenance('NSE:INFY')['status'], 'mock')
        self.assertEqual(len(self.store.read_candles('NSE:INFY')), 21)

    def test_staleness_and_same_day_exclusion(self):
        self.store.write_candles(candles(), source='mock')
        stale_snapshot = snapshot(self.store, datetime(2026, 2, 15))
        self.assertEqual(stale_snapshot['rows'][0]['freshness'], 'stale')
        self.assertEqual(stale_snapshot['rows'][0]['age_calendar_days'], 25)
        self.assertEqual(snapshot(self.store, datetime(2026, 1, 21))['coverage'], 0)

    def test_invalid_provider_is_recoverable(self):
        with self.assertRaises(ValueError):
            get_provider('not-a-provider')


if __name__ == '__main__':
    unittest.main()

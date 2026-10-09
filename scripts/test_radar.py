import os
import secrets
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from apps.api.radar import score_daily, snapshot
from libs.shared.models import Candle


def candles(symbol='NSE:INFY', offset=0):
    start = datetime(2026, 1, 1) + timedelta(days=offset)
    rows = [Candle(instrument=symbol, timestamp=start + timedelta(days=i), open=100, high=102, low=98, close=100, volume=10) for i in range(21)]
    rows[-1] = rows[-1].model_copy(update={'high': 109, 'low': 99, 'close': 108})
    return rows


class RadarTests(unittest.TestCase):
    def test_baseline_excludes_current_candle(self):
        row = score_daily(candles())
        self.assertEqual(row['adr'], 4)
        self.assertEqual(row['score'], 2)
        self.assertEqual(row['resistance'], 102)
        self.assertEqual(row['direction'], 'bullish')

    def test_choppy_and_bearish(self):
        rows = candles()
        rows[-1] = rows[-1].model_copy(update={'low': 91})
        self.assertEqual(score_daily(rows)['score'], 0)
        rows[-1] = rows[-1].model_copy(update={'high': 101, 'close': 92})
        self.assertEqual(score_daily(rows)['score'], -2)

    def test_invalid_and_intraday_rejected(self):
        for rows in (candles()[:20], candles() + [candles()[-1]], [c.model_copy(update={'high': float('inf')}) for c in candles()]):
            with self.assertRaises(ValueError):
                score_daily(rows)

    def test_mixed_sessions_excluded_from_breadth(self):
        store = Mock()
        store.list_instruments.return_value = ['NSE_INFY', 'NSE_TCS']
        store.read_candles.side_effect = [candles(), candles('NSE:TCS', -1)]
        data = snapshot(store, datetime(2026, 2, 1))
        self.assertEqual(data['coverage'], 1)
        self.assertEqual(data['breadth']['advancing'], 1)
        self.assertEqual(len(data['excluded']), 1)
        self.assertEqual(data['provenance'], 'unverified')

    def test_empty_and_corrupt(self):
        store = Mock()
        store.list_instruments.return_value = ['NSE_BAD']
        store.read_candles.side_effect = OSError('sensitive internal path')
        data = snapshot(store)
        self.assertIsNone(data['session'])
        self.assertNotIn('sensitive', str(data))

    def test_auth(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        operator_token = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {'API_AUTH_TOKEN': operator_token}):
            client = TestClient(app)
            self.assertEqual(client.get('/radar').status_code, 401)
            with patch('apps.api.main.radar_snapshot', return_value={'coverage': 0}):
                result = client.get('/radar', headers={'Authorization': f'Bearer {operator_token}'})
                self.assertEqual(result.status_code, 200)


if __name__ == '__main__':
    unittest.main()

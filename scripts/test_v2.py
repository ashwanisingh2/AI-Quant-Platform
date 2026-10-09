"""V2 contracts, recovery admission and real Nautilus decision parity."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from apps.engine.live import LiveTrader
from apps.engine.strategies.evaluator import StrategyEvaluator
from libs.storage.execution_journal import ExecutionJournal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.journal = ExecutionJournal(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_requires_reconciliation(self):
        run_id = self.journal.create_run('kite', 'NSE:TEST', 'live')
        other = ExecutionJournal(self.path)
        with self.assertRaises(ValueError):
            other.create_run('kite', 'NSE:TEST', 'live')
        other.reconcile(run_id, 'Verified all orders and positions directly at broker')
        self.assertTrue(other.create_run('kite', 'NSE:TEST', 'live'))
        self.assertEqual(len(other.snapshot()['runs']), 2)

    def test_concurrent_live_admission(self):
        def start(_):
            try:
                return self.journal.create_run('kite', 'NSE:TEST', 'live')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(start, range(2)))
        self.assertEqual(sum(bool(r) for r in results), 1)

    def test_submission_is_preceded_by_intent_and_timeout_is_unknown(self):
        run_id = self.journal.create_run('kite', 'NSE:TEST', 'dry_run')
        broker = Mock()
        def timeout(*args, **kwargs):
            self.assertEqual(self.journal.snapshot()['intents'][0]['state'], 'prepared')
            raise TimeoutError('secret broker error')
        broker.place_market_order.side_effect = timeout
        trader = LiveTrader('NSE:TEST', broker=broker, journal=self.journal, run_id=run_id)
        with self.assertRaises(TimeoutError):
            trader._submit_order('NSE', 'TEST', 'BUY', 1)
        snapshot = ExecutionJournal(self.path).snapshot()
        self.assertEqual(snapshot['intents'][0]['state'], 'unknown')
        self.assertNotIn('secret', str(snapshot))
        broker.place_market_order.assert_called_once()

    def test_journal_failure_prevents_submission(self):
        broker, journal = Mock(), Mock()
        journal.intent.side_effect = OSError('disk full')
        trader = LiveTrader('NSE:TEST', broker=broker, journal=journal, run_id='r')
        with self.assertRaises(OSError):
            trader._submit_order('NSE', 'TEST', 'BUY', 1)
        broker.place_market_order.assert_not_called()

    def test_api_attestation_is_explicit_and_active_run_protected(self):
        from fastapi.testclient import TestClient

        from apps.api import main
        token = 'v2-test-token-with-more-than-thirty-two-characters'
        run_id = self.journal.create_run('kite', 'NSE:TEST', 'live')
        with patch.object(main, 'journal', self.journal), patch.dict(os.environ, {'API_AUTH_TOKEN': token}):
            with TestClient(main.app) as client:
                headers = {'Authorization': 'Bearer ' + token}
                url = f'/operations/runs/{run_id}/reconcile'
                payload = {'confirm': 'I VERIFIED BROKER ORDERS AND POSITIONS',
                           'note': 'Checked the broker order book and all positions'}
                self.assertEqual(client.post(url, json=payload).status_code, 401)
                self.assertEqual(client.post(url, headers=headers, json={**payload, 'confirm': 'yes'}).status_code, 400)
                live = Mock(run_id=run_id, running=True)
                with patch.object(main, 'live_trader', live):
                    self.assertEqual(client.post(url, headers=headers, json=payload).status_code, 409)
                with patch.object(main, 'live_trader', None):
                    self.assertEqual(client.post(url, headers=headers, json=payload).status_code, 200)
                self.assertEqual(client.get('/operations', headers=headers).json()['unresolved_live_runs'], 0)
                self.assertEqual(client.post('/live/start', headers=headers, json={'instrument': 'NSE:TEST', 'capital': -1}).status_code, 422)


class KernelTests(unittest.TestCase):
    def test_invalid_input_fails_explicitly(self):
        for params in ({'quantity': 0}, {'fast_ema': 30, 'slow_ema': 10}, {'quantity': float('nan')}):
            with self.assertRaises(ValueError):
                StrategyEvaluator('ema_cross', params)
        with self.assertRaises(ValueError):
            StrategyEvaluator('ema_cross').on_price(float('nan'))

    def test_nautilus_trace_matches_shared_kernel(self):
        from apps.data_gateway.providers.mock_provider import MockProvider
        from apps.engine.data_loader import load_bars
        from apps.engine.runner import run_backtest
        from apps.engine.strategies import STRATEGIES
        from libs.storage.parquet_store import ParquetStore
        # Separate symbol; no existing user datasets are modified.
        ParquetStore().write_candles(MockProvider(seed=42).get_historical('V2PARITY', days=90))
        _, _, bars = load_bars('NSE:V2PARITY')
        prices = {b.ts_event: b.close.as_double() for b in bars}
        for name in ('ema_cross', 'rsi'):
            result = run_backtest('NSE:V2PARITY', name, cost_bps=10)
            evaluator = StrategyEvaluator(name, STRATEGIES[name]['defaults'])
            self.assertEqual(len(result['signal_trace']), len(bars))
            self.assertTrue(any(row['signal'] for row in result['signal_trace']))
            for row in result['signal_trace']:
                self.assertEqual(evaluator.on_price(prices[row['timestamp_ns']], row['held_qty']), row['signal'])
            self.assertEqual(len(result['data_sha256']), 64)
            self.assertLessEqual(result['net_return_pct'], result['total_return_pct'])
            self.assertEqual(result['validation'], 'in_sample_only')
            repeat = run_backtest('NSE:V2PARITY', name)
            self.assertEqual(result['data_sha256'], repeat['data_sha256'])
            self.assertEqual(result['signal_trace'], repeat['signal_trace'])


if __name__ == '__main__':
    unittest.main()

"""Failure-path regression tests. Fake brokers only; no real orders."""
import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from apps.engine.live import LiveTrader

ROOT = Path(__file__).resolve().parents[1]


class DevStartupTests(unittest.TestCase):
    def run_script(self, token=None):
        env = dict(os.environ)
        env.pop('API_AUTH_TOKEN', None)
        if token is not None:
            env['API_AUTH_TOKEN'] = token
        with tempfile.TemporaryDirectory() as directory:
            fake_python = Path(directory) / 'python3'
            fake_python.write_text('#!/bin/sh\n[ "$API_AUTH_TOKEN" = "$EXPECTED_TOKEN" ] || exit 9\nprintf "%s\\n" "$@"\n')
            fake_python.chmod(0o700)
            env['PATH'] = directory + os.pathsep + env['PATH']
            env['EXPECTED_TOKEN'] = token or ''
            return subprocess.run(['sh', str(ROOT / 'scripts/dev_api.sh')],
                                  env=env, capture_output=True, text=True)

    def test_missing_short_and_ci_tokens_rejected(self):
        for token in (None, 'short', 'ci-only-test-token-not-a-production-secret-123456'):
            self.assertNotEqual(self.run_script(token).returncode, 0)

    def test_private_token_preserved_and_not_printed(self):
        token = 'private-test-token-for-startup-verification-only'
        result = self.run_script(token)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(token, result.stdout + result.stderr)
        self.assertIn('127.0.0.1', result.stdout)


class TradingFailureTests(unittest.IsolatedAsyncioTestCase):
    def trader(self):
        broker = Mock()
        broker.mode = 'dry_run'
        broker.dry_run = True
        broker.open_orders.return_value = []
        broker.positions.return_value = []
        broker.all_orders.return_value = []
        trader = LiveTrader('NSE:TESTCO', broker=broker, trading_hours_only=False)
        trader.running = True
        return trader, broker

    async def test_cancel_failure_does_not_skip_other_actions(self):
        trader, broker = self.trader()
        broker.open_orders.return_value = [{'order_id': '1'}, {'order_id': '2'}]
        broker.cancel_order.side_effect = [RuntimeError('private SDK details'), {'status': 'CANCELLED'}]
        broker.positions.return_value = [
            {'symbol': 'A', 'qty': 2, 'product': 'MIS'}, {'symbol': 'B', 'qty': -3}]
        broker.place_market_order.side_effect = [RuntimeError('private details'), {'status': 'COMPLETE'}]
        result = trader.kill()
        self.assertEqual(broker.cancel_order.call_count, 2)
        self.assertEqual(broker.place_market_order.call_count, 2)
        self.assertEqual(result['cancelled_orders'], 1)
        self.assertEqual(result['squared_off'], 1)
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['manual_action_required'])
        self.assertNotIn('private', str(result))
        self.assertEqual(broker.place_market_order.call_args_list[0].kwargs['product'], 'MIS')
        self.assertFalse(trader.running)
        self.assertTrue(trader.risk.killed)

    async def test_pending_or_rejected_exits_never_count_as_fills(self):
        for status in ('OPEN', 'REJECTED', 'UNKNOWN'):
            trader, broker = self.trader()
            broker.positions.return_value = [{'symbol': 'A', 'qty': 1}]
            broker.place_market_order.return_value = {'status': status}
            result = trader.kill()
            self.assertEqual(result['squared_off'], 0)
            self.assertTrue(result['manual_action_required'])
            self.assertEqual(result['exit_orders_submitted'], int(status == 'OPEN'))
            self.assertEqual(trader.kill(), result)
            self.assertEqual(broker.place_market_order.call_count, 1)

    async def test_order_listing_failure_still_attempts_exits(self):
        trader, broker = self.trader()
        broker.open_orders.side_effect = RuntimeError()
        broker.positions.return_value = [{'symbol': 'A', 'qty': 1}]
        broker.place_market_order.return_value = {'status': 'COMPLETE'}
        self.assertEqual(trader.kill()['squared_off'], 1)
        broker.place_market_order.assert_called_once()

    async def test_crash_stops_and_emits_error_without_secret_text(self):
        trader, broker = self.trader()
        events = []
        trader.on_event = events.append
        class BrokenSource:
            async def get_price(self):
                raise RuntimeError('sensitive SDK details')
        trader.price_source = BrokenSource()
        await trader._loop()
        self.assertFalse(trader.running)
        self.assertTrue(trader.risk.killed)
        self.assertEqual(events[-1]['type'], 'live.error')
        self.assertNotIn('sensitive', str(events))
        broker.all_orders.side_effect = RuntimeError('account unavailable')
        state = trader.state()
        self.assertFalse(state['running'])
        self.assertFalse(state['portfolio_available'])
        self.assertEqual(state['last_error']['code'], 'trading_loop_failed')

    async def test_cancelled_loop_clears_running_without_error(self):
        trader, _ = self.trader()
        class WaitingSource:
            async def get_price(self):
                await asyncio.Future()
        trader.price_source = WaitingSource()
        task = asyncio.create_task(trader._loop())
        await asyncio.sleep(0)
        task.cancel()
        await task
        self.assertFalse(trader.running)
        self.assertIsNone(trader.last_error)

    async def test_api_reports_incomplete_exit(self):
        from unittest.mock import patch

        from apps.api import main
        trader, broker = self.trader()
        broker.positions.side_effect = RuntimeError()
        with patch.object(main, 'live_trader', trader), patch.object(main, 'paper_trader', None):
            result = await main.kill_switch()
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['manual_action_required'])


if __name__ == '__main__':
    unittest.main()

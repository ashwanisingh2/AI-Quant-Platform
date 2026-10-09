import os
import secrets
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api.readiness import check_readiness
from libs.storage.execution_journal import ExecutionJournal
from scripts.backup_journal import backup_journal
from scripts.init_deployment import initialize_configuration


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def test_configuration_private_and_never_overwritten(self):
        destination = self.root / '.env'
        initialize_configuration(destination)
        original = destination.read_bytes()
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertIn(b'LIVE_TRADING_ENABLED=false', original)
        with self.assertRaises(FileExistsError):
            initialize_configuration(destination)
        self.assertEqual(destination.read_bytes(), original)

    def test_readiness_is_fail_closed(self):
        journal = ExecutionJournal(self.root / 'execution.sqlite3')
        with patch.dict(os.environ, {'API_AUTH_TOKEN': secrets.token_urlsafe(32)}):
            self.assertEqual(check_readiness(self.root, journal)['status'], 'ready')
            self.assertEqual(check_readiness(self.root / 'missing', journal)['status'], 'unavailable')
        with patch.dict(os.environ, {'API_AUTH_TOKEN': ''}):
            self.assertEqual(check_readiness(self.root, journal)['status'], 'unavailable')

    def test_backup_restore_retains_unresolved_admission_gate(self):
        source = self.root / 'execution.sqlite3'
        journal = ExecutionJournal(source)
        run_id = journal.create_run('kite', 'NSE:TEST', 'live')
        intent_id = journal.intent(run_id, 'TEST', 'BUY', 1, 'entry')
        journal.outcome(intent_id, 'unknown')
        destination = self.root / 'restored.sqlite3'
        backup_journal(source, destination)
        restored = ExecutionJournal(destination)
        self.assertEqual(restored.snapshot()['unresolved_live_runs'], 1)
        self.assertEqual(restored.snapshot()['intents'][0]['state'], 'unknown')
        with self.assertRaises(ValueError):
            restored.create_run('kite', 'NSE:TEST', 'live')
        with self.assertRaises(FileExistsError):
            backup_journal(source, destination)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_corrupt_backup_is_removed(self):
        source = self.root / 'broken.sqlite3'
        source.write_text('invalid database')
        destination = self.root / 'backup.sqlite3'
        with self.assertRaises(sqlite3.Error):
            backup_journal(source, destination)
        self.assertFalse(destination.exists())

    def test_readiness_endpoint_requires_auth(self):
        from fastapi.testclient import TestClient

        from apps.api import main
        token = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {'API_AUTH_TOKEN': token}):
            client = TestClient(main.app)
            self.assertEqual(client.get('/ready').status_code, 401)
            with patch.object(main, 'check_readiness', return_value={'status': 'unavailable'}):
                self.assertEqual(client.get('/ready', headers={'Authorization': f'Bearer {token}'}).status_code, 503)


if __name__ == '__main__':
    unittest.main()

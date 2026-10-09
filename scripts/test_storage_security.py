import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from libs.storage.parquet_store import ParquetStore, instrument_key


class StorageBoundaryTests(unittest.TestCase):
    def test_unsafe_identifiers_rejected(self):
        for identifier in ('../secret', 'NSE:../../secret', '/etc/passwd', 'NSE:TEST*', 'NSE:TEST?', 'NSE:TEST\\outside', "NSE:TEST' OR 1=1"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                instrument_key(identifier)

    def test_valid_symbols_preserved(self):
        for identifier in ('NSE:M&M', 'NSE:BAJAJ-AUTO', 'NSE:TEST_EQ', 'BINANCE:BTCUSDT'):
            self.assertEqual(instrument_key(identifier), identifier.replace(':', '_', 1))

    def test_symlink_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            store = ParquetStore(root)
            (Path(root) / 'NSE_TEST').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                store.read_candles('NSE:TEST')

    def test_api_rejects_invalid_paths_and_limits(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        operator_token = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {"API_AUTH_TOKEN": operator_token}):
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {operator_token}"}
            self.assertEqual(client.get("/data/candles", params={"instrument": "../outside"}, headers=headers).status_code, 400)
            for limit in (0, -1, 5001):
                self.assertEqual(client.get("/data/candles", params={"instrument": "NSE:TEST", "limit": limit}, headers=headers).status_code, 422)

    def test_missing_valid_instrument_is_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(ParquetStore(root).read_candles('NSE:ABSENT'), [])


if __name__ == '__main__':
    unittest.main()

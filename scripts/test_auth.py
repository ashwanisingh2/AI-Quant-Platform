"""Authentication boundary tests; no broker calls or real funds."""
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.api.auth import AuthMiddleware, authenticate_websocket

TOKEN = "test-only-operator-token-with-32-plus-characters"


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"API_AUTH_TOKEN": TOKEN})
        self.env.start()
        app = FastAPI()
        app.add_middleware(AuthMiddleware)

        @app.get('/health')
        def health():
            return {'status': 'ok'}

        @app.post('/live/start')
        def sensitive():
            return {'ok': True}

        @app.websocket('/ws/events')
        async def events(ws: WebSocket):
            if await authenticate_websocket(ws):
                await ws.send_json({'authenticated': True})
                await ws.close()

        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def test_real_api_routes_are_protected(self):
        from apps.api.main import app
        with TestClient(app) as client:
            for route in app.routes:
                path = getattr(route, 'path', '')
                methods = getattr(route, 'methods', None)
                if methods and path != '/health':
                    method = 'POST' if 'POST' in methods else 'GET'
                    self.assertEqual(client.request(method, path).status_code, 401, path)
            self.assertEqual(client.get('/brokers', headers={
                'Authorization': 'Bearer ' + TOKEN}).status_code, 200)

    def test_http_boundary(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        for headers in ({}, {'Authorization': 'Bearer wrong'}):
            self.assertEqual(self.client.post('/live/start', headers=headers).status_code, 401)
        self.assertEqual(self.client.post('/live/start', headers={
            'Authorization': 'Bearer ' + TOKEN}).status_code, 200)
        self.assertEqual(self.client.get('/docs').status_code, 401)

    def test_missing_and_short_config_fail_closed(self):
        for token in ('', 'short'):
            with patch.dict(os.environ, {'API_AUTH_TOKEN': token}):
                self.assertEqual(self.client.post('/live/start').status_code, 503)

    def test_websocket_good_token(self):
        with self.client.websocket_connect('/ws/events', headers={
            'origin': 'http://localhost:5173'}) as ws:
            ws.send_json({'token': TOKEN})
            self.assertEqual(ws.receive_json(), {'authenticated': True})

    def test_websocket_rejects_bad_token_and_malformed_message(self):
        for message in ({'token': 'wrong'}, [], {'token': 123}):
            with self.client.websocket_connect('/ws/events') as ws:
                ws.send_json(message)
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_json()

    def test_websocket_rejects_foreign_origin(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/ws/events', headers={
                'origin': 'https://untrusted.example'}):
                pass

    def test_websocket_auth_timeout(self):
        with self.client.websocket_connect('/ws/events') as ws:
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_broker_credential_presence_requires_access_token(self):
        from apps.engine.brokers import available_brokers
        with patch.dict(os.environ, {'KITE_API_KEY': 'key', 'DHAN_CLIENT_ID': 'id',
                                    'KITE_ACCESS_TOKEN': '', 'DHAN_ACCESS_TOKEN': ''}):
            brokers = {b['name']: b for b in available_brokers()}
            self.assertFalse(brokers['kite']['credentials_present'])
            self.assertFalse(brokers['dhan']['credentials_present'])

    def test_broker_error_responses_fail(self):
        from unittest.mock import Mock

        from apps.engine.brokers.dhan_broker import DhanBroker
        from apps.engine.brokers.fyers_broker import FyersBroker
        for cls, attr, method in ((DhanBroker, '_dhan', 'get_fund_limits'),
                                  (FyersBroker, '_fyers', 'funds')):
            broker = cls(dry_run=True)
            broker.dry_run = False
            sdk = Mock()
            getattr(sdk, method).return_value = {'status': 'failure', 's': 'error'}
            setattr(broker, attr, sdk)
            with self.assertRaises(ValueError):
                broker.connect()


if __name__ == '__main__':
    unittest.main()

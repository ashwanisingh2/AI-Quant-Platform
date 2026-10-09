"""Single-operator API authentication. Secrets stay in memory; no cookies or URLs."""
import asyncio
import os
import secrets

from starlette.responses import JSONResponse


def configured_token():
    token = os.environ.get("API_AUTH_TOKEN", "")
    return token if len(token) >= 32 else None


def valid_token(value):
    expected = configured_token()
    return bool(expected and isinstance(value, str) and secrets.compare_digest(
        value.encode("utf-8"), expected.encode("utf-8")))


def allowed_origins():
    return [x.strip() for x in os.environ.get(
        "API_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if x.strip() and x.strip() != "*"]


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = dict(scope["headers"])
            value = headers.get(b"authorization", b"").decode("latin-1")
            if not configured_token():
                response = JSONResponse({"detail": "API authentication is not configured"}, 503)
                await response(scope, receive, send)
                return
            if not value.startswith("Bearer ") or not valid_token(value[7:]):
                response = JSONResponse({"detail": "Authentication required"}, 401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


async def authenticate_websocket(ws):
    origin = ws.headers.get("origin")
    if not configured_token() or (origin and origin not in allowed_origins()):
        await ws.close(code=1008)
        return False
    await ws.accept()
    try:
        message = await asyncio.wait_for(ws.receive_json(), timeout=5)
        if not isinstance(message, dict) or not valid_token(message.get("token")):
            await ws.close(code=1008)
            return False
    except Exception:
        await ws.close(code=1008)
        return False
    return True

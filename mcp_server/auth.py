"""HTTP Basic Auth for this server's Streamable-HTTP transport.

Copied from Agent/RLHF_Tools/mcp_servers/common/auth.py's pattern (generic,
not RLHF-specific) rather than imported from there, so this server has no
dependency on the RLHF_Tools folder or its venv.
"""
from __future__ import annotations

import base64
import binascii
import secrets

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next):
        if not self._is_authorized(request.headers.get("authorization")):
            return Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="mcp"'},
            )
        return await call_next(request)

    def _is_authorized(self, header: str | None) -> bool:
        if not header or not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.removeprefix("Basic "), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, sep, password = decoded.partition(":")
        if not sep:
            return False
        return secrets.compare_digest(username, self._username) and secrets.compare_digest(password, self._password)


def run_streamable_http(mcp, *, host: str, port: int, username: str, password: str) -> None:
    import uvicorn

    app: Starlette = mcp.streamable_http_app(host=host)
    app.add_middleware(BasicAuthMiddleware, username=username, password=password)

    uvicorn.run(app, host=host, port=port, log_level=mcp.settings.log_level.lower())

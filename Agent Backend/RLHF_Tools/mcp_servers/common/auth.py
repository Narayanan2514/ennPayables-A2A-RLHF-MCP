"""HTTP Basic Auth for the MCP servers' Streamable-HTTP transport.

Every server in mcp_servers/ now listens on its own local TCP port instead of
being spawned over stdio, so this is the only thing standing between that
port and an unauthenticated tool call. It is wired in via run_streamable_http
below (called from each server's `if __name__ == "__main__":` block) rather
than left as something a caller opts into.
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
        # secrets.compare_digest to avoid leaking match-length via timing
        return secrets.compare_digest(username, self._username) and secrets.compare_digest(password, self._password)


def run_streamable_http(mcp, *, host: str, port: int, username: str, password: str) -> None:
    """Serve an MCPServer (FastMCP) instance over Streamable-HTTP on host:port,
    gated by HTTP Basic Auth. Replaces `mcp.run(transport="streamable-http",
    host=host, port=port)` so the auth middleware can be inserted into the
    Starlette app it builds before uvicorn ever binds the socket.

    mcp>=2.0.0's Settings model has no host/port fields -- those are passed as
    call-time kwargs to streamable_http_app()/run_streamable_http_async()
    instead, unlike the pre-2.0 FastMCP where they lived on `.settings`.
    """
    import uvicorn

    app: Starlette = mcp.streamable_http_app(host=host)
    app.add_middleware(BasicAuthMiddleware, username=username, password=password)

    uvicorn.run(app, host=host, port=port, log_level=mcp.settings.log_level.lower())

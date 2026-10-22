"""Synchronous client for the shared pipeline-tools MCP server (../mcp_server).

Shells out to that project's mcp_call.py, run under ITS OWN venv, rather
than importing the `mcp` SDK into this process -- mcp>=2.0.0's dependency
pins (starlette/pydantic/uvicorn) are incompatible with the FastAPI version
every agent's own A2A service needs (confirmed: installing it here breaks
`FastAPI()` app construction outright). A subprocess per call costs a few
hundred ms of interpreter startup, negligible next to the multi-second
service calls each of these tools wraps (attachment download, OCR/vision
extraction, live ERP push).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from shared.config import settings

_PYTHON = Path(settings.PIPELINE_MCP_SERVER_DIR) / "myenv" / "Scripts" / "python.exe"
_MCP_CALL_SCRIPT = Path(settings.PIPELINE_MCP_SERVER_DIR) / "mcp_call.py"


class McpToolError(Exception):
    """Raised for a tool-level failure, a transport failure (server
    unreachable), or malformed output from the bridge subprocess -- callers
    already need to catch broadly around a remote call, so this collapses
    all three into one exception type."""


def call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    try:
        result = subprocess.run(
            [str(_PYTHON), str(_MCP_CALL_SCRIPT), tool_name],
            input=json.dumps(arguments),
            capture_output=True,
            text=True,
            timeout=settings.PIPELINE_MCP_CALL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise McpToolError(f"Could not reach pipeline-tools MCP server: {exc}") from exc

    stdout = (result.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        raise McpToolError(
            f"pipeline-tools MCP bridge returned non-JSON output (exit {result.returncode}): "
            f"{stdout!r} stderr={result.stderr!r}"
        )

    if result.returncode != 0:
        message = payload.get("error") if isinstance(payload, dict) else None
        raise McpToolError(message or f"MCP tool '{tool_name}' failed (exit {result.returncode})")

    return payload

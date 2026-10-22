"""CLI bridge: `python mcp_call.py <tool_name>` (JSON arguments on stdin)
connects to this folder's own running server and prints the tool's result
as JSON on stdout, or `{"error": ...}` plus a non-zero exit code on failure.

Exists so Agent's own processes (Agent/myenv) can reach this server's tools
without installing the `mcp` SDK into their own venv -- mcp>=2.0.0 pulls in
a starlette/pydantic/uvicorn bump that breaks the FastAPI version every
agent's own A2A service needs (see server.py's docstring for the exact
conflict). Agent's client (shared/mcp_tools/client.py) shells out to THIS
script, run under this project's own venv where the real mcp SDK lives,
instead of importing mcp directly.

Arguments travel on stdin rather than argv to avoid any OS command-line
length limit on a large attachments/encoded_image_paths list.
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import settings


async def _call(tool_name: str, arguments: dict) -> None:
    auth = (settings.MCP_USERNAME, settings.MCP_PASSWORD)
    url = f"http://{settings.MCP_HOST}:{settings.MCP_PORT}/mcp"
    # trust_env=False: this is always a same-machine call to our own server --
    # never route it through an HTTP_PROXY/HTTPS_PROXY a caller's environment
    # happens to have set (a corporate proxy silently intercepting/dropping a
    # localhost connection is a known failure mode already documented in
    # this codebase's client/orchestrator/exception_handling.py). Generous
    # connect timeout for a slow-to-schedule subprocess; no read timeout,
    # since a real tool call (vision extraction, ERP push) can legitimately
    # take a while -- the caller (shared/mcp_tools/client.py) enforces the
    # actual outer time budget via its own subprocess timeout.
    timeout = httpx2.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    async with httpx2.AsyncClient(auth=auth, trust_env=False, timeout=timeout) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.is_error:
                    detail = "; ".join(getattr(block, "text", "") for block in result.content) or f"tool '{tool_name}' failed"
                    print(json.dumps({"error": detail}))
                    sys.exit(1)
                if result.structured_content is not None:
                    print(json.dumps(result.structured_content))
                    return
                for block in result.content:
                    if hasattr(block, "text"):
                        print(block.text)
                        return
                print(json.dumps(None))


def main() -> None:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: mcp_call.py <tool_name>  (JSON arguments on stdin)"}))
        sys.exit(2)
    tool_name = sys.argv[1]
    try:
        arguments = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON arguments on stdin: {exc}"}))
        sys.exit(2)
    try:
        asyncio.run(_call(tool_name, arguments))
    except Exception as exc:
        print(json.dumps({"error": f"could not reach MCP server: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Unified MCP tool registry for the Orchestrator/Planner Agent (Section 3).

"the target architecture introduces an orchestrating agent that plans its own
next action by calling tools -- exposed through MCP servers -- rather than
being hardcoded to call Agent 2 after Agent 1."

Connects to every MCP server declared in SERVER_URLS over Streamable-HTTP
(each server is its own long-running process listening on its own local
port, started with `python -m mcp_servers.<name>_server`), authenticating
with the shared HTTP Basic Auth credentials (config.settings.mcp_username /
mcp_password) every server's transport enforces (see
mcp_servers/common/auth.py). Tool names are namespaced `<server>__<tool>` so
the same logical name (e.g. any server could plausibly expose a
`create_invoice`-style tool) never collides across servers.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config.settings import Settings, get_settings


def _server_urls(settings: Settings) -> dict[str, str]:
    host = settings.mcp_host
    return {
        "invoice_db": f"http://{host}:{settings.invoice_db_port}/mcp",
        "document_intelligence": f"http://{host}:{settings.document_intelligence_port}/mcp",
        "oracle_ebs": f"http://{host}:{settings.oracle_ebs_port}/mcp",
        "jde": f"http://{host}:{settings.jde_port}/mcp",
        "supplier_communication": f"http://{host}:{settings.supplier_communication_port}/mcp",
        "memory_policy": f"http://{host}:{settings.memory_policy_port}/mcp",
    }


@dataclass
class RegisteredTool:
    server_name: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.server_name}__{self.tool_name}"

    @property
    def wraps_result_in_envelope(self) -> bool:
        """True for any tool whose Python return type isn't a plain `dict` --
        Optional[dict], list, bool, str, etc. all get JSON-Schema-wrapped as
        {"result": ...} by the server SDK, since MCP structured output must be
        a JSON object at the top level. `insert_invoice`'s `dict[str, int]`
        return, by contrast, IS already an object and is never wrapped.
        """
        if not self.output_schema:
            return False
        return self.output_schema.get("required") == ["result"] and set(
            self.output_schema.get("properties", {})
        ) == {"result"}


class MCPToolRegistry:
    """Owns one live ClientSession (over Streamable-HTTP) per configured MCP
    server for the lifetime of an orchestrator run. Use as an async context
    manager:

        async with MCPToolRegistry() as registry:
            tools = registry.tool_schemas()
            result = await registry.call("invoice_db__get_invoice", {"src_id": "src_001"})
    """

    def __init__(self, server_urls: dict[str, str] | None = None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._server_urls = server_urls or _server_urls(self._settings)
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, RegisteredTool] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "MCPToolRegistry":
        auth = httpx2.BasicAuth(self._settings.mcp_username, self._settings.mcp_password)
        for server_name, url in self._server_urls.items():
            http_client = httpx2.AsyncClient(
                auth=auth, timeout=httpx2.Timeout(30.0, read=300.0), follow_redirects=True
            )
            await self._stack.enter_async_context(http_client)
            read, write = await self._stack.enter_async_context(
                streamable_http_client(url, http_client=http_client)
            )
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[server_name] = session

            listed = await session.list_tools()
            for tool in listed.tools:
                registered = RegisteredTool(
                    server_name=server_name,
                    tool_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                )
                self._tools[registered.qualified_name] = registered
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.qualified_name,
                "description": f"[{tool.server_name} MCP server] {tool.description}",
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def call(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(qualified_name)
        if tool is None:
            raise KeyError(f"Unknown tool '{qualified_name}'")
        session = self._sessions[tool.server_name]
        result = await session.call_tool(tool.tool_name, arguments)
        if result.is_error:
            raise RuntimeError(f"Tool {qualified_name} returned an error: {result.content}")
        # Tools returning a plain dict are auto-populated into
        # structured_content by the server SDK as-is; anything else
        # (Optional[dict], list, bool, str...) arrives wrapped as
        # {"result": <value>} because MCP structured output must be a JSON
        # object at the top level -- unwrap it back to the tool's real
        # Python return value.
        if result.structured_content is not None:
            if tool.wraps_result_in_envelope:
                return result.structured_content.get("result")
            return result.structured_content
        content = result.content
        if len(content) == 1 and getattr(content[0], "type", None) == "text":
            try:
                return json.loads(content[0].text)
            except json.JSONDecodeError:
                return content[0].text
        return content

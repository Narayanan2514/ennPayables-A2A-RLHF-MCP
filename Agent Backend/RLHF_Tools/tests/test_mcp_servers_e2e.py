"""End-to-end proof the MCP servers work over real Streamable-HTTP transport
with HTTP Basic Auth, not just as plain Python modules. Spawns
invoice_db_server and memory_policy_server as actual subprocesses listening
on local ports (mirroring how the Orchestrator/Planner Agent talks to them in
production, just over HTTP instead of stdio) and drives them through
orchestrator.mcp_client.

These take real process-spawn + HTTP-server-startup time (~1-3s per server)
-- kept to the two servers that need no external network calls (EBS/JDE/
OpenAI/Graph require live credentials this environment doesn't have, see
EXISTING_SYSTEM_AUDIT.md's validation-approach decision).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest

from config.settings import get_settings
from orchestrator.mcp_client import MCPToolRegistry

pytestmark = pytest.mark.asyncio

MCP_USERNAME = "test_admin"
MCP_PASSWORD = "test_pass123"

# Ports dedicated to this test module so a real dev instance of these servers
# (default ports from .env.example) can run on the same machine untouched.
SERVER_MODULES = {
    "invoice_db": ("mcp_servers.invoice_db_server", "INVOICE_DB_PORT", 18101),
    "memory_policy": ("mcp_servers.memory_policy_server", "MEMORY_POLICY_PORT", 18102),
}


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise TimeoutError(f"server on {host}:{port} did not start within {timeout}s")
    time.sleep(0.5)  # grace period for the ASGI app's lifespan/session manager to finish starting


@pytest.fixture
def mcp_settings(monkeypatch):
    monkeypatch.setenv("MCP_USERNAME", MCP_USERNAME)
    monkeypatch.setenv("MCP_PASSWORD", MCP_PASSWORD)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def running_servers(mcp_settings):
    env = dict(os.environ)
    procs: list[subprocess.Popen] = []
    urls: dict[str, str] = {}
    try:
        for name, (module, port_env_var, port) in SERVER_MODULES.items():
            env[port_env_var] = str(port)
            proc = subprocess.Popen([sys.executable, "-m", module], env=env)
            procs.append(proc)
            _wait_for_port("127.0.0.1", port)
            urls[name] = f"http://127.0.0.1:{port}/mcp"
        yield urls
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


async def test_tool_discovery_across_both_servers(running_servers, mcp_settings):
    async with MCPToolRegistry(running_servers, mcp_settings) as registry:
        names = {t["name"] for t in registry.tool_schemas()}
        assert "invoice_db__get_source" in names
        assert "memory_policy__get_bandit_weights" in names


async def test_optional_dict_return_unwraps_to_none_not_envelope(running_servers, mcp_settings):
    async with MCPToolRegistry(running_servers, mcp_settings) as registry:
        result = await registry.call("invoice_db__get_source", {"src_id": "does_not_exist"})
        assert result is None


async def test_log_event_then_list_exceptions_round_trips_over_http(running_servers, mcp_settings):
    async with MCPToolRegistry(running_servers, mcp_settings) as registry:
        await registry.call(
            "invoice_db__log_event",
            {"entity_id": "src_e2e", "status": "Failed", "stage": "EBS", "description": "e2e test"},
        )
        exceptions = await registry.call("invoice_db__list_exceptions", {"target_erp": "EBS", "limit": 10})
        assert any(e["entity_id"] == "src_e2e" for e in exceptions)


async def test_bandit_weights_tool_returns_fresh_priors_over_http(running_servers, mcp_settings):
    async with MCPToolRegistry(running_servers, mcp_settings) as registry:
        weights = await registry.call(
            "memory_policy__get_bandit_weights", {"supplier_name": "Acme Corp", "exception_type": "invalid_po"}
        )
        assert weights["escalate"]["alpha"] == 1.0
        assert weights["escalate"]["beta"] == 1.0


async def test_wrong_credentials_are_rejected(running_servers, mcp_settings):
    import httpx

    url = running_servers["invoice_db"]

    async with httpx.AsyncClient(auth=httpx.BasicAuth(MCP_USERNAME, "wrong-password")) as client:
        response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status_code == 401

    async with httpx.AsyncClient() as client:  # no Authorization header at all
        response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status_code == 401

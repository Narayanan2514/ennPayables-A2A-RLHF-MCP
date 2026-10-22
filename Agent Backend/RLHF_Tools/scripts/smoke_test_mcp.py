"""One-off smoke test: spawns the Invoice-DB and Memory-Policy MCP servers as
real Streamable-HTTP subprocesses (HTTP Basic Auth included), lists their
tools, and calls a couple end to end against a scratch sqlite DB -- proof the
MCP plumbing (not just the Python logic underneath it) actually works,
without needing live MySQL/EBS/JDE credentials.

Run with:
    python scripts/smoke_test_mcp.py
"""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("DB_URL_OVERRIDE", f"sqlite:///{tempfile.mktemp(suffix='.db')}")
os.environ.setdefault("CHROMA_PERSIST_DIR", tempfile.mkdtemp())
os.environ.setdefault("MCP_USERNAME", "admin")
os.environ.setdefault("MCP_PASSWORD", "pass123")
os.environ.setdefault("INVOICE_DB_PORT", "18201")
os.environ.setdefault("MEMORY_POLICY_PORT", "18202")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings  # noqa: E402
from db.session import create_legacy_tables_for_tests, create_new_tables  # noqa: E402
from orchestrator.mcp_client import MCPToolRegistry  # noqa: E402

create_legacy_tables_for_tests()
create_new_tables()

SERVER_MODULES = ["mcp_servers.invoice_db_server", "mcp_servers.memory_policy_server"]


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"server on {host}:{port} did not start within {timeout}s")


async def main():
    settings = get_settings()
    urls = {
        "invoice_db": f"http://{settings.mcp_host}:{settings.invoice_db_port}/mcp",
        "memory_policy": f"http://{settings.mcp_host}:{settings.memory_policy_port}/mcp",
    }

    procs = [subprocess.Popen([sys.executable, "-m", module], env=dict(os.environ)) for module in SERVER_MODULES]
    try:
        for name, url in urls.items():
            port = int(url.rsplit(":", 1)[1].split("/")[0])
            _wait_for_port(settings.mcp_host, port)
            print(f"  {name} up at {url}")
        time.sleep(0.5)  # grace period for the ASGI app's lifespan to finish starting

        async with MCPToolRegistry(urls, settings) as registry:
            schemas = registry.tool_schemas()
            print(f"\nDiscovered {len(schemas)} tools across {len(urls)} live MCP servers:")
            for s in schemas:
                print(f"  - {s['name']}")

            print("\nCalling invoice_db__get_source for a src_id that doesn't exist yet...")
            result = await registry.call("invoice_db__get_source", {"src_id": "src_999"})
            print(f"  -> {result!r}")
            assert result is None

            print("\nCalling invoice_db__log_event (stage=EBS, the stage list_exceptions filters on)...")
            result = await registry.call(
                "invoice_db__log_event",
                {"entity_id": "src_999", "status": "Failed", "stage": "EBS", "description": "smoke test"},
            )
            print(f"  -> {result!r}")

            print("\nCalling invoice_db__list_exceptions...")
            result = await registry.call("invoice_db__list_exceptions", {"target_erp": "EBS", "limit": 10})
            print(f"  -> {result!r}")
            assert any(r["entity_id"] == "src_999" for r in result)

            print("\nCalling memory_policy__get_bandit_weights...")
            result = await registry.call(
                "memory_policy__get_bandit_weights", {"supplier_name": "Acme Corp", "exception_type": "invalid_po"}
            )
            print(f"  -> {result!r}")

        print("\nSmoke test passed: real MCP Streamable-HTTP transport (with Basic Auth), tool discovery, and tool execution all work.")
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    asyncio.run(main())

"""Shared MCP tool server for ennvault's Agent pipeline (agent_1-4).

Phase 1 of consolidating each agent's own in-process tool into one shared
server: process_email_message/mark_email_invalid (Agent 1),
validate_intake_record (Agent 2), extract_and_store_invoice (Agent 3),
push_invoice_to_erp (Agent 4). Each tool is a thin wrapper over the SAME
service module its agent always used (Agent/agents/agent_N/services/*.py,
imported from the sibling Agent/ folder -- see settings.py -- not
duplicated here); only where that code executes changes, not what it does.

Phase 2 adds the RLHF-backed exception-handling tools (choose_bandit_action,
apply_learned_correction, apply_learned_email, escalate_to_human) -- thin
wrappers over RLHF_Tools/orchestrator/native_tools.py's existing handlers,
imported in place from the sibling Agent/RLHF_Tools folder (also not
duplicated; RLHF's own orchestrator/agent.py keeps using the same handlers
locally, unchanged). client/orchestrator/exception_handling.py calls these
here instead of RLHF's separate REST API.

The supervisor's self-correction loop adds attempt_self_correction --
bounded, one-shot re-extraction + retry for an 'invalid_item' ERP
rejection, tried before exception_handling.py's sequence runs (see
client/orchestrator/self_correction.py).

Served over Streamable-HTTP with HTTP Basic Auth, matching the convention
already used by Agent/RLHF_Tools/mcp_servers/*.py.

Run with this folder's own dedicated venv (kept separate from Agent/myenv --
installing the `mcp` SDK there pulls in a starlette/pydantic/uvicorn bump
that breaks FastAPI, which Agent's own A2A services depend on):
    myenv\\Scripts\\python.exe server.py
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer as FastMCP

import settings  # noqa: F401  -- import first: puts Agent/ on sys.path before tools/* import agents.*/shared.*

mcp = FastMCP("ennvault-pipeline-tools")

from tools import email_intake, erp_push, exception_handling, extraction, self_correction, validation  # noqa: E402

email_intake.register(mcp)
validation.register(mcp)
extraction.register(mcp)
erp_push.register(mcp)
exception_handling.register(mcp)
self_correction.register(mcp)


if __name__ == "__main__":
    from auth import run_streamable_http

    run_streamable_http(
        mcp,
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        username=settings.MCP_USERNAME,
        password=settings.MCP_PASSWORD,
    )

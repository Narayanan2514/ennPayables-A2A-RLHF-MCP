"""Environment-driven configuration for the shared pipeline-tools MCP server.

Phase 1 tools (process_email_message, mark_email_invalid,
validate_intake_record, extract_and_store_invoice, push_invoice_to_erp) --
Agent 1-4's own CrewAI tools (Agent/agents/*/skills/tools.py) call these
instead of each running its own in-process copy of
intake_service/validation_service/extraction_service/ebs_push/jde_push.

Phase 2 tools (choose_bandit_action, apply_learned_correction,
apply_learned_email, escalate_to_human) -- client/orchestrator/
exception_handling.py calls these instead of RLHF's separate REST API.

Neither set is duplicated here -- this server imports the existing service
modules in place from the sibling Agent/ and Agent/RLHF_Tools/ folders, so
both roots must be on sys.path before anything under tools/ imports
agents.*/shared.* or config.*/orchestrator.*/mcp_servers.*/learning.*.

NOTE: both Agent/ and Agent/RLHF_Tools/ happen to define a top-level `api`
package (Agent/api/ and Agent/RLHF_Tools/api/) -- neither is imported by
anything this server actually uses, but a bare `import api` here would be
ambiguous (resolves to whichever root sys.path lists first). Don't add one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_THIS_DIR = Path(__file__).resolve().parent
load_dotenv(_THIS_DIR / ".env")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


AGENT_ROOT = _env_str("AGENT_ROOT", str((_THIS_DIR.parent / "Agent").resolve()))
if AGENT_ROOT not in sys.path:
    sys.path.insert(0, AGENT_ROOT)

RLHF_ROOT = _env_str("RLHF_ROOT", str((_THIS_DIR.parent / "Agent" / "RLHF_Tools").resolve()))
if RLHF_ROOT not in sys.path:
    sys.path.insert(0, RLHF_ROOT)

MCP_HOST = _env_str("MCP_HOST", "127.0.0.1")
MCP_PORT = _env_int("MCP_PORT", 9010)
MCP_USERNAME = _env_str("MCP_USERNAME", "admin")
MCP_PASSWORD = _env_str("MCP_PASSWORD", "pass123")

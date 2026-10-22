"""Supervisor-level self-correction loop for one narrow ERP-push failure:
'item not found' (ExceptionType.INVALID_ITEM).

Runs BEFORE exception_handling.py's learned-replay-then-escalate sequence,
in `client/orchestrator/orchestrator.py`'s `_finish_from_recorded_steps`.
This module makes no decision beyond *sequencing*, same as
exception_handling.py: the actual classification, re-extraction, DB update,
retry-push, and correction-logging all happen self-contained inside the
`attempt_self_correction` MCP tool (mcp_server/tools/self_correction.py) --
this just gathers this run's already-recorded page images/mapping_path and
calls it.

Deliberately NOT an LLM call, for the same reason exception_handling.py
isn't: this is a fixed, bounded, one-shot retry, not something an LLM
should improvise turn to turn.
"""
from __future__ import annotations

import asyncio
from typing import Any

from shared.mcp_tools.client import McpToolError, call_tool
from shared.utilities.logging import get_logger

logger = get_logger("client.orchestrator.self_correction")

# Redefined locally rather than imported from orchestrator.py to avoid a
# circular import (orchestrator.py imports this module) -- same convention
# email_polling.py already uses for EMAIL_INTAKE_AGENT.
VALIDATOR_AGENT = "validator-agent"


async def attempt_self_correction(record: Any, src_id: str, target_erp: str, failure_message: str) -> dict[str, Any]:
    """Returns the attempt_self_correction MCP tool's result verbatim:
    {"attempted": False, ...} immediately for anything other than an
    invalid_item rejection (or if this run has no validator page images to
    re-extract from), {"attempted": True, "changed": False, ...} if it
    tried but the re-extraction didn't actually produce a different value,
    or {"attempted": True, "changed": True, "succeeded": bool, ...} once it
    retried the push. Never raises for an ordinary "nothing to fix" outcome
    or a transport hiccup -- the caller falls through to
    _run_exception_handling exactly as before in either case.
    """
    validator_step = next(
        (s for s in record.steps if s.get("agentId") == VALIDATOR_AGENT and s.get("status") == "completed"), None
    )
    validator_data = (validator_step or {}).get("data") or {}
    encoded_image_paths = validator_data.get("encoded_image_paths") or []
    mapping_path = validator_data.get("mapping_path")
    if not encoded_image_paths or not mapping_path:
        return {"attempted": False, "reason": "no validator page images available in this run to re-extract from"}

    try:
        result = await asyncio.to_thread(
            call_tool,
            "attempt_self_correction",
            {
                "src_id": src_id,
                "target_erp": target_erp,
                "failure_message": failure_message,
                "encoded_image_paths": encoded_image_paths,
                "mapping_path": mapping_path,
            },
        )
    except McpToolError as exc:
        logger.warning("src_id=%s: self-correction call to pipeline-tools MCP server failed: %s", src_id, exc)
        return {"attempted": False, "reason": f"pipeline-tools MCP server unreachable: {exc}"}

    return result

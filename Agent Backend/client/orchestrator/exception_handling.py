"""Autonomous exception handling after an ERP-push failure.

This is the decision step Phase 2 adds: `run_email_pipeline` calls
`handle_erp_failure` right after Agent 4's push comes back anything other
than "success". This module makes no decision of its own beyond *sequencing*
-- it calls RLHF's already-built, self-contained policy tools
(`RLHF_Tools/orchestrator/native_tools.py`, reached via the shared
pipeline-tools MCP server -- see ../../../mcp_server/tools/exception_handling.py)
in the exact order that project's own orchestrator/agent.py SYSTEM_PROMPT
specifies (step 5): always try apply_learned_correction, then
apply_learned_email, and only escalate to a human once both have genuinely
found nothing to replay. Document-detail lookup (is this src_id an open
exception, and its classification) still comes from RLHF's own REST API --
that's dashboard-composition logic (api/repo.py) this module was never
meant to duplicate, only the 4 action tools moved.

Deliberately NOT an LLM call: this sequence is fixed and mechanical (same
reasoning `run_email_pipeline` itself already documents for why it's plain
Python rather than an LLM-driven relay), and every step it calls is already
self-contained -- each one re-checks its own authorization, applies its own
fix, resubmits, and logs its own outcome/bandit reward. This module only
decides *whether* to call the next one.

While RLHF's AUTONOMY_STAGE is "shadow", every apply_learned_* call below
returns applied=false (governance unconditionally blocks), so this always
ends at escalate_to_human -- safe to run against production data before
anyone flips that to "limited".
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from shared.config.settings import RLHF_API_TIMEOUT_SECONDS, RLHF_API_URL
from shared.mcp_tools.client import McpToolError, call_tool
from shared.utilities.logging import get_logger

logger = get_logger("client.orchestrator.exception_handling")

ExceptionAction = Literal["auto_fix_line_item", "email_supplier", "escalated", "skipped"]


async def _call_policy_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Calls one of the 4 exception-handling policy tools on the shared
    pipeline-tools MCP server. Run in a thread since
    shared.mcp_tools.client.call_tool is a blocking subprocess call (it
    shells out to mcp_server's own venv -- see that module's docstring for
    why), and this whole sequence runs inside the orchestrator's async
    event loop."""
    return await asyncio.to_thread(call_tool, tool_name, args)


async def _get_document_detail(client: httpx.AsyncClient, src_id: str) -> dict[str, Any] | None:
    response = await client.get(f"{RLHF_API_URL}/api/documents/{src_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def handle_erp_failure(src_id: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Runs the learned-replay-then-escalate sequence for one failed/on-hold
    push. Returns {"action": ..., "detail": {...}} -- never raises for an
    ordinary "nothing to replay yet" outcome; a genuine RLHF-API
    unreachability is caught and reported as action="skipped" so a hiccup in
    the exception-handling side-channel never breaks the pipeline run itself.

    `client` can be injected for testing (e.g. an httpx.AsyncClient wired to
    an httpx.MockTransport) -- production code leaves it unset, same
    convention as a2a_client.client.call_agent_task.
    """
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=RLHF_API_TIMEOUT_SECONDS)
    try:
        detail = await _get_document_detail(active_client, src_id)
        if detail is None or not detail.get("is_open_exception") or not detail.get("recommendation"):
            return {"action": "skipped", "reason": "no open exception found for this src_id"}

        supplier_name = (detail.get("header") or {}).get("supplier_name") or "unknown"
        exception_type = detail["recommendation"]["exception_type"]

        bandit_choice = await _call_policy_tool(
            "choose_bandit_action", {"supplier_name": supplier_name, "exception_type": exception_type}
        )
        action_recommended = bandit_choice.get("action", "escalate")

        correction = await _call_policy_tool(
            "apply_learned_correction",
            {"src_id": src_id, "supplier_name": supplier_name, "exception_type": exception_type},
        )
        if correction.get("applied") and correction.get("succeeded"):
            logger.info("src_id=%s: auto-fixed via learned correction", src_id)
            return {"action": "auto_fix_line_item", "detail": correction}

        email = await _call_policy_tool(
            "apply_learned_email",
            {"src_id": src_id, "supplier_name": supplier_name, "exception_type": exception_type},
        )
        if email.get("applied"):
            logger.info("src_id=%s: auto-emailed supplier via learned precedent", src_id)
            return {"action": "email_supplier", "detail": email}

        escalation = await _call_policy_tool(
            "escalate_to_human",
            {
                "src_id": src_id,
                "supplier_name": supplier_name,
                "exception_type": exception_type,
                "action_recommended": action_recommended,
                "reason": email.get("reason") or correction.get("reason") or "no learned precedent yet or not authorized",
            },
        )
        logger.info("src_id=%s: escalated to human (%s)", src_id, escalation)
        return {"action": "escalated", "detail": escalation}

    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
        # str(exc) can be empty for some low-level httpx/httpcore connection
        # errors (e.g. a proxy env var like HTTP_PROXY/ALL_PROXY silently
        # swallowing a localhost connection) -- repr() + the exception type
        # name + any wrapped __cause__ gives something to actually diagnose,
        # where "RLHF API unreachable: " alone does not.
        detail = repr(exc)
        if exc.__cause__ is not None:
            detail += f" (caused by: {exc.__cause__!r})"
        logger.warning("src_id=%s: exception-handling call to RLHF API failed: %s", src_id, detail)
        return {"action": "skipped", "reason": f"RLHF API unreachable: {type(exc).__name__}: {detail}"}
    except McpToolError as exc:
        logger.warning("src_id=%s: exception-handling call to pipeline-tools MCP server failed: %s", src_id, exc)
        return {"action": "skipped", "reason": f"pipeline-tools MCP server unreachable: {exc}"}
    finally:
        if owns_client:
            await active_client.aclose()

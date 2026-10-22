"""Memory / Policy MCP Server (proposal Section 3).

"searchSimilarCases, logCorrection, getBanditWeights -- the new component that
makes the feedback loop possible (Sections 4.2-4.4)."

This is the one server with no ennvault-existing analog at all -- audit
section 13: "no confidence-score column exists anywhere in the schema... no
dedicated exceptions or corrections table exists either." Everything here is
net-new (db/new_schema.py + learning/*).

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.memory_policy_server
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from learning import bandit_store, feedback_logger
from learning.exemplar_refresh import get_active_exemplars, refresh_exemplars
from learning.vector_memory import search_similar_cases

mcp = FastMCP("memory-policy")


@mcp.tool()
def search_similar_cases_tool(
    supplier_name: str,
    exception_type: str,
    features: dict[str, Any],
    document_layout: str | None = None,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve similar past resolved exceptions for this supplier + exception
    type, to use as few-shot context before deciding how to handle a new one
    (Section 4.2). Indexed on supplier, exception type, document layout, and
    amount (via the `features` dict).
    """
    return search_similar_cases(supplier_name, exception_type, features, document_layout, n_results)


@mcp.tool()
def log_correction(
    src_id: str,
    supplier_name: str,
    doc_type: str,
    exception_type: str,
    invoice_features: dict[str, Any],
    ai_recommendation: str,
    human_action: str,
    ai_recommendation_correct: bool | None = None,
    confidence_at_decision: float | None = None,
    document_layout: str | None = None,
) -> dict[str, Any]:
    """Log a resolved exception as a labeled training example. Called every
    time a human corrects (or confirms) an AI decision -- this is the write
    side of the feedback loop (Section 4.2, Section 5's data-flow diagram).
    """
    correction_id = feedback_logger.log_correction(
        src_id,
        supplier_name,
        doc_type,
        exception_type,
        invoice_features,
        ai_recommendation,
        human_action,
        ai_recommendation_correct,
        confidence_at_decision,
        document_layout,
    )
    return {"correction_id": correction_id}


@mcp.tool()
def get_bandit_weights(supplier_name: str, exception_type: str) -> dict[str, dict[str, float]]:
    """Return the current Beta(alpha, beta) posterior for every action in this
    exception type's action space, for this supplier (Section 4.3). The
    orchestrator's Thompson-sampling policy (orchestrator/bandit.py) reads
    this before deciding an action.
    """
    return bandit_store.get_arm_states(supplier_name, exception_type)


@mcp.tool()
def update_bandit_weights(supplier_name: str, exception_type: str, action: str, success: bool) -> dict[str, str]:
    """Feed a realized outcome back into the bandit posterior for this arm
    (success = the action held without human reversal or later dispute).
    """
    bandit_store.update_arm(supplier_name, exception_type, action, success)
    return {"updated": "true", "supplier_name": supplier_name, "exception_type": exception_type, "action": action}


@mcp.tool()
def get_few_shot_exemplars(supplier_name: str, doc_type: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return the current few-shot exemplar library for this supplier + doc
    type (Section 4.4), for injection into the Document-Intelligence server's
    extraction prompts.
    """
    return get_active_exemplars(supplier_name, doc_type, limit)


@mcp.tool()
def refresh_exemplar_library() -> dict[str, int]:
    """Trigger an on-demand refresh of the few-shot exemplar library from
    accumulated corrections (normally run on a schedule by
    learning/exemplar_refresh.py via supervisor_main.py, exposed here so the
    orchestrator/a human can also trigger it ad hoc).
    """
    return refresh_exemplars()


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.memory_policy_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

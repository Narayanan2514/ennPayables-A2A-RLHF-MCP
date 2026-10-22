"""Invoice-DB MCP Server (proposal Section 3).

"query, insert, and update invoice records -- the same persistence layer
Agent 1 writes to today, now addressable as tools."

Wraps db/legacy_schema.py + mcp_servers/common/legacy_repo.py -- the exact
tables ennvault-existing's entity_extractor/db.py already writes to
(inv_header, inv_line, po_header, po_line, jde_inv_header/lines, source,
log_table). No new tables here; this server is purely a tool-shaped front door
onto the existing persistence layer.

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.invoice_db_server
"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from mcp_servers.common import legacy_repo

mcp = FastMCP("invoice-db")


@mcp.tool()
def get_source(src_id: str) -> dict[str, Any] | None:
    """Look up the master `source` record for a document (target ERP, doc_type,
    channel, archive path). This is the entry point for resolving any src_id.
    """
    return legacy_repo.get_source(src_id)


@mcp.tool()
def get_invoice(src_id: str) -> dict[str, Any] | None:
    """Fetch the invoice header plus its line items for a given src_id.

    Returns None if no inv_header row exists yet for this src_id (e.g. it
    hasn't finished extraction, or it's an EBS-only table and the ERP was JDE).
    """
    header = legacy_repo.get_invoice_header(src_id)
    if header is None:
        return None
    header["lines"] = legacy_repo.get_invoice_lines(header["id"])
    return header


@mcp.tool()
def get_jde_invoice(src_id: str) -> dict[str, Any] | None:
    """Fetch the JDE invoice header + lines (jde_inv_header/jde_inv_lines) for a src_id."""
    return legacy_repo.get_jde_invoice(src_id)


@mcp.tool()
def get_purchase_order(po_number: str) -> dict[str, Any] | None:
    """Fetch a purchase order header + lines by PO number, for cross-checking an
    invoice's customer_po_number before submission (used by the Verifier agent
    and confidence-aware routing, Sections 4.1/4.5).
    """
    header = legacy_repo.get_po_header_by_number(po_number)
    if header is None:
        return None
    header["lines"] = legacy_repo.get_po_lines(header["id"])
    return header


@mcp.tool()
def insert_invoice(src_id: str, header_fields: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, int]:
    """Persist a freshly-extracted invoice (from the Document-Intelligence
    server's extract_invoice output) into inv_header/inv_line. Call this after
    confidence-aware routing decides straight_through or auto_correct, before
    attempting ERP submission.
    """
    header_id = legacy_repo.insert_invoice(src_id, header_fields, lines)
    return {"header_id": header_id}


@mcp.tool()
def update_invoice_field(header_id: int, field: str, value: str) -> bool:
    """Update a single allow-listed field on an invoice header (e.g. after a
    human correction or an auto-fix action). Mirrors the field allow-list
    ennvault-existing's request_approval_ebs_db already enforces so an agent
    cannot write to arbitrary columns.
    """
    return legacy_repo.update_invoice_field(header_id, field, value)


@mcp.tool()
def update_invoice_line_field(line_id: int, field: str, value: str) -> bool:
    """Update a single allow-listed field on an invoice line (e.g. a wrong
    item_name causing an invalid_item exception). Line-level counterpart to
    update_invoice_field.
    """
    return legacy_repo.update_invoice_line_field(line_id, field, value)


@mcp.tool()
def list_exceptions(target_erp: str = "EBS", limit: int = 50) -> list[dict[str, Any]]:
    """List currently-active exception entities (status Failed/OnHold, stage
    EBS/JDE) -- the same query backing ennvault-existing's Exceptions tab.
    """
    return legacy_repo.list_exceptions(target_erp=target_erp, limit=limit)


@mcp.tool()
def log_event(
    entity_id: str,
    status: Literal["Successful", "Failed", "OnHold"],
    stage: str,
    description: str,
    is_reviewed: str = "0",
    action_taken: str = "",
) -> dict[str, str]:
    """Append a status event to the shared audit trail (log_table), deactivating
    prior rows for this entity. Every orchestrator decision, verifier verdict,
    and governance gate outcome should be logged here with stage="MCP" so the
    existing Collections/Processed/Exceptions UI stays a truthful view of what
    the new agents did.

    `status` MUST be exactly one of "Successful", "Failed", or "OnHold" --
    never a free-text description of what happened (that belongs in
    `description`). Every list/count/dashboard in this system matches on
    these exact three strings; anything else makes the row invisible to the
    Manual Review queue, the dashboard, and governance metrics even though it
    exists in the database. Use "Failed" for an exception still awaiting a
    fix or a decision (including "escalated to a human" -- escalating does
    NOT mean the case is resolved), "OnHold" for a hold pending approval, and
    "Successful" only once the case is genuinely closed out (autonomously
    fixed and resubmitted, or a human's decision was recorded).
    """
    legacy_repo.insert_log(entity_id, status, stage, description, is_reviewed=is_reviewed, action_taken=action_taken)
    return {"logged": "true", "entity_id": entity_id, "stage": stage}


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.invoice_db_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

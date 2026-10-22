"""Oracle-EBS MCP Server (proposal Section 3).

"createInvoice, matchPO, getSupplierMaster, holdInvoice -- a thin, versioned
wrapper around the existing REST API."

createInvoice hits the real create_invoices REST webservice documented in
AP_EBS_API_Documentation.txt, same payload shape ennvault-existing's
ERP/EBS/inv_payload.py builds. matchPO and getSupplierMaster are local,
Invoice-DB-backed pre-checks (there is no dedicated EBS REST endpoint for
either documented in AP_EBS_API_Documentation.txt -- PO/supplier validation
today happens implicitly inside create_invoices itself, surfacing as an
X_MESSAGE error). Doing the pre-check locally lets the orchestrator route on
confidence *before* spending an EBS round-trip. holdInvoice records a hold in
the shared log_table since EBS itself has no formal hold state today (audit
section 9/section on JDE vs EBS hold model) -- unlike JDE's ApprovalRequired
flow, an EBS hold is purely a new-architecture concept until Oracle exposes
one.

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.oracle_ebs_server
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from mcp_servers.common import legacy_repo
from mcp_servers.common.ebs_client import build_invoice_payload, call_create_invoice
from mcp_servers.common.errors import classify_erp_error

mcp = FastMCP("oracle-ebs")


@mcp.tool()
def create_invoice(src_id: str) -> dict[str, Any]:
    """Submit an invoice (already extracted into inv_header/inv_line for this
    src_id) to Oracle EBS via the create_invoices REST webservice. Returns the
    structured result plus a classified exception_type/action_space if it
    failed, and writes the outcome to the shared log_table (stage="EBS").
    """
    header = legacy_repo.get_invoice_header(src_id)
    if header is None:
        return {"status": "E", "message": f"No inv_header found for src_id={src_id}"}
    lines = legacy_repo.get_invoice_lines(header["id"])
    payload = build_invoice_payload(header, lines)
    result = call_create_invoice(payload)

    if result["status"] == "S":
        legacy_repo.insert_log(src_id, "Successful", "EBS", result.get("message", "AP Invoice processed successfully"))
        return result

    classified = classify_erp_error(result.get("message"))
    legacy_repo.insert_log(src_id, "Failed", "EBS", result.get("message", ""))
    return {**result, "exception_type": classified.exception_type.value, "action_space": classified.action_space}


@mcp.tool()
def match_po(po_number: str, invoice_amount: float | None = None) -> dict[str, Any]:
    """Pre-check whether a PO number exists and (optionally) whether the given
    invoice amount is within the PO's line-total envelope, before attempting
    EBS submission. Local DB lookup, not a live Oracle call.

    Looks up inv_header/inv_line rather than po_header/po_line: po_header only
    fills from a separately-emailed "po" document, which an invoice-only flow
    (the normal case here) never produces, so it would always report
    po_not_found. inv_header is guaranteed populated by the time this runs
    (insert_invoice always precedes match_po), so the invoice's own extracted
    PO number and line totals stand in for a real PO record.
    """
    inv = legacy_repo.get_invoice_header_by_po_number(po_number)
    if inv is None:
        return {"matched": False, "reason": "po_not_found"}
    lines = legacy_repo.get_invoice_lines(inv["id"])
    po_total = 0.0
    for line in lines:
        try:
            po_total += float(line.get("total") or 0)
        except (TypeError, ValueError):
            continue
    within_envelope = invoice_amount is None or po_total == 0 or invoice_amount <= po_total * 1.05
    return {"matched": True, "po_total": po_total, "within_envelope": within_envelope}


@mcp.tool()
def get_supplier_master(supplier_name: str) -> dict[str, Any]:
    """Best-effort supplier lookup from prior invoice history (there is no
    documented EBS supplier-master REST endpoint to call directly -- this is a
    proxy signal for "have we successfully invoiced this supplier before",
    useful input to confidence-aware routing).
    """
    from sqlalchemy import select

    from db.legacy_schema import InvHeader
    from db.session import session_scope

    with session_scope() as session:
        rows = session.scalars(
            select(InvHeader).where(InvHeader.supplier_name == supplier_name)
        ).all()
        return {
            "supplier_name": supplier_name,
            "known_supplier": len(rows) > 0,
            "prior_invoice_count": len(rows),
        }


@mcp.tool()
def hold_invoice(src_id: str, reason: str) -> dict[str, str]:
    """Place an invoice on hold pending human review. EBS has no formal
    server-side hold state today (unlike JDE's ApprovalRequired flow) -- this
    records the hold in the shared audit trail so it surfaces in the
    Exceptions view exactly like a Failed row does, with action_taken noting
    it's a policy hold rather than an ERP-side rejection.
    """
    legacy_repo.insert_log(src_id, "OnHold", "EBS", reason, action_taken="Policy Hold")
    return {"src_id": src_id, "status": "OnHold"}


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.oracle_ebs_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

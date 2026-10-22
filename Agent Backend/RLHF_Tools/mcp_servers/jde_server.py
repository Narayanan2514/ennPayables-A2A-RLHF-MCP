"""JDE MCP Server.

The proposal's Section 3 topology names an Oracle-EBS MCP server explicitly;
ennvault-existing's pipeline also targets JDE for a subset of customers
(`TARGET_ERP` env var), so this is the JDE-side sibling exposing the same
multi-step orchestrator flow as ERP/JDE/inv_payload.py (audit section 8):
CheckPO -> AddSupplierInvoice -> [voucher hold branch] -> RunVMADriverUBE.

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.jde_server
"""
from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from mcp_servers.common import legacy_repo
from mcp_servers.common.jde_client import (
    add_supplier_invoice,
    approve_voucher as jde_approve_voucher,
    check_po,
    check_vma_batch_status,
    run_vma_driver_ube,
)

mcp = FastMCP("jde-erp")


@mcp.tool()
def check_purchase_order(order_number: str) -> dict[str, Any]:
    """Validate an order number against JDE and resolve CompanyNo/CostCenter/OrderType.
    ErrorCode == "2" signals a hard failure (order not found / invalid).
    """
    response = check_po(order_number)
    return {
        "error_code": response.get("ErrorCode"),
        "error_description": response.get("ErrorDescription"),
        "company_no": response.get("CompanyNo"),
        "cost_center": response.get("CostCenter"),
        "order_type": response.get("OrderType"),
    }


@mcp.tool()
def create_invoice(src_id: str) -> dict[str, Any]:
    """Run the full JDE submission flow for a previously-extracted invoice:
    CheckPO -> AddSupplierInvoice -> (voucher-hold branch if ApprovalRequired)
    -> RunVMADriverUBE. Mirrors ERP/JDE/inv_payload.py's push_to_jde exactly,
    with every stage logged to the shared log_table (stage="JDE").
    """
    invoice = legacy_repo.get_jde_invoice(src_id)
    if invoice is None:
        return {"status": "error", "message": f"No jde_inv_header found for src_id={src_id}"}

    for line in invoice["lines"]:
        po_check = check_po(line["order_number"] or "")
        if po_check.get("ErrorCode") == "2":
            legacy_repo.insert_log(src_id, "Failed", "JDE", po_check.get("ErrorDescription", "PO check failed"))
            return {"status": "error", "message": po_check.get("ErrorDescription")}
        legacy_repo.update_jde_header_from_po_check(
            invoice["id"], po_check.get("CompanyNo", ""), po_check.get("CostCenter", "")
        )

    grid_in = [
        {
            "GrossAmount": line["gross_amount"],
            "Remark": "Auto-submitted by agentic AP pipeline",
            "AutomationFlag": "Y",
            "OrderNumber": line["order_number"],
            "ItemNumber": line["item_number"],
        }
        for line in invoice["lines"]
    ]
    add_result = add_supplier_invoice(
        company=invoice["company"],
        supplier_number=invoice["supplier_number"],
        invoice_number=invoice["invoice_number"],
        invoice_date=invoice["invoice_date"],
        gl_date=date.today().isoformat(),
        business_unit=invoice["business_unit"],
        grid_in=grid_in,
    )

    if add_result.get("Status") != "SUCCESS":
        legacy_repo.insert_log(src_id, "Failed", "JDE", str(add_result.get("message", add_result)))
        return {"status": "error", "message": add_result}

    batch_number = add_result.get("BatchNumber", "")
    if add_result.get("ApprovalRequired") == "Y":
        legacy_repo.update_jde_batch_number(invoice["id"], batch_number, approval_required="Y")
        legacy_repo.insert_log(src_id, "OnHold", "JDE", "Voucher is on hold pending approval")
        return {"status": "on_hold", "batch_number": batch_number, "approver_email": add_result.get("ApproverEmail")}

    legacy_repo.update_jde_batch_number(invoice["id"], batch_number, approval_required="N")
    ube_result = run_vma_driver_ube(batch_number)
    if ube_result.get("Status") != "SUCCESS":
        legacy_repo.insert_log(src_id, "Failed", "JDE", "RunVMADriverUBE failed")
        return {"status": "error", "message": ube_result}

    legacy_repo.insert_log(src_id, "Successful", "JDE", "Invoice pushed to JDE")
    return {"status": "success", "message": "Invoice pushed to JDE"}


@mcp.tool()
def approve_voucher(src_id: str) -> dict[str, Any]:
    """Resolve a JDE 'OnHold' voucher: ApproveVoucher -> RunVMADriverUBE ->
    CheckVMABatchStatus. Mirrors ennvault-existing's /approve_voucher endpoint.
    """
    invoice = legacy_repo.get_jde_invoice(src_id)
    if invoice is None or not invoice.get("batch_number"):
        return {"status": "error", "message": "No batch_number on file for this src_id"}
    batch_number = invoice["batch_number"]

    approve_result = jde_approve_voucher(batch_number)
    if approve_result.get("Status") != "SUCCESS":
        legacy_repo.insert_log(src_id, "Failed", "JDE", "Voucher approval failed")
        return {"status": "error", "message": approve_result}

    run_vma_driver_ube(batch_number)
    status_result = check_vma_batch_status(batch_number)
    legacy_repo.insert_log(src_id, "Successful", "JDE", "Voucher approved", is_reviewed="1", action_taken="Approved")
    return {"status": "success", "batch_status": status_result}


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.jde_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

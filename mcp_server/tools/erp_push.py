"""MCP tool backing Agent 4 (ERP Push Agent).

Thin wrapper over agents.agent_4.services.ebs_push/jde_push, imported in
place from the sibling Agent/ folder -- not duplicated here.
"""
from __future__ import annotations

from typing import Any

from agents.agent_4.services import ebs_push, jde_push
from shared.config import settings as agent_settings

_PUSH_ROUTER = {"JDE": jde_push.push_to_jde, "EBS": ebs_push.push_to_ebs_inv}


def register(mcp) -> None:
    @mcp.tool()
    def push_invoice_to_erp(src_id: str, target_erp: str = "") -> dict[str, Any]:
        """Pushes a stored invoice to the live ERP for target_erp: JDE
        (CheckPO -> AddSupplierInvoice -> approval-hold-and-email if
        required -> RunVMADriverUBE) or EBS (create_invoices REST call).
        Reads the invoice back from the ennvault DB by src_id -- does not
        take invoice fields as arguments. target_erp defaults to this
        deployment's TARGET_ERP setting when left blank."""
        erp = (target_erp or agent_settings.TARGET_ERP).upper()
        push_func = _PUSH_ROUTER.get(erp)
        if not push_func:
            return {"status": "error", "message": f"Unsupported ERP: {erp}"}
        try:
            return push_func(src_id)
        except Exception as exc:  # connectivity/DB failures surface as a business failure, not a crash
            return {"status": "error", "message": f"ERP push failed: {exc}"}

"""CrewAI tool wrapping Agent 4's live ERP push. Owned only by Agent 4's crew.

Exact port of the gate ennVault_org_backend's prep.py uses right after
extraction: `if TARGET_ERP == "JDE": push_to_jde(src_id) elif TARGET_ERP ==
"EBS": push_to_ebs_inv(src_id)`. This agent no longer builds an EBS-only
document from a forwarded extracted_fields payload -- it reads the invoice
Agent 3 already stored back by src_id and pushes it to whichever ERP this
run targets.
"""
from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from shared.config import settings
from shared.crew.payload_store import PayloadStore
from shared.mcp_tools.client import McpToolError, call_tool

# Agent 3's result (src_id, target_erp) rides in as a DataPart (see
# executor.py) rather than through the LLM's tool-call arguments -- see
# payload_store.py for why.
payload_store = PayloadStore()


def _ok(skill: str, data: dict) -> str:
    return json.dumps({"skill_used": skill, "success": True, "data": data, "error": None})


def _err(skill: str, error: str) -> str:
    return json.dumps({"skill_used": skill, "success": False, "data": None, "error": error})


class PushInvoiceToErpArgs(BaseModel):
    payload_key: str = Field(
        ...,
        description="The payload_key value given in the task text -- copy it exactly. Looks up the Extraction "
        "Agent's result (src_id, target_erp) attached to this request.",
    )
    target_erp: str = Field(
        default_factory=lambda: settings.TARGET_ERP,
        description="Target ERP system for this run ('JDE' or 'EBS'), driven by the TARGET_ERP setting",
    )


class PushInvoiceToErpTool(BaseTool):
    name: str = "push_invoice_to_erp"
    description: str = (
        "Pushes a stored invoice to the live ERP for this run's target_erp: JDE (CheckPO -> AddSupplierInvoice -> "
        "approval-hold-and-email if required -> RunVMADriverUBE) or EBS (create_invoices REST call). Reads the "
        "invoice back from the ennvault DB by src_id -- does not take invoice fields as arguments. payload_key "
        "must be copied verbatim from the task text -- never invent one."
    )
    args_schema: type[BaseModel] = PushInvoiceToErpArgs

    def _run(self, payload_key: str, target_erp: str = settings.TARGET_ERP) -> str:
        payload = payload_store.pop(payload_key)
        if payload is None:
            return _err(self.name, f"No extraction-result payload found for payload_key '{payload_key}'.")

        result = payload.get("data", payload) if isinstance(payload, dict) else payload
        src_id = result.get("src_id")
        target_erp = (result.get("target_erp") or target_erp or settings.TARGET_ERP).upper()

        if not src_id:
            return _err(self.name, f"Payload for payload_key '{payload_key}' has no src_id to push.")

        try:
            result = call_tool("push_invoice_to_erp", {"src_id": src_id, "target_erp": target_erp})
        except McpToolError as exc:
            return _err(self.name, f"ERP push failed: {exc}")
        return _ok(self.name, result)


def get_tools() -> list[BaseTool]:
    return [PushInvoiceToErpTool()]

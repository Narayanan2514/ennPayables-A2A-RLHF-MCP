"""CrewAI tool wrapping Agent 3's vision extraction + DB storage.

Owned only by Agent 3's crew.
"""
from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from shared.config import settings
from shared.crew.payload_store import PayloadStore
from shared.mcp_tools.client import McpToolError, call_tool

# Agent 2's validation result (encoded_image_paths/mapping_path/pdf_path)
# rides in as a DataPart (see executor.py) rather than through the LLM's
# tool-call arguments -- see payload_store.py for why.
payload_store = PayloadStore()


def _ok(skill: str, data: dict) -> str:
    return json.dumps({"skill_used": skill, "success": True, "data": data, "error": None})


def _err(skill: str, error: str) -> str:
    return json.dumps({"skill_used": skill, "success": False, "data": None, "error": error})


class ExtractAndStoreInvoiceArgs(BaseModel):
    payload_key: str = Field(
        ...,
        description="The payload_key value given in the task text -- copy it exactly. Looks up the Validator "
        "Agent's result (encoded_image_paths, mapping_path, pdf_path) attached to this request.",
    )
    from_email: str = Field("", description="Sender email address. Pass an empty string if not known -- never pass null.")
    subject: str = Field("", description="Email subject line. Pass an empty string if not known -- never pass null.")
    body_text: str = Field("", description="Cleaned email body text. Pass an empty string if not known -- never pass null.")
    conversation_id: str = Field("", description="Graph conversation id. Pass an empty string if not known -- never pass null.")
    message_id: str = Field("", description="Graph message id. Pass an empty string if not known -- never pass null.")
    target_erp: str = Field(
        default_factory=lambda: settings.TARGET_ERP,
        description="Target ERP system for this run ('JDE' or 'EBS'), driven by the TARGET_ERP setting",
    )


class ExtractAndStoreInvoiceTool(BaseTool):
    name: str = "extract_and_store_invoice"
    description: str = (
        "Runs vision-based extraction over the Validator Agent's PII-masked page images (JDE or EBS taxonomy, "
        "per target_erp), decodes the masked values back, and stores the invoice in the ennvault DB (source, "
        "email, log_table, plus jde_inv_header/jde_inv_lines for JDE or inv_header/inv_line for EBS). Does not "
        "submit to a live ERP -- that is the ERP Push Agent's job. payload_key must be copied verbatim from the "
        "task text -- never invent one."
    )
    args_schema: type[BaseModel] = ExtractAndStoreInvoiceArgs

    def _run(
        self,
        payload_key: str,
        from_email: str = "",
        subject: str = "",
        body_text: str = "",
        conversation_id: str = "",
        message_id: str = "",
        target_erp: str = settings.TARGET_ERP,
    ) -> str:
        payload = payload_store.pop(payload_key)
        if payload is None:
            return _err(self.name, f"No validation-result payload found for payload_key '{payload_key}'.")

        # The forwarded payload can be either the Validator Agent's flat
        # result directly, or something wrapping it -- unwrap defensively
        # the same way Agent 4's tool unwraps Agent 3's forwarded result.
        result = payload.get("data", payload) if isinstance(payload, dict) else payload
        encoded_image_paths = result.get("encoded_image_paths") or []
        mapping_path = result.get("mapping_path")
        pdf_path = result.get("pdf_path") or ""

        if not encoded_image_paths or not mapping_path:
            return _err(
                self.name,
                f"Payload for payload_key '{payload_key}' has no encoded_image_paths/mapping_path -- "
                "was this record actually validated (is_valid=true) before extraction was requested?",
            )

        try:
            result = call_tool(
                "extract_and_store_invoice",
                {
                    "encoded_image_paths": encoded_image_paths,
                    "mapping_path": mapping_path,
                    "pdf_path": pdf_path,
                    "from_email": from_email,
                    "subject": subject,
                    "body_text": body_text,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "target_erp": target_erp,
                },
            )
        except McpToolError as exc:
            return _err(self.name, f"Extraction/storage failed: {exc}")
        if isinstance(result, dict) and result.get("error"):
            return _err(self.name, result["error"])
        return _ok(self.name, result)


def get_tools() -> list[BaseTool]:
    return [ExtractAndStoreInvoiceTool()]

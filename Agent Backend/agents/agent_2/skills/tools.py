"""CrewAI tool wrapping Agent 2's intake validation rule engine.

Owned only by Agent 2's crew.
"""
from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from shared.crew.payload_store import PayloadStore
from shared.mcp_tools.client import McpToolError, call_tool

# The attachments list rides in as a DataPart (see executor.py) rather than
# through the LLM's tool-call arguments -- see payload_store.py for why.
payload_store = PayloadStore()


def _ok(skill: str, data: dict) -> str:
    return json.dumps({"skill_used": skill, "success": True, "data": data, "error": None})


def _err(skill: str, error: str) -> str:
    return json.dumps({"skill_used": skill, "success": False, "data": None, "error": error})


class ValidateIntakeRecordArgs(BaseModel):
    # No Optional[...]/None-default fields here on purpose -- see the note
    # in agents/agent_4/skills/tools.py::BuildEbsDocumentArgs for why
    # (CrewAI's ast.literal_eval-based Action Input parser has a failure
    # mode specifically triggered by fields the model would set to null).
    from_email: str = Field("", description="Sender email address. Pass an empty string if not known -- never pass null.")
    subject: str = Field("", description="Email subject line. Pass an empty string if not known -- never pass null.")
    doc_type: str = Field("", description="Detected document type, e.g. 'invoice', 'purchase_order'. Pass an empty string if not known -- never pass null.")
    payload_key: str = Field(
        ...,
        description="The payload_key value given in the task text -- copy it exactly, character for character. It looks up the attachments list attached to this request.",
    )


class ValidateIntakeRecordTool(BaseTool):
    name: str = "validate_intake_record"
    description: str = (
        "Runs deterministic rule checks on an email intake record (sender, subject, doc type, PDF attachment "
        "readability) and returns a pass/flag/block verdict plus an is_valid flag for whether the pipeline "
        "should continue extracting this record. payload_key must be copied verbatim from the task text -- "
        "never invent one. Every argument is a plain string -- use an empty string for anything unknown, never "
        "the value null."
    )
    args_schema: type[BaseModel] = ValidateIntakeRecordArgs

    def _run(self, payload_key: str, from_email: str = "", subject: str = "", doc_type: str = "") -> str:
        payload = payload_store.pop(payload_key)
        if payload is None:
            return _err(self.name, f"No attachments payload found for payload_key '{payload_key}'.")
        attachments = payload.get("attachments", [])

        try:
            data = call_tool(
                "validate_intake_record",
                {"from_email": from_email, "subject": subject, "doc_type": doc_type, "attachments": attachments},
            )
        except McpToolError as exc:
            return _err(self.name, f"Failed to validate intake record: {exc}")
        return _ok(self.name, data)


def get_tools() -> list[BaseTool]:
    return [ValidateIntakeRecordTool()]

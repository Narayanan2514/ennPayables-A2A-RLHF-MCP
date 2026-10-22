"""CrewAI tool wrappers around Agent 1's per-message email intake.

Owned only by Agent 1's crew. Agent 1 no longer polls or classifies -- the
supervisor (client/orchestrator/email_polling.py) does that and tells Agent 1
exactly which of these two things to do for one specific message, via a
DataPart (see executor.py) rather than through the LLM's tool-call
arguments -- see payload_store.py for why.
"""
from __future__ import annotations

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from shared.crew.payload_store import PayloadStore
from shared.mcp_tools.client import McpToolError, call_tool

payload_store = PayloadStore()


def _ok(skill: str, data: dict) -> str:
    return json.dumps({"skill_used": skill, "success": True, "data": data, "error": None})


def _err(skill: str, error: str) -> str:
    return json.dumps({"skill_used": skill, "success": False, "data": None, "error": error})


class ProcessEmailMessageArgs(BaseModel):
    payload_key: str = Field(
        ...,
        description="The payload_key value given in the task text -- copy it exactly. Looks up the specific "
        "message (id, conversation id, subject, from, body, doc_type) the supervisor already classified as valid.",
    )


class ProcessEmailMessageTool(BaseTool):
    name: str = "process_email_message"
    description: str = (
        "Processes ONE specific email message the supervisor has already classified as valid (in this "
        "pipeline's scope): downloads its attachments, marks it read, and returns an intake record for the "
        "pipeline. payload_key must be copied verbatim from the task text -- never invent one."
    )
    args_schema: type[BaseModel] = ProcessEmailMessageArgs

    def _run(self, payload_key: str) -> str:
        payload = payload_store.pop(payload_key)
        if payload is None:
            return _err(self.name, f"No message payload found for payload_key '{payload_key}'.")
        try:
            record = call_tool(
                "process_email_message",
                {
                    "message_id": payload["message_id"],
                    "conversation_id": payload.get("conversation_id", ""),
                    "from_email": payload.get("from_email", ""),
                    "subject": payload.get("subject", ""),
                    "body_html": payload.get("body_html", ""),
                    "doc_type": payload["doc_type"],
                    "received_at": payload.get("received_at", ""),
                },
            )
        except McpToolError as exc:
            return _err(self.name, f"Failed to process message: {exc}")
        return _ok(self.name, record)


class MarkEmailInvalidArgs(BaseModel):
    payload_key: str = Field(
        ...,
        description="The payload_key value given in the task text -- copy it exactly. Looks up the message id "
        "the supervisor classified as invalid/out-of-scope.",
    )


class MarkEmailInvalidTool(BaseTool):
    name: str = "mark_email_invalid"
    description: str = (
        "Marks ONE specific email message read without processing it -- the supervisor already classified it "
        "as invalid/out-of-scope for this pipeline. Prevents it from resurfacing on the next poll. "
        "payload_key must be copied verbatim from the task text -- never invent one."
    )
    args_schema: type[BaseModel] = MarkEmailInvalidArgs

    def _run(self, payload_key: str) -> str:
        payload = payload_store.pop(payload_key)
        if payload is None:
            return _err(self.name, f"No message payload found for payload_key '{payload_key}'.")
        try:
            result = call_tool("mark_email_invalid", {"message_id": payload["message_id"]})
        except McpToolError as exc:
            return _err(self.name, f"Failed to mark message invalid: {exc}")
        return _ok(self.name, result)


def get_tools() -> list[BaseTool]:
    return [ProcessEmailMessageTool(), MarkEmailInvalidTool()]

"""MCP tools backing Agent 1 (Email Intake Agent).

Thin wrappers over agents.agent_1.services.intake_service, imported in
place from the sibling Agent/ folder (see ../settings.py) -- not duplicated
here. Agent 1's own CrewAI tool (Agent/agents/agent_1/skills/tools.py) used
to call this service directly in-process; it now calls these same two
actions over MCP instead.
"""
from __future__ import annotations

from typing import Any

from agents.agent_1.services import intake_service


def register(mcp) -> None:
    @mcp.tool()
    def process_email_message(
        message_id: str,
        conversation_id: str,
        from_email: str,
        subject: str,
        body_html: str,
        doc_type: str,
        received_at: str,
    ) -> dict[str, Any]:
        """Processes ONE email message the caller has already classified as
        valid (in this pipeline's scope): downloads its attachments, marks
        it read, and returns an intake record (attachments, cleaned body
        text, doc_type, etc.) for validate_intake_record to pick up next."""
        return intake_service.process_message(
            message_id=message_id,
            conversation_id=conversation_id,
            from_email=from_email,
            subject=subject,
            body_html=body_html,
            doc_type=doc_type,
            received_at=received_at,
        )

    @mcp.tool()
    def mark_email_invalid(message_id: str) -> dict[str, Any]:
        """Marks ONE email message read without processing it -- already
        classified as invalid/out-of-scope for this pipeline. Prevents it
        from resurfacing on the next poll."""
        return intake_service.mark_invalid(message_id=message_id)

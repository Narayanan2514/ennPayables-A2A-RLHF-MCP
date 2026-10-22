"""Email intake: act on ONE specific message the supervisor has already
classified, rather than polling/classifying itself.

The supervisor (client/orchestrator/email_polling.py) now owns listing the
mailbox and deciding valid vs. invalid (shared/email_classification.py) --
Agent 1 never lists anything and never classifies anything. It only ever
does two things, each triggered by one A2A call carrying a specific
message id:
  - `process_message`: the message was valid (an invoice) -- download its
    attachments, mark it read, and hand back an intake record for the
    pipeline.
  - `mark_invalid`: the message was invalid (out of scope) -- mark it read
    and do nothing else. Only Agent 1 ever writes to the mailbox, even for
    messages the supervisor itself decided to skip.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared import graph_client
from shared.email_classification import clean_body
from shared.utilities.logging import get_logger

logger = get_logger("agent_1.intake_service")

_SUBFOLDER_BY_DOC_TYPE = {"invoice": "inv", "purchase_order": "po", "remittance": "remit", "bank": "bank"}


def process_message(
    message_id: str,
    conversation_id: str,
    from_email: str,
    subject: str,
    body_html: str,
    doc_type: str,
    received_at: str,
) -> dict[str, Any]:
    """The supervisor already decided this message is valid (in
    `doc_type`'s pipeline scope) -- this downloads its attachments, marks it
    read, and returns the same intake-record shape the old bulk poller used
    to build for the orchestrator to run through `run_email_pipeline`.
    """
    token = graph_client.get_graph_token()
    subfolder = _SUBFOLDER_BY_DOC_TYPE.get(doc_type, "others")

    try:
        attachments = graph_client.download_attachments(token, message_id, subfolder)
    except Exception:
        logger.exception("Failed to download attachments for message %s", message_id)
        attachments = []

    record = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "from_email": from_email,
        "subject": subject,
        "body_text": clean_body(body_html),
        "doc_type": doc_type,
        "is_erp_relevant": True,
        "is_pipeline_scope": True,
        "attachments": attachments,
        "received_at": received_at,
        "polled_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        graph_client.mark_email_as_read(token, message_id)
    except Exception:
        logger.exception("Failed to mark message %s as read", message_id)

    return record


def mark_invalid(message_id: str) -> dict[str, Any]:
    """The supervisor decided this message is out of scope -- mark it read
    so it doesn't keep resurfacing on every future poll, and do nothing
    else (no download, no intake record, no pipeline run)."""
    token = graph_client.get_graph_token()
    try:
        graph_client.mark_email_as_read(token, message_id)
        marked = True
    except Exception:
        logger.exception("Failed to mark invalid message %s as read", message_id)
        marked = False
    return {"message_id": message_id, "marked_read": marked}

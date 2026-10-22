"""Mailbox polling + valid/invalid triage, owned by the supervisor.

This used to live inside Agent 1 (its own background loop, self-classifying,
self-queueing). Now the supervisor lists the mailbox itself, classifies each
message itself (shared/email_classification.py, unchanged logic), and for
each message calls exactly one of Agent 1's two per-message A2A skills:
`process_email_message` for a valid (in-scope) message, or
`mark_email_invalid` for everything else -- a real per-message A2A
conversation instead of the old "list pending emails" queue-drain.

Returns the intake records for valid messages Agent 1 successfully
processed; the caller (orchestrator.py) still owns running each one through
`run_email_pipeline` -- kept separate to avoid a circular import (orchestrator
imports this module, not the other way around).
"""
from __future__ import annotations

import hashlib
from typing import Any

from shared import graph_client
from shared.a2a_protocol.schemas import TaskState
from shared.config.settings import WORKER_NODE_ID
from shared.db import workflow_session_repo as session_repo
from shared.email_classification import is_valid_for_pipeline
from shared.utilities.logging import get_logger

from ..a2a_client.client import call_agent_task
from ..agent_registry.registry import registry

logger = get_logger("client.orchestrator.email_polling")

EMAIL_INTAKE_AGENT = "email-intake-agent"


def _placeholder_src_id(message_id: str) -> str:
    """The real `source.src_id` (e.g. "src_0001") doesn't exist yet at this
    point -- Agent 3's extraction stage is what creates that row. A durable
    session still needs SOME src_id value the moment it's created (the
    column is NOT NULL), so this is a short, deterministic stand-in that
    `orchestrator.py` swaps out for the real src_id as soon as extraction
    reports one -- see `workflow_session_repo.set_src_id`.
    """
    return "pnd_" + hashlib.sha1(message_id.encode()).hexdigest()[:12]


def _extract_result(task) -> dict[str, Any] | None:
    if not task or task.status.state != TaskState.COMPLETED:
        return None
    artifact = task.artifacts[0] if task.artifacts else None
    return artifact.parts[0].data if artifact and artifact.parts else {}


async def poll_and_dispatch() -> list[dict[str, Any]]:
    """Lists unread mail, classifies each message, and dispatches it to
    Agent 1 accordingly. Returns the intake records for messages classified
    valid AND successfully processed by Agent 1 -- ready for
    `run_email_pipeline`. Never raises for an ordinary Graph/agent hiccup on
    one message; that message is just skipped (logged) and polling
    continues with the rest.
    """
    agent = registry.get_agent(EMAIL_INTAKE_AGENT)
    if not agent:
        logger.warning("poll_and_dispatch: %s is not registered", EMAIL_INTAKE_AGENT)
        return []

    try:
        token = graph_client.get_graph_token()
        emails = graph_client.fetch_unread_emails(token)
    except Exception:
        logger.exception("poll_and_dispatch: failed to list unread mail")
        return []

    if emails:
        logger.info("Poll found %s unread email(s) in the mailbox", len(emails))

    records: list[dict[str, Any]] = []
    for mail in emails:
        try:
            record = await _dispatch_one(agent.base_url, mail)
            if record is not None:
                records.append(record)
        except Exception:
            logger.exception("poll_and_dispatch: failed to dispatch message %s", mail.get("id"))

    if records:
        logger.info("Poll dispatched %s valid email(s) to the pipeline", len(records))
    return records


async def _dispatch_one(agent_base_url: str, mail: dict[str, Any]) -> dict[str, Any] | None:
    message_id = mail["id"]
    subject = mail.get("subject", "")
    valid, doc_type = is_valid_for_pipeline(subject)

    if not valid:
        logger.info("Message %s classified invalid (doc_type=%s) -- marking read", message_id, doc_type)
        await call_agent_task(
            EMAIL_INTAKE_AGENT,
            agent_base_url,
            "Mark this out-of-scope email as read",
            data={"message_id": message_id},
        )
        return None

    from_email = mail.get("from", {}).get("emailAddress", {}).get("address", "")
    logger.info(
        "Valid email received: message=%s from=%s subject=%r (doc_type=%s) -- sending to Agent 1 for processing",
        message_id, from_email, subject, doc_type,
    )

    payload = {
        "message_id": message_id,
        "conversation_id": mail.get("conversationId", ""),
        "from_email": from_email,
        "subject": subject,
        "body_html": mail.get("body", {}).get("content", ""),
        "doc_type": doc_type,
        "received_at": mail.get("receivedDateTime", ""),
    }

    # Durable session, created as early as possible -- before Agent 1 even
    # runs -- so a crash from this point on still leaves a recoverable
    # record of "this email was in flight". Claimed by this worker
    # immediately: in this single-poller design the same process that
    # creates the session is the one about to process it, but the claim is
    # still the real atomic guard (see workflow_session_repo.claim_session)
    # so a second worker process racing the same poll can never also own it.
    session_id = session_repo.create_session(_placeholder_src_id(message_id), current_step="AGENT_1")
    if not session_repo.claim_session(session_id, WORKER_NODE_ID):
        logger.warning("Session %s could not be claimed by %s right after creation (unexpected)", session_id, WORKER_NODE_ID)

    result = await call_agent_task(
        EMAIL_INTAKE_AGENT,
        agent_base_url,
        "Process this email intake message",
        data=payload,
    )
    record = _extract_result(result.task)
    if record is None:
        logger.warning("Message %s: process_email_message did not complete (error=%s)", message_id, result.error)
        session_repo.fail_session(session_id)
    else:
        logger.info(
            "Agent 1 finished processing message %s -- %s attachment(s) downloaded, handing off to the pipeline",
            message_id, len(record.get("attachments") or []),
        )
        record["session_id"] = session_id
    return record

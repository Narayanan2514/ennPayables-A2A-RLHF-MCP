"""Supplier-Communication MCP Server (proposal Section 3).

"sendEmail, getResponse -- the same supplier-notification capability the UI
triggers manually today, now callable by an agent under policy."

Wraps modules/email_module's Graph-based send/poll pattern (audit section 2),
but callable as a tool with a governance-gated caller (orchestrator/governance.py
decides *whether* an agent is allowed to auto-send vs. only draft-and-escalate;
this server does not enforce that policy itself, it just executes the action).

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.supplier_communication_server
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from mcp_servers.common import legacy_repo
from mcp_servers.common.graph_client import get_conversation_messages, send_mail

mcp = FastMCP("supplier-communication")


@mcp.tool()
def send_email(src_id: str, subject: str, body_html: str) -> dict[str, Any]:
    """Send an email to a supplier (e.g. PO-mismatch correction request,
    duplicate-invoice notice). The orchestrator should only call this after
    the governance gate (Section 4.7) has cleared autonomous supplier contact
    for this supplier/exception type -- otherwise the recommendation should be
    surfaced to a human instead.

    Deliberately takes `src_id`, not a recipient address: the only correct
    recipient is whoever this specific document actually arrived from, looked
    up here via legacy_repo.get_source_email (the `email` table row
    email_module/service.py wrote when the document was first ingested) --
    never an address the caller supplies or invents. If there's no email
    record for this src_id (e.g. it didn't arrive by email), this refuses
    rather than guessing; the caller should treat that as a reason to
    escalate to a human instead.

    Also attaches whatever file(s) this document itself arrived with
    (legacy_repo.get_source_attachment_paths -- the original invoice PDF,
    typically), so the supplier doesn't have to go dig up their own copy of
    what we're asking them about.
    """
    email_record = legacy_repo.get_source_email(src_id)
    if not email_record or not email_record.get("from_email"):
        return {"sent": False, "error": f"no email record (sender address) on file for src_id={src_id}"}
    attachment_paths = legacy_repo.get_source_attachment_paths(src_id)
    result = send_mail(
        email_record["from_email"], subject, body_html, email_record.get("conversation_id"), attachment_paths=attachment_paths
    )
    return {**result, "conversation_id": email_record.get("conversation_id")}


@mcp.tool()
def get_response(conversation_id: str) -> dict[str, Any]:
    """Check whether the supplier has replied on a given conversation thread.
    Returns the most recent message snippet if a reply exists.
    """
    messages = get_conversation_messages(conversation_id)
    if not messages:
        return {"has_reply": False}
    latest = messages[0]
    return {
        "has_reply": len(messages) > 1,
        "latest_from": latest.get("from", {}).get("emailAddress", {}).get("address"),
        "latest_subject": latest.get("subject"),
        "received_at": latest.get("receivedDateTime"),
    }


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.supplier_communication_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

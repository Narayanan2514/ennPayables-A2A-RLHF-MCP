"""Microsoft Graph client for supplier email communication.

ennvault-existing has two redundant OAuth2 client-credentials implementations
for this (audit section 11: `get_graph_token` via MSAL vs. `get_access_token`
via raw requests) -- this module keeps only the MSAL path and centralizes it,
same scope (`https://graph.microsoft.com/.default`) and target mailbox
(`TARGET_USER_EMAIL`) convention as modules/email_module/poll.py.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from typing import Any

import msal
import requests

from config.settings import get_settings

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def get_graph_token() -> str:
    settings = get_settings()
    app = msal.ConfidentialClientApplication(
        client_id=settings.client_id,
        client_credential=settings.client_secret,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire Graph token: {result.get('error_description')}")
    return result["access_token"]


def _file_attachment(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        content_bytes = f.read()
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": os.path.basename(path),
        "contentType": content_type,
        "contentBytes": base64.b64encode(content_bytes).decode("ascii"),
    }


def send_mail(
    to_address: str,
    subject: str,
    body_html: str,
    conversation_id: str | None = None,
    attachment_paths: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    token = get_graph_token()
    url = f"{GRAPH_BASE}/users/{settings.target_user_email}/sendMail"
    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": to_address}}],
    }
    if attachment_paths:
        message["attachments"] = [_file_attachment(path) for path in attachment_paths]
    payload = {"message": message, "saveToSentItems": "true"}
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    return {"sent": True, "to": to_address, "subject": subject}


def get_conversation_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Fetch messages in a conversation thread -- used to check whether a
    supplier has replied to a PO-mismatch / duplicate-invoice email
    (getResponse in the proposal's tool list).
    """
    settings = get_settings()
    token = get_graph_token()
    url = (
        f"{GRAPH_BASE}/users/{settings.target_user_email}/messages"
        f"?$filter=conversationId eq '{conversation_id}'&$orderby=receivedDateTime desc"
    )
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    return response.json().get("value", [])

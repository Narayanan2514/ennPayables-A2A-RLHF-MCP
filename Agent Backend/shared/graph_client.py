"""Microsoft Graph client for the target mailbox.

Shared between the client/orchestrator supervisor (which now owns polling --
`get_graph_token` + `fetch_unread_emails`, listing unread mail to classify)
and Agent 1 (which owns everything that actually mutates the mailbox or reads
one message's full content -- `download_attachments` + `mark_email_as_read`).
Moved here, unchanged, from agents/agent_1/services/graph_client.py now that
both sides need it; only Agent 1 talks to Graph past the listing call.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Any

import msal
import requests

from shared.config.settings import CLIENT_ID, CLIENT_SECRET, EMAIL_ATTACHMENT_DIR, TARGET_USER_EMAIL, TENANT_ID
from shared.utilities.logging import get_logger

logger = get_logger("shared.graph_client")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphNotConfiguredError(Exception):
    """Raised when TENANT_ID / CLIENT_ID / CLIENT_SECRET / TARGET_USER_EMAIL are missing."""


def _require_configured() -> None:
    missing = [
        name
        for name, value in [("TENANT_ID", TENANT_ID), ("CLIENT_ID", CLIENT_ID), ("CLIENT_SECRET", CLIENT_SECRET), ("TARGET_USER_EMAIL", TARGET_USER_EMAIL)]
        if not value
    ]
    if missing:
        raise GraphNotConfiguredError(f"Microsoft Graph is not configured -- missing env var(s): {', '.join(missing)}")


def get_graph_token() -> str:
    _require_configured()
    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire Graph token: {result.get('error_description')}")
    return result["access_token"]


def fetch_unread_emails(token: str) -> list[dict[str, Any]]:
    """Lists unread inbox mail -- called by the supervisor's poll loop to
    classify each message. Not called by Agent 1 anymore; it only ever acts
    on one message it's already been told about."""
    url = (
        f"{GRAPH_BASE}/users/{TARGET_USER_EMAIL}/mailFolders/inbox/messages"
        "?$filter=isRead eq false"
        "&$select=id,subject,from,body,conversationId,receivedDateTime,hasAttachments"
        "&$top=25"
    )
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    return response.json().get("value", [])


def mark_email_as_read(token: str, message_id: str) -> None:
    url = f"{GRAPH_BASE}/users/{TARGET_USER_EMAIL}/messages/{message_id}"
    response = requests.patch(url, headers={"Authorization": f"Bearer {token}"}, json={"isRead": True}, timeout=30)
    response.raise_for_status()


def download_attachments(token: str, message_id: str, subfolder: str) -> list[dict[str, str]]:
    """Downloads every non-inline attachment for a message to local disk
    under EMAIL_ATTACHMENT_DIR/<subfolder>/upload_<timestamp>/, mirroring the
    reference's folder convention. Returns [{name, path, content_type}]."""
    url = f"{GRAPH_BASE}/users/{TARGET_USER_EMAIL}/messages/{message_id}/attachments"
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    attachments = response.json().get("value", [])
    if not attachments:
        return []

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder = os.path.join(EMAIL_ATTACHMENT_DIR, subfolder, f"upload_{timestamp}_{message_id[-8:]}")
    os.makedirs(folder, exist_ok=True)

    saved: list[dict[str, str]] = []
    for att in attachments:
        if att.get("isInline") or "contentBytes" not in att:
            continue
        name = att.get("name", "attachment")
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(att["contentBytes"]))
        saved.append({"name": name, "path": path, "content_type": att.get("contentType", "")})
        logger.info("Saved attachment %s to %s", name, path)

    return saved

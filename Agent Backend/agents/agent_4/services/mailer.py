"""Sends the JDE voucher-approval-needed email via Microsoft Graph, using
the same application-permission client-credentials flow Agent 1 uses to
read mail.

Port of ennVault_org_backend's modules/email_module/service.py::send_email
+ app/setttings/config.py::get_access_token, and content.py::
generate_voucher_approval_body.

Deliberate deviation from the reference: the reference's send_email()
unconditionally overwrites `to_email` with a hardcoded test address
("krithika.appandaraj@ennvee.net") before sending -- every approval email
that code sends goes to that one inbox regardless of who the real
approver is. That looks like a debugging leftover rather than intended
behavior, so it is NOT reproduced here: this sends to the real
`approver_email` MSAL/Graph gives us. If you actually want approval
emails redirected to a fixed test inbox for now, set
JDE_APPROVAL_EMAIL_OVERRIDE in .env.
"""
from __future__ import annotations

import base64
import os

import requests

from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("agent_4.mailer")

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


def _get_access_token() -> str | None:
    url = _TOKEN_URL.format(tenant=settings.TENANT_ID)
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.CLIENT_ID,
        "client_secret": settings.CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    response = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data, timeout=30)
    if response.status_code == 200:
        return response.json().get("access_token")
    logger.warning("Failed to acquire Graph token: %s %s", response.status_code, response.text[:300])
    return None


def generate_voucher_approval_body(approver_name: str, ref_id: str) -> str:
    return f"""
<p>Hi {approver_name},</p>

<p>
  A voucher has been created and requires your <b>manual approval</b>
  before further processing can continue.
</p>

<table style="border-collapse: collapse; width: 50%; margin-top: 10px;">
  <tr>
    <td style="border: 1px solid #ddd; padding: 8px;"><b>Reference Number</b></td>
    <td style="border: 1px solid #ddd; padding: 8px;">{ref_id}</td>
  </tr>
  <tr>
    <td style="border: 1px solid #ddd; padding: 8px;"><b>Status</b></td>
    <td style="border: 1px solid #ddd; padding: 8px; color: orange;"><b>Pending Approval</b></td>
  </tr>
</table>

<p style="margin-top: 15px;">Kindly review and approve the voucher at your earliest convenience.</p>
<p>You can approve the request from the Exception tab in the application.</p>
<br>
<p>Thanks &amp; Regards,<br><b>AI Ticketing System</b></p>
"""


def send_email(from_email: str, to_email: str, subject: str, body: str) -> bool:
    access_token = _get_access_token()
    if access_token is None:
        return False

    to_email = settings.JDE_APPROVAL_EMAIL_OVERRIDE or to_email

    url = f"https://graph.microsoft.com/v1.0/users/{from_email}/sendMail"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    email_message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
    }

    response = requests.post(url, json=email_message, headers=headers, timeout=30)
    if response.status_code == 202:
        logger.info("Approval email sent to %s", to_email)
        return True
    logger.warning("Failed to send approval email to %s: %s %s", to_email, response.status_code, response.text[:300])
    return False

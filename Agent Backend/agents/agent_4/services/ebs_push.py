"""Live push of a stored EBS-taxonomy invoice to the Oracle EBS AP REST
webservice.

Exact port of ennVault_org_backend/ERP/EBS/inv_payload.py::push_to_ebs_inv.
Reads the invoice Agent 3 already stored (inv_header/inv_line, the real
EBS taxonomy -- bill_to/ship_to/supplier_name/invoice_amount/etc, not a
JDE field borrowed as a stand-in) back by src_id, matching the reference's
own shape (push_to_ebs_inv(src_id) takes nothing else).
"""
from __future__ import annotations

import re
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from . import db_repo
from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("agent_4.ebs_push")

_EMBEDDED_CURRENCY_RE = re.compile(r"^(.*\S)\s+([A-Za-z]{3})$")


def _pre_push_issues(header_info: dict[str, Any], line_info: list[dict[str, Any]]) -> list[str]:
    """Sanity-checks the DB-stored invoice before it ever reaches the live
    EBS endpoint -- not part of the reference project, added after
    observing a vision-extraction defect slip through to a live push
    (an adjacent 'PO Number'/'Currency Code' column pair merged into one
    field, e.g. "6739 USD"). Agent 3 now corrects that specific pattern at
    extraction time (see vision_extraction._split_merged_po_and_currency),
    but checking again here is cheap and catches it (or a similar defect)
    regardless of what produced the stored row."""
    issues = []
    if not (header_info.get("invoice_number") or "").strip():
        issues.append("invoice_number is blank")
    if not (header_info.get("supplier_name") or "").strip():
        issues.append("supplier_name is blank")

    po_number = (header_info.get("customer_po_number") or "").strip()
    if _EMBEDDED_CURRENCY_RE.match(po_number):
        issues.append(f"customer_po_number '{po_number}' looks like it has a currency code merged into it")

    if not line_info:
        issues.append("no line items")
    elif not any(float(line.get("total") or 0) > 0 for line in line_info):
        issues.append("every line item's total is zero/blank")

    return issues


def push_to_ebs_inv(src_id: str) -> dict[str, Any]:
    if not settings.EBS_BASE_URL:
        return {"status": "error", "message": "EBS_BASE_URL is not configured."}

    auth = (settings.EBS_USERNAME, settings.EBS_PASSWORD) if settings.EBS_USERNAME else None
    url = f"{settings.EBS_BASE_URL}/create_invoices/"

    try:
        header_info, line_info = db_repo.extract_inv_data_ebs(src_id)
        if not header_info or not line_info:
            db_repo.insert_log(src_id, "Failed", "EBS", "Missing invoice data")
            return {"status": "error", "message": "Missing data"}

        issues = _pre_push_issues(header_info, line_info)
        if issues:
            message = "Pre-push validation failed: " + "; ".join(issues)
            db_repo.insert_log(src_id, "Failed", "EBS", message)
            return {"status": "error", "message": message}

        invoice_date = header_info.get("invoice_date")
        payload = {
            "RESTHeader": {
                "Responsibility": "APPLICATION_DEVELOPER",
                "RespApplication": "FND",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Language": "US",
                "Org_Id": "",
            },
            "InputParameters": {
                "P_INVOICE_HEADER": {
                    "P_INVOICE_HEADER_ITEM": {
                        "INVOICE_NUMBER": header_info.get("invoice_number"),
                        "SUPPLIER_NAME": header_info.get("supplier_name"),
                        "SUPPLIER_SITE_NAME": header_info.get("supplier_site_name", "") or "",
                        "INVOICE_AMOUNT": str(header_info.get("invoice_amount", "")),
                        "INVOICE_DATE": invoice_date.isoformat() if hasattr(invoice_date, "isoformat") else (invoice_date or None),
                        "PO_NUMBER": header_info.get("customer_po_number"),
                        "CURRENCY_CODE": header_info.get("currency_code") or "USD",
                        "PAYMENT_TERMS": "Immediate",
                    }
                },
                "P_INVOICE_LINES": {
                    "P_INVOICE_LINES_ITEM": [
                        {
                            "ITEM_NAME": line.get("item_name"),
                            "LINE_DESCRIPTION": line.get("item_desc", "") or "",
                            "QTY": "1",
                            "LINE_AMOUNT": line.get("total") if line.get("total") is not None else 0,
                        }
                        for line in line_info
                    ]
                },
            },
        }

        if not settings.EBS_VERIFY_TLS:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            auth=HTTPBasicAuth(*auth) if auth else None,
            verify=settings.EBS_VERIFY_TLS,
            # timeout=300,
        )

        if not response.ok:
            db_repo.insert_log(src_id, "Failed", "EBS", f"{response.status_code} {response.text[:1000]}")
            return {"status": "error", "message": f"{response.status_code} from EBS: {response.text[:500]}"}

        output = response.json().get("OutputParameters", {})
        status = output.get("X_STATUS")

        if status == "S":
            db_repo.insert_log(src_id, "Successful", "EBS", "Invoice successfully posted in EBS")
            return {"status": "success", "message": "Invoice successfully posted in EBS"}

        db_repo.insert_log(src_id, "Failed", "EBS", output.get("X_MESSAGE"))
        return {"status": "error", "message": output.get("X_MESSAGE", "EBS posting failed")}

    except Exception as exc:
        logger.exception("EBS push failed for src_id=%s", src_id)
        db_repo.insert_log(src_id, "Failed", "EBS", str(exc))
        return {"status": "error", "message": "Unexpected error in EBS"}

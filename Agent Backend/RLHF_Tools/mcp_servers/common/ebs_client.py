"""Thin, versioned wrapper around the Oracle EBS AP REST webservice.

Same payload shape as ennvault-existing's ERP/EBS/inv_payload.py, verified
against AP_EBS_API_Documentation.txt (RESTHeader / InputParameters /
P_INVOICE_HEADER / P_INVOICE_LINES) -- but credentials and the base URL come
from config.settings instead of being hardcoded literals
(`HTTPBasicAuth("esb_user", "oracle321")`, `verify=False` -- audit section
6/flag list item 6), and TLS verification is a config toggle rather than
permanently disabled.
"""
from __future__ import annotations

from typing import Any

import requests
import urllib3

from config.settings import get_settings


def _rest_header(org_id: str = "") -> dict:
    return {
        "Responsibility": "APPLICATION_DEVELOPER",
        "RespApplication": "FND",
        "SecurityGroup": "STANDARD",
        "NLSLanguage": "AMERICAN",
        "Language": "US",
        "Org_Id": org_id,
    }


def build_invoice_payload(header: dict[str, Any], lines: list[dict[str, Any]]) -> dict:
    return {
        "RESTHeader": _rest_header(),
        "InputParameters": {
            "P_INVOICE_HEADER": {
                "P_INVOICE_HEADER_ITEM": {
                    "INVOICE_NUMBER": header.get("invoice_number", ""),
                    "SUPPLIER_NAME": header.get("supplier_name", ""),
                    "SUPPLIER_SITE_NAME": header.get("supplier_site", ""),
                    "INVOICE_AMOUNT": str(header.get("invoice_amount", "")),
                    "INVOICE_DATE": header.get("invoice_date", ""),
                    "PO_NUMBER": header.get("customer_po_number", ""),
                    "CURRENCY_CODE": header.get("currency_code", ""),
                    "PAYMENT_TERMS": header.get("payment_terms") or "Immediate",
                }
            },
            "P_INVOICE_LINES": {
                "P_INVOICE_LINES_ITEM": [
                    {
                        "ITEM_NAME": line.get("item_name", ""),
                        "LINE_DESCRIPTION": line.get("item_desc") or line.get("item_description", ""),
                        "QTY": str(line.get("ordered_quantity", "")),
                        "LINE_AMOUNT": str(line.get("total", "")),
                    }
                    for line in lines
                ]
            },
        },
    }


def call_create_invoice(payload: dict) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ebs_verify_tls:
        urllib3.disable_warnings()
    url = f"{settings.ebs_base_url}/create_invoices/"
    auth = (settings.ebs_username, settings.ebs_password) if settings.ebs_username else None
    response = requests.post(url, json=payload, auth=auth, verify=settings.ebs_verify_tls)
    response.raise_for_status()
    output = response.json().get("OutputParameters", {})
    return {
        "status": output.get("X_STATUS"),
        "invoice_number": output.get("X_INVOICE_NUMBER"),
        "message": output.get("X_MESSAGE"),
    }


def call_reporting_summary(date_from: str, date_to: str) -> dict[str, Any]:
    """Replaces the hardcoded August-2026 date window in ennvault-existing's
    reporting_summary_ebs() (audit section 8) with real caller-supplied dates.
    """
    settings = get_settings()
    if not settings.ebs_verify_tls:
        urllib3.disable_warnings()
    url = f"{settings.ebs_base_url}/get_ap_invoices/"
    auth = (settings.ebs_username, settings.ebs_password) if settings.ebs_username else None
    payload = {
        "RESTHeader": _rest_header(),
        "InputParameters": {"P_INVOICE_DATE_FROM": date_from, "P_INVOICE_DATE_TO": date_to},
    }
    response = requests.post(url, json=payload, auth=auth, verify=settings.ebs_verify_tls, timeout=30)
    response.raise_for_status()
    return response.json()

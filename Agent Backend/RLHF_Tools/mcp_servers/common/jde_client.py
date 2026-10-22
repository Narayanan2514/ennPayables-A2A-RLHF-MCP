"""Thin wrapper around the JDE Orchestrator REST endpoints ennvault-existing's
ERP/JDE/inv_payload.py calls (audit section 8): AI_CheckPO,
AI_AddSupplierInvoice, AI_RunVMADriverUBE, AI_ApproveVoucher,
AI_CheckVMABatchStatus. Same orchestrator names/payload shapes; credentials
and base URL come from config.settings instead of hardcoded
HTTPBasicAuth("SVCAI01", "aiagent") + verify=False.
"""
from __future__ import annotations

from typing import Any

import requests
import urllib3

from config.settings import get_settings


def _post(orchestrator_name: str, payload: dict) -> dict[str, Any]:
    settings = get_settings()
    if not settings.jde_verify_tls:
        urllib3.disable_warnings()
    url = f"{settings.jde_base_url}/{orchestrator_name}"
    auth = (settings.jde_username, settings.jde_password) if settings.jde_username else None
    response = requests.post(url, json=payload, auth=auth, verify=settings.jde_verify_tls, timeout=30)
    response.raise_for_status()
    return response.json()


def check_po(order_number: str) -> dict[str, Any]:
    return _post("JDE_ORCH_AI_CheckPO", {"OrderNumber": order_number})


def add_supplier_invoice(
    company: str,
    supplier_number: str,
    invoice_number: str,
    invoice_date: str,
    gl_date: str,
    business_unit: str,
    grid_in: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "Company": company,
        "SupplierNumber": supplier_number,
        "InvoiceNumber": invoice_number,
        "InvoiceDate": invoice_date,
        "GLDate": gl_date,
        "BusinessUnit": business_unit,
        "GridIn": grid_in,
    }
    return _post("JDE_ORCH_AI_AddSupplierInvoice", payload)


def run_vma_driver_ube(batch_number: str) -> dict[str, Any]:
    return _post("JDE_ORCH_AI_RunVMADriverUBE", {"BatchNumber": batch_number})


def approve_voucher(batch_number: str) -> dict[str, Any]:
    return _post("JDE_ORCH_AI_ApproveVoucher", {"BatchNumber": batch_number})


def check_vma_batch_status(batch_number: str) -> dict[str, Any]:
    return _post("JDE_ORCH_AI_CheckVMABatchStatus", {"BatchNumber": batch_number})

"""Multi-step live push of a stored JDE invoice to the JDE Orchestrator.

Exact port of ennVault_org_backend/ERP/JDE/inv_payload.py::push_to_jde:
CheckPO -> (on ApprovalRequired) send a voucher-approval email and hold ->
AddSupplierInvoice -> RunVMADriverUBE. Reads the invoice Agent 3 already
stored (jde_inv_header/jde_inv_lines) back by src_id -- it does not build
the payload from a payload the caller hands it, matching the reference's
own shape (push_to_jde(src_id) takes nothing else).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from . import db_repo, mailer
from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("agent_4.jde_push")


def _session() -> requests.Session:
    session = requests.Session()
    auth = (settings.JDE_USERNAME, settings.JDE_PASSWORD) if settings.JDE_USERNAME else None
    if auth:
        session.auth = HTTPBasicAuth(*auth)
    return session


def push_to_jde(src_id: str) -> dict[str, Any]:
    if not settings.JDE_BASE_URL:
        return {"status": "error", "message": "JDE_BASE_URL is not configured."}

    session = _session()
    headers = {"Content-Type": "application/json"}

    try:
        header_info, line_info = db_repo.extract_inv_data(src_id)
        if not line_info:
            db_repo.insert_log(src_id, "Failed", "JDE", "No line data")
            return {"status": "error", "message": "No line data"}

        if not (header_info.get("supplier_number") or "").strip():
            db_repo.insert_log(src_id, "Failed", "JDE", "Missing supplier_number")
            return {"status": "error", "message": "Missing supplier_number"}
        if not (header_info.get("invoice_number") or "").strip():
            db_repo.insert_log(src_id, "Failed", "JDE", "Missing invoice_number")
            return {"status": "error", "message": "Missing invoice_number"}

        order_number = line_info[0].get("order_number")
        if not order_number:
            db_repo.insert_log(src_id, "Failed", "JDE", "Missing order number")
            return {"status": "error", "message": "Missing order number"}

        # ---- STEP 1: CHECK PO ----
        response = session.post(
            f"{settings.JDE_BASE_URL}/JDE_ORCH_AI_CheckPO",
            json={"OrderNumber": order_number},
            headers=headers,
            verify=settings.JDE_VERIFY_TLS,
            timeout=30,
        )
        response_json = response.json()
        error_code = (response_json.get("ErrorCode") or "").strip()
        error_desc = response_json.get("ErrorDescription")

        if error_code == "2":
            db_repo.insert_log(src_id, "Failed", "JDE", error_desc)
            return {"status": "error", "message": "CheckPO Failed"}

        # ---- STEP 2: PREPARE + ADD SUPPLIER INVOICE ----
        try:
            inv_dt = datetime.strptime(str(header_info["invoice_date"]), "%Y-%m-%d")
        except Exception:
            db_repo.insert_log(src_id, "Failed", "JDE", "Invalid invoice_date")
            return {"status": "error", "message": "Invalid invoice date"}

        gl_dt = datetime.now()
        db_repo.update_company_number(response_json.get("CompanyNo"), response_json.get("CostCenter"), src_id)
        db_repo.update_order_line_items(response_json.get("CompanyNo"), response_json.get("OrderType"), src_id)

        payload = {
            "Company": response_json.get("CompanyNo"),
            "SupplierNumber": header_info.get("supplier_number"),
            "InvoiceNumber": header_info.get("invoice_number"),
            "InvoiceDate": inv_dt.strftime("%m/%d/%Y"),
            "GLDate": gl_dt.strftime("%m/%d/%Y"),
            "BusinessUnit": response_json.get("CostCenter"),
            "GridIn": [
                {
                    "GrossAmount": float(line.get("gross_amount") or 0),
                    "Remark": line.get("remark"),
                    "AutomationFlag": line.get("automation_flag"),
                    "OrderNumber": order_number,
                    "OrderCompany": response_json.get("CompanyNo"),
                    "OrderType": response_json.get("OrderType"),
                    "ItemNumber": line.get("item_number"),
                }
                for line in line_info
            ],
        }

        response_2 = session.post(
            f"{settings.JDE_BASE_URL}/JDE_ORCH_AI_AddSupplierInvoice",
            json=payload,
            headers=headers,
            verify=settings.JDE_VERIFY_TLS,
            timeout=30,
        ).json()

        if response_2.get("jde__status") != "SUCCESS":
            error_log = ""
            try:
                for errorlog in response_2["message"]["ServiceRequest: JDE_FREQ_AI_AddSupplierInvoice"]["JAS Response"]["fs_P0411Z1_W0411Z1D"]["errors"]:
                    error_log += errorlog["TITLE"] + "\n"
            except Exception:
                error_log = str(response_2)
            db_repo.insert_log(src_id, "Failed", "JDE", error_log)
            return {"status": "error", "message": "AddSupplierInvoice Failed"}

        # ---- APPROVAL HOLD ----
        if response_2.get("ApprovalRequired") == "Y":
            approver_name = response_2.get("ApproverName")
            approver_email = response_2.get("ApproverEmail")
            db_repo.update_voucher_approval(src_id, response_2.get("ApprovalRequired"), approver_name, approver_email)
            db_repo.insert_log(src_id, "OnHold", "JDE", "Voucher is on Hold. Approval is required")

            batch_number = response_2.get("BatchNumber")
            db_repo.update_batch_number(batch_number, src_id)

            body = mailer.generate_voucher_approval_body(approver_name, src_id)
            mailer.send_email(settings.TARGET_USER_EMAIL, approver_email, "Voucher Approval Needed", body)

            return {"status": "on Hold", "message": "Voucher Approval Needed"}

        # ---- STEP 3: RUN UBE ----
        batch_number = response_2.get("BatchNumber")
        db_repo.update_batch_number(batch_number, src_id)

        response_3 = session.post(
            f"{settings.JDE_BASE_URL}/JDE_ORCH_AI_RunVMADriverUBE",
            json={"BatchNumber": batch_number},
            headers=headers,
            verify=settings.JDE_VERIFY_TLS,
            timeout=30,
        ).json()

        if response_3.get("jde__status") != "SUCCESS":
            db_repo.insert_log(src_id, "Failed", "JDE", "RunVMADriverUBE Failed")
            return {"status": "error", "message": "RunVMADriverUBE Failed"}

        db_repo.insert_log(src_id, "Successful", "JDE", "Invoice Pushed to JDE")
        return {"status": "success", "message": "Invoice Pushed to JDE"}

    except Exception as exc:
        logger.exception("JDE push failed for src_id=%s", src_id)
        db_repo.insert_log(src_id, "Failed", "JDE", str(exc))
        return {"status": "error", "message": "Unexpected error"}

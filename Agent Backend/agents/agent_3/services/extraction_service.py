"""Orchestrates Agent 3's one job: turn a validated intake record's
PII-masked page images into decoded invoice fields, and store them in the
ennvault DB under the taxonomy matching this run's TARGET_ERP.

Port of ennVault_org_backend/modules/processing/entity_extractor/
llm_service/inv_extract.py's inv_extract_jde/inv_extract_ebs (extraction +
decode + DB insert; live ERP submission is Agent 4's job now, reading this
data back by src_id -- see agents/agent_4/services/jde_push.py and
ebs_push.py, ports of ERP/JDE/inv_payload.py's push_to_jde and
ERP/EBS/inv_payload.py's push_to_ebs_inv).
"""
from __future__ import annotations

import os
from typing import Any

import requests

from . import db_repo
from .vision_extraction import ExtractionError, extract_invoice
from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("agent_3.extraction_service")


class Agent3OperationError(Exception):
    pass


def _notify_backend_source_ready(src_id: str) -> None:
    """Tells Backend to archive this document's attachment folder (see
    Backend/app/api/internal/service.py's archive_source) now that this
    `source` row is fully committed -- the explicit handoff that replaced
    the retired to_process_listener.py's filesystem-watch trigger.

    Best-effort: a failed handoff means the invoice-preview endpoint won't
    find an archived copy yet, which is far better than blowing up an
    otherwise-successful extraction over a Backend hiccup.
    """
    try:
        response = requests.post(
            f"{settings.BACKEND_API_URL}/internal/source-ready",
            data={"src_id": src_id},
            timeout=settings.BACKEND_API_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Backend archive handoff failed for src_id=%s: %s", src_id, exc)


def process_invoice(
    encoded_image_paths: list[str],
    mapping_path: str,
    pdf_path: str,
    from_email: str,
    subject: str,
    body_text: str = "",
    conversation_id: str = "",
    message_id: str = "",
    target_erp: str = settings.TARGET_ERP,
) -> dict[str, Any]:
    target_erp = (target_erp or settings.TARGET_ERP).upper()
    try:
        extracted = extract_invoice(target_erp, encoded_image_paths, mapping_path)
    except ExtractionError as exc:
        raise Agent3OperationError(str(exc)) from exc

    header = extracted["header"]
    lines = extracted["line_items"]

    # source.folder_path/atch_nm are read back later by
    # ennvault_RLHF_with_Tools/mcp_servers/common/legacy_repo.py's
    # get_source_attachment_paths (folder_path is a DIRECTORY, atch_nm the
    # filename(s) within it, joined together) -- from a DIFFERENT process
    # than this one, so folder_path is stored RELATIVE TO ENNVAULT_DATA_ROOT
    # rather than absolute: an absolute path only resolves on the exact
    # machine/cwd that wrote it, which breaks the moment a reader runs
    # elsewhere. Every reader must join it back onto its own ENNVAULT_DATA_ROOT
    # (kept identical across Agent/.env, Agent/RLHF_Tools/.env and Backend/.env).
    if not settings.ENNVAULT_DATA_ROOT:
        raise Agent3OperationError("ENNVAULT_DATA_ROOT is not configured")
    pdf_abs_path = os.path.abspath(pdf_path)
    folder_path = os.path.relpath(os.path.dirname(pdf_abs_path), settings.ENNVAULT_DATA_ROOT)
    src_id = db_repo.insert_source(
        channel="email",
        target=target_erp,
        doc_type="invoice",
        atch_nm=os.path.basename(pdf_abs_path),
        archive=None,
        folder_path=folder_path,
    )
    db_repo.insert_email(src_id, from_email, subject, body_text, conversation_id, message_id)

    if target_erp == "JDE":
        header_id = db_repo.insert_jde_invoice_header(
            src_id=src_id,
            company=header.get("company") or "",
            supplier_number=header.get("supplier_number") or "",
            invoice_number=header.get("invoice_number") or "",
            invoice_date=header.get("invoice_date") or "",
            gl_date=header.get("invoice_date") or "",
            business_unit=settings.JDE_DEFAULT_BUSINESS_UNIT,
        )
        line_ids = [db_repo.insert_jde_invoice_line(header_id, line) for line in lines]
    elif target_erp == "EBS":
        header_id = db_repo.insert_inv_header(header, src_id)
        line_ids = [db_repo.insert_inv_line(header_id, line) for line in lines]
    else:
        raise Agent3OperationError(f"Unsupported TARGET_ERP: {target_erp}")

    db_repo.insert_log(src_id, "Successful", target_erp, "Invoice extracted and stored")

    _notify_backend_source_ready(src_id)

    return {
        "src_id": src_id,
        "header_id": header_id,
        "line_ids": line_ids,
        "target_erp": target_erp,
        "extracted_fields": {**header, "line_items": lines},
    }


# Which line field a "PO/item not found" self-correction targets, per ERP --
# matches db_repo's allow-listed update_*_line_field fields.
_LINE_ITEM_FIELD_BY_ERP = {"EBS": "item_name", "JDE": "item_number"}


def reextract_line_item(
    target_erp: str,
    encoded_image_paths: list[str],
    mapping_path: str,
    rejected_item_value: str,
    line_id: int,
    line_number: str,
) -> dict[str, Any]:
    """Self-correction for an `invalid_item` ERP rejection (see
    client/orchestrator/self_correction.py): re-runs vision extraction with
    the ERP's own rejection fed back as a prompt hint (at a non-zero
    temperature -- see vision_extraction.extract_invoice_ebs's docstring for
    why), and applies the corrected value for ONE specific line only if the
    fresh reading actually differs from what was rejected. Never fabricates
    a "fix" that didn't actually change anything -- a re-extraction that
    reproduces the same value, or can't find that line at all, reports
    changed=False so the caller falls through to escalation instead.
    """
    target_erp = target_erp.upper()
    field = _LINE_ITEM_FIELD_BY_ERP.get(target_erp)
    if field is None:
        return {"changed": False, "reason": f"unsupported TARGET_ERP: {target_erp}"}

    correction_hint = (
        f'the item for line {line_number} ("{rejected_item_value}") could not be found in the ERP. '
        f"Look very carefully at every character in this line's item number/description -- masking, print "
        f"quality, or a similar-looking character (e.g. O/0, l/1, S/5) may have caused a misread. If, after "
        f"close re-examination, you are confident the same value is correct, return it unchanged."
    )
    logger.info("reextract_line_item: line_id=%s line_number=%s old_value=%r hint=%r", line_id, line_number, rejected_item_value, correction_hint)
    try:
        extracted = extract_invoice(target_erp, encoded_image_paths, mapping_path, correction_hint=correction_hint)
    except ExtractionError as exc:
        logger.warning("reextract_line_item: re-extraction raised: %s", exc)
        return {"changed": False, "reason": f"re-extraction failed: {exc}"}

    matching_line = next(
        (line for line in extracted.get("line_items", []) if str(line.get("line_number")) == str(line_number)), None
    )
    if matching_line is None:
        logger.warning(
            "reextract_line_item: no line_number=%s in re-extracted result (got line_numbers=%s)",
            line_number, [line.get("line_number") for line in extracted.get("line_items", [])],
        )
        return {"changed": False, "reason": f"no line_number={line_number} in re-extracted result"}

    old_value = (rejected_item_value or "").strip()
    new_value = (matching_line.get(field) or "").strip()
    logger.info("reextract_line_item: re-extraction returned %s=%r (old was %r)", field, new_value, old_value)
    if not new_value or new_value == old_value:
        return {"changed": False}

    if target_erp == "EBS":
        db_repo.update_ebs_line_field(line_id, field, new_value)
    else:
        db_repo.update_jde_line_field(line_id, field, new_value)

    logger.info("Self-correction updated line_id=%s %s: %r -> %r", line_id, field, old_value, new_value)
    return {"changed": True, "field": field, "old_value": old_value, "new_value": new_value}

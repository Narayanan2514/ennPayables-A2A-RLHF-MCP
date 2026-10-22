"""MCP tool backing the supervisor's bounded self-correction loop
(client/orchestrator/self_correction.py).

Scoped narrowly to ExceptionType.INVALID_ITEM ("item not found") -- the one
exception type this system's own action-space design
(RLHF_Tools/mcp_servers/common/errors.py's DEFAULT_ACTION_SPACE) already
treats as mechanically fixable, unlike e.g. duplicate_invoice ("never safe
to auto-resolve"). Every other exception type returns attempted=False
immediately, and the caller falls straight through to the existing
_run_exception_handling sequence, unchanged.

Imports RLHF's classify_erp_error and feedback_logger in place from the
sibling Agent/RLHF_Tools folder (see ../settings.py) and Agent 3's own
extraction/db services from the sibling Agent/ folder -- neither duplicated
here, same pattern as tools/exception_handling.py and tools/erp_push.py.
"""
from __future__ import annotations

import re
from typing import Any

from agents.agent_3.services import db_repo
from agents.agent_3.services.extraction_service import reextract_line_item
from mcp_servers.common.errors import ExceptionType, classify_erp_error
from shared.utilities.logging import get_logger
from tools.erp_push import _PUSH_ROUTER

try:
    from learning import feedback_logger
except ImportError:  # pragma: no cover -- keeps self-correction usable even if RLHF's DB tables aren't migrated yet
    feedback_logger = None

logger = get_logger("mcp_server.self_correction")

_LINE_FIELD_BY_ERP = {"EBS": "item_name", "JDE": "item_number"}

# Best-effort, tried in order. The first pattern is the confirmed real EBS
# "item not found" shape ("0001-0120xxx Item not found in the PO Number" --
# the rejected value comes BEFORE the phrase, not after a colon). The second
# is a "label:VALUE" shape seen on a different rejection (invalid_po's
# "PO Number not found!:6739000") -- kept as a fallback in case some
# invalid_item message ever uses it too. If neither matches, this cleanly
# reports attempted=False (see below) rather than guessing at a line to touch.
_REJECTED_VALUE_PATTERNS = [
    re.compile(r"^\s*(\S+)\s+item\s+not\s+found", re.IGNORECASE),
    re.compile(r":\s*(\S+)\s*$"),
]


def _parse_rejected_item_value(failure_message: str) -> str | None:
    message = failure_message or ""
    for pattern in _REJECTED_VALUE_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1).strip().rstrip(".,;:")
    return None


def _read_stored_invoice(target_erp: str, src_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if target_erp == "EBS":
        return db_repo.extract_inv_data_ebs(src_id)
    return db_repo.extract_inv_data(src_id)


def _log_correction_if_available(*, src_id, supplier_name, exception_type, field, old_value, new_value) -> None:
    """Records the fix via RLHF's existing feedback_logger.log_correction --
    same table refresh_exemplars (future prompts) and apply_learned_correction
    (future auto-replay) already read from, in EXACTLY the manual-edit shape
    orchestrator.native_tools._parse_manual_edit_fields expects. Never lets a
    logging hiccup fail an otherwise-successful self-correction."""
    if feedback_logger is None:
        return
    import json

    human_action = "manual_edit:" + json.dumps(
        {"lines": [{"match_field": field, "match_value": old_value, "set_field": field, "set_value": new_value}]}
    )
    try:
        feedback_logger.log_correction(
            src_id=src_id,
            supplier_name=supplier_name,
            doc_type="invoice",
            exception_type=exception_type,
            invoice_features={field: old_value},
            ai_recommendation=old_value,
            human_action=human_action,
            ai_recommendation_correct=False,
        )
    except Exception:
        pass


def attempt_self_correction(
    src_id: str,
    target_erp: str,
    failure_message: str,
    encoded_image_paths: list[str],
    mapping_path: str,
) -> dict[str, Any]:
    """Bounded, one-shot self-correction for an ERP push failure.
    Classifies failure_message; if it's not an 'invalid_item' ("item
    not found") rejection, returns immediately with attempted=False so
    the caller falls through to the existing exception-handling
    sequence unchanged. For invalid_item, identifies the rejected
    line's current value, re-runs vision extraction with the rejection
    fed back as a hint, applies the corrected value if (and only if) it
    actually differs, retries the ERP push once, and -- on success --
    records the fix as a learnable correction. Never guesses: any step
    that can't confidently proceed (unparseable rejection, no matching
    line, re-extraction unchanged) reports why and stops rather than
    acting on a guess.

    Defined at module level (not nested in register()) so it stays a
    directly importable, testable plain function -- see
    mcp_server/tests/test_self_correction.py.
    """
    classified = classify_erp_error(failure_message)
    logger.info("src_id=%s: classified failure_message=%r as %s", src_id, failure_message, classified.exception_type.value)
    if classified.exception_type != ExceptionType.INVALID_ITEM:
        return {"attempted": False, "exception_type": classified.exception_type.value}

    erp = target_erp.upper()
    field = _LINE_FIELD_BY_ERP.get(erp)
    if field is None:
        return {"attempted": False, "exception_type": classified.exception_type.value, "reason": f"unsupported TARGET_ERP: {erp}"}

    rejected_value = _parse_rejected_item_value(failure_message)
    if not rejected_value:
        logger.warning("src_id=%s: could not parse a rejected item value out of %r", src_id, failure_message)
        return {
            "attempted": False,
            "exception_type": classified.exception_type.value,
            "reason": "could not parse the rejected item value from the ERP's message",
        }

    header, lines = _read_stored_invoice(erp, src_id)
    if not header:
        return {"attempted": False, "exception_type": classified.exception_type.value, "reason": f"no stored invoice found for src_id={src_id}"}

    matching_line = next((line for line in lines if str(line.get(field, "")).strip() == rejected_value), None)
    if matching_line is None:
        logger.warning(
            "src_id=%s: parsed rejected value %r but no stored line's %s matches it (lines: %s)",
            src_id, rejected_value, field, [line.get(field) for line in lines],
        )
        return {
            "attempted": False,
            "exception_type": classified.exception_type.value,
            "reason": "could not identify which line the ERP's message refers to",
        }

    reextract_result = reextract_line_item(
        target_erp=erp,
        encoded_image_paths=encoded_image_paths,
        mapping_path=mapping_path,
        rejected_item_value=rejected_value,
        line_id=matching_line["id"],
        line_number=str(matching_line.get("line_number", "")),
    )
    if not reextract_result.get("changed"):
        return {
            "attempted": True,
            "exception_type": classified.exception_type.value,
            "changed": False,
            "reason": reextract_result.get("reason", "re-extraction did not produce a different value"),
        }

    push_func = _PUSH_ROUTER.get(erp)
    push_result = push_func(src_id)
    succeeded = (push_result.get("status") or "").strip().lower() in ("success", "on hold", "onhold", "on_hold")

    supplier_name = header.get("supplier_name") or header.get("company") or "unknown"
    if succeeded:
        _log_correction_if_available(
            src_id=src_id,
            supplier_name=supplier_name,
            exception_type=classified.exception_type.value,
            field=reextract_result["field"],
            old_value=reextract_result["old_value"],
            new_value=reextract_result["new_value"],
        )

    return {
        "attempted": True,
        "exception_type": classified.exception_type.value,
        "changed": True,
        "field": reextract_result["field"],
        "old_value": reextract_result["old_value"],
        "new_value": reextract_result["new_value"],
        "push_result": push_result,
        "succeeded": succeeded,
    }


def register(mcp) -> None:
    mcp.tool()(attempt_self_correction)

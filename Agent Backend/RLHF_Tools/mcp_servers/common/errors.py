"""Structured ERP exception classification.

ennvault-existing's Exceptions UI decides which corrective action button to
offer purely by ad hoc substring checks scattered across services.py files,
e.g. `"item not found" in msg`, `"exists" in msg`, `"exceeds" in msg`, `"po"
in msg` (audit section 8/§21). That coupling is fragile -- it breaks the
moment Oracle changes an error string's wording -- and it's duplicated per
domain (ennPayables, ennCash, ennOrder) instead of living in one place.

This module is the single place that turns a raw EBS/JDE X_MESSAGE (or JDE
ErrorDescription) into a typed ExceptionType. Everything downstream --
routing (4.1), the bandit's action space (4.3), memory retrieval keys (4.2),
and governance metrics (4.7/8) -- is keyed on this enum instead of re-parsing
error strings independently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ExceptionType(str, Enum):
    INVALID_ITEM = "invalid_item"
    INVALID_PO = "invalid_po"
    DUPLICATE_INVOICE = "duplicate_invoice"
    AMOUNT_OVERAPPLY = "amount_overapply"
    VOUCHER_HOLD = "voucher_hold"  # JDE ApprovalRequired == 'Y'
    UNMATCHED_REMITTANCE = "unmatched_remittance"
    UNKNOWN = "unknown"


# Ordered so the most specific pattern wins when a message could match more
# than one (e.g. an "exists" message that also happens to mention a PO).
_CLASSIFICATION_RULES: list[tuple[ExceptionType, re.Pattern]] = [
    (ExceptionType.INVALID_ITEM, re.compile(r"item not found", re.IGNORECASE)),
    (ExceptionType.INVALID_PO, re.compile(r"po number not found|invalid po", re.IGNORECASE)),
    (ExceptionType.DUPLICATE_INVOICE, re.compile(r"already exists", re.IGNORECASE)),
    (ExceptionType.AMOUNT_OVERAPPLY, re.compile(r"exceeds total receipt", re.IGNORECASE)),
]

# The corrective action a human currently takes for each exception type in the
# existing UI (audit section 8) -- this becomes the bandit's action space
# (Section 4.3): auto_fix_line_item | request_po_correction | email_supplier |
# auto_approve | escalate.
DEFAULT_ACTION_SPACE: dict[ExceptionType, list[str]] = {
    ExceptionType.INVALID_ITEM: ["auto_fix_line_item", "escalate"],
    ExceptionType.INVALID_PO: ["auto_fix_line_item", "request_po_correction", "email_supplier", "escalate"],
    ExceptionType.DUPLICATE_INVOICE: ["escalate", "email_supplier"],  # never safe to auto-resolve
    ExceptionType.AMOUNT_OVERAPPLY: ["auto_fix_line_item", "request_po_correction", "email_supplier", "escalate"],
    ExceptionType.VOUCHER_HOLD: ["auto_approve", "escalate"],
    ExceptionType.UNMATCHED_REMITTANCE: ["email_supplier", "escalate"],
    ExceptionType.UNKNOWN: ["escalate"],
}


# When a human manually edits invoice fields and successfully reprocesses an
# exception (api/repo.py:edit_and_reprocess), the fix isn't itself one of
# DEFAULT_ACTION_SPACE's labels -- but it's evidence for whichever of that
# exception type's actions the fix most resembles, so the bandit posterior for
# *that* arm is what should move. Never maps to an action outside the type's
# own action_space. A direct field edit is what "auto_fix_line_item" means in
# practice (orchestrator.native_tools.apply_learned_correction is what
# replays it later), so every field-fixable type maps there.
EDIT_REPROCESS_ACTION_MAP: dict[ExceptionType, str] = {
    ExceptionType.INVALID_ITEM: "auto_fix_line_item",
    ExceptionType.INVALID_PO: "auto_fix_line_item",
    ExceptionType.DUPLICATE_INVOICE: "escalate",
    ExceptionType.AMOUNT_OVERAPPLY: "auto_fix_line_item",
    ExceptionType.VOUCHER_HOLD: "auto_approve",
    ExceptionType.UNMATCHED_REMITTANCE: "email_supplier",
    ExceptionType.UNKNOWN: "escalate",
}


@dataclass
class ClassifiedError:
    exception_type: ExceptionType
    raw_message: str
    action_space: list[str]


def classify_erp_error(raw_message: str | None) -> ClassifiedError:
    message = raw_message or ""
    for exception_type, pattern in _CLASSIFICATION_RULES:
        if pattern.search(message):
            return ClassifiedError(exception_type, message, DEFAULT_ACTION_SPACE[exception_type])
    return ClassifiedError(ExceptionType.UNKNOWN, message, DEFAULT_ACTION_SPACE[ExceptionType.UNKNOWN])

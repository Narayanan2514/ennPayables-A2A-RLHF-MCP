"""Intake validation: cheap sender/subject/attachment rule checks, THEN the
real gate ennVault_org_backend uses -- does this doc_type have a customer
exclusion_config, and does the PDF's OCR'd words match a known customer
invoice layout (transform_service.detect_invoice_format). A record that
fails either stage never reaches Agents 3/4.

The rule-engine *pattern* for the first stage is a from-scratch recreation
of the one used by the reference project's `orchestrator/verifier_agent.py`
(deterministic checks -> a list of {rule, severity, detail} violations -> a
pass/flag/block verdict). The second stage is org_backend's actual
validation gate (prep.py's `load_config` + `transform()` success check),
ported here via config_loader.py/transform_service.py -- everything after
this point in the pipeline works on the PII-masked page images and
mapping_path this stage produces, not the raw PDF.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import config_loader, transform_service


@dataclass
class RuleViolation:
    rule: str
    severity: str  # "block" | "flag"
    detail: str


@dataclass
class ValidationResult:
    verdict: str  # "pass" | "flag" | "block"
    is_valid: bool
    violations: list[RuleViolation] = field(default_factory=list)
    pdf_path: str | None = None
    encoded_image_paths: list[str] = field(default_factory=list)
    mapping_path: str | None = None


def _first_readable_pdf(attachments: list[dict[str, Any]]) -> tuple[str | None, list[RuleViolation]]:
    violations: list[RuleViolation] = []
    pdf_candidates = [a for a in attachments if str(a.get("name", "")).lower().endswith(".pdf")]

    if attachments and not pdf_candidates:
        violations.append(RuleViolation("non_pdf_attachment", "flag", "attachment(s) present but none are .pdf"))
        return None, violations

    for candidate in pdf_candidates:
        path = candidate.get("path", "")
        if not path or not os.path.isfile(path):
            continue
        try:
            PdfReader(path)
            return path, violations
        except (PdfReadError, OSError):
            continue

    if pdf_candidates:
        violations.append(RuleViolation("unreadable_pdf", "block", "PDF attachment present but could not be opened/parsed"))

    return None, violations


def _run_transform_gate(pdf_path: str, doc_type: str) -> tuple[list[RuleViolation], list[str], str | None]:
    """org_backend's real validation gate: prep.py's `load_config(doc_type)`
    then `transform(pdf_path, output_folder, config, doc_type)`, gated on
    `success`. Returns (violations, encoded_image_paths, mapping_path)."""
    config = config_loader.load_config(doc_type)
    if not config:
        return (
            [RuleViolation("customer_config_not_found", "block", f"No exclusion_config for doc_type '{doc_type}'")],
            [],
            None,
        )

    output_folder = os.path.join(os.path.dirname(pdf_path), "_transform")
    try:
        encoded_paths, mapping_path, success, _dup_refs, _format_ok, err_desc = transform_service.transform(
            pdf_path=pdf_path, output_folder=output_folder, config=config, doc_type=doc_type
        )
    except Exception as exc:
        return ([RuleViolation("transform_failed", "block", f"transform() raised: {exc}")], [], None)

    if not success:
        return ([RuleViolation("format_not_recognized", "block", err_desc or "transform() did not succeed")], [], None)

    return ([], encoded_paths, mapping_path)


def validate_intake_record(
    from_email: str,
    subject: str,
    doc_type: str | None,
    attachments: list[dict[str, Any]] | None = None,
) -> ValidationResult:
    attachments = attachments or []
    violations: list[RuleViolation] = []

    if not from_email:
        violations.append(RuleViolation("missing_sender", "block", "from_email is empty"))
    if not subject:
        violations.append(RuleViolation("missing_subject", "flag", "subject is empty"))
    if doc_type != "invoice":
        violations.append(RuleViolation("unsupported_doc_type", "block", f"doc_type '{doc_type}' is not 'invoice' -- this pipeline only processes invoices"))
    if not attachments:
        violations.append(RuleViolation("missing_attachment", "block", "no attachments found on this email"))

    pdf_path = None
    if attachments:
        pdf_path, pdf_violations = _first_readable_pdf(attachments)
        violations.extend(pdf_violations)

    encoded_image_paths: list[str] = []
    mapping_path: str | None = None
    # Only worth running the (expensive) OCR/format-detection gate if the
    # cheap checks above haven't already blocked this record.
    if pdf_path and not any(v.severity == "block" for v in violations):
        transform_violations, encoded_image_paths, mapping_path = _run_transform_gate(pdf_path, doc_type or "")
        violations.extend(transform_violations)

    verdict = "block" if any(v.severity == "block" for v in violations) else ("flag" if violations else "pass")
    return ValidationResult(
        verdict=verdict,
        is_valid=verdict != "block",
        violations=violations,
        pdf_path=pdf_path,
        encoded_image_paths=encoded_image_paths,
        mapping_path=mapping_path,
    )

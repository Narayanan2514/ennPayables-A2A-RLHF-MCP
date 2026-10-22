"""Verifier / Critic Agent (Section 4.5).

"Add a fourth agent whose sole responsibility is to check the proposed Oracle
EBS payload against business rules and historical patterns before
submission, attaching a reasoning trace to its judgment. When a human later
overrides the verifier, that override is itself a training signal."

Deterministic rule checks run first (cheap, fast, no LLM round-trip) and
alone decide the pass/flag/block verdict -- the LLM call only narrates
*why* in natural language for the audit trail, so the verdict itself never
depends on an LLM being reachable. If OPENAI_API_KEY isn't configured, a
templated reasoning trace is used instead so this still runs end-to-end
offline/in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from db.new_schema import VerifierFinding
from db.session import session_scope


class Verdict(str, Enum):
    PASS = "pass"
    FLAG = "flag"
    BLOCK = "block"


@dataclass
class RuleViolation:
    rule: str
    severity: str  # "block" | "flag"
    detail: str


@dataclass
class VerifierResult:
    verdict: Verdict
    violations: list[RuleViolation] = field(default_factory=list)
    reasoning_trace: str = ""


# Tolerance bands mirror the EBS "Amount Overapply" scenario documented in
# AP_EBS_API_Documentation.txt -- an invoice can legitimately run slightly
# over a PO's receipted total, but a large overage is a block, not a flag.
_AMOUNT_OVERAGE_BLOCK_RATIO = 1.20
_AMOUNT_OVERAGE_FLAG_RATIO = 1.05


def run_rule_checks(
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    po_match: dict[str, Any] | None,
    supplier_known: bool,
) -> list[RuleViolation]:
    violations: list[RuleViolation] = []

    if not header.get("invoice_number"):
        violations.append(RuleViolation("missing_invoice_number", "block", "invoice_number is empty"))
    if not header.get("supplier_name"):
        violations.append(RuleViolation("missing_supplier_name", "block", "supplier_name is empty"))
    if not lines:
        violations.append(RuleViolation("no_line_items", "block", "invoice has zero extracted line items"))

    invoice_amount = header.get("invoice_amount")
    if invoice_amount is not None and lines:
        try:
            line_total = sum(float(l.get("total") or 0) for l in lines)
        except (TypeError, ValueError):
            line_total = None
        if line_total is not None and line_total > 0:
            if abs(float(invoice_amount) - line_total) / line_total > 0.02:
                violations.append(
                    RuleViolation(
                        "header_line_amount_mismatch",
                        "flag",
                        f"header invoice_amount {invoice_amount} vs. sum(line totals) {line_total}",
                    )
                )

    if po_match is not None:
        if not po_match.get("matched"):
            violations.append(RuleViolation("po_not_found", "block", f"PO {header.get('customer_po_number')} not found"))
        elif not po_match.get("within_envelope", True):
            po_total = po_match.get("po_total", 0)
            ratio = (float(invoice_amount) / po_total) if invoice_amount and po_total else None
            if ratio is not None and ratio > _AMOUNT_OVERAGE_BLOCK_RATIO:
                violations.append(
                    RuleViolation("amount_overapply_severe", "block", f"invoice_amount is {ratio:.2f}x PO total")
                )
            elif ratio is not None and ratio > _AMOUNT_OVERAGE_FLAG_RATIO:
                violations.append(
                    RuleViolation("amount_overapply_minor", "flag", f"invoice_amount is {ratio:.2f}x PO total")
                )

    if not supplier_known:
        violations.append(RuleViolation("unknown_supplier", "flag", f"no prior invoice history for {header.get('supplier_name')}"))

    return violations


def _verdict_from_violations(violations: list[RuleViolation]) -> Verdict:
    if any(v.severity == "block" for v in violations):
        return Verdict.BLOCK
    if violations:
        return Verdict.FLAG
    return Verdict.PASS


def _templated_reasoning_trace(header: dict[str, Any], violations: list[RuleViolation], verdict: Verdict) -> str:
    if not violations:
        return (
            f"Invoice {header.get('invoice_number')} from {header.get('supplier_name')} passed all business-rule "
            "checks: required fields present, header/line amounts reconcile, PO matched within envelope, "
            "supplier has prior invoice history."
        )
    lines = [f"- [{v.severity.upper()}] {v.rule}: {v.detail}" for v in violations]
    return (
        f"Invoice {header.get('invoice_number')} from {header.get('supplier_name')} verdict={verdict.value}.\n"
        + "\n".join(lines)
    )


def _llm_reasoning_trace(header: dict[str, Any], violations: list[RuleViolation], verdict: Verdict) -> str:
    from config.settings import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        return _templated_reasoning_trace(header, violations, verdict)

    import openai

    client = openai.OpenAI(api_key=settings.openai_api_key)
    violation_text = "\n".join(f"- [{v.severity}] {v.rule}: {v.detail}" for v in violations) or "None."
    prompt = (
        "You are the Verifier/Critic agent in an AP invoice pipeline. Business-rule checks have already "
        f"produced a verdict of '{verdict.value}' for this invoice, with these violations:\n{violation_text}\n\n"
        f"Invoice header: {header}\n\n"
        "Write a concise (3-5 sentence) reasoning trace explaining this verdict for the audit log, as if "
        "briefing an AP reviewer. Do not change the verdict."
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def verify_invoice(
    src_id: str,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    po_match: dict[str, Any] | None,
    supplier_known: bool,
    use_llm_narration: bool = True,
) -> VerifierResult:
    violations = run_rule_checks(header, lines, po_match, supplier_known)
    verdict = _verdict_from_violations(violations)
    reasoning_trace = (
        _llm_reasoning_trace(header, violations, verdict)
        if use_llm_narration
        else _templated_reasoning_trace(header, violations, verdict)
    )

    with session_scope() as session:
        import json

        session.add(
            VerifierFinding(
                src_id=src_id,
                verdict=verdict.value,
                reasoning_trace=reasoning_trace,
                rule_violations_json=json.dumps([v.__dict__ for v in violations]),
            )
        )

    return VerifierResult(verdict=verdict, violations=violations, reasoning_trace=reasoning_trace)


def record_human_override(src_id: str, override_reason: str) -> None:
    """When a human overrides the verifier's verdict, that's itself a training
    signal (feeds Sections 4.2/4.4) -- flag the most recent finding for this
    src_id as overridden rather than leaving it looking silently correct.
    """
    from sqlalchemy import select

    with session_scope() as session:
        finding = session.scalar(
            select(VerifierFinding).where(VerifierFinding.src_id == src_id).order_by(VerifierFinding.created_at.desc())
        )
        if finding is not None:
            finding.overridden_by_human = True
            finding.override_reason = override_reason

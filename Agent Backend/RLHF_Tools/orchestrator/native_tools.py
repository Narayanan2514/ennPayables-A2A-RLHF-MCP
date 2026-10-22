"""In-process "policy tools" the Orchestrator/Planner Agent calls alongside
the MCP servers.

Section 3 says the orchestrator should decide sequencing and tool use "at run
time, constrained by the tools available and the policies described in
Section 4." Concretely: the *policy math* for confidence routing (4.1), the
bandit (4.3), the verifier (4.5), and the governance gate (4.7) must be
deterministic and testable (see tests/), not something an LLM improvises turn
to turn. So those mechanisms are implemented as plain Python, then wrapped
here as tools with the same calling convention as the MCP servers -- the
LLM-driven agent loop (agent.py) chooses *when* to call them, but never
reimplements what they compute.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Callable

from config.settings import get_settings
from email_module.content import build_email_template
from learning import feedback_logger
from learning.vector_memory import search_similar_cases
from mcp_servers import jde_server, oracle_ebs_server
from mcp_servers.common import graph_client, legacy_repo
from orchestrator import bandit, governance, routing, verifier_agent

# Chroma similarity search returns lower distances for closer matches (exact
# metric depends on the collection's embedding space, but the direction is
# universal). This is deliberately conservative -- apply_learned_correction
# would rather refuse and let the agent escalate than replay a loosely
# related past fix onto the wrong document.
_SIMILARITY_THRESHOLD = 0.35

_MANUAL_EDIT_PREFIX = "manual_edit:"


def _parse_manual_edit_fields(human_action: str) -> dict[str, Any] | None:
    """Reverses api/repo.py:edit_and_reprocess's `human_action` encoding
    (f"manual_edit:{json.dumps(fields)}") back into a {field: value} dict.
    Returns None for anything else (e.g. a bandit action-space label like
    "request_po_correction" logged by submit_feedback) -- those aren't
    replayable field corrections.
    """
    if not human_action or not human_action.startswith(_MANUAL_EDIT_PREFIX):
        return None
    try:
        parsed = json.loads(human_action[len(_MANUAL_EDIT_PREFIX):])
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _decide_extraction_routing(overall_confidence: float, field_confidence: dict[str, float]) -> dict[str, Any]:
    decision = routing.route_extraction(overall_confidence, field_confidence)
    print(f"decide_extraction_routing: {decision.action.value} (overall_confidence={overall_confidence}, low_fields={decision.low_confidence_fields})")
    return {
        "action": decision.action.value,
        "overall_confidence": decision.overall_confidence,
        "low_confidence_fields": decision.low_confidence_fields,
        "reason": decision.reason,
    }


def _choose_bandit_action(supplier_name: str, exception_type: str) -> dict[str, Any]:
    decision = bandit.choose_action(supplier_name, exception_type)
    return {
        "action": decision.action,
        "sampled_values": decision.sampled_values,
        "arm_states": decision.arm_states,
    }


def _record_bandit_outcome(supplier_name: str, exception_type: str, action: str, success: bool) -> dict[str, str]:
    bandit.record_outcome(supplier_name, exception_type, action, success)
    return {"recorded": "true"}


def _authorize_autonomous_action(
    supplier_name: str, exception_type: str, confidence: float, amount: float | None = None
) -> dict[str, Any]:
    result = governance.authorize_autonomous_action(supplier_name, exception_type, confidence, amount)
    return {"allowed": result.allowed, "stage_used": result.stage_used.value, "reason": result.reason}


def _run_verifier(
    src_id: str,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
    po_match: dict[str, Any] | None,
    supplier_known: bool,
) -> dict[str, Any]:
    result = verifier_agent.verify_invoice(src_id, header, lines, po_match, supplier_known)
    return {
        "verdict": result.verdict.value,
        "violations": [asdict(v) for v in result.violations],
        "reasoning_trace": result.reasoning_trace,
    }


def _apply_learned_correction(src_id: str, supplier_name: str, exception_type: str) -> dict[str, Any]:
    """Actually executes the 'auto_fix_line_item' bandit action -- and does
    the whole job itself rather than trusting the calling LLM to also
    remember to authorize/log/reward it correctly afterward.

    That LLM-reliability gap is exactly what let real exceptions get
    silently mishandled in production: a chosen action of "escalate" got
    logged as decided_by="policy" (autonomous) instead of "human", and
    log_outcome/record_bandit_outcome calls were sometimes skipped entirely.
    Making the *execution* of an autonomous fix a single, deterministic,
    self-contained tool call removes that failure mode for this path -- the
    agent only has to decide *whether* to call this tool, not remember every
    follow-up step.

    Concretely, in order:
      1. Loads the invoice itself (header + lines) -- never trusts an
         LLM-supplied copy of the document's own data.
      2. Searches vector memory for the closest past human correction for
         this (supplier, exception_type). Refuses immediately (never
         fabricates a value) if nothing sufficiently similar exists yet --
         this is the "first time, a human handles it" half of the loop.
      3. Re-checks authorize_autonomous_action itself, using the match's own
         similarity as the confidence signal (a near-exact match to a
         previously-confirmed fix IS the evidence that this specific replay
         is safe -- the bandit's aggregate success rate for the whole
         "auto_fix_line_item" arm starts at a fresh 0.5 and would otherwise
         make this path unable to ever authorize its own first use). Even if
         the calling agent already checked authorization once, this tool
         refuses to act if it isn't authorized *right now* -- it is the last
         line of defense, not a second opinion the agent can override.
      4. Applies the correction (header fields verbatim, line fields by
         value-match, since a line_id from a different document is
         meaningless here), then resubmits to the ERP.
      5. Logs the outcome and updates the bandit posterior itself --
         decided_by="policy" is only ever recorded here, after a concrete
         action was actually taken, never for "the bandit's suggestion was
         to escalate."
    """
    header = legacy_repo.get_invoice_header(src_id)
    if header is None:
        return {"applied": False, "reason": "no_invoice_header_for_src_id"}
    lines = legacy_repo.get_invoice_lines(header["id"])
    invoice_features = {**header, "lines": lines}

    matches = search_similar_cases(supplier_name, exception_type, invoice_features, n_results=1)
    if not matches or matches[0]["distance"] > _SIMILARITY_THRESHOLD:
        return {"applied": False, "reason": "no_sufficiently_similar_past_correction"}

    confidence = max(0.0, min(1.0, 1.0 - matches[0]["distance"]))
    authorization = governance.authorize_autonomous_action(
        supplier_name, exception_type, confidence=confidence, amount=header.get("invoice_amount")
    )
    if not authorization.allowed:
        return {"applied": False, "reason": f"not_authorized: {authorization.reason}"}

    payload = _parse_manual_edit_fields(matches[0]["metadata"].get("human_action", ""))
    header_fields = (payload or {}).get("header") or {}
    line_rules = (payload or {}).get("lines") or []
    if not header_fields and not line_rules:
        return {"applied": False, "reason": "matched_case_has_no_replayable_field_correction"}

    for field, value in header_fields.items():
        legacy_repo.update_invoice_field(header["id"], field, value)

    lines_applied = []
    for rule in line_rules:
        for line in lines:
            if str(line.get(rule["match_field"])) == str(rule["match_value"]):
                legacy_repo.update_invoice_line_field(line["id"], rule["set_field"], rule["set_value"])
                lines_applied.append({"line_id": line["id"], **rule})

    if not header_fields and not lines_applied:
        return {"applied": False, "reason": "no_matching_line_found_to_correct"}

    source = legacy_repo.get_source(src_id)
    if source and source.get("target") == "JDE":
        erp_result = jde_server.create_invoice(src_id)
        succeeded = erp_result.get("status") == "success"
    else:
        erp_result = oracle_ebs_server.create_invoice(src_id)
        succeeded = erp_result.get("status") == "S"

    legacy_repo.insert_log(
        src_id,
        "Successful" if succeeded else "Failed",
        (source.get("target") if source else None) or "MCP",
        f"Auto-fix replayed from a prior human correction: {erp_result.get('message', '')}",
        is_reviewed="1",
        action_taken="auto_fix_line_item",
        what_modified=json.dumps({"header": header_fields, "lines": lines_applied}, default=str),
    )
    bandit.record_outcome(supplier_name, exception_type, "auto_fix_line_item", success=succeeded)
    feedback_logger.log_outcome(
        src_id,
        supplier_name,
        exception_type,
        "auto_fix_line_item",
        decided_by="policy",
        autonomy_stage=authorization.stage_used.value,
        confidence_at_decision=confidence,
    )

    return {
        "applied": True,
        "header_fields_applied": header_fields,
        "line_fields_applied": lines_applied,
        "succeeded": succeeded,
        "erp_result": erp_result,
    }


def _build_exception_email(header: dict[str, Any], exception_type: str) -> tuple[str, str]:
    subject = f"Correction needed: invoice {header.get('invoice_number') or header.get('id')}"
    body_text = (
        f"Hello,\n\n"
        f"Our system flagged invoice {header.get('invoice_number')} "
        f"(PO {header.get('customer_po_number') or 'n/a'}, amount {header.get('invoice_amount')}) "
        f"for a {exception_type.replace('_', ' ')} exception during processing.\n\n"
        f"Could you please confirm the correct details, or issue a corrected invoice/PO, at your "
        f"earliest convenience?\n\n"
        f"Thanks."
    )
    return subject, build_email_template(subject, body_text)


def _send_and_log_email(
    src_id: str,
    supplier_name: str,
    exception_type: str,
    subject: str,
    body_html: str,
    decided_by: str,
    confidence: float | None = None,
    autonomy_stage: str | None = None,
) -> dict[str, Any]:
    """Atomically sends the supplier email and records both the audit trail
    (log_table, via legacy_repo.insert_log) and the reward signal
    (outcomes_log, via feedback_logger.log_outcome) in one call -- the same
    "execution + logging can't be silently split across turns" pattern
    _apply_learned_correction uses, now covering the email_supplier action
    too. Shared by both the human-triggered "send email now" endpoint
    (api/repo.py:send_supplier_email) and the autonomous _apply_learned_email
    tool below.
    """
    email_record = legacy_repo.get_source_email(src_id)
    if not email_record or not email_record.get("from_email"):
        return {"sent": False, "reason": f"no email record (sender address) on file for src_id={src_id}"}

    attachment_paths = legacy_repo.get_source_attachment_paths(src_id)
    graph_client.send_mail(
        email_record["from_email"],
        subject,
        body_html,
        email_record.get("conversation_id"),
        attachment_paths=attachment_paths,
    )

    # stage="MCP" (never the ERP target) even though this document's target
    # is EBS/JDE -- this row is orchestrator bookkeeping, not an ERP call
    # result. api/repo.py:_erp_failure_description relies on that
    # distinction to keep re-classifying an escalated/emailed exception
    # against its real ERP error text instead of this note.
    legacy_repo.insert_log(
        src_id,
        "OnHold",
        "MCP",
        f"Emailed supplier ({email_record['from_email']}): {subject}",
        is_reviewed="1" if decided_by == "human" else "0",
        action_taken="email_supplier",
    )
    bandit.record_outcome(supplier_name, exception_type, "email_supplier", success=True)
    feedback_logger.log_outcome(
        src_id,
        supplier_name,
        exception_type,
        "email_supplier",
        decided_by=decided_by,
        autonomy_stage=autonomy_stage or get_settings().autonomy_stage,
        confidence_at_decision=confidence,
    )
    return {
        "sent": True,
        "to": email_record["from_email"],
        "subject": subject,
        "conversation_id": email_record.get("conversation_id"),
        "attachments": [os.path.basename(p) for p in attachment_paths],
    }


def _escalate_to_human(
    src_id: str,
    supplier_name: str,
    exception_type: str,
    action_recommended: str,
    reason: str,
    hold: bool = False,
) -> dict[str, Any]:
    """Executes the "this is NOT resolved, a human must act" outcome as one
    atomic call instead of trusting the calling LLM to remember both
    log_outcome (outcomes_log) and log_event (log_table) across separate
    turns. That two-call gap is exactly what let a document get narrated as
    "flagged for review" while never actually landing in the Manual Review
    queue (log_table.status was never set) -- see the module docstring on
    _apply_learned_correction for the same failure mode's first occurrence.

    stage="MCP" (never the ERP target) for the same reason
    _send_and_log_email uses it: this row is orchestrator bookkeeping (the
    escalation `reason`), not an ERP call result, and api/repo.py's
    _erp_failure_description relies on that distinction to keep
    re-classifying an escalated exception against its real ERP error text
    instead of this note.
    """
    legacy_repo.insert_log(
        src_id,
        "OnHold" if hold else "Failed",
        "MCP",
        reason,
        is_reviewed="0",
        action_taken=action_recommended,
    )
    feedback_logger.log_outcome(
        src_id,
        supplier_name,
        exception_type,
        action_recommended,
        decided_by="human",
        autonomy_stage=get_settings().autonomy_stage,
    )
    return {"escalated": True}


def _apply_learned_email(src_id: str, supplier_name: str, exception_type: str) -> dict[str, Any]:
    """Executes the 'email_supplier'/'request_po_correction' actions for
    real, self-contained the same way _apply_learned_correction is for
    'auto_fix_line_item': it only replays an email when a human has already
    resolved this exact (supplier, exception_type) by emailing the supplier
    once before (via api/repo.py:send_supplier_email), re-checks
    authorization itself using that precedent's own similarity as the
    confidence signal, and logs the outcome/bandit reward itself. Returns
    applied=false (never guesses a recipient or drafts a fix from nothing) if
    there's no such precedent yet or it isn't currently authorized -- the
    caller should treat that as a reason to escalate to a human instead.
    """
    header = legacy_repo.get_invoice_header(src_id)
    if header is None:
        return {"applied": False, "reason": "no_invoice_header_for_src_id"}
    lines = legacy_repo.get_invoice_lines(header["id"])
    invoice_features = {**header, "lines": lines}

    matches = search_similar_cases(supplier_name, exception_type, invoice_features, n_results=1)
    if not matches or matches[0]["distance"] > _SIMILARITY_THRESHOLD:
        return {"applied": False, "reason": "no_sufficiently_similar_past_correction"}
    if matches[0]["metadata"].get("human_action") not in ("email_supplier", "request_po_correction"):
        return {"applied": False, "reason": "closest_precedent_was_not_an_email_action"}

    confidence = max(0.0, min(1.0, 1.0 - matches[0]["distance"]))
    authorization = governance.authorize_autonomous_action(
        supplier_name, exception_type, confidence=confidence, amount=header.get("invoice_amount")
    )
    if not authorization.allowed:
        return {"applied": False, "reason": f"not_authorized: {authorization.reason}"}

    subject, body_html = _build_exception_email(header, exception_type)
    result = _send_and_log_email(
        src_id,
        supplier_name,
        exception_type,
        subject,
        body_html,
        decided_by="policy",
        confidence=confidence,
        autonomy_stage=authorization.stage_used.value,
    )
    if not result["sent"]:
        return {"applied": False, "reason": result["reason"]}
    return {"applied": True, **result}


def _log_outcome(
    src_id: str,
    supplier_name: str,
    exception_type: str,
    action_taken: str,
    decided_by: str,
    autonomy_stage: str,
    confidence_at_decision: float | None = None,
) -> dict[str, int]:
    outcome_id = feedback_logger.log_outcome(
        src_id, supplier_name, exception_type, action_taken, decided_by, autonomy_stage, confidence_at_decision
    )
    return {"outcome_id": outcome_id}


NATIVE_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "decide_extraction_routing",
        "description": (
            "[orchestrator policy] Confidence-aware routing (Section 4.1): given an extraction's overall and "
            "per-field confidence, decide straight_through / auto_correct / escalate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "overall_confidence": {"type": "number"},
                "field_confidence": {"type": "object"},
            },
            "required": ["overall_confidence", "field_confidence"],
        },
    },
    {
        "name": "choose_bandit_action",
        "description": (
            "[orchestrator policy] Contextual bandit (Section 4.3): Thompson-sample the action posteriors for "
            "this supplier + exception_type and return the chosen exception-handling action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_name": {"type": "string"},
                "exception_type": {
                    "type": "string",
                    "enum": ["invalid_item", "invalid_po", "duplicate_invoice", "amount_overapply", "voucher_hold", "unmatched_remittance", "unknown"],
                },
            },
            "required": ["supplier_name", "exception_type"],
        },
    },
    {
        "name": "record_bandit_outcome",
        "description": "[orchestrator policy] Feed a realized outcome back into the bandit's posterior for one arm.",
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
                "action": {"type": "string"},
                "success": {"type": "boolean"},
            },
            "required": ["supplier_name", "exception_type", "action", "success"],
        },
    },
    {
        "name": "authorize_autonomous_action",
        "description": (
            "[orchestrator policy] Staged-autonomy governance gate (Section 4.7). MUST be called and must return "
            "allowed=true before executing any action that isn't a human-initiated one (auto-fix, auto-approve, "
            "auto-send-email, autonomous ERP submission)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
                "confidence": {"type": "number"},
                "amount": {"type": "number"},
            },
            "required": ["supplier_name", "exception_type", "confidence"],
        },
    },
    {
        "name": "run_verifier",
        "description": (
            "[orchestrator policy] Verifier/Critic agent (Section 4.5): check a proposed invoice payload against "
            "business rules and historical patterns before ERP submission. Returns pass/flag/block plus a "
            "reasoning trace. MUST be called before any create_invoice tool call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "string"},
                "header": {"type": "object"},
                "lines": {"type": "array", "items": {"type": "object"}},
                "po_match": {"type": "object"},
                "supplier_known": {"type": "boolean"},
            },
            "required": ["src_id", "header", "lines", "supplier_known"],
        },
    },
    {
        "name": "apply_learned_correction",
        "description": (
            "[orchestrator policy] Executes the 'auto_fix_line_item' action for real, and is fully "
            "self-contained -- it loads the invoice itself, re-checks authorization itself, and logs the "
            "outcome and bandit reward itself. You do not need to call authorize_autonomous_action or "
            "log_outcome yourself when using this tool. It replays the closest past human field-correction "
            "for this supplier + exception_type (from vector memory) onto this document's header/lines, then "
            "resubmits to the ERP. Returns applied=false (never guesses, never fabricates a value) if it "
            "isn't currently authorized to act, or no sufficiently similar past correction exists -- treat "
            "applied=false as a signal to escalate to a human instead (log_outcome yourself with "
            "decided_by='human' in that case)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "string"},
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
            },
            "required": ["src_id", "supplier_name", "exception_type"],
        },
    },
    {
        "name": "apply_learned_email",
        "description": (
            "[orchestrator policy] Executes the 'email_supplier'/'request_po_correction' action for real, and "
            "is fully self-contained -- it only sends when a human has already resolved this exact "
            "(supplier_name, exception_type) by emailing the supplier once before, re-checks authorization "
            "itself, and logs the outcome and bandit reward itself. You do not need to call "
            "authorize_autonomous_action or log_outcome yourself when using this tool. Returns applied=false "
            "(never invents a recipient or drafts a fix from nothing) if there's no such past precedent yet, "
            "or it isn't currently authorized -- treat applied=false as a signal to call escalate_to_human "
            "instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "string"},
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
            },
            "required": ["src_id", "supplier_name", "exception_type"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "[orchestrator policy] Marks a case as NOT resolved and puts it in front of a human, atomically -- "
            "writes both outcomes_log (decided_by='human') and log_table (status='Failed' or 'OnHold') in one "
            "call, so it's guaranteed to actually show up in the Manual Review queue. Call this instead of "
            "separately calling log_outcome and log_event whenever authorize_autonomous_action returned "
            "allowed=false, the recommended action is literally 'escalate', or apply_learned_correction / "
            "apply_learned_email returned applied=false."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "string"},
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
                "action_recommended": {"type": "string"},
                "reason": {"type": "string"},
                "hold": {"type": "boolean", "description": "true for a hold-for-approval case (status=OnHold); false for status=Failed."},
            },
            "required": ["src_id", "supplier_name", "exception_type", "action_recommended", "reason"],
        },
    },
    {
        "name": "log_outcome",
        "description": (
            "[orchestrator policy] Open an outcomes_log row for a decision (Section 4.3's reward signal / "
            "Section 8's dashboard metrics). Call once per decision, autonomous or human-executed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "src_id": {"type": "string"},
                "supplier_name": {"type": "string"},
                "exception_type": {"type": "string"},
                "action_taken": {"type": "string"},
                "decided_by": {"type": "string", "enum": ["policy", "human"]},
                "autonomy_stage": {"type": "string"},
                "confidence_at_decision": {"type": "number"},
            },
            "required": ["src_id", "supplier_name", "exception_type", "action_taken", "decided_by", "autonomy_stage"],
        },
    },
]

NATIVE_TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "decide_extraction_routing": _decide_extraction_routing,
    "choose_bandit_action": _choose_bandit_action,
    "record_bandit_outcome": _record_bandit_outcome,
    "authorize_autonomous_action": _authorize_autonomous_action,
    "run_verifier": _run_verifier,
    "apply_learned_correction": _apply_learned_correction,
    "apply_learned_email": _apply_learned_email,
    "escalate_to_human": _escalate_to_human,
    "log_outcome": _log_outcome,
}

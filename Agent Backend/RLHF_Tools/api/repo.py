"""Composition layer behind the frontend's REST API.

Everything here reads/writes through the same modules the MCP servers and
orchestrator use (mcp_servers/common/legacy_repo.py, orchestrator/bandit.py,
learning/feedback_logger.py) -- the API layer adds no new business logic of
its own, it just assembles their outputs into shapes the frontend can render
directly, and exposes the human-feedback write path
(mcp_servers/common tools are only reachable via MCP stdio, which a browser
can't speak -- this is the plain HTTP front door onto the same functions).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from db.new_schema import AgentLog, OutcomesLog, VerifierFinding
from db.session import session_scope
from learning import feedback_logger
from mcp_servers import jde_server, oracle_ebs_server
from mcp_servers.common import legacy_repo
from mcp_servers.common.errors import (
    DEFAULT_ACTION_SPACE,
    EDIT_REPROCESS_ACTION_MAP,
    ExceptionType,
    classify_erp_error,
)
from orchestrator import bandit, governance
from orchestrator import trace_logger
from orchestrator.native_tools import _send_and_log_email


def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    return legacy_repo.list_recent_sources(limit)


def document_exists(src_id: str) -> bool:
    return legacy_repo.get_source(src_id) is not None


def _latest_verifier_finding(src_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalar(
            select(VerifierFinding).where(VerifierFinding.src_id == src_id).order_by(VerifierFinding.created_at.desc())
        )
        if row is None:
            return None
        return {
            "verdict": row.verdict,
            "reasoning_trace": row.reasoning_trace,
            "violations": json.loads(row.rule_violations_json) if row.rule_violations_json else [],
            "overridden_by_human": row.overridden_by_human,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def _erp_failure_description(history: list[dict[str, Any]]) -> str | None:
    """The description to classify_erp_error against -- the most recent row
    that's an actual ERP submission result (stage in EBS/JDE), not just the
    latest log_table row overall. Once a document has been escalated (or
    emailed, or auto-fix-replayed), later rows are the orchestrator's own
    bookkeeping (escalate_to_human's `reason`, _send_and_log_email's "Emailed
    supplier: ..." note, etc, all written with stage="MCP" precisely so they
    don't get mistaken for this) -- classifying against one of those instead
    of the real ERP error text always produces exception_type="unknown",
    which is what made every escalated document's exception type/action
    space go blank on the second look. Falls back to the plain latest row
    if no ERP-stage row exists at all (e.g. an extraction-only escalation).
    """
    for row in reversed(history):
        if row["stage"] in ("EBS", "JDE"):
            return row["description"]
    return history[-1]["description"] if history else None


def get_document_detail(src_id: str) -> dict[str, Any] | None:
    source = legacy_repo.get_source(src_id)
    if source is None:
        return None

    header = legacy_repo.get_invoice_header(src_id)
    lines = legacy_repo.get_invoice_lines(header["id"]) if header else []
    history = legacy_repo.get_log_history(src_id)
    latest_log = history[-1] if history else None
    verifier_finding = _latest_verifier_finding(src_id)

    recommendation = None
    is_open_exception = bool(latest_log and latest_log["status"] in ("Failed", "OnHold", "ON_HOLD"))
    if is_open_exception and header is not None:
        classified = classify_erp_error(_erp_failure_description(history))
        supplier_name = header.get("supplier_name") or "unknown"
        decision = bandit.choose_action(supplier_name, classified.exception_type.value)
        suggested_action = bandit.best_action_by_expected_value(decision.arm_states)
        authorization = governance.authorize_autonomous_action(
            supplier_name,
            classified.exception_type.value,
            confidence=bandit.expected_value(decision.arm_states[suggested_action]),
            amount=header.get("invoice_amount"),
        )
        recommendation = {
            "exception_type": classified.exception_type.value,
            "action_space": classified.action_space,
            "suggested_action": suggested_action,
            "arm_states": decision.arm_states,
            "autonomy_check": {
                "allowed": authorization.allowed,
                "stage_used": authorization.stage_used.value,
                "reason": authorization.reason,
            },
        }

    return {
        "source": source,
        "header": header,
        "lines": lines,
        "history": history,
        "latest_status": latest_log,
        "verifier_finding": verifier_finding,
        "is_open_exception": is_open_exception,
        "recommendation": recommendation,
        "supplier_email": legacy_repo.get_source_email(src_id),
    }


def get_agent_trace(src_id: str) -> list[dict[str, Any]]:
    return trace_logger.get_trace(src_id)


def list_open_exceptions(limit: int = 100) -> list[dict[str, Any]]:
    documents = list_documents(limit=limit)
    open_docs = [d for d in documents if d["status"] in ("Failed", "OnHold", "ON_HOLD")]
    detailed = []
    for doc in open_docs:
        detail = get_document_detail(doc["src_id"])
        if detail:
            detailed.append({**doc, "recommendation": detail["recommendation"], "latest_status": detail["latest_status"]})
    return detailed


# "Processed" means actually posted to an ERP -- status="Successful" alone
# also matches stage="Collection" (the email merely arrived) or
# "Preprocessing"/"LLM Extraction" (upstream steps succeeded, ERP submission
# hasn't happened yet), so this must also constrain on stage.
_ERP_STAGES = ["EBS", "JDE"]


def list_processed_documents(limit: int | None = 200, _exclude_ids: set[str] | None = None) -> list[dict[str, Any]]:
    # Excludes agent-resolved documents so this drill-down list always agrees
    # with the dashboard's "Processed Successfully" count -- see the matching
    # exclusion in get_dashboard_summary for why. `_exclude_ids` lets
    # get_dashboard_summary pass in a set it already computed rather than
    # re-querying OutcomesLog a second time for the same request.
    exclude_ids = _exclude_ids if _exclude_ids is not None else {
        row["src_id"] for row in list_agent_handled_exceptions(limit=10_000)
    }
    processed = legacy_repo.list_sources_by_status(["Successful"], stages=_ERP_STAGES, limit=None)
    return [p for p in processed if p["src_id"] not in exclude_ids][:limit]


def get_recent_agent_runs(limit: int = 10) -> list[dict[str, Any]]:
    """One line item per Orchestrator/Planner Agent run (process_document()
    call), newest first -- the dashboard's "recent agent activity" feed.
    """
    with session_scope() as session:
        rows = session.scalars(
            select(AgentLog).where(AgentLog.step_type == "run_end").order_by(AgentLog.created_at.desc()).limit(limit)
        ).all()

    results = []
    for row in rows:
        source = legacy_repo.get_source(row.src_id)
        header = legacy_repo.get_invoice_header(row.src_id)
        latest_log = legacy_repo.get_latest_log(row.src_id)
        results.append(
            {
                "run_id": row.run_id,
                "src_id": row.src_id,
                "supplier_name": header.get("supplier_name") if header else None,
                "doc_type": source.get("doc_type") if source else None,
                "run_outcome": row.message,
                "is_error": row.is_error,
                "status": latest_log["status"] if latest_log else None,
                "completed_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return results


def list_agent_handled_exceptions(limit: int = 100) -> list[dict[str, Any]]:
    """src_ids the Orchestrator/Planner Agent resolved on its own -- an
    outcomes_log row with decided_by="policy" -- whose current status is now
    "Successful", i.e. the agent's own action is what closed the exception
    (no human called submit_feedback/edit_and_reprocess afterward).
    """
    with session_scope() as session:
        rows = session.scalars(
            select(OutcomesLog)
            .where(OutcomesLog.decided_by == "policy")
            .order_by(OutcomesLog.created_at.desc())
        ).all()

    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in rows:
        if row.src_id in seen:
            continue
        seen.add(row.src_id)
        latest_log = legacy_repo.get_latest_log(row.src_id)
        if not latest_log or latest_log["status"] != "Successful":
            continue
        source = legacy_repo.get_source(row.src_id)
        header = legacy_repo.get_invoice_header(row.src_id)
        results.append(
            {
                "src_id": row.src_id,
                "supplier_name": row.supplier_name,
                "exception_type": row.exception_type,
                "action_taken": row.action_taken,
                "autonomy_stage": row.autonomy_stage,
                "confidence_at_decision": row.confidence_at_decision,
                "resolved_at": (row.resolved_at or row.created_at).isoformat() if (row.resolved_at or row.created_at) else None,
                "doc_type": source.get("doc_type") if source else None,
                "target": source.get("target") if source else None,
                "invoice_number": header.get("invoice_number") if header else None,
                "invoice_amount": header.get("invoice_amount") if header else None,
            }
        )
        if len(results) >= limit:
            break
    return results


def get_dashboard_summary(recent_limit: int = 10) -> dict[str, Any]:
    with session_scope() as session:
        runs_completed = session.scalar(
            select(func.count(func.distinct(AgentLog.run_id))).where(AgentLog.step_type == "run_end")
        ) or 0

    # A src_id resolved via apply_learned_correction (auto_fix_line_item) both
    # ends with status="Successful"/stage in _ERP_STAGES *and* has an
    # OutcomesLog row with decided_by="policy" -- so it matches
    # count_sources_by_status's "processed" query and
    # list_agent_handled_exceptions at the same time. Left alone, that
    # document is counted in both headline numbers. "Processed Successfully"
    # is meant to mean straight-through processing (no exception occurred at
    # all), so list_processed_documents (shared with the drill-down list
    # this tile links to) already excludes agent-resolved documents, and is
    # counted only once, under "Exceptions -- Agent Handled".
    agent_handled = list_agent_handled_exceptions(limit=10_000)

    return {
        "total_received": legacy_repo.count_sources(),
        "runs_completed": runs_completed,
        "processed_successfully": len(
            list_processed_documents(limit=None, _exclude_ids={row["src_id"] for row in agent_handled})
        ),
        "exceptions_human_review": legacy_repo.count_sources_by_status(["Failed", "OnHold", "ON_HOLD"]),
        "exceptions_agent_handled": len(agent_handled),
        "recent_transactions": get_recent_agent_runs(recent_limit),
    }


def edit_and_reprocess(
    src_id: str,
    header_fields: dict[str, Any] | None = None,
    line_edits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The human edit-then-reprocess path for an open exception: apply
    corrected invoice fields and resubmit directly to the ERP -- no LLM call,
    no /run-agent -- then log the fix so a future occurrence of this
    (supplier, exception_type) can be auto-resolved by
    orchestrator.native_tools.apply_learned_correction, which replays it.

    `line_edits` is `[{"line_id": int, "field": str, "value": Any}, ...]` for
    invalid_item-style fixes (a wrong item_name/item_desc/etc. on one line).
    The line's value *before* the edit is captured here from the database,
    never trusted from the caller, and stored alongside the new value as a
    match_value/set_value rule -- replaying "line_id 42's item_name is now X"
    on a different document is meaningless (that document has its own,
    different line_ids), but "wherever this supplier's item_name was
    'abc-x', it should be 'abc-1'" is exactly the kind of rule
    apply_learned_correction can find and apply on a future document's lines.
    """
    source = legacy_repo.get_source(src_id)
    if source is None:
        raise ValueError(f"No source found for src_id={src_id}")
    header = legacy_repo.get_invoice_header(src_id)
    if header is None:
        raise ValueError(f"No extracted invoice header to edit for src_id={src_id}")

    header_fields = header_fields or {}
    line_edits = line_edits or []
    if not header_fields and not line_edits:
        raise ValueError("No fields supplied to edit")

    history = legacy_repo.get_log_history(src_id)
    classified = classify_erp_error(_erp_failure_description(history))
    supplier_name = header.get("supplier_name") or "unknown"

    decision = bandit.choose_action(supplier_name, classified.exception_type.value)
    suggested_action = bandit.best_action_by_expected_value(decision.arm_states)

    existing_lines = {line["id"]: line for line in legacy_repo.get_invoice_lines(header["id"])}
    line_rules = []
    for edit in line_edits:
        line_id, field, value = edit["line_id"], edit["field"], edit["value"]
        line = existing_lines.get(line_id)
        if line is None:
            raise ValueError(f"line_id {line_id} does not belong to src_id={src_id}")
        legacy_repo.update_invoice_line_field(line_id, field, value)
        line_rules.append({"match_field": field, "match_value": line.get(field), "set_field": field, "set_value": value})

    for field, value in header_fields.items():
        legacy_repo.update_invoice_field(header["id"], field, value)

    if source.get("target") == "JDE":
        erp_result = jde_server.create_invoice(src_id)
        succeeded = erp_result.get("status") == "success"
    else:
        erp_result = oracle_ebs_server.create_invoice(src_id)
        succeeded = erp_result.get("status") == "S"

    correction_payload = {"header": header_fields, "lines": line_rules}

    legacy_repo.insert_log(
        src_id,
        "Successful" if succeeded else "Failed",
        source.get("target") or "MCP",
        f"Manual edit + reprocess: {erp_result.get('message', '')}",
        is_reviewed="1",
        action_taken="manual_edit",
        what_modified=json.dumps(correction_payload, default=str),
    )

    correction_id = feedback_logger.log_correction(
        src_id=src_id,
        supplier_name=supplier_name,
        doc_type=source.get("doc_type") or "unknown",
        exception_type=classified.exception_type.value,
        invoice_features={**header, "lines": list(existing_lines.values())},
        ai_recommendation=suggested_action,
        human_action=f"manual_edit:{json.dumps(correction_payload, default=str)}",
        ai_recommendation_correct=succeeded,
    )

    mapped_action = EDIT_REPROCESS_ACTION_MAP[classified.exception_type]
    bandit.record_outcome(supplier_name, classified.exception_type.value, mapped_action, success=succeeded)

    return {
        "success": succeeded,
        "erp_result": erp_result,
        "correction_id": correction_id,
        "src_id": src_id,
        "header_fields_applied": header_fields,
        "line_fields_applied": line_rules,
    }


def send_supplier_email(src_id: str, subject: str, body_html: str) -> dict[str, Any]:
    """The human "send email to supplier" action from the Manual Review /
    document detail page -- actually sends (via _send_and_log_email, the
    same atomic send+log helper the agent's own apply_learned_email tool
    uses), then records the decision as a Correction so the next time this
    exact (supplier, exception_type) hits the same exception, the agent's
    apply_learned_email tool finds this as a precedent and can auto-send
    without waiting on a human again.
    """
    source = legacy_repo.get_source(src_id)
    if source is None:
        raise ValueError(f"No source found for src_id={src_id}")
    header = legacy_repo.get_invoice_header(src_id)

    history = legacy_repo.get_log_history(src_id)
    classified = classify_erp_error(_erp_failure_description(history))
    supplier_name = (header.get("supplier_name") if header else None) or "unknown"

    decision = bandit.choose_action(supplier_name, classified.exception_type.value)
    suggested_action = bandit.best_action_by_expected_value(decision.arm_states)

    result = _send_and_log_email(
        src_id, supplier_name, classified.exception_type.value, subject, body_html, decided_by="human"
    )
    if not result["sent"]:
        return {"success": False, **result}

    correction_id = feedback_logger.log_correction(
        src_id=src_id,
        supplier_name=supplier_name,
        doc_type=source.get("doc_type") or "unknown",
        exception_type=classified.exception_type.value,
        invoice_features={**(header or {}), "lines": legacy_repo.get_invoice_lines(header["id"]) if header else []},
        ai_recommendation=suggested_action,
        human_action="email_supplier",
        ai_recommendation_correct=(suggested_action == "email_supplier"),
    )

    return {"success": True, "correction_id": correction_id, **result}


def submit_feedback(
    src_id: str,
    human_action: str,
    correct: bool,
    ai_recommendation: str | None = None,
    exception_type: str | None = None,
    supplier_name: str | None = None,
    doc_type: str | None = None,
    invoice_features: dict[str, Any] | None = None,
    confidence_at_decision: float | None = None,
) -> dict[str, Any]:
    """The human-feedback write path a frontend "Approve" / "Correct" button
    calls. This is the RLHF-style loop's actual entry point: it (1) logs a
    labeled correction example, (2) updates the bandit's posterior for
    whichever action was actually taken, and (3) closes the exception out of
    the open-exceptions queue in the shared audit trail.
    """
    source = legacy_repo.get_source(src_id)
    header = legacy_repo.get_invoice_header(src_id)

    resolved_supplier = supplier_name or (header.get("supplier_name") if header else None) or "unknown"
    resolved_doc_type = doc_type or (source.get("doc_type") if source else None) or "unknown"
    resolved_exception_type = exception_type or ExceptionType.UNKNOWN.value
    resolved_features = invoice_features or (header or {})

    correction_id = feedback_logger.log_correction(
        src_id=src_id,
        supplier_name=resolved_supplier,
        doc_type=resolved_doc_type,
        exception_type=resolved_exception_type,
        invoice_features=resolved_features,
        ai_recommendation=ai_recommendation or "",
        human_action=human_action,
        ai_recommendation_correct=correct,
        confidence_at_decision=confidence_at_decision,
    )

    valid_exception_types = {e.value for e in ExceptionType}
    exception_type_enum = ExceptionType(resolved_exception_type) if resolved_exception_type in valid_exception_types else ExceptionType.UNKNOWN
    action_space = DEFAULT_ACTION_SPACE.get(exception_type_enum, [])
    action_for_bandit = ai_recommendation if ai_recommendation in action_space else human_action
    bandit.record_outcome(resolved_supplier, resolved_exception_type, action_for_bandit, success=correct)

    # Mirror the orchestrator's own rule (agent.py SYSTEM_PROMPT step 5c):
    # "escalate" means this case is NOT resolved, no matter which button was
    # clicked to record it -- it must stay open (Failed) so it keeps showing
    # up in Manual Review, not silently close out as "Successful". Every
    # other recorded action here means the human is confirming the exception
    # was actually taken care of.
    resolved_status = "Failed" if human_action == "escalate" else "Successful"

    legacy_repo.insert_log(
        src_id,
        resolved_status,
        "MCP",
        f"Human feedback recorded: {human_action}",
        is_reviewed="1",
        action_taken=human_action,
    )

    return {"correction_id": correction_id, "src_id": src_id, "recorded": True}

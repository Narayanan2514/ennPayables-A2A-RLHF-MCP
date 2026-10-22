"""Central client-side orchestrator/supervisor.

Every orchestration decision in this system -- discovery, agent selection,
sequencing, and result aggregation -- lives in this module (and the modules
it calls under `client/`). No agent contains any of this logic; each agent
only validates the request, lets its own CrewAI crew pick and run one tool,
and responds.

Two kinds of workflow share the same WorkflowRecord/step schema so the
frontend can render both the same way:

- `run_nl_workflow` / `run_structured_workflow`: ad-hoc, on-demand chat/API
  requests routed to one or more agents (Workflow A/B from the spec).
- `run_email_pipeline` (+ `watch_email_pipeline` background loop): the
  autonomous email-to-ERP pipeline, an exact-replica port of
  ennVault_org_backend's real pipeline (email_module -> prep.py's
  run_parser -> inv_extract.py -> ERP/{JDE,EBS}/inv_payload.py), just with
  each stage behind an A2A agent instead of a plain Python call chain.
  This orchestrator polls the mailbox and classifies each message itself
  (see email_polling.py) -- Agent 1 no longer polls or classifies anything;
  it only acts on one specific message per A2A call, once told whether the
  supervisor found it valid or invalid. For each valid message, a real
  CrewAI orchestrator agent (orchestrator_agent.py) decides, turn by turn,
  which of Agent 2 (validate), Agent 3 (extract), and Agent 4 (push to ERP)
  to call next and with what task -- based on what each agent actually
  returns, not a hardcoded Python call sequence. Data still moves
  agent-to-agent via payload_key references (the orchestrator's `call_agent`
  tool stashes each real result and hands back a fresh key the crew can
  forward into a later call) -- see orchestrator_agent.py's own docstring
  for the full design and how it's built to fail loudly (a task error) on a
  forgotten/wrong key rather than silently accepting fabricated data.
  `run_email_pipeline` itself still owns interpreting the REAL recorded
  step data afterward for the final status and Phase 2 exception handling
  (`exception_handling.py`) -- it does not trust the crew's own narrated
  summary for that part, so ERP-push outcome handling stays exactly as
  reliable as it was before this was LLM-driven.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from crewai import Crew, Process
from crewai import Task as CrewTask

from ..a2a_client.client import call_agent_task
from ..agent_registry.registry import registry
from ..response_aggregator.aggregator import aggregate
from ..task_router.router import RoutedCall, route
from . import email_polling
from .exception_handling import handle_erp_failure
from .orchestrator_agent import CallAgentTool, OrchestrationResult, build_orchestrator_agent, describe_session_context
from .self_correction import attempt_self_correction
from shared.crew.payload_store import PayloadStore
from shared.config.settings import PIPELINE_WATCH_INTERVAL_SECONDS, TARGET_ERP
from shared.db import workflow_session_repo as session_repo
from shared.utilities.logging import get_logger

logger = get_logger("client.orchestrator")

WorkflowMode = Literal["auto", "sequential", "parallel"]
WorkflowKind = Literal["chat", "email_pipeline"]

EMAIL_INTAKE_AGENT = "email-intake-agent"
VALIDATOR_AGENT = "validator-agent"
EXTRACTION_AGENT = "extraction-agent"
ERP_PUSH_AGENT = "erp-push-agent"


@dataclass
class WorkflowRecord:
    workflow_id: str
    user_text: str
    mode: WorkflowMode
    status: str
    started_at: str
    kind: WorkflowKind = "chat"
    title: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_response: dict[str, Any] | None = None
    # Durable workflow_session id (see shared/db/workflow_session_repo.py) --
    # set only for email_pipeline runs; a chat/structured WorkflowRecord has
    # no durable session behind it.
    session_id: str | None = None


_history: dict[str, WorkflowRecord] = {}
_watcher_task: asyncio.Task | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_discovered() -> None:
    if not registry.agents:
        await registry.discover()


# ---------------------------------------------------------------------------
# Ad-hoc chat / structured workflows
# ---------------------------------------------------------------------------


async def run_nl_workflow(user_text: str, mode: WorkflowMode = "auto") -> WorkflowRecord:
    """Workflow A/B entrypoint for free-text requests: discover -> select
    agent(s) -> execute (single or multi-agent) -> aggregate."""
    await ensure_discovered()
    workflow_id = f"wf-{uuid.uuid4().hex[:10]}"
    record = WorkflowRecord(workflow_id=workflow_id, user_text=user_text, mode=mode, status="running", started_at=_now(), kind="chat")
    _history[workflow_id] = record

    calls = route(registry, user_text)
    if not calls:
        record.status = "no_match"
        record.final_response = {
            "overallStatus": "no_match",
            "summary": "No registered agent matched this request.",
            "results": [],
        }
        record.finished_at = _now()
        return record

    await _execute_calls(record, calls, mode)
    return record


async def run_structured_workflow(steps: list[dict[str, Any]], mode: WorkflowMode = "parallel") -> WorkflowRecord:
    """Entrypoint for explicit, programmatic multi-step requests, e.g.
    [{"agentId": "validator-agent", "taskText": "Validate ..."}, ...]. Each
    named agent's own crew still decides which tool to run."""
    await ensure_discovered()
    workflow_id = f"wf-{uuid.uuid4().hex[:10]}"
    record = WorkflowRecord(workflow_id=workflow_id, user_text="[structured request]", mode=mode, status="running", started_at=_now(), kind="chat")
    _history[workflow_id] = record

    calls: list[RoutedCall] = []
    for step in steps:
        agent_id = step.get("agentId")
        agent = registry.get_agent(agent_id) if agent_id else None
        if not agent:
            record.steps.append(
                {
                    "agentId": agent_id or "unknown",
                    "taskText": step.get("taskText", ""),
                    "status": "failed",
                    "error": f"Agent '{agent_id}' is not registered. Try POST /api/discovery/refresh.",
                }
            )
            continue
        calls.append(RoutedCall(agent.card.id, agent.base_url, step.get("taskText", ""), reason="explicit step"))

    await _execute_calls(record, calls, mode)
    return record


async def _execute_calls(record: WorkflowRecord, calls: list[RoutedCall], mode: WorkflowMode) -> None:
    if not calls:
        aggregated = aggregate([])
        record.final_response = {"overallStatus": aggregated.overall_status, "summary": aggregated.summary, "results": aggregated.results, "executionMode": mode}
        record.status = aggregated.overall_status
        record.finished_at = _now()
        return

    resolved_mode = mode
    if mode == "auto":
        resolved_mode = "parallel" if len({call.agent_id for call in calls}) > 1 else "sequential"

    selected_steps = []
    for call in calls:
        step = {"agentId": call.agent_id, "taskText": call.task_text, "status": "selected", "reason": call.reason}
        record.steps.append(step)
        selected_steps.append(step)

    if resolved_mode == "parallel":
        results = await asyncio.gather(
            *[call_agent_task(call.agent_id, call.base_url, call.task_text) for call in calls]
        )
    else:
        results = []
        for call in calls:
            results.append(await call_agent_task(call.agent_id, call.base_url, call.task_text))

    for step, result in zip(selected_steps, results):
        step["status"] = "completed" if result.task and result.task.status.state == "completed" else "failed"
        step["durationMs"] = result.duration_ms
        if result.task is not None:
            step["skillUsed"] = result.task.metadata.get("skillUsed")
        if result.error:
            step["error"] = result.error

    aggregated = aggregate(list(results))
    record.final_response = {
        "overallStatus": aggregated.overall_status,
        "summary": aggregated.summary,
        "results": aggregated.results,
        "executionMode": resolved_mode,
    }
    record.status = aggregated.overall_status
    record.finished_at = _now()


def get_workflow(workflow_id: str) -> WorkflowRecord | None:
    return _history.get(workflow_id)


def list_history(limit: int = 50, kind: WorkflowKind | None = None) -> list[WorkflowRecord]:
    records = list(_history.values())
    if kind is not None:
        records = [r for r in records if r.kind == kind]
    return records[-limit:][::-1]


# ---------------------------------------------------------------------------
# Autonomous email -> ERP pipeline
# ---------------------------------------------------------------------------


async def run_email_pipeline(intake_record: dict[str, Any]) -> WorkflowRecord:
    """Drives one intake record through Validate -> Extract+Store -> Push to
    ERP. Which agent to call, in what order, is decided turn-by-turn by a
    real CrewAI orchestrator agent (orchestrator_agent.py) -- not a
    hardcoded Python call sequence. Data still flows agent-to-agent via
    payload_key references the orchestrator's own tool manages (see
    orchestrator_agent.py's module docstring); this function's own job is
    to seed that run, then interpret the REAL recorded step data afterward
    for the final status and Phase 2 exception handling -- not to trust the
    crew's own summary for that part, so ERP-push outcome handling stays as
    reliable as it was before this was LLM-driven."""
    await ensure_discovered()
    workflow_id = f"wf-{uuid.uuid4().hex[:10]}"
    subject = intake_record.get("subject") or "(no subject)"
    session_id = intake_record.get("session_id")
    record = WorkflowRecord(
        workflow_id=workflow_id,
        user_text=f"Email pipeline for: {subject}",
        mode="sequential",
        status="running",
        started_at=_now(),
        kind="email_pipeline",
        title=subject,
        session_id=session_id,
    )
    _history[workflow_id] = record

    # Stage 1 is already done -- Agent 1's background poller produced this
    # intake record. Record it as a completed step so the frontend shows all
    # four stages, without re-calling Agent 1.
    record.steps.append(
        {
            "agentId": EMAIL_INTAKE_AGENT,
            "taskText": "(background poll) intake record queued",
            "status": "completed",
            "skillUsed": "poll_inbox",
            "data": intake_record,
        }
    )

    if session_id:
        # email_polling.py already created + claimed the session and left
        # current_step=AGENT_1; Agent 1's own work is what just got recorded
        # above, so the durable step pointer advances to AGENT_2 here.
        session_repo.advance_step(session_id, "AGENT_2")

    if TARGET_ERP not in ("JDE", "EBS"):
        return _finish(record, "failed", f"Unsupported TARGET_ERP: {TARGET_ERP!r}. Expected 'JDE' or 'EBS'.")

    return await _run_orchestrator_agent(record, intake_record)


async def _run_orchestrator_agent(record: WorkflowRecord, intake_record: dict[str, Any]) -> WorkflowRecord:
    """Seeds a fresh CallAgentTool + PayloadStore for this one run (never
    shared across runs -- see orchestrator_agent.py), lets the CrewAI
    orchestrator agent decide and drive the whole Validate->Extract->Push
    sequence, then interprets the REAL recorded step data (not the crew's
    own narrated summary) for the final status and Phase 2 exception
    handling.
    """
    payload_store = PayloadStore()
    initial_key = payload_store.put({"attachments": intake_record.get("attachments", [])})

    tool = CallAgentTool()
    tool.record = record
    tool.registry = registry
    tool.payload_store = payload_store
    tool.session_id = record.session_id
    # {agent_id: current_step to advance the durable session to once that
    # agent's call completes} -- erp-push-agent has no "next" agent, so it
    # maps to itself; the session's terminal status is decided separately,
    # from the REAL recorded ERP outcome (see _finish_from_recorded_steps).
    tool.next_step_map = {
        VALIDATOR_AGENT: "AGENT_3",
        EXTRACTION_AGENT: "AGENT_4",
        ERP_PUSH_AGENT: "AGENT_4",
    }

    crew_agent = build_orchestrator_agent(registry, tool)

    # Each target agent's own crew parses from_email/subject/doc_type/etc.
    # OUT OF ITS TASK TEXT (see e.g. agents/agent_2/skills/tools.py's
    # ValidateIntakeRecordArgs) -- these are NOT carried by a DataPart, only
    # attachments/encoded_image_paths/etc. are. Pre-building the exact text
    # here, with the real values Python already has, and telling the
    # orchestrator crew to copy it verbatim removes an entire class of
    # failure: the crew forgetting or garbling a field while composing task
    # text from memory (exactly the kind of transcription risk the
    # payload_key mechanism already exists to avoid for structured data --
    # this is the same principle applied to the task-text side).
    validator_task_text = (
        "Validate this email intake record for ERP processing.\n"
        f"from_email: {intake_record.get('from_email', '')}\n"
        f"subject: {intake_record.get('subject', '')}\n"
        f"doc_type: {intake_record.get('doc_type') or ''}\n"
    )
    extraction_task_text = (
        "Extract invoice details from the validated, PII-masked page images.\n"
        f"from_email: {intake_record.get('from_email', '')}\n"
        f"subject: {intake_record.get('subject', '')}\n"
        f"body_text: {intake_record.get('body_text', '')[:2000]}\n"
        f"conversation_id: {intake_record.get('conversation_id', '')}\n"
        f"message_id: {intake_record.get('message_id', '')}\n"
        f"target_erp: {TARGET_ERP}\n"
    )
    push_task_text = f"Push the stored invoice to the live ERP for target_erp: {TARGET_ERP}."

    session_context = describe_session_context(session_repo.get_session(record.session_id) if record.session_id else None)

    task_description = (
        session_context
        + f"Process this email intake record toward ERP submission for target_erp={TARGET_ERP}.\n\n"
        f'The initial attachments payload is stored under payload_key="{initial_key}".\n\n'
        "Call agents using EXACTLY these task_text values (copy each one verbatim, character for "
        "character, including every field line -- do not paraphrase, summarize, or reconstruct them "
        "yourself, and do not omit a field even if it looks empty):\n\n"
        f'When calling validator-agent, use this task_text and pass forward_payload_key="{initial_key}":\n'
        f"---\n{validator_task_text}---\n\n"
        "When calling extraction-agent (only after validator-agent's result has is_valid=true), use this "
        "task_text, and pass forward_payload_key set to validator-agent's own result_payload_key from its "
        "call_agent result (never the initial attachments key again):\n"
        f"---\n{extraction_task_text}---\n\n"
        "When calling erp-push-agent (only after extraction-agent succeeds), use this task_text, and pass "
        "forward_payload_key set to extraction-agent's own result_payload_key:\n"
        f"---\n{push_task_text}\n---"
    )
    crew_task = CrewTask(
        description=task_description,
        expected_output="A JSON object with fields final_status ('success'|'blocked'|'failed') and summary.",
        agent=crew_agent,
        output_pydantic=OrchestrationResult,
    )
    crew = Crew(agents=[crew_agent], tasks=[crew_task], process=Process.sequential, verbose=False)

    try:
        crew_output = await asyncio.to_thread(crew.kickoff)
    except Exception as exc:
        logger.exception("Orchestrator crew execution failed")
        return _finish(record, "failed", f"Orchestrator crew execution failed: {exc}")

    parsed: OrchestrationResult | None = crew_output.pydantic
    if parsed is None:
        return _finish(record, "failed", f"Could not parse orchestrator output: {crew_output.raw}")

    return await _finish_from_recorded_steps(record, parsed)


async def _finish_from_recorded_steps(record: WorkflowRecord, parsed: OrchestrationResult) -> WorkflowRecord:
    """Ground truth for the ERP-push outcome comes from the real recorded
    step data (CallAgentTool._run wrote it faithfully) -- not from the
    crew's own summary -- so Phase 2's exception handling stays reliable
    regardless of how well the crew narrates its own outcome. Split out
    from `_run_orchestrator_agent` so it's directly testable against a
    hand-built `record.steps` list, without needing to mock CrewAI/the LLM
    at all.
    """
    push_step = next(
        (s for s in reversed(record.steps) if s["agentId"] == ERP_PUSH_AGENT and s.get("status") == "completed"), None
    )
    if push_step is not None:
        push_result = push_step["data"]
        push_status = (push_result.get("status") or "").strip().lower()
        message = push_result.get("message", "")
        if push_status == "success":
            return _finish(record, "success", message or "Invoice pushed to ERP.")
        if push_status in ("on hold", "onhold", "on_hold"):
            # JDE's own voucher-approval-hold flow (jde_push.py already
            # emailed the approver) -- not an ERP-data exception to
            # classify/replay, so exception handling does not apply here.
            return _finish(record, "blocked", message or "Invoice is on hold pending approval.")

        extraction_step = next(
            (s for s in reversed(record.steps) if s["agentId"] == EXTRACTION_AGENT and s.get("status") == "completed"), None
        )
        src_id = extraction_step["data"].get("src_id") if extraction_step else None

        if src_id:
            correction = await _run_self_correction(record, src_id, message)
            if correction and correction.get("changed") and correction.get("succeeded"):
                retry_result = correction.get("push_result") or {}
                retry_status = (retry_result.get("status") or "").strip().lower()
                retry_message = retry_result.get("message", "")
                if retry_status in ("on hold", "onhold", "on_hold"):
                    return _finish(record, "blocked", retry_message or "Invoice is on hold pending approval.")
                return _finish(record, "success", retry_message or "Invoice pushed to ERP after self-correction.")

        await _run_exception_handling(record, src_id)
        return _finish(record, "failed", message or "ERP push failed.")

    # No completed push step at all -- the crew stopped earlier (validation
    # blocked, extraction failed, or it chose to stop on its own) or a call
    # itself failed. Trust its own status/summary for that case; there is no
    # real ERP outcome to independently verify.
    return _finish(record, parsed.final_status, parsed.summary)


async def _run_self_correction(record: WorkflowRecord, src_id: str, failure_message: str) -> dict[str, Any] | None:
    """Runs the bounded, one-shot self-correction attempt (self_correction.py)
    for a failed ERP push, tried BEFORE the Phase 2 exception-handling
    sequence, and records it as one more step in the run -- same convention
    _run_exception_handling uses for its own stage. Only ever changes
    anything for an 'item not found' rejection (see
    mcp_server/tools/self_correction.py); every other failure reports
    attempted=False and the caller falls straight through to
    _run_exception_handling, unchanged. Never lets a problem here (MCP
    server down, etc.) break the pipeline run itself.
    """
    step = {
        "agentId": "self-correction",
        "taskText": f"Self-correction attempt for src_id={src_id}",
        "status": "running",
    }
    record.steps.append(step)
    try:
        result = await attempt_self_correction(record, src_id, TARGET_ERP, failure_message)
    except Exception as exc:  # noqa: BLE001 -- must never break the pipeline run itself
        logger.exception("Self-correction failed for src_id=%s", src_id)
        step["status"] = "failed"
        step["error"] = str(exc)
        return None
    step["status"] = "completed"
    step["data"] = result
    return result


async def _run_exception_handling(record: WorkflowRecord, src_id: str | None) -> dict[str, Any] | None:
    """Runs the Phase 2 learned-replay-then-escalate sequence for a failed
    ERP push and records it as one more step in the run, exactly like every
    other stage -- but never lets a problem here (RLHF API down, etc.) break
    the pipeline run itself; the run still finishes as "failed" either way,
    this only adds visibility into what the exception-handling side-channel
    did or didn't manage to do about it.
    """
    if not src_id:
        return None
    step = {
        "agentId": "exception-handler",
        "taskText": f"Autonomous exception handling for src_id={src_id}",
        "status": "running",
    }
    record.steps.append(step)
    try:
        result = await handle_erp_failure(src_id)
    except Exception as exc:  # noqa: BLE001 -- must never break the pipeline run itself
        logger.exception("Exception handling failed for src_id=%s", src_id)
        step["status"] = "failed"
        step["error"] = str(exc)
        return None
    step["status"] = "completed"
    step["data"] = result
    return result


def _finish(record: WorkflowRecord, status: str, summary: str) -> WorkflowRecord:
    record.status = status
    record.finished_at = _now()
    record.final_response = {"overallStatus": status, "summary": summary, "steps": len(record.steps)}
    if record.session_id:
        # Single funnel point for every run_email_pipeline outcome (success,
        # blocked, no_match, partial, failed) -- resolves the durable
        # session's terminal state from the SAME status this function was
        # just given, which is itself always grounded in the real recorded
        # step data (see _finish_from_recorded_steps), never the crew's own
        # narration. Never lets a DB hiccup here break the run itself.
        try:
            if status == "failed":
                outcome = session_repo.fail_session(record.session_id)
                if outcome:
                    record.final_response["session"] = outcome
            else:
                session_repo.mark_success(record.session_id)
        except Exception:
            logger.exception("Failed to update workflow_session %s for terminal status=%s", record.session_id, status)
    return record


def recover_sessions_on_startup() -> list[dict[str, Any]]:
    """Worker-startup recovery pass: surfaces every session left in RETRY by
    a prior worker/process (e.g. one that crashed mid-run) so they're
    visible immediately -- in the Sessions tab and in this process's own
    logs -- instead of silently sitting there until someone happens to look.

    Does not auto-reclaim them: the in-memory intake payload (attachments,
    extracted fields not yet persisted) from the run that failed does not
    survive a process restart -- see PayloadStore's docstring and
    workflow_session_repo.py's module docstring on why the DB session is
    durable control state, not a durable payload store. A retryable session
    stays claimable (see the Sessions tab's "Claim" action / POST
    /api/sessions/{id}/claim) by any worker; this only makes sure it's not
    forgotten.
    """
    retryable = session_repo.find_retryable_sessions()
    if retryable:
        logger.warning(
            "Startup recovery: %s session(s) left in RETRY by a prior worker: %s",
            len(retryable),
            ", ".join(f"{s['session_id']} (current_step={s['current_step']}, retry_count={s['retry_count']})" for s in retryable),
        )
    return retryable


async def poll_now() -> list[WorkflowRecord]:
    """Manual trigger: poll the mailbox immediately (supervisor-owned --
    see email_polling.py) and run the pipeline for every valid email found
    (used by the frontend's 'Poll Now' button and by the background watcher
    on its own schedule)."""
    await ensure_discovered()
    records = await email_polling.poll_and_dispatch()
    return [await run_email_pipeline(r) for r in records]


async def watch_email_pipeline() -> None:
    """Background loop: periodically polls the mailbox (the supervisor lists
    unread mail and classifies each message itself now -- see
    email_polling.py -- rather than draining a queue Agent 1 used to
    maintain) and drives each valid record through the pipeline. Started
    once at API startup; never runs on the agent side."""
    logger.info("Email pipeline watcher started (every %ss)", PIPELINE_WATCH_INTERVAL_SECONDS)
    while True:
        try:
            await ensure_discovered()
            records = await email_polling.poll_and_dispatch()
            for record in records:
                await run_email_pipeline(record)
        except Exception:
            logger.exception("Pipeline watcher iteration failed")
        await asyncio.sleep(PIPELINE_WATCH_INTERVAL_SECONDS)

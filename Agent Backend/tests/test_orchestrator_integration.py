"""End-to-end orchestrator tests: real discovery over HTTP (in-process via
ASGI transport, no real sockets). Discovery itself never touches an LLM, so
those tests always run. The email pipeline's Stage 2 (validation) only
needs the Validator Agent's crew (OpenAI) -- no DB or Graph credentials --
so it's the one live-pipeline path tested here; the full Stage 3/4 chain
additionally needs a real MySQL DB and a real PDF, which is out of scope for
this offline test suite.
"""
import os

import pytest

from client.agent_registry.registry import registry
from client.orchestrator import orchestrator

requires_openai = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires OPENAI_API_KEY for live CrewAI execution")


async def _fake_self_correction_not_applicable(record, src_id, target_erp, failure_message):
    return {"attempted": False, "exception_type": "invalid_po"}


async def _fake_self_correction_success(record, src_id, target_erp, failure_message):
    return {
        "attempted": True,
        "exception_type": "invalid_item",
        "changed": True,
        "field": "item_name",
        "old_value": "WIDGET-X",
        "new_value": "WIDGET-9",
        "push_result": {"status": "success", "message": "Invoice posted after correction"},
        "succeeded": True,
    }


# --- Discovery: no LLM involved, always runs ---------------------------------


@pytest.mark.asyncio
async def test_discovery_registers_all_four_agents(in_process_httpx):
    await registry.discover()
    assert set(registry.agents.keys()) == {"email-intake-agent", "validator-agent", "extraction-agent", "erp-push-agent"}
    assert registry.discovery_errors == {}


@pytest.mark.asyncio
async def test_discovery_records_error_for_unreachable_agent(in_process_httpx):
    await registry.discover(urls=["http://localhost:8001", "http://localhost:9999"])
    assert "email-intake-agent" in registry.agents
    assert "http://localhost:9999" in registry.discovery_errors


@pytest.mark.asyncio
async def test_structured_workflow_unregistered_agent_is_reported_without_calling_it(in_process_httpx):
    await registry.discover()
    steps = [{"agentId": "not-a-real-agent", "taskText": "do something"}]
    record = await orchestrator.run_structured_workflow(steps)
    assert any(step["agentId"] == "not-a-real-agent" and step["status"] == "failed" for step in record.steps)


@pytest.mark.asyncio
async def test_nl_workflow_no_match_does_not_call_any_agent(in_process_httpx):
    await registry.discover()
    record = await orchestrator.run_nl_workflow("tell me a joke")
    assert record.status == "no_match"
    assert record.final_response["results"] == []


# --- Email pipeline: Stage 2 only, requires a live LLM (no DB/Graph needed) --


@requires_openai
@pytest.mark.asyncio
async def test_email_pipeline_stops_at_validation_when_record_is_blocked(in_process_httpx):
    """Real end-to-end: the real CrewAI orchestrator agent (orchestrator_agent.py)
    calls the real Validator Agent crew, sees is_valid=False for an
    out-of-scope doc_type, and must decide on its own not to call
    extraction-agent -- concluding final_status="blocked" as its own task
    output rather than via any separate decision mechanism."""
    await registry.discover()
    intake_record = {
        "message_id": "msg-1",
        "conversation_id": "conv-1",
        "from_email": "ap@supplier.com",
        "subject": "Purchase Order 42",
        "body_text": "See attached PO.",
        "doc_type": "purchase_order",  # out of scope for this pipeline -> validator should block it
        "is_erp_relevant": True,
        "is_pipeline_scope": False,
        "attachments": [],
        "received_at": "",
    }
    record = await orchestrator.run_email_pipeline(intake_record)

    assert record.kind == "email_pipeline"
    assert record.status == "blocked"
    agent_sequence = [step["agentId"] for step in record.steps]
    assert agent_sequence == ["email-intake-agent", "validator-agent"]  # never called extraction-agent
    assert record.steps[1]["status"] == "completed"
    assert record.steps[1]["data"]["is_valid"] is False


@pytest.mark.asyncio
async def test_finish_from_recorded_steps_uses_real_push_data_not_crew_summary(monkeypatch):
    """Offline (no OPENAI_API_KEY needed): ground truth for the final status
    comes from the real recorded erp-push-agent step, not from whatever the
    crew claims -- even a crew that (wrongly) says "success" gets overridden
    by a real recorded failure.

    "PO Number not found!" classifies as invalid_po, not invalid_item, so
    the supervisor's self-correction loop must report attempted=False here
    -- mocked rather than left to a real (offline-unreachable) MCP call, to
    keep this test's existing offline guarantee.
    """
    from client.orchestrator.orchestrator import WorkflowRecord
    from client.orchestrator.orchestrator_agent import OrchestrationResult

    monkeypatch.setattr(orchestrator, "attempt_self_correction", _fake_self_correction_not_applicable)

    record = WorkflowRecord(
        workflow_id="wf-test", user_text="x", mode="sequential", status="running", started_at="now", kind="email_pipeline"
    )
    record.steps = [
        {"agentId": orchestrator.EMAIL_INTAKE_AGENT, "status": "completed", "data": {}},
        {"agentId": orchestrator.VALIDATOR_AGENT, "status": "completed", "data": {"is_valid": True}},
        {"agentId": orchestrator.EXTRACTION_AGENT, "status": "completed", "data": {"src_id": "src_42", "target_erp": "EBS"}},
        {"agentId": orchestrator.ERP_PUSH_AGENT, "status": "completed", "data": {"status": "error", "message": "PO Number not found!"}},
    ]
    # The crew (wrongly, or just optimistically) claims success -- must be overridden.
    parsed = OrchestrationResult(final_status="success", summary="crew thinks it worked")

    result = await orchestrator._finish_from_recorded_steps(record, parsed)

    assert result.status == "failed"
    assert "PO Number not found" in result.final_response["summary"]
    self_correction_step = next(s for s in record.steps if s["agentId"] == "self-correction")
    assert self_correction_step["data"]["attempted"] is False


@pytest.mark.asyncio
async def test_finish_from_recorded_steps_reports_real_success():
    from client.orchestrator.orchestrator import WorkflowRecord
    from client.orchestrator.orchestrator_agent import OrchestrationResult

    record = WorkflowRecord(
        workflow_id="wf-test", user_text="x", mode="sequential", status="running", started_at="now", kind="email_pipeline"
    )
    record.steps = [
        {"agentId": orchestrator.EMAIL_INTAKE_AGENT, "status": "completed", "data": {}},
        {"agentId": orchestrator.VALIDATOR_AGENT, "status": "completed", "data": {"is_valid": True}},
        {"agentId": orchestrator.EXTRACTION_AGENT, "status": "completed", "data": {"src_id": "src_42", "target_erp": "EBS"}},
        {"agentId": orchestrator.ERP_PUSH_AGENT, "status": "completed", "data": {"status": "success", "message": "Invoice posted"}},
    ]
    parsed = OrchestrationResult(final_status="success", summary="posted")

    result = await orchestrator._finish_from_recorded_steps(record, parsed)

    assert result.status == "success"


@pytest.mark.asyncio
async def test_finish_from_recorded_steps_falls_back_to_crew_summary_when_no_push_happened():
    """No erp-push-agent step at all (e.g. the crew stopped at validation) --
    there's no real ERP outcome to independently verify, so the crew's own
    final_status/summary is trusted for that case only."""
    from client.orchestrator.orchestrator import WorkflowRecord
    from client.orchestrator.orchestrator_agent import OrchestrationResult

    record = WorkflowRecord(
        workflow_id="wf-test", user_text="x", mode="sequential", status="running", started_at="now", kind="email_pipeline"
    )
    record.steps = [
        {"agentId": orchestrator.EMAIL_INTAKE_AGENT, "status": "completed", "data": {}},
        {"agentId": orchestrator.VALIDATOR_AGENT, "status": "completed", "data": {"is_valid": False}},
    ]
    parsed = OrchestrationResult(final_status="blocked", summary="validation failed")

    result = await orchestrator._finish_from_recorded_steps(record, parsed)

    assert result.status == "blocked"
    assert result.final_response["summary"] == "validation failed"


# --- Supervisor self-correction loop -----------------------------------------


@pytest.mark.asyncio
async def test_self_correction_fixes_invalid_item_and_run_succeeds(monkeypatch):
    """An 'item not found' rejection that the self-correction loop manages
    to fix and successfully re-push must resolve the run as a real success
    -- never reaching (or needing) exception_handling.py at all."""
    from client.orchestrator.orchestrator import WorkflowRecord
    from client.orchestrator.orchestrator_agent import OrchestrationResult

    monkeypatch.setattr(orchestrator, "attempt_self_correction", _fake_self_correction_success)

    record = WorkflowRecord(
        workflow_id="wf-test", user_text="x", mode="sequential", status="running", started_at="now", kind="email_pipeline"
    )
    record.steps = [
        {"agentId": orchestrator.EMAIL_INTAKE_AGENT, "status": "completed", "data": {}},
        {
            "agentId": orchestrator.VALIDATOR_AGENT,
            "status": "completed",
            "data": {"is_valid": True, "encoded_image_paths": ["page_1.png"], "mapping_path": "mapping.xlsx"},
        },
        {"agentId": orchestrator.EXTRACTION_AGENT, "status": "completed", "data": {"src_id": "src_42", "target_erp": "EBS"}},
        {
            "agentId": orchestrator.ERP_PUSH_AGENT,
            "status": "completed",
            "data": {"status": "error", "message": "Item not found!:WIDGET-X"},
        },
    ]
    parsed = OrchestrationResult(final_status="failed", summary="crew saw the push fail")

    result = await orchestrator._finish_from_recorded_steps(record, parsed)

    assert result.status == "success"
    self_correction_step = next(s for s in record.steps if s["agentId"] == "self-correction")
    assert self_correction_step["status"] == "completed"
    assert self_correction_step["data"]["changed"] is True
    assert not any(s["agentId"] == "exception-handler" for s in record.steps)


@pytest.mark.asyncio
async def test_self_correction_not_applicable_falls_through_to_exception_handling(monkeypatch):
    """A non-invalid_item rejection (e.g. duplicate_invoice) must report
    attempted=False and fall straight through to the existing
    exception-handling sequence, exactly as before self-correction existed."""
    from client.orchestrator.orchestrator import WorkflowRecord
    from client.orchestrator.orchestrator_agent import OrchestrationResult

    monkeypatch.setattr(orchestrator, "attempt_self_correction", _fake_self_correction_not_applicable)

    record = WorkflowRecord(
        workflow_id="wf-test", user_text="x", mode="sequential", status="running", started_at="now", kind="email_pipeline"
    )
    record.steps = [
        {"agentId": orchestrator.EMAIL_INTAKE_AGENT, "status": "completed", "data": {}},
        {"agentId": orchestrator.VALIDATOR_AGENT, "status": "completed", "data": {"is_valid": True}},
        {"agentId": orchestrator.EXTRACTION_AGENT, "status": "completed", "data": {"src_id": "src_42", "target_erp": "EBS"}},
        {
            "agentId": orchestrator.ERP_PUSH_AGENT,
            "status": "completed",
            "data": {"status": "error", "message": "Invoice Number Already Exists for this Supplier !"},
        },
    ]
    parsed = OrchestrationResult(final_status="failed", summary="crew saw the push fail")

    result = await orchestrator._finish_from_recorded_steps(record, parsed)

    assert result.status == "failed"
    self_correction_step = next(s for s in record.steps if s["agentId"] == "self-correction")
    assert self_correction_step["data"]["attempted"] is False
    assert any(s["agentId"] == "exception-handler" for s in record.steps)

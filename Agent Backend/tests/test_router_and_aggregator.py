"""Task routing (Agent Card understanding + agent selection) and response
aggregation, tested without any network calls or LLM.

Routing is a lightweight, best-effort keyword matcher used only for the
ad-hoc chat feature -- the real email pipeline (`run_email_pipeline`) calls
Agent 2/3/4 by fixed id and never goes through this router, so these tests
check "the expected agent is among the matches" rather than exact single-
agent precision.
"""
import json
from pathlib import Path

from client.a2a_client.client import AgentCallResult
from client.agent_registry.registry import AgentRegistry, RegisteredAgent
from client.response_aggregator.aggregator import aggregate
from client.task_router.router import route
from shared.a2a_protocol.helpers import completed_task, failed_task
from shared.a2a_protocol.schemas import AgentCard

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def _load_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for name, port in [("agent_1", 8001), ("agent_2", 8002), ("agent_3", 8003), ("agent_4", 8004)]:
        card_path = AGENTS_DIR / name / "agent_card.json"
        card = AgentCard(**json.loads(card_path.read_text()))
        registry.agents[card.id] = RegisteredAgent(card=card, base_url=f"http://localhost:{port}")
    return registry


def test_route_validation_request_includes_validator_agent():
    registry = _load_registry()
    calls = route(registry, "Validate this intake record for ERP processing")
    agent_ids = {call.agent_id for call in calls}
    assert "validator-agent" in agent_ids


def test_route_ebs_request_includes_erp_push_agent():
    registry = _load_registry()
    calls = route(registry, "Push this invoice to EBS")
    agent_ids = {call.agent_id for call in calls}
    assert "erp-push-agent" in agent_ids


def test_route_no_match_returns_empty():
    registry = _load_registry()
    calls = route(registry, "what's the weather like today")
    assert calls == []


def test_aggregate_all_success():
    task = completed_task("ctx-1", "validate_intake_record", {"is_valid": True}, history=[], metadata={"skillUsed": "validate_intake_record"})
    result = AgentCallResult("validator-agent", "validate this record", task, None, 12.3)
    aggregated = aggregate([result])
    assert aggregated.overall_status == "success"
    assert aggregated.results[0]["data"] == {"is_valid": True}
    assert aggregated.results[0]["skillUsed"] == "validate_intake_record"


def test_aggregate_partial_failure_attributes_error_to_correct_agent():
    ok_task = completed_task("ctx-1", "validate_intake_record", {"is_valid": True}, history=[], metadata={"skillUsed": "validate_intake_record"})
    ok_result = AgentCallResult("validator-agent", "validate", ok_task, None, 10.0)
    failed_result = AgentCallResult("extraction-agent", "extract invoice", None, "Communication with agent failed", 5000.0)

    aggregated = aggregate([ok_result, failed_result])
    assert aggregated.overall_status == "partial"
    statuses = {r["agentId"]: r["status"] for r in aggregated.results}
    assert statuses["validator-agent"] == "completed"
    assert statuses["extraction-agent"] == "failed"


def test_aggregate_all_failed():
    task = failed_task("ctx-1", "Invoice not found", history=[])
    result = AgentCallResult("extraction-agent", "extract invoice", task, None, 8.0)
    aggregated = aggregate([result])
    assert aggregated.overall_status == "failed"
    assert aggregated.results[0]["error"] == "Invoice not found"


def test_aggregate_no_calls_is_no_match():
    aggregated = aggregate([])
    assert aggregated.overall_status == "no_match"

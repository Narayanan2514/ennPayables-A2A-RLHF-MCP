"""client/orchestrator/orchestrator_agent.py's CallAgentTool: the one tool
the supervisor CrewAI agent can call. No LLM/OpenAI needed here -- these
call `tool._run(...)` directly, the same way CrewAI would after parsing the
model's chosen arguments, to test the tool's own dispatch and payload_store
handling in isolation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from client.a2a_client.client import AgentCallResult
from client.agent_registry.registry import AgentRegistry, RegisteredAgent
from client.orchestrator.orchestrator_agent import CallAgentTool
from shared.a2a_protocol.schemas import AgentCard, Artifact, Part, PartKind, Task, TaskState, TaskStatus
from shared.crew.payload_store import PayloadStore


def _agent_card(agent_id: str) -> AgentCard:
    return AgentCard(
        id=agent_id, name=agent_id, description="test", version="1.0.0", url=f"http://localhost/{agent_id}",
        protocolVersion="0.3.0-ennvault",
        capabilities={"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        skills=[],
    )


@dataclass
class _FakeWorkflowRecord:
    steps: list[dict[str, Any]] = field(default_factory=list)


def _completed_task(data: dict) -> Task:
    return Task(
        contextId="ctx-1",
        status=TaskStatus(state=TaskState.COMPLETED),
        artifacts=[Artifact(name="skill", parts=[Part(kind=PartKind.DATA, data=data)])],
        history=[],
    )


class _CallTracker:
    last_call: dict[str, Any] | None = None


def _make_tool(
    registry: AgentRegistry, monkeypatch, call_result: AgentCallResult
) -> tuple[CallAgentTool, _FakeWorkflowRecord, PayloadStore, _CallTracker]:
    record = _FakeWorkflowRecord()
    payload_store = PayloadStore()
    tool = CallAgentTool()
    tool.record = record
    tool.registry = registry
    tool.payload_store = payload_store

    tracker = _CallTracker()

    async def fake_call_agent_task(agent_id, base_url, task_text, data=None, **kwargs):
        tracker.last_call = {"agent_id": agent_id, "base_url": base_url, "task_text": task_text, "data": data}
        return call_result

    monkeypatch.setattr("client.orchestrator.orchestrator_agent.call_agent_task", fake_call_agent_task)
    return tool, record, payload_store, tracker


def test_unknown_agent_id_is_refused_without_calling_anything(monkeypatch):
    registry = AgentRegistry()
    registry.agents = {"validator-agent": RegisteredAgent(card=_agent_card("validator-agent"), base_url="http://x")}
    call_result = AgentCallResult("x", "x", _completed_task({}), None, 1.0)
    tool, record, _, _ = _make_tool(registry, monkeypatch, call_result)

    result = json.loads(tool._run(agent_id="not-a-real-agent", task_text="do something"))

    assert "error" in result
    assert "not-a-real-agent" in result["error"]
    assert record.steps == []  # never even attempted a call


def test_successful_call_records_step_and_returns_result_payload_key(monkeypatch):
    registry = AgentRegistry()
    registry.agents = {"validator-agent": RegisteredAgent(card=_agent_card("validator-agent"), base_url="http://x")}
    real_result = {"is_valid": True, "verdict": "pass"}
    call_result = AgentCallResult("validator-agent", "x", _completed_task(real_result), None, 12.5)
    tool, record, payload_store, _ = _make_tool(registry, monkeypatch, call_result)

    result = json.loads(tool._run(agent_id="validator-agent", task_text="validate this"))

    assert result["status"] == "completed"
    assert result["result"] == real_result
    assert record.steps[-1]["status"] == "completed"
    assert record.steps[-1]["data"] == real_result

    # The result_payload_key must resolve back to the REAL result -- not
    # anything the LLM produced -- when forwarded on a later call.
    stored = payload_store.pop(result["result_payload_key"])
    assert stored == real_result


def test_forward_payload_key_is_resolved_and_passed_as_real_data(monkeypatch):
    registry = AgentRegistry()
    registry.agents = {"extraction-agent": RegisteredAgent(card=_agent_card("extraction-agent"), base_url="http://x")}
    call_result = AgentCallResult("extraction-agent", "x", _completed_task({"src_id": "src_1"}), None, 1.0)
    tool, record, payload_store, tracker = _make_tool(registry, monkeypatch, call_result)

    real_validation = {"is_valid": True, "verdict": "pass"}
    key = payload_store.put(real_validation)

    tool._run(agent_id="extraction-agent", task_text="extract this", forward_payload_key=key)

    # The exact real dict must have been forwarded as `data=`, never
    # anything the LLM typed out itself.
    assert tracker.last_call["data"] is real_validation
    # And the key is consumed (popped), same as every other payload_store use in this codebase.
    assert payload_store.pop(key) is None


def test_failed_task_is_reported_without_crashing(monkeypatch):
    registry = AgentRegistry()
    registry.agents = {"validator-agent": RegisteredAgent(card=_agent_card("validator-agent"), base_url="http://x")}
    call_result = AgentCallResult("validator-agent", "x", None, "connection refused", 1.0)
    tool, record, _, _ = _make_tool(registry, monkeypatch, call_result)

    result = json.loads(tool._run(agent_id="validator-agent", task_text="validate this"))

    assert result["status"] == "failed"
    assert "connection refused" in result["error"]
    assert record.steps[-1]["status"] == "failed"

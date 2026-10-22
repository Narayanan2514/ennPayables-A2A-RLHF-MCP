"""client/orchestrator/email_polling.py: the supervisor's own mailbox
polling + valid/invalid classification + per-message A2A dispatch.

Mocks Graph (no real mailbox) and call_agent_task (no real Agent 1 crew/LLM)
-- this tests the classify-then-route decision, not Agent 1's executor,
which is exercised separately (test_agent_cards.py's schema check, and
Agent 1's own service-layer tests in test_agent_execution.py).
"""
from __future__ import annotations

import pytest

from client.a2a_client.client import AgentCallResult
from client.agent_registry.registry import AgentRegistry, RegisteredAgent
from client.orchestrator import email_polling
from shared.a2a_protocol.schemas import Artifact, Part, PartKind, Task, TaskStatus, TaskState
from shared.a2a_protocol.schemas import AgentCard


def _agent_card() -> AgentCard:
    return AgentCard(
        id="email-intake-agent",
        name="Email Intake Agent",
        description="test",
        version="2.0.0",
        url="http://localhost:8001",
        protocolVersion="0.3.0-ennvault",
        capabilities={"streaming": False, "pushNotifications": False, "stateTransitionHistory": True},
        skills=[],
    )


def _completed_result(agent_id: str, task_text: str, data: dict) -> AgentCallResult:
    task = Task(
        contextId="ctx-1",
        status=TaskStatus(state=TaskState.COMPLETED),
        artifacts=[Artifact(name="skill", parts=[Part(kind=PartKind.DATA, data=data)])],
        history=[],
    )
    return AgentCallResult(agent_id=agent_id, task_text=task_text, task=task, error=None, duration_ms=1.0)


@pytest.fixture(autouse=True)
def _register_agent1():
    email_polling.registry.agents = {"email-intake-agent": RegisteredAgent(card=_agent_card(), base_url="http://localhost:8001")}
    yield
    email_polling.registry.agents = {}


@pytest.mark.asyncio
async def test_valid_email_dispatches_to_process_and_returns_its_record(monkeypatch):
    monkeypatch.setattr(email_polling.graph_client, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        email_polling.graph_client,
        "fetch_unread_emails",
        lambda token: [
            {
                "id": "msg-1",
                "subject": "Invoice #123",
                "from": {"emailAddress": {"address": "ap@supplier.com"}},
                "body": {"content": "<p>see attached</p>"},
                "conversationId": "conv-1",
                "receivedDateTime": "2026-01-01T00:00:00Z",
            }
        ],
    )

    calls = []

    async def fake_call_agent_task(agent_id, base_url, task_text, data=None, **kwargs):
        calls.append((task_text, data))
        return _completed_result(agent_id, task_text, {"message_id": "msg-1", "is_pipeline_scope": True, "attachments": []})

    monkeypatch.setattr(email_polling, "call_agent_task", fake_call_agent_task)

    records = await email_polling.poll_and_dispatch()

    assert len(calls) == 1
    task_text, data = calls[0]
    assert "process" in task_text.lower()
    assert data["message_id"] == "msg-1"
    assert data["doc_type"] == "invoice"
    assert records == [{"message_id": "msg-1", "is_pipeline_scope": True, "attachments": []}]


@pytest.mark.asyncio
async def test_invalid_email_dispatches_to_mark_invalid_and_yields_no_record(monkeypatch):
    monkeypatch.setattr(email_polling.graph_client, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        email_polling.graph_client,
        "fetch_unread_emails",
        lambda token: [{"id": "msg-2", "subject": "PO 555 confirmation", "from": {}, "body": {}, "conversationId": "", "receivedDateTime": ""}],
    )

    calls = []

    async def fake_call_agent_task(agent_id, base_url, task_text, data=None, **kwargs):
        calls.append((task_text, data))
        return _completed_result(agent_id, task_text, {"message_id": "msg-2", "marked_read": True})

    monkeypatch.setattr(email_polling, "call_agent_task", fake_call_agent_task)

    records = await email_polling.poll_and_dispatch()

    assert len(calls) == 1
    task_text, data = calls[0]
    assert "invalid" in task_text.lower() or "read" in task_text.lower()
    assert data == {"message_id": "msg-2"}
    assert records == []


@pytest.mark.asyncio
async def test_returns_empty_when_agent1_not_registered(monkeypatch):
    email_polling.registry.agents = {}
    records = await email_polling.poll_and_dispatch()
    assert records == []

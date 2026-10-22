"""Convenience builders for A2A messages and tasks, used by both the
orchestrator (building requests) and the agents (building responses).

Each agent is now a CrewAI crew that reasons over natural-language task text
and picks its own tool -- so the A2A message carries a plain instruction
(TextPart) rather than a pre-parsed {skillId, input} payload. Which tool
actually ran is only known after execution, and travels back on the Task
(artifact name + `skillUsed` metadata).
"""
from __future__ import annotations

from typing import Any

from .schemas import Artifact, Message, Part, PartKind, Role, Task, TaskState, TaskStatus


def build_task_message(
    task_text: str,
    context_id: str | None = None,
    data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """Builds the A2A user Message that asks an agent's crew to handle a
    natural-language request.

    `data`, when given, rides along as a DataPart -- structured content the
    agent's *executor* can read directly (no LLM involved), as opposed to
    `task_text`, which the agent's crew reasons over to pick a tool and
    arguments. This matters because CrewAI's tool-call argument parser is a
    ReAct-style text parser (not native OpenAI function calling): it's
    unreliable at reproducing large or nested JSON as an "Action Input"
    value, so large structured payloads travel here instead of inside the
    text the LLM has to transcribe.
    """
    parts = [Part(kind=PartKind.TEXT, text=task_text)]
    if data is not None:
        parts.append(Part(kind=PartKind.DATA, data=data))
    return Message(
        role=Role.USER,
        parts=parts,
        contextId=context_id,
        metadata=metadata or {},
    )


def extract_task_text(message: Message) -> str:
    """Concatenates every TextPart in an inbound A2A message into the
    instruction the agent's crew should act on."""
    texts = [part.text for part in message.parts if part.kind == PartKind.TEXT and part.text]
    return "\n".join(t.strip() for t in texts if t).strip()


def extract_task_data(message: Message) -> dict[str, Any] | None:
    """Pulls the DataPart (if any) out of an inbound A2A message -- the
    structured payload the executor reads directly, bypassing the LLM."""
    for part in message.parts:
        if part.kind == PartKind.DATA and part.data is not None:
            return part.data
    return None


def completed_task(
    context_id: str,
    artifact_name: str,
    result: dict[str, Any],
    history: list[Message],
    metadata: dict[str, Any] | None = None,
) -> Task:
    agent_message = Message(
        role=Role.AGENT,
        parts=[Part(kind=PartKind.TEXT, text=f"{artifact_name} completed successfully.")],
        contextId=context_id,
    )
    return Task(
        contextId=context_id,
        status=TaskStatus(state=TaskState.COMPLETED, message=agent_message),
        artifacts=[Artifact(name=artifact_name, parts=[Part(kind=PartKind.DATA, data=result)])],
        history=history + [agent_message],
        metadata=metadata or {},
    )


def failed_task(
    context_id: str,
    reason: str,
    history: list[Message],
    error_code: str = "ERP_OPERATION_FAILED",
) -> Task:
    agent_message = Message(role=Role.AGENT, parts=[Part(kind=PartKind.TEXT, text=reason)], contextId=context_id)
    return Task(
        contextId=context_id,
        status=TaskStatus(state=TaskState.FAILED, message=agent_message),
        artifacts=[],
        history=history + [agent_message],
        metadata={"errorCode": error_code},
    )

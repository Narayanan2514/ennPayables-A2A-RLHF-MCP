"""Thin async A2A client used by the orchestrator to call agents over HTTP.

This is the ONLY place in the client that speaks the wire protocol to an
agent. It builds a JSON-RPC `message/send` request carrying a natural-
language task instruction, posts it to the agent's `/a2a/message`
endpoint, and returns a structured result the orchestrator can reason about
(including on network/timeout failures). Which tool the agent's crew
actually picked is only known afterwards, via `task.metadata['skillUsed']`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from shared.a2a_protocol.helpers import build_task_message
from shared.a2a_protocol.schemas import JSONRPCRequest, Task
from shared.config.settings import AGENT_MAX_RETRIES, AGENT_REQUEST_TIMEOUT_SECONDS
from shared.utilities.logging import get_logger

logger = get_logger("client.a2a_client")


@dataclass
class AgentCallResult:
    agent_id: str
    task_text: str
    task: Optional[Task]
    error: Optional[str]
    duration_ms: float


async def call_agent_task(
    agent_id: str,
    base_url: str,
    task_text: str,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> AgentCallResult:
    """Invokes one agent's crew with a natural-language instruction, plus an
    optional structured `data` payload the agent's executor reads directly
    (bypassing the LLM -- see `build_task_message`'s docstring for why).
    `client` can be injected for testing (e.g. an httpx.AsyncClient wired to
    an ASGITransport) -- production code leaves it unset."""
    message = build_task_message(task_text, context_id=context_id, data=data)
    request = JSONRPCRequest(method="message/send", params={"message": message.model_dump(mode="json")})

    loop = asyncio.get_event_loop()
    started = loop.time()
    last_error: str | None = None
    owns_client = client is None

    for attempt in range(AGENT_MAX_RETRIES + 1):
        active_client = client or httpx.AsyncClient(timeout=AGENT_REQUEST_TIMEOUT_SECONDS)
        try:
            response = await active_client.post(f"{base_url}/a2a/message", json=request.model_dump(mode="json"))
            response.raise_for_status()
            body = response.json()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Attempt %s/%s to call agent %s failed: %s", attempt + 1, AGENT_MAX_RETRIES + 1, agent_id, last_error
            )
            continue
        finally:
            if owns_client:
                await active_client.aclose()

        duration_ms = round((loop.time() - started) * 1000, 1)
        if body.get("error"):
            return AgentCallResult(agent_id, task_text, None, body["error"].get("message", "Unknown agent error"), duration_ms)

        task = Task(**body["result"])
        return AgentCallResult(agent_id, task_text, task, None, duration_ms)

    duration_ms = round((loop.time() - started) * 1000, 1)
    return AgentCallResult(agent_id, task_text, None, last_error or "Unknown communication failure", duration_ms)

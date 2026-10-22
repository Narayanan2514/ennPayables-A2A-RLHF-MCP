"""Agent Executor for the ERP Push Agent.

Independent from Agent 1 / Agent 2 / Agent 3's executors -- it owns a single
CrewAI Agent (built from `agent_definition.build_agent`, with only Agent 4's
tools) wrapped in a one-task Crew.
"""
from __future__ import annotations

import asyncio

from crewai import Crew, Process
from crewai import Task as CrewTask

from shared.a2a_protocol.helpers import completed_task, extract_task_data, extract_task_text, failed_task
from shared.a2a_protocol.schemas import Message, Task
from shared.crew.schemas import ToolResultOutput
from shared.utilities.logging import get_logger

from .agent_definition import build_agent
from ..skills.tools import payload_store

logger = get_logger("agent_4.executor")


class Agent4Executor:
    agent_id = "erp-push-agent"

    def __init__(self) -> None:
        self._crew_agent = build_agent()

    async def execute(self, message: Message) -> Task:
        context_id = message.contextId or "ctx-unknown"
        history = [message]
        task_text = extract_task_text(message)

        if not task_text:
            return failed_task(context_id, "No task text found in the message payload.", history, "VALIDATION_FAILED")

        task_data = extract_task_data(message)
        payload_key: str | None = None
        if task_data is not None:
            payload_key = payload_store.put(task_data)
            task_text = (
                f'{task_text}\n\nWhen you call your tool, pass payload_key="{payload_key}" exactly as written '
                "-- do not omit it, and do not invent a different value."
            )

        try:
            return await self._run_crew(context_id, task_text, history)
        finally:
            if payload_key is not None:
                payload_store.discard(payload_key)

    async def _run_crew(self, context_id: str, task_text: str, history: list[Message]) -> Task:
        crew_task = CrewTask(
            description=(
                f'Handle this ERP-push request from a colleague: "{task_text}"\n'
                "Call exactly one of your tools with arguments extracted from the request, then report its raw result."
            ),
            expected_output="A JSON object with fields skill_used, success, data, error -- exactly what the tool returned.",
            agent=self._crew_agent,
            output_pydantic=ToolResultOutput,
        )
        crew = Crew(agents=[self._crew_agent], tasks=[crew_task], process=Process.sequential, verbose=False)

        try:
            crew_output = await asyncio.to_thread(crew.kickoff)
        except Exception as exc:
            logger.exception("Crew execution failed")
            return failed_task(context_id, f"Crew execution failed: {exc}", history, "INTERNAL_ERROR")

        parsed: ToolResultOutput | None = crew_output.pydantic
        if parsed is None:
            return failed_task(
                context_id, f"Could not parse crew output as structured JSON: {crew_output.raw}", history, "INTERNAL_ERROR"
            )

        if not parsed.success:
            return failed_task(context_id, parsed.error or "ERP push operation failed.", history, "OPERATION_FAILED")

        return completed_task(context_id, parsed.skill_used, parsed.data or {}, history, metadata={"skillUsed": parsed.skill_used})

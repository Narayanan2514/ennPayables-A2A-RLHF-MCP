"""Dynamic, LLM-driven orchestration for the email-to-ERP pipeline.

Unlike a hardcoded "call Agent 2, then Agent 3, then Agent 4" Python
function, this builds a CrewAI orchestrator agent whose only tool is
`call_agent` -- calling any discovered agent by id with a task and,
optionally, previously-stored structured data. The orchestrator's own crew
decides, turn by turn, which agent to call next based on what the previous
call actually returned, using the exact same A2A client
(`client/a2a_client/client.py`) every other caller in this codebase uses.

This is still 100% client-side orchestration -- agents never call each
other, only the client calls agents -- only the *sequencing decision*
moved from Python control flow into the orchestrator's own reasoning.

NOTE: no `from __future__ import annotations` in this file. CrewAI's
`generate_model_description` (used for `Task(output_pydantic=...)`) reads
`model.__annotations__` directly and expects real type objects, not the
stringified annotations PEP 563 would produce -- see shared/crew/schemas.py
for the incident this caused.
"""
import asyncio
import json
from typing import Any

from crewai import Agent
from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ..a2a_client.client import call_agent_task
from ..agent_registry.registry import AgentRegistry
from shared.crew.llm import build_llm
from shared.crew.payload_store import PayloadStore
from shared.db import workflow_session_repo as session_repo
from shared.utilities.logging import get_logger

logger = get_logger("client.orchestrator.orchestrator_agent")


class OrchestrationResult(BaseModel):
    final_status: str  # "success" | "blocked" | "failed"
    summary: str


def describe_session_context(session: dict[str, Any] | None) -> str:
    """The planner's read-only view of durable session state (DB is the
    source of truth for recovery, never the planner's own memory of a prior
    turn) -- prepended to the crew task description in orchestrator.py so
    the planner can make an informed recovery decision without ever being
    handed a hardcoded Agent 2 -> 3 -> 4 script."""
    if not session:
        return ""
    lines = [
        "Durable workflow session context (from the database -- the source of truth for recovery; read-only, "
        "informational -- you still decide the next agent call dynamically from what each call actually returns):",
        f"- session_id: {session.get('session_id')}",
        f"- status: {session.get('status')}",
        f"- current_step: {session.get('current_step')}",
        f"- retry_count: {session.get('retry_count')}",
        f"- worker_id: {session.get('worker_id')}",
    ]
    if (session.get("retry_count") or 0) > 0:
        lines.append(
            f"- This session is RESUMING after a prior failure at current_step={session.get('current_step')}. Do "
            "not restart the whole pipeline from the beginning -- pick up from that step based on what any "
            "already-completed agents in this run actually returned."
        )
    return "\n".join(lines) + "\n\n"


def describe_available_agents(registry: AgentRegistry) -> str:
    """The orchestrator's view of what it can call -- read live from each
    agent's Agent Card at call time, never hardcoded, so it stays accurate
    as agents' capabilities change."""
    lines = []
    for agent in registry.list_agents():
        skill_bits = "; ".join(f"{s.id} ({s.description})" for s in agent.card.skills)
        lines.append(f"- {agent.card.id}: {agent.card.description} Skills: {skill_bits}")
    return "\n".join(lines) if lines else "(no agents discovered)"


class CallAgentArgs(BaseModel):
    agent_id: str = Field(..., description="The id of the agent to call, exactly as listed in your available agents, e.g. 'validator-agent'.")
    task_text: str = Field(..., description="The natural-language instruction to send to that agent.")
    # A plain string, never Optional[str]/None, on purpose -- see the note
    # in agents/agent_4/skills/tools.py::BuildEbsDocumentArgs for why
    # (CrewAI's ast.literal_eval-based Action Input parser has a failure
    # mode specifically triggered by fields the model would set to null).
    forward_payload_key: str = Field(
        "",
        description=(
            "A payload_key you were given by an EARLIER call_agent result (e.g. an attachments_key from the "
            "task, or a result_payload_key from a previous agent's output) that this call's target agent needs "
            "as structured data. Copy it exactly. Leave as an empty string if this call needs no attached data "
            "-- never pass null."
        ),
    )


class CallAgentTool(BaseTool):
    """Constructed fresh per pipeline run (see orchestrator.py:run_email_pipeline)
    so each run gets its own WorkflowRecord and PayloadStore -- never shared
    across concurrent runs."""

    name: str = "call_agent"
    description: str = (
        "Calls one agent in the pipeline by id with a task, optionally forwarding structured data via a "
        "payload_key from an earlier result. Returns that agent's status and result, plus a fresh "
        "result_payload_key you can forward into a later call if a downstream agent needs this result's data."
    )
    args_schema: type[BaseModel] = CallAgentArgs
    model_config = ConfigDict(arbitrary_types_allowed=True)

    record: Any = None
    registry: Any = None
    payload_store: Any = None

    # Durable-session wiring (client/orchestrator/orchestrator.py sets both
    # before handing this tool to the crew). `session_id` may be None (e.g.
    # a chat/structured workflow has no durable session) -- every session
    # update below is a no-op in that case. `next_step_map` is {agent_id:
    # the workflow_session.current_step value to advance to once THAT
    # agent's call completes} -- kept as data the caller supplies rather
    # than agent-id constants hardcoded here, so this tool stays usable for
    # any pipeline shape, not just the 4-agent invoice one.
    session_id: Any = None
    next_step_map: Any = None

    def _run(self, agent_id: str, task_text: str, forward_payload_key: str = "") -> str:
        agent = self.registry.get_agent(agent_id)
        if not agent:
            known = ", ".join(self.registry.agents.keys())
            return json.dumps({"error": f"Unknown agent_id '{agent_id}'. Known agents: {known}"})

        data = self.payload_store.pop(forward_payload_key) if forward_payload_key else None

        step = {"agentId": agent_id, "taskText": task_text, "status": "running"}
        self.record.steps.append(step)

        # asyncio.run is safe here: CrewAI tool _run() executes inside the
        # worker thread asyncio.to_thread(crew.kickoff) spawned in
        # run_email_pipeline, which has no event loop of its own.
        result = asyncio.run(call_agent_task(agent_id, agent.base_url, task_text, data=data))

        step["status"] = "completed" if result.task and result.task.status.state == "completed" else "failed"
        step["durationMs"] = result.duration_ms
        if result.task is not None:
            step["skillUsed"] = result.task.metadata.get("skillUsed")

        if step["status"] != "completed":
            error_message = result.error
            if error_message is None and result.task is not None:
                message = result.task.status.message
                error_message = message.parts[0].text if message and message.parts else "Task failed"
            step["error"] = error_message
            if self.session_id:
                # Records the failure against whatever current_step the
                # session is already on -- it's only ever advanced below on
                # success, so it's always the step that just failed here.
                session_repo.fail_session(self.session_id)
            return json.dumps({"agentId": agent_id, "status": "failed", "error": error_message})

        artifact = result.task.artifacts[0] if result.task.artifacts else None
        result_data = artifact.parts[0].data if artifact and artifact.parts else {}
        step["data"] = result_data

        if self.session_id:
            if isinstance(result_data, dict) and result_data.get("src_id"):
                # The real source.src_id only exists once extraction has run
                # and inserted it -- swap out the session's creation-time
                # placeholder for it the moment any agent's result carries one.
                session_repo.set_src_id(self.session_id, str(result_data["src_id"]))
            next_step = (self.next_step_map or {}).get(agent_id)
            if next_step:
                session_repo.advance_step(self.session_id, next_step)

        result_payload_key = self.payload_store.put(result_data)
        return json.dumps(
            {
                "agentId": agent_id,
                "status": "completed",
                "skillUsed": step.get("skillUsed"),
                "result": result_data,
                "result_payload_key": result_payload_key,
            }
        )


def build_orchestrator_agent(registry: AgentRegistry, tool: BaseTool) -> Agent:
    return Agent(
        role="Email-to-ERP Pipeline Orchestrator",
        goal=(
            "Given one email intake record, decide which agents to call and in what order to get it correctly "
            "processed toward ERP submission -- based on what each agent actually reports back, not a fixed script."
        ),
        backstory=(
            "You coordinate a team of specialist agents for accounts-payable invoice processing:\n"
            f"{describe_available_agents(registry)}\n\n"
            "Standard practice is to validate a record before extracting it, and to extract it before building "
            "an ERP document from it -- but you decide the real sequence based on what each agent actually "
            "returns, not by following a fixed script. If a validation result says the record is not valid, "
            "stop and explain why instead of continuing anyway. If any agent call fails, stop and explain why "
            "instead of guessing at what it would have returned. Never fabricate a result an agent did not "
            "actually give you. When one agent's result needs to reach a later agent (for example, an "
            "extraction result a document-building agent needs), use the result_payload_key you were given and "
            "pass it as forward_payload_key on the later call -- never retype or reconstruct that data yourself.\n\n"
            "Your final_status must distinguish two different things: use \"blocked\" when an agent correctly "
            "did its job and its own result says this record should not proceed (e.g. a validator's verdict is "
            "\"block\", or is_valid is false) -- that is a normal, expected outcome, not an error. Use \"failed\" "
            "only when something actually went wrong while trying to process this record (an agent call itself "
            "errored, timed out, or returned status=\"failed\"). A clean validation block is \"blocked\", never "
            "\"failed\"."
        ),
        tools=[tool],
        llm=build_llm(),
        allow_delegation=False,
        max_iter=15,
        max_retry_limit=5,
        verbose=False,
    )

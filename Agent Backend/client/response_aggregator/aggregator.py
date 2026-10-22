"""Merges the results of one or more agent invocations into a single
structured response for the frontend, clearly attributing success/failure
and the tool actually used to the agent that produced it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..a2a_client.client import AgentCallResult


@dataclass
class AggregatedResult:
    overall_status: str
    results: list[dict[str, Any]]
    summary: str


def aggregate(call_results: list[AgentCallResult]) -> AggregatedResult:
    results: list[dict[str, Any]] = []
    success_count = 0

    for call in call_results:
        if call.task is not None and call.task.status.state == "completed":
            success_count += 1
            artifact = call.task.artifacts[0] if call.task.artifacts else None
            data = artifact.parts[0].data if artifact and artifact.parts else None
            results.append(
                {
                    "agentId": call.agent_id,
                    "skillUsed": call.task.metadata.get("skillUsed"),
                    "status": "completed",
                    "durationMs": call.duration_ms,
                    "data": data,
                    "error": None,
                }
            )
        else:
            error_message = call.error
            skill_used = None
            if error_message is None and call.task is not None:
                message = call.task.status.message
                error_message = message.parts[0].text if message and message.parts else "Task failed"
                skill_used = call.task.metadata.get("skillUsed")
            results.append(
                {
                    "agentId": call.agent_id,
                    "skillUsed": skill_used,
                    "status": "failed",
                    "durationMs": call.duration_ms,
                    "data": None,
                    "error": error_message,
                }
            )

    if not call_results:
        overall_status, summary = "no_match", "No agent matched this request."
    elif success_count == len(call_results):
        overall_status, summary = "success", f"All {len(call_results)} agent call(s) completed successfully."
    elif success_count == 0:
        overall_status, summary = "failed", f"All {len(call_results)} agent call(s) failed."
    else:
        overall_status = "partial"
        summary = f"{success_count}/{len(call_results)} agent call(s) completed successfully."

    return AggregatedResult(overall_status=overall_status, results=results, summary=summary)

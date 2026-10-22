"""Write/read side of the agent_log trace table.

The orchestrator (agent.py) already assembles a `transcript` in memory for
its own return value, but supervisor_main.py's watchdog path never looks at
it beyond printing the final status -- so every step an unattended run took
was lost. This module gives that transcript a durable home, keyed by
(src_id, run_id), so the frontend's document detail page can show it later
as a trace regardless of whether the run was triggered by the API or the
folder-watcher supervisor.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from db.new_schema import AgentLog
from db.session import session_scope


def log_step(
    src_id: str,
    run_id: str,
    turn: int,
    step_type: str,
    tool_name: str | None = None,
    tool_input: Any = None,
    tool_output: Any = None,
    is_error: bool = False,
    message: str | None = None,
) -> None:
    with session_scope() as session:
        session.add(
            AgentLog(
                src_id=src_id,
                run_id=run_id,
                turn=turn,
                step_type=step_type,
                tool_name=tool_name,
                tool_input_json=json.dumps(tool_input, default=str) if tool_input is not None else None,
                tool_output_json=json.dumps(tool_output, default=str) if tool_output is not None else None,
                is_error=is_error,
                message=message,
            )
        )


def get_trace(src_id: str) -> list[dict[str, Any]]:
    """All logged steps for a src_id, oldest first, across every run.
    Group by `run_id` client-side to separate distinct process_document()
    invocations.
    """
    with session_scope() as session:
        rows = session.scalars(
            select(AgentLog).where(AgentLog.src_id == src_id).order_by(AgentLog.id.asc())
        ).all()
        return [
            {
                "run_id": r.run_id,
                "turn": r.turn,
                "step_type": r.step_type,
                "tool_name": r.tool_name,
                "tool_input": json.loads(r.tool_input_json) if r.tool_input_json else None,
                "tool_output": json.loads(r.tool_output_json) if r.tool_output_json else None,
                "is_error": r.is_error,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

"""Client / Orchestrator backend API (port 8000).

This is the only service that talks to all four agents: it owns discovery,
routing, execution and aggregation. Agents never call each other or this
API -- they are only ever called BY it. It also runs the autonomous email
pipeline watcher (see `client/orchestrator/orchestrator.py`), which drains
Agent 1's queue and drives each intake record through Agents 2-4.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from client.agent_registry.registry import registry
from client.orchestrator import orchestrator
from shared.config import settings
from shared.db import workflow_session_repo as session_repo
from shared.utilities.logging import get_logger

logger = get_logger("api.main")

_watcher_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _watcher_task
    await registry.discover()
    logger.info("Startup discovery complete: %s agent(s) registered, %s error(s)", len(registry.agents), len(registry.discovery_errors))
    orchestrator.recover_sessions_on_startup()
    _watcher_task = asyncio.create_task(orchestrator.watch_email_pipeline())
    try:
        yield
    finally:
        if _watcher_task:
            _watcher_task.cancel()


app = FastAPI(title="ennVault A2A Client / Orchestrator", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    text: str
    mode: Literal["auto", "sequential", "parallel"] = "auto"


class WorkflowStep(BaseModel):
    agentId: str
    taskText: str


class WorkflowRequest(BaseModel):
    steps: list[WorkflowStep]
    mode: Literal["auto", "sequential", "parallel"] = "parallel"


class ClaimSessionRequest(BaseModel):
    workerId: str | None = None


def _record_to_dict(record: orchestrator.WorkflowRecord) -> dict:
    return {
        "workflowId": record.workflow_id,
        "kind": record.kind,
        "title": record.title,
        "userText": record.user_text,
        "mode": record.mode,
        "status": record.status,
        "startedAt": record.started_at,
        "finishedAt": record.finished_at,
        "steps": record.steps,
        "finalResponse": record.final_response,
        "sessionId": record.session_id,
    }


def _session_to_dict(session: dict) -> dict:
    return {
        "sessionId": session["session_id"],
        "workerId": session.get("worker_id"),
        "srcId": session.get("src_id"),
        "status": session.get("status"),
        "currentStep": session.get("current_step"),
        "retryCount": session.get("retry_count"),
        "createdAt": session.get("created_at"),
        "statusAt": session.get("status_at"),
        "finishedAt": session.get("finished_at"),
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "client-orchestrator"}


@app.get("/api/config")
async def config() -> dict:
    # Single interval now -- the supervisor's poll -> classify -> dispatch ->
    # pipeline loop (client/orchestrator/email_polling.py) replaced the old
    # two-loop setup (Agent 1's own poller + this watcher draining its queue).
    return {
        "pipelineWatchIntervalSeconds": settings.PIPELINE_WATCH_INTERVAL_SECONDS,
    }


@app.post("/api/discovery/refresh")
async def refresh_discovery() -> dict:
    await registry.discover()
    return {"agents": [agent.card.id for agent in registry.list_agents()], "errors": registry.discovery_errors}


@app.get("/api/agents")
async def list_agents() -> dict:
    return {
        "agents": [
            {
                "agentId": agent.card.id,
                "name": agent.card.name,
                "baseUrl": agent.base_url,
                "status": agent.status,
                "skillCount": len(agent.card.skills),
            }
            for agent in registry.list_agents()
        ],
        "errors": registry.discovery_errors,
    }


@app.get("/api/agents/{agent_id}/card")
async def get_agent_card(agent_id: str) -> dict:
    agent = registry.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' is not registered. Try POST /api/discovery/refresh.")
    return agent.card.model_dump(mode="json")


@app.get("/api/skills")
async def list_skills() -> dict:
    return {"skills": registry.all_skills()}


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    record = await orchestrator.run_nl_workflow(request.text, request.mode)
    return _record_to_dict(record)


@app.post("/api/workflows/execute")
async def execute_workflow(request: WorkflowRequest) -> dict:
    record = await orchestrator.run_structured_workflow([step.model_dump() for step in request.steps], request.mode)
    return _record_to_dict(record)


@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict:
    record = orchestrator.get_workflow(workflow_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    return _record_to_dict(record)


@app.get("/api/history")
async def history(limit: int = 50, kind: Literal["chat", "email_pipeline"] | None = None) -> dict:
    return {"workflows": [_record_to_dict(record) for record in orchestrator.list_history(limit, kind)]}


@app.post("/api/pipeline/poll-now")
async def pipeline_poll_now() -> dict:
    """Forces an immediate mailbox poll (instead of waiting for Agent 1's
    schedule) and runs the pipeline for anything found -- used by the
    frontend's 'Poll Now' button."""
    records = await orchestrator.poll_now()
    return {"workflows": [_record_to_dict(record) for record in records]}


@app.get("/api/sessions")
async def list_sessions(status: str | None = None, limit: int = 100) -> dict:
    """Durable workflow_session rows (shared/db/workflow_session_repo.py) --
    the DB-backed control state behind the email pipeline, independent of
    this process's own in-memory WorkflowRecord history. Powers the
    frontend's Sessions tab."""
    return {
        "sessions": [_session_to_dict(s) for s in session_repo.list_sessions(limit=limit, status=status)],
        "workerId": settings.WORKER_NODE_ID,
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    session = session_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return _session_to_dict(session)


@app.post("/api/sessions/{session_id}/claim")
async def claim_session(session_id: str, request: ClaimSessionRequest) -> dict:
    """Atomically claims a CREATED/RETRY session for a worker. Exposed
    directly (not just used internally by the pipeline) so the Sessions tab
    can exercise -- and demonstrate -- the same atomic claim two real
    workers rely on: only one of two concurrent claims for the same session
    ever succeeds."""
    session = session_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    worker_id = request.workerId or settings.WORKER_NODE_ID
    claimed = session_repo.claim_session(session_id, worker_id)
    return {"claimed": claimed, "workerId": worker_id, "session": _session_to_dict(session_repo.get_session(session_id))}


def run() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.CLIENT_HOST, port=settings.CLIENT_PORT)


if __name__ == "__main__":
    run()

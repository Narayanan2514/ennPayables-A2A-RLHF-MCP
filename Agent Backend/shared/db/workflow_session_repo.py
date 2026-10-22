"""Durable control state for one email-to-ERP workflow run, backed by the
`workflow_session` table (DB_Schema/script.sql) -- the source of truth for
"which invoice workflow is this, who owns it, what state is it in, and
which step should be resumed" that survives a worker/client process crash.

This is NOT a replacement for `client.orchestrator.orchestrator.WorkflowRecord`
(process-local UI/history state) or `shared.crew.payload_store.PayloadStore`
(temporary structured-payload transport). It only answers the durable
control-state questions; everything else keeps working exactly as before --
see the module docstrings on those two for the split.

Uses SQLAlchemy Core (parameterized `text()` statements) against the same
`ennvault` MySQL database and connection convention as
`agents/agent_3/services/db_repo.py`, since this table lives in that same
schema and this repo intentionally does not introduce an ORM layer the rest
of the codebase doesn't already use.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("shared.db.workflow_session_repo")

_engine: Engine | None = None

STATUS_CREATED = "CREATED"
STATUS_RUNNING = "RUNNING"
STATUS_RETRY = "RETRY"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"

# retry_count >= MAX_RETRIES -> FAILED (a first failure is RETRY, a second
# is terminal) -- see the module docstring's design doc, section 6.
MAX_RETRIES = 2


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if settings.database_url().startswith("sqlite") else {}
        _engine = create_engine(settings.database_url(), pool_pre_ping=True, connect_args=connect_args)
    return _engine


def new_session_id() -> str:
    return f"sess-{uuid.uuid4().hex[:20]}"


def create_session(src_id: str, current_step: str = "AGENT_1") -> str:
    """Creates a session row as early as possible -- right after an email is
    classified in-scope, before Agent 1 even runs -- so a crash from this
    point on is still recoverable/visible. `src_id` is frequently a
    placeholder here: the real `source.src_id` row doesn't exist yet (Agent
    3's extraction stage is what creates it) -- see `set_src_id`, called
    once the real one is known.
    """
    session_id = new_session_id()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflow_session (session_id, src_id, status, current_step) "
                "VALUES (:session_id, :src_id, 'CREATED', :current_step)"
            ),
            {"session_id": session_id, "src_id": src_id[:20], "current_step": current_step},
        )
    logger.info("Session %s created (src_id=%s, current_step=%s)", session_id, src_id, current_step)
    return session_id


def claim_session(session_id: str, worker_id: str) -> bool:
    """Atomically claims a CREATED or RETRY session for `worker_id`. The
    UPDATE's WHERE clause (not a prior SELECT) is the concurrency guard --
    two workers racing to claim the same session will only ever have one
    UPDATE affect a row; the other gets rowcount 0 and must back off. Never
    resets retry_count.
    """
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "UPDATE workflow_session SET worker_id = :worker_id, status = 'RUNNING', "
                "status_at = CURRENT_TIMESTAMP WHERE session_id = :session_id AND status IN ('CREATED', 'RETRY')"
            ),
            {"worker_id": worker_id, "session_id": session_id},
        )
        claimed = result.rowcount > 0
    logger.info("Session %s claim by %s: %s", session_id, worker_id, "ok" if claimed else "already claimed")
    return claimed


def set_src_id(session_id: str, src_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE workflow_session SET src_id = :src_id WHERE session_id = :session_id"),
            {"src_id": src_id[:20], "session_id": session_id},
        )


def advance_step(session_id: str, current_step: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE workflow_session SET current_step = :current_step, status_at = CURRENT_TIMESTAMP "
                "WHERE session_id = :session_id"
            ),
            {"current_step": current_step, "session_id": session_id},
        )


def mark_success(session_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE workflow_session SET status = 'SUCCESS', status_at = CURRENT_TIMESTAMP, "
                "finished_at = CURRENT_TIMESTAMP WHERE session_id = :session_id"
            ),
            {"session_id": session_id},
        )
    logger.info("Session %s -> SUCCESS", session_id)


def fail_session(session_id: str) -> dict[str, Any] | None:
    """Records a failure at whatever `current_step` the session is already
    on -- current_step is only ever advanced on success, so it is always the
    step that just failed, without the caller having to say which step that
    was. First failure -> RETRY (resumable from current_step, by any
    worker). Second failure -> FAILED, terminal. retry_count is persisted in
    the same row/transaction, so a process restart can never reset it.
    """
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT retry_count FROM workflow_session WHERE session_id = :session_id"),
            {"session_id": session_id},
        ).first()
        if row is None:
            logger.warning("fail_session: unknown session_id=%s", session_id)
            return None
        new_retry_count = row[0] + 1
        new_status = STATUS_FAILED if new_retry_count >= MAX_RETRIES else STATUS_RETRY
        finished_clause = ", finished_at = CURRENT_TIMESTAMP" if new_status == STATUS_FAILED else ""
        conn.execute(
            text(
                f"UPDATE workflow_session SET retry_count = :retry_count, status = :status, "
                f"status_at = CURRENT_TIMESTAMP{finished_clause} WHERE session_id = :session_id"
            ),
            {"retry_count": new_retry_count, "status": new_status, "session_id": session_id},
        )
    logger.info("Session %s failure recorded: retry_count=%s status=%s", session_id, new_retry_count, new_status)
    return {"retry_count": new_retry_count, "status": new_status}


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT * FROM workflow_session WHERE session_id = :session_id"), {"session_id": session_id}
        ).mappings().first()
        return dict(row) if row else None


def get_latest_session_for_src(src_id: str) -> dict[str, Any] | None:
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT * FROM workflow_session WHERE src_id = :src_id ORDER BY created_at DESC LIMIT 1"),
            {"src_id": src_id},
        ).mappings().first()
        return dict(row) if row else None


def list_sessions(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    with get_engine().begin() as conn:
        if status:
            rows = conn.execute(
                text("SELECT * FROM workflow_session WHERE status = :status ORDER BY created_at DESC LIMIT :limit"),
                {"status": status, "limit": limit},
            ).mappings().all()
        else:
            rows = conn.execute(
                text("SELECT * FROM workflow_session ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}
            ).mappings().all()
        return [dict(r) for r in rows]


def find_retryable_sessions() -> list[dict[str, Any]]:
    """Sessions any worker can claim right now -- used by a worker's startup
    recovery pass."""
    with get_engine().begin() as conn:
        rows = conn.execute(
            text("SELECT * FROM workflow_session WHERE status = 'RETRY' ORDER BY status_at ASC")
        ).mappings().all()
        return [dict(r) for r in rows]

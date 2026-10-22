"""The REST API the React ops dashboard (frontend/) talks to.

A browser can't speak MCP stdio, so this is the plain-HTTP front door onto
the same functions the MCP servers and orchestrator use --
mcp_servers/common/legacy_repo.py, learning/feedback_logger.py,
orchestrator/bandit.py, orchestrator/agent.py. No business logic lives here
that doesn't already live in one of those modules; see api/repo.py for the
composition layer.

Run with:
    uvicorn api.main:app --reload --port 8010
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import repo
from api.governance_dashboard import router as governance_router
from config.settings import get_settings
from orchestrator.agent import process_document
from orchestrator.native_tools import NATIVE_TOOL_HANDLERS

app = FastAPI(title="ennVault Agentic AP API")

app.add_middleware(
    CORSMiddleware,
    # Vite picks the next free port (5174, 5175, ...) whenever 5173 is
    # already in use, so a fixed origin list breaks the moment that happens.
    # This is a local dev tool talking to a local backend -- matching any
    # localhost/127.0.0.1 port is the pragmatic fix, not a production CORS
    # policy (don't reuse this regex for a public-facing deployment).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(governance_router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "autonomy_stage": settings.autonomy_stage,
        "openai_configured": bool(settings.openai_api_key),
        "ebs_configured": bool(settings.ebs_base_url),
        "jde_configured": bool(settings.jde_base_url),
    }


@app.get("/api/documents")
def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    return repo.list_documents(limit)


@app.get("/api/documents/processed")
def list_processed_documents(limit: int = 200) -> list[dict[str, Any]]:
    # Must be declared before /api/documents/{src_id} -- FastAPI matches
    # routes in registration order, and {src_id} would otherwise swallow the
    # literal "processed" as a src_id.
    return repo.list_processed_documents(limit)


@app.get("/api/documents/{src_id}")
def get_document(src_id: str) -> dict[str, Any]:
    detail = repo.get_document_detail(src_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No document found for src_id={src_id}")
    return detail


@app.get("/api/exceptions/agent-handled")
def list_agent_handled_exceptions(limit: int = 100) -> list[dict[str, Any]]:
    # Same ordering note as above, relative to /api/exceptions -- this one's
    # already distinct enough (no shared dynamic segment) but kept adjacent
    # to its sibling for readability.
    return repo.list_agent_handled_exceptions(limit)


@app.get("/api/exceptions")
def list_exceptions(limit: int = 100) -> list[dict[str, Any]]:
    return repo.list_open_exceptions(limit)


@app.get("/api/dashboard/summary")
def dashboard_summary(recent_limit: int = 10) -> dict[str, Any]:
    return repo.get_dashboard_summary(recent_limit)


@app.get("/api/documents/{src_id}/trace")
def get_document_trace(src_id: str) -> list[dict[str, Any]]:
    """Every step the Orchestrator/Planner Agent has logged for this src_id,
    across all runs (grouped by run_id) -- the trace view on the document
    detail page. Empty list, not 404, if the agent hasn't run yet.
    """
    if not repo.document_exists(src_id):
        raise HTTPException(status_code=404, detail=f"No document found for src_id={src_id}")
    return repo.get_agent_trace(src_id)


class FeedbackRequest(BaseModel):
    human_action: str
    correct: bool
    ai_recommendation: str | None = None
    exception_type: str | None = None
    supplier_name: str | None = None
    doc_type: str | None = None
    invoice_features: dict[str, Any] | None = None
    confidence_at_decision: float | None = None


@app.post("/api/documents/{src_id}/feedback")
def submit_feedback(src_id: str, body: FeedbackRequest) -> dict[str, Any]:
    """The human-feedback ("RLHF-style") write path -- an Approve/Correct
    click in the frontend calls this. See RLHF_AND_AGENTS.md for the full
    explanation of what this does and doesn't do.
    """
    if not repo.document_exists(src_id):
        raise HTTPException(status_code=404, detail=f"No document found for src_id={src_id}")
    return repo.submit_feedback(
        src_id=src_id,
        human_action=body.human_action,
        correct=body.correct,
        ai_recommendation=body.ai_recommendation,
        exception_type=body.exception_type,
        supplier_name=body.supplier_name,
        doc_type=body.doc_type,
        invoice_features=body.invoice_features,
        confidence_at_decision=body.confidence_at_decision,
    )


class LineEdit(BaseModel):
    line_id: int
    field: str
    value: Any


class EditReprocessRequest(BaseModel):
    header_fields: dict[str, Any] | None = None
    line_edits: list[LineEdit] | None = None


@app.post("/api/documents/{src_id}/edit-and-reprocess")
def edit_and_reprocess(src_id: str, body: EditReprocessRequest) -> dict[str, Any]:
    """A human corrects invoice header and/or line fields directly and the
    document is resubmitted to the ERP immediately -- no LLM call. Logs the
    fix as a correction so a future occurrence of the same
    (supplier, exception_type) can be auto-resolved by the agent's
    apply_learned_correction tool.
    """
    if not repo.document_exists(src_id):
        raise HTTPException(status_code=404, detail=f"No document found for src_id={src_id}")
    try:
        return repo.edit_and_reprocess(
            src_id,
            header_fields=body.header_fields,
            line_edits=[edit.model_dump() for edit in body.line_edits] if body.line_edits else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SendSupplierEmailRequest(BaseModel):
    subject: str
    body_html: str


@app.post("/api/documents/{src_id}/send-supplier-email")
def send_supplier_email(src_id: str, body: SendSupplierEmailRequest) -> dict[str, Any]:
    """A human sending an email to the supplier right now from the Manual
    Review / document detail page -- actually sends via Microsoft Graph
    (see mcp_servers/common/graph_client.py), and logs the decision so a
    future occurrence of the same (supplier, exception_type) can be
    auto-emailed by the agent's apply_learned_email tool.
    """
    if not repo.document_exists(src_id):
        raise HTTPException(status_code=404, detail=f"No document found for src_id={src_id}")
    try:
        return repo.send_supplier_email(src_id, body.subject, body.body_html)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tools/{tool_name}")
def call_native_tool(tool_name: str, args: dict[str, Any]) -> Any:
    """Lets an external supervisor (the A2A client/orchestrator) call the same
    self-contained policy tools (apply_learned_correction, apply_learned_email,
    escalate_to_human, choose_bandit_action, ...) that orchestrator/agent.py's
    own LLM tool-calling loop uses -- see orchestrator/native_tools.py for what
    each one actually does. This endpoint adds no logic of its own; it's a
    thin dispatch onto that same NATIVE_TOOL_HANDLERS registry so a second,
    external decision-maker doesn't have to re-derive equivalent behavior.
    """
    handler = NATIVE_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'")
    try:
        return handler(**args)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/{src_id}/run-agent")
async def run_agent(src_id: str) -> dict[str, Any]:
    """Triggers the Orchestrator/Planner Agent for this document and waits
    for it to reach a terminal state. Requires OPENAI_API_KEY (used for both
    the orchestrator's OPENAI_MODEL and, for extraction, OPENAI_VISION_MODEL)
    -- see /api/health to check what's configured before calling this.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured -- see .env.example")
    return await process_document(src_id)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8010, log_level="info",reload=True)
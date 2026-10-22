"""Standalone FastAPI entrypoint for the ERP Push Agent (port 8004).

Run independently: `python -m agents.agent_4.main.main` from `backend/`.
This process never imports Agent 1, Agent 2, or Agent 3 code.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.a2a_protocol.schemas import JSONRPCRequest
from shared.config import settings as shared_settings
from shared.utilities.logging import get_logger

from ..config import settings
from ..handlers.message_handler import handle_jsonrpc

logger = get_logger("agent_4.main")

CARD_PATH = Path(__file__).resolve().parent.parent / "agent_card.json"


def load_agent_card() -> dict:
    card = json.loads(CARD_PATH.read_text())
    card["url"] = settings.AGENT_URL
    return card


app = FastAPI(title=settings.AGENT_NAME, version=settings.AGENT_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=shared_settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "agentId": settings.AGENT_ID, "agentName": settings.AGENT_NAME}


@app.get("/.well-known/agent.json")
async def agent_card() -> dict:
    return load_agent_card()


@app.post("/a2a/message")
async def a2a_message(request: JSONRPCRequest) -> dict:
    logger.info("POST /a2a/message request payload: %s", request.model_dump_json())
    response = await handle_jsonrpc(request)
    response_payload = response.model_dump(mode="json", exclude_none=True)
    logger.info("POST /a2a/message response payload: %s", json.dumps(response_payload))
    return response_payload


def run() -> None:
    import uvicorn

    logger.info("Starting %s on port %s", settings.AGENT_NAME, settings.AGENT_PORT)
    uvicorn.run(app, host="0.0.0.0", port=settings.AGENT_PORT)


if __name__ == "__main__":
    run()

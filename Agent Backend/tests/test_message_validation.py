"""A2A message/JSON-RPC validation at the transport layer, exercised through
Agent 2's real HTTP endpoint. These fail before the request ever reaches the
crew, so none of them need an LLM."""
import os

import pytest
from fastapi.testclient import TestClient

from agents.agent_2.main.main import app as agent2_app

client = TestClient(agent2_app)


def _rpc(method, params):
    return {"jsonrpc": "2.0", "id": "rpc-1", "method": method, "params": params}


def test_unsupported_method_returns_jsonrpc_error():
    response = client.post("/a2a/message", json=_rpc("tasks/cancel", {}))
    body = response.json()
    assert body["error"]["code"] == -32601


def test_missing_message_param_returns_jsonrpc_error():
    response = client.post("/a2a/message", json=_rpc("message/send", {}))
    body = response.json()
    assert body["error"]["code"] == -32602


def test_malformed_message_returns_jsonrpc_error():
    response = client.post("/a2a/message", json=_rpc("message/send", {"message": {"role": "not-a-role", "parts": []}}))
    body = response.json()
    assert body["error"]["code"] == -32600


def test_message_with_no_text_parts_fails_validation_without_llm():
    message = {"role": "user", "parts": [], "contextId": "ctx-http-empty"}
    response = client.post("/a2a/message", json=_rpc("message/send", {"message": message}))
    body = response.json()
    assert body["result"]["status"]["state"] == "failed"
    assert body["result"]["metadata"]["errorCode"] == "VALIDATION_FAILED"


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires OPENAI_API_KEY for live CrewAI execution")
def test_valid_message_returns_completed_task():
    message = {
        "role": "user",
        "parts": [
            {"kind": "text", "text": "Validate this intake record.\nfrom_email: ap@x.com\nsubject: Invoice 1\ndoc_type: invoice"},
            {"kind": "data", "data": {"attachments": []}},
        ],
        "contextId": "ctx-http-1",
    }
    response = client.post("/a2a/message", json=_rpc("message/send", {"message": message}))
    body = response.json()
    assert body.get("error") is None
    assert body["result"]["status"]["state"] == "completed"

"""Unit tests for client/orchestrator/exception_handling.py's decision
sequence, against a mocked RLHF API (httpx.MockTransport -- no real network,
no real RLHF process needed). Mirrors a2a_client.client's own
client-injection convention for testability.
"""
from __future__ import annotations

import httpx
import pytest

from client.orchestrator.exception_handling import handle_erp_failure

SRC_ID = "src_999"

DOCUMENT_DETAIL = {
    "header": {"supplier_name": "3M Health Care"},
    "is_open_exception": True,
    "recommendation": {"exception_type": "invalid_po", "suggested_action": "email_supplier"},
}


def _make_client(tool_responses: dict[str, dict], document_detail: dict | None = DOCUMENT_DETAIL) -> httpx.AsyncClient:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path == f"/api/documents/{SRC_ID}":
            if document_detail is None:
                return httpx.Response(404)
            return httpx.Response(200, json=document_detail)
        for tool_name, response in tool_responses.items():
            if path == f"/api/tools/{tool_name}":
                return httpx.Response(200, json=response)
        raise AssertionError(f"Unexpected call to {path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._test_calls = calls  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_auto_fix_succeeds_and_stops_there():
    client = _make_client(
        {
            "choose_bandit_action": {"action": "auto_fix_line_item"},
            "apply_learned_correction": {"applied": True, "succeeded": True},
        }
    )
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "auto_fix_line_item"
    assert "/api/tools/apply_learned_email" not in client._test_calls  # type: ignore[attr-defined]
    assert "/api/tools/escalate_to_human" not in client._test_calls  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_falls_back_to_learned_email_when_correction_not_applied():
    client = _make_client(
        {
            "choose_bandit_action": {"action": "email_supplier"},
            "apply_learned_correction": {"applied": False, "reason": "no_sufficiently_similar_past_correction"},
            "apply_learned_email": {"applied": True, "sent": True},
        }
    )
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "email_supplier"
    assert "/api/tools/escalate_to_human" not in client._test_calls  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_escalates_when_no_precedent_found_for_either_action():
    client = _make_client(
        {
            "choose_bandit_action": {"action": "escalate"},
            "apply_learned_correction": {"applied": False, "reason": "no_sufficiently_similar_past_correction"},
            "apply_learned_email": {"applied": False, "reason": "no_sufficiently_similar_past_correction"},
            "escalate_to_human": {"escalated": True},
        }
    )
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "escalated"


@pytest.mark.asyncio
async def test_correction_applied_but_resubmit_failed_tries_email_not_a_retry():
    client = _make_client(
        {
            "choose_bandit_action": {"action": "auto_fix_line_item"},
            "apply_learned_correction": {"applied": True, "succeeded": False},
            "apply_learned_email": {"applied": True, "sent": True},
        }
    )
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "email_supplier"
    # apply_learned_correction must only ever be called once, never retried.
    assert client._test_calls.count("/api/tools/apply_learned_correction") == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_skips_when_document_has_no_open_exception():
    client = _make_client({}, document_detail={"header": {}, "is_open_exception": False, "recommendation": None})
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "skipped"


@pytest.mark.asyncio
async def test_skips_when_document_not_found():
    client = _make_client({}, document_detail=None)
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "skipped"


@pytest.mark.asyncio
async def test_skips_gracefully_when_rlhf_api_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with client:
        result = await handle_erp_failure(SRC_ID, client=client)
    assert result["action"] == "skipped"
    assert "unreachable" in result["reason"]

"""Tests for api/main.py -- the REST API the React frontend calls. Exercises
the same document -> exception -> feedback loop the ops dashboard drives,
through real HTTP requests (FastAPI TestClient), against the sqlite fixture.
"""
from fastapi.testclient import TestClient

from db.legacy_schema import Source
from db.session import session_scope
from mcp_servers.common import legacy_repo


def _seed_open_invoice_exception(src_id="src_api_1", supplier="Acme Corp"):
    with session_scope() as session:
        session.add(Source(src_id=src_id, target="EBS", doc_type="invoice", channel="email"))
    header_id = legacy_repo.insert_invoice(
        src_id,
        {
            "supplier_name": supplier,
            "invoice_number": "24020",
            "customer_po_number": "673900",
            "currency_code": "USD",
            "total": "100.00",
        },
        [{"line_number": "1", "item_name": "0001-0120H", "total": "100"}],
    )
    legacy_repo.insert_log(src_id, "Failed", "EBS", "PO Number not found!:673900")
    return header_id


def _client():
    from api.main import app

    return TestClient(app)


def test_health_reports_configuration_state():
    resp = _client().get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "openai_configured" in body
    assert "autonomy_stage" in body


def test_list_documents_empty_when_no_sources():
    resp = _client().get("/api/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_document_404_for_unknown_src_id():
    resp = _client().get("/api/documents/does_not_exist")
    assert resp.status_code == 404


def test_document_detail_surfaces_bandit_recommendation_for_open_exception():
    _seed_open_invoice_exception()
    resp = _client().get("/api/documents/src_api_1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_open_exception"] is True
    assert body["recommendation"]["exception_type"] == "invalid_po"
    assert body["recommendation"]["suggested_action"] in body["recommendation"]["action_space"]
    assert "arm_states" in body["recommendation"]


def test_list_exceptions_returns_the_open_one():
    _seed_open_invoice_exception(src_id="src_api_2", supplier="Beta LLC")
    resp = _client().get("/api/exceptions")
    assert resp.status_code == 200
    assert any(e["src_id"] == "src_api_2" for e in resp.json())


def test_feedback_closes_the_exception_and_updates_bandit():
    _seed_open_invoice_exception(src_id="src_api_3", supplier="Gamma Inc")

    before = _client().get("/api/documents/src_api_3").json()
    suggested = before["recommendation"]["suggested_action"]

    resp = _client().post(
        "/api/documents/src_api_3/feedback",
        json={
            "human_action": "request_po_correction",
            "correct": suggested == "request_po_correction",
            "ai_recommendation": suggested,
            "exception_type": "invalid_po",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True

    after = _client().get("/api/documents/src_api_3").json()
    assert after["is_open_exception"] is False
    assert after["latest_status"]["action_taken"] == "request_po_correction"


def test_feedback_404_for_unknown_document():
    resp = _client().post(
        "/api/documents/does_not_exist/feedback",
        json={"human_action": "escalate", "correct": False},
    )
    assert resp.status_code == 404


def test_run_agent_503_without_openai_key(monkeypatch):
    from config.settings import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    resp = _client().post("/api/documents/src_anything/run-agent")
    assert resp.status_code == 503


def test_dashboard_summary_shape_on_empty_db():
    resp = _client().get("/api/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "total_received",
        "runs_completed",
        "processed_successfully",
        "exceptions_human_review",
        "exceptions_agent_handled",
        "recent_transactions",
    ):
        assert key in body
    assert body["runs_completed"] == 0
    assert body["total_received"] == 0
    assert body["recent_transactions"] == []


def test_list_processed_documents_includes_successful_docs_from_either_erp():
    with session_scope() as session:
        session.add(Source(src_id="src_api_jde", target="JDE", doc_type="invoice", channel="email"))
    legacy_repo.insert_log("src_api_jde", "Successful", "JDE", "Invoice pushed to JDE")

    resp = _client().get("/api/documents/processed")
    assert resp.status_code == 200
    body = resp.json()
    assert any(d["src_id"] == "src_api_jde" and d["target"] == "JDE" for d in body)


def test_agent_handled_lists_only_policy_resolved_still_successful():
    from learning import feedback_logger

    with session_scope() as session:
        session.add(Source(src_id="src_api_handled", target="EBS", doc_type="invoice", channel="email"))
    feedback_logger.log_outcome(
        src_id="src_api_handled",
        supplier_name="Delta LLC",
        exception_type="voucher_hold",
        action_taken="auto_approve",
        decided_by="policy",
        autonomy_stage="expanded",
    )
    legacy_repo.insert_log("src_api_handled", "Successful", "MCP", "Auto-approved by policy")

    resp = _client().get("/api/exceptions/agent-handled")
    assert resp.status_code == 200
    assert any(e["src_id"] == "src_api_handled" for e in resp.json())


def test_edit_and_reprocess_applies_fields_and_closes_exception_on_success(monkeypatch):
    _seed_open_invoice_exception(src_id="src_api_edit", supplier="Epsilon Co")
    monkeypatch.setattr(
        "mcp_servers.oracle_ebs_server.call_create_invoice",
        lambda payload: {"status": "S", "invoice_number": "INV-1", "message": "AP Invoice processed successfully"},
    )

    resp = _client().post(
        "/api/documents/src_api_edit/edit-and-reprocess",
        json={"header_fields": {"customer_po_number": "673901"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["correction_id"] is not None

    after = _client().get("/api/documents/src_api_edit").json()
    assert after["is_open_exception"] is False
    assert after["header"]["customer_po_number"] == "673901"


def test_edit_and_reprocess_404_for_unknown_document():
    resp = _client().post(
        "/api/documents/does_not_exist/edit-and-reprocess",
        json={"header_fields": {"customer_po_number": "1"}},
    )
    assert resp.status_code == 404

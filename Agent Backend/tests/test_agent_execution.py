"""Individual agent execution.

Two layers are tested:

1. Each agent's deterministic service/tool logic -- no LLM, no network, no
   DB. This is where the real pipeline behavior lives (doc-type detection,
   the validation rule engine, JDE/EBS payload shape), so it's exercised
   thoroughly offline.
2. The full executor (`Executor.execute`), which wraps a tool call in a
   real CrewAI Agent + Task + Crew and requires the crew's LLM (OpenAI) to
   reason and pick a tool. Skipped unless OPENAI_API_KEY is set.
"""
import json
import os

import pytest

from shared.email_classification import clean_body, detect_doc_type, is_erp_relevant, is_pipeline_scope
from agents.agent_2.services import validation_service
from agents.agent_2.services.validation_service import validate_intake_record
from agents.agent_3.services.decoder import decode_fields
from shared.a2a_protocol.helpers import build_task_message
from shared.a2a_protocol.schemas import TaskState

requires_openai = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="requires OPENAI_API_KEY for live CrewAI execution")


# --- Layer 1: deterministic service logic ------------------------------------


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Invoice #4521 for August services", "invoice"),
        ("Tax Invoice attached", "invoice"),
        ("PO 88213 confirmation", "purchase_order"),
        ("Remittance advice for payment", "remittance"),
        ("Bank statement - September", "bank"),
        ("Let's catch up next week", None),
        (None, None),
    ],
)
def test_detect_doc_type(subject, expected):
    assert detect_doc_type(subject) == expected


def test_is_erp_relevant_and_pipeline_scope():
    assert is_erp_relevant("invoice") is True
    assert is_erp_relevant(None) is False
    assert is_pipeline_scope("invoice") is True
    assert is_pipeline_scope("purchase_order") is False


def test_clean_body_strips_html_and_signature():
    html = "<div>Please find the invoice attached.</div><div>Best regards,<br>Jane</div>"
    cleaned = clean_body(html)
    assert "invoice attached" in cleaned.lower()
    assert "jane" not in cleaned.lower()


def test_is_valid_for_pipeline_matches_detect_doc_type():
    from shared.email_classification import is_valid_for_pipeline

    assert is_valid_for_pipeline("Invoice #4521 for August services") == (True, "invoice")
    assert is_valid_for_pipeline("PO 88213 confirmation") == (False, "purchase_order")
    assert is_valid_for_pipeline("Let's catch up next week") == (False, None)


# --- Agent 1: per-message intake, driven by the supervisor -------------------


def test_process_message_downloads_attachments_marks_read_and_builds_record(monkeypatch):
    from agents.agent_1.services import intake_service

    calls = []
    monkeypatch.setattr(intake_service.graph_client, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(
        intake_service.graph_client,
        "download_attachments",
        lambda token, message_id, subfolder: calls.append(("download", message_id, subfolder)) or [{"name": "inv.pdf", "path": "/x/inv.pdf", "content_type": "application/pdf"}],
    )
    monkeypatch.setattr(intake_service.graph_client, "mark_email_as_read", lambda token, message_id: calls.append(("mark_read", message_id)))

    record = intake_service.process_message(
        message_id="msg-1",
        conversation_id="conv-1",
        from_email="ap@supplier.com",
        subject="Invoice #123",
        body_html="<p>Please see attached. Best regards, Jane</p>",
        doc_type="invoice",
        received_at="2026-01-01T00:00:00Z",
    )

    assert record["message_id"] == "msg-1"
    assert record["is_pipeline_scope"] is True
    assert record["attachments"] == [{"name": "inv.pdf", "path": "/x/inv.pdf", "content_type": "application/pdf"}]
    assert "jane" not in record["body_text"].lower()
    assert ("download", "msg-1", "inv") in calls
    assert ("mark_read", "msg-1") in calls


def test_process_message_still_marks_read_and_returns_record_when_download_fails(monkeypatch):
    """An attachment-download failure shouldn't lose the message -- same
    fail-soft behavior the old bulk poller had for one bad message."""
    from agents.agent_1.services import intake_service

    monkeypatch.setattr(intake_service.graph_client, "get_graph_token", lambda: "tok")

    def _boom(token, message_id, subfolder):
        raise RuntimeError("Graph is down")

    monkeypatch.setattr(intake_service.graph_client, "download_attachments", _boom)
    marked = []
    monkeypatch.setattr(intake_service.graph_client, "mark_email_as_read", lambda token, message_id: marked.append(message_id))

    record = intake_service.process_message(
        message_id="msg-2", conversation_id="", from_email="", subject="Invoice", body_html="", doc_type="invoice", received_at=""
    )
    assert record["attachments"] == []
    assert marked == ["msg-2"]


def test_mark_invalid_marks_read_without_downloading(monkeypatch):
    from agents.agent_1.services import intake_service

    calls = []
    monkeypatch.setattr(intake_service.graph_client, "get_graph_token", lambda: "tok")
    monkeypatch.setattr(intake_service.graph_client, "mark_email_as_read", lambda token, message_id: calls.append(message_id))

    result = intake_service.mark_invalid("msg-3")
    assert result == {"message_id": "msg-3", "marked_read": True}
    assert calls == ["msg-3"]


def test_validate_intake_record_passes_with_valid_pdf(tmp_path, monkeypatch):
    """A blank test-fixture PDF will never match a real customer's
    exclusion_config (org_backend's real format-detection gate -- see
    transform_service.detect_invoice_format), so the transform gate itself
    is monkeypatched here to isolate the rule-engine's happy path from
    that real, data-dependent gate (which needs an actual customer invoice
    layout and a working Tesseract install to test meaningfully)."""
    pdf_path = tmp_path / "invoice.pdf"
    _write_minimal_pdf(pdf_path)
    monkeypatch.setattr(
        validation_service, "_run_transform_gate", lambda pdf_path, doc_type: ([], ["page_1.png"], "mapping.xlsx")
    )

    result = validate_intake_record(
        from_email="ap@supplier.com",
        subject="Invoice 123",
        doc_type="invoice",
        attachments=[{"name": "invoice.pdf", "path": str(pdf_path)}],
    )
    assert result.verdict in ("pass", "flag")
    assert result.is_valid is True
    assert result.pdf_path == str(pdf_path)
    assert result.encoded_image_paths == ["page_1.png"]
    assert result.mapping_path == "mapping.xlsx"


def test_validate_intake_record_blocks_unrecognized_invoice_format(tmp_path, monkeypatch):
    """The real org_backend gate: no matching customer exclusion_config ->
    blocked, even though the cheap rule checks all pass."""
    pdf_path = tmp_path / "invoice.pdf"
    _write_minimal_pdf(pdf_path)
    monkeypatch.setattr(
        validation_service,
        "_run_transform_gate",
        lambda pdf_path, doc_type: (
            [validation_service.RuleViolation("customer_config_not_found", "block", "no match")],
            [],
            None,
        ),
    )

    result = validate_intake_record(
        from_email="ap@supplier.com",
        subject="Invoice 123",
        doc_type="invoice",
        attachments=[{"name": "invoice.pdf", "path": str(pdf_path)}],
    )
    assert result.verdict == "block"
    assert result.is_valid is False
    assert any(v.rule == "customer_config_not_found" for v in result.violations)


def test_validate_intake_record_blocks_missing_attachment():
    result = validate_intake_record(from_email="ap@supplier.com", subject="Invoice 123", doc_type="invoice", attachments=[])
    assert result.verdict == "block"
    assert result.is_valid is False
    assert any(v.rule == "missing_attachment" for v in result.violations)


def test_validate_intake_record_blocks_wrong_doc_type():
    result = validate_intake_record(from_email="ap@supplier.com", subject="Purchase Order 99", doc_type="purchase_order", attachments=[])
    assert any(v.rule == "unsupported_doc_type" and v.severity == "block" for v in result.violations)


def test_validate_intake_record_blocks_missing_sender():
    result = validate_intake_record(from_email="", subject="Invoice 123", doc_type="invoice", attachments=[{"name": "x.pdf", "path": "/nowhere.pdf"}])
    assert any(v.rule == "missing_sender" and v.severity == "block" for v in result.violations)
    assert result.verdict == "block"


def test_decode_fields_resolves_3digit_and_1char_codes(tmp_path):
    import pandas as pd

    mapping_path = tmp_path / "mapping.xlsx"
    pd.DataFrame([{"Original Word": "Acme", "Encrypted Word": "100"}, {"Original Word": "Corp", "Encrypted Word": "a"}]).to_excel(
        mapping_path, index=False
    )
    decoded = decode_fields(str(mapping_path), {"supplier_name": "100 a", "invoice_number": "INV-42"})
    assert decoded["supplier_name"] == "Acme Corp"
    assert decoded["invoice_number"] == "INV-42"  # untouched -- not a masked code


def test_decode_fields_falls_back_to_raw_values_on_bad_mapping_path():
    decoded = decode_fields("/does/not/exist.xlsx", {"invoice_number": "INV-1"})
    assert decoded == {"invoice_number": "INV-1"}


def test_payload_store_put_pop_and_discard():
    from shared.crew.payload_store import PayloadStore

    store = PayloadStore()
    key = store.put({"attachments": [{"name": "x.pdf"}]})
    assert store.pop(key) == {"attachments": [{"name": "x.pdf"}]}
    assert store.pop(key) is None  # popped once, gone

    key2 = store.put({"a": 1})
    store.discard(key2)
    assert store.pop(key2) is None


def test_agent2_tool_reads_attachments_from_payload_store():
    from agents.agent_2.skills.tools import ValidateIntakeRecordTool, payload_store

    key = payload_store.put({"attachments": [{"name": "invoice.pdf", "path": "/nowhere.pdf"}]})
    result = json.loads(ValidateIntakeRecordTool()._run(payload_key=key, from_email="ap@x.com", subject="Invoice 1", doc_type="invoice"))
    assert result["success"] is True
    # unreadable (missing) PDF -> block, but proves the attachment was actually retrieved via the key
    assert result["data"]["verdict"] == "block"


def test_agent2_tool_reports_missing_payload_key():
    from agents.agent_2.skills.tools import ValidateIntakeRecordTool

    result = json.loads(ValidateIntakeRecordTool()._run(payload_key="does-not-exist", from_email="ap@x.com", subject="Invoice 1", doc_type="invoice"))
    assert result["success"] is False
    assert "payload_key" in result["error"]


def test_agent3_tool_reports_missing_encoded_images(monkeypatch):
    """Agent 3's tool requires the Validator Agent's result to actually
    carry encoded_image_paths/mapping_path -- i.e. is_valid was true --
    not just any payload."""
    from agents.agent_3.skills.tools import ExtractAndStoreInvoiceTool, payload_store

    key = payload_store.put({"pdf_path": "/some/invoice.pdf", "encoded_image_paths": [], "mapping_path": None})
    result = json.loads(ExtractAndStoreInvoiceTool()._run(payload_key=key))
    assert result["success"] is False
    assert "encoded_image_paths" in result["error"]


def test_agent3_tool_reports_missing_payload_key():
    from agents.agent_3.skills.tools import ExtractAndStoreInvoiceTool

    result = json.loads(ExtractAndStoreInvoiceTool()._run(payload_key="does-not-exist"))
    assert result["success"] is False
    assert "payload_key" in result["error"]


def test_agent3_tool_unwraps_validator_agents_full_result_wrapper(monkeypatch):
    """Regression test: the orchestrator's call_agent tool stores the
    *entire* Validator Agent result under result_payload_key, wrapped as
    {"skill_used": ..., "data": {...}} in some call paths -- Agent 3's
    tool must unwrap to the actual encoded_image_paths/mapping_path, or it
    silently reports them missing instead of extracting."""
    from agents.agent_3.skills import tools as agent3_tools
    from agents.agent_3.skills.tools import ExtractAndStoreInvoiceTool, payload_store

    captured = {}

    def fake_process_invoice(encoded_image_paths, mapping_path, pdf_path, *args, **kwargs):
        captured["encoded_image_paths"] = encoded_image_paths
        captured["mapping_path"] = mapping_path
        return {"src_id": "SRC-1", "header_id": 1, "line_ids": [], "target_erp": "JDE", "extracted_fields": {}}

    monkeypatch.setattr(agent3_tools, "process_invoice", fake_process_invoice)

    wrapper = {"data": {"pdf_path": "/x/invoice.pdf", "encoded_image_paths": ["page_1.png"], "mapping_path": "mapping.xlsx"}}
    key = payload_store.put(wrapper)
    result = json.loads(ExtractAndStoreInvoiceTool()._run(payload_key=key))

    assert result["success"] is True
    assert captured["encoded_image_paths"] == ["page_1.png"]
    assert captured["mapping_path"] == "mapping.xlsx"


def test_agent4_tool_routes_to_jde_or_ebs_push_by_target_erp(monkeypatch):
    """Agent 4 no longer builds an EBS-only document from a forwarded
    extracted_fields payload -- it reads src_id/target_erp from the
    Extraction Agent's result and dispatches to the matching push
    function. This is the structural gate that keeps the JDE and EBS
    flows from both firing for the same record."""
    from agents.agent_4.skills.tools import PushInvoiceToErpTool, payload_store, _PUSH_ROUTER

    calls = []
    monkeypatch.setitem(_PUSH_ROUTER, "JDE", lambda src_id: calls.append(("JDE", src_id)) or {"status": "success"})
    monkeypatch.setitem(_PUSH_ROUTER, "EBS", lambda src_id: calls.append(("EBS", src_id)) or {"status": "success"})

    key = payload_store.put({"src_id": "SRC-1", "target_erp": "JDE"})
    result = json.loads(PushInvoiceToErpTool()._run(payload_key=key))
    assert result["success"] is True
    assert calls == [("JDE", "SRC-1")]


def test_agent4_tool_reports_error_for_missing_src_id():
    from agents.agent_4.skills.tools import PushInvoiceToErpTool, payload_store

    key = payload_store.put({"target_erp": "JDE"})
    result = json.loads(PushInvoiceToErpTool()._run(payload_key=key))
    assert result["success"] is False
    assert "src_id" in result["error"]


def _write_minimal_pdf(path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)


# --- Layer 2: full crew execution, requires a live LLM -----------------------


@requires_openai
@pytest.mark.asyncio
async def test_agent2_executor_picks_and_runs_validation():
    from agents.agent_2.executor.executor import Agent2Executor

    executor = Agent2Executor()
    message = build_task_message(
        "Validate this intake record for ERP processing.\n"
        "from_email: \n"
        "subject: Invoice 1\n"
        "doc_type: invoice\n"
        "The attachments list is attached as structured data -- pass its payload_key to your tool.",
        context_id="ctx-live-2",
        data={"attachments": []},
    )
    task = await executor.execute(message)
    assert task.status.state == TaskState.COMPLETED
    assert task.metadata["skillUsed"] == "validate_intake_record"

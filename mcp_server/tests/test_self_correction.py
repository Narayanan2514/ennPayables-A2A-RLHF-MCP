"""Unit tests for the attempt_self_correction MCP tool
(tools/self_correction.py), mocked at its natural boundaries -- DB
read/write (agent_3.services.db_repo / reextract_line_item), the live ERP
push (_PUSH_ROUTER), and RLHF's correction logger -- same philosophy
Agent/tests/test_agent_execution.py already uses (mock services, test the
surrounding decision logic), since there's no throwaway-DB fixture for
inv_header/inv_line here the way RLHF_Tools has one for its own schema.
"""
from __future__ import annotations

from tools import self_correction


def _seeded_ebs_invoice():
    header = {"id": 1, "src_id": "src_042", "supplier_name": "Acme Supplies"}
    lines = [{"id": 501, "line_number": "1", "item_name": "WIDGET-X"}]
    return header, lines


def test_fixes_invalid_item_retries_push_and_logs_correction(monkeypatch):
    header, lines = _seeded_ebs_invoice()
    monkeypatch.setattr(self_correction, "_read_stored_invoice", lambda erp, src_id: (header, lines))

    def fake_reextract(**kwargs):
        assert kwargs["line_id"] == 501
        assert kwargs["line_number"] == "1"
        assert kwargs["rejected_item_value"] == "WIDGET-X"
        return {"changed": True, "field": "item_name", "old_value": "WIDGET-X", "new_value": "WIDGET-9"}

    monkeypatch.setattr(self_correction, "reextract_line_item", fake_reextract)
    monkeypatch.setitem(self_correction._PUSH_ROUTER, "EBS", lambda src_id: {"status": "success", "message": "posted"})

    logged = {}
    monkeypatch.setattr(
        self_correction,
        "feedback_logger",
        type("_FakeLogger", (), {"log_correction": staticmethod(lambda **kw: logged.update(kw))}),
    )

    result = self_correction.attempt_self_correction(
        src_id="src_042",
        target_erp="EBS",
        failure_message="Item not found!:WIDGET-X",
        encoded_image_paths=["page_1.png"],
        mapping_path="mapping.xlsx",
    )

    assert result["attempted"] is True
    assert result["changed"] is True
    assert result["succeeded"] is True
    assert result["old_value"] == "WIDGET-X"
    assert result["new_value"] == "WIDGET-9"

    # A Correction was logged in the exact manual-edit shape
    # orchestrator.native_tools._parse_manual_edit_fields expects.
    assert logged["src_id"] == "src_042"
    assert logged["supplier_name"] == "Acme Supplies"
    assert logged["ai_recommendation"] == "WIDGET-X"
    assert logged["ai_recommendation_correct"] is False
    assert '"match_value": "WIDGET-X"' in logged["human_action"]
    assert '"set_value": "WIDGET-9"' in logged["human_action"]


def test_parses_real_ebs_item_not_found_message(monkeypatch):
    """Regression test for a real production message
    ('0001-0120xxx Item not found in the PO Number') -- the rejected value
    comes BEFORE the phrase here, unlike the colon-suffixed shape the
    parser originally assumed from a different (invalid_po) message."""
    header = {"id": 1, "src_id": "src_042", "supplier_name": "Acme Supplies"}
    lines = [{"id": 501, "line_number": "1", "item_name": "0001-0120xxx"}]
    monkeypatch.setattr(self_correction, "_read_stored_invoice", lambda erp, src_id: (header, lines))
    monkeypatch.setattr(
        self_correction,
        "reextract_line_item",
        lambda **k: {"changed": True, "field": "item_name", "old_value": "0001-0120xxx", "new_value": "0001-0120001"},
    )
    monkeypatch.setitem(self_correction._PUSH_ROUTER, "EBS", lambda src_id: {"status": "success", "message": "posted"})
    monkeypatch.setattr(self_correction, "feedback_logger", None)

    result = self_correction.attempt_self_correction(
        src_id="src_042",
        target_erp="EBS",
        failure_message="0001-0120xxx Item not found in the PO Number",
        encoded_image_paths=["page_1.png"],
        mapping_path="mapping.xlsx",
    )

    assert result["attempted"] is True
    assert result["changed"] is True
    assert result["succeeded"] is True


def test_skips_non_invalid_item_without_touching_db_or_erp(monkeypatch):
    """duplicate_invoice ('never safe to auto-resolve') must report
    attempted=False immediately -- and never call the DB, vision, or push,
    proving this path is a pure classify-and-bail, not a partial attempt."""
    calls = []
    monkeypatch.setattr(self_correction, "_read_stored_invoice", lambda *a, **k: calls.append("db") or (None, []))
    monkeypatch.setattr(self_correction, "reextract_line_item", lambda **k: calls.append("reextract"))
    monkeypatch.setitem(self_correction._PUSH_ROUTER, "EBS", lambda src_id: calls.append("push"))

    result = self_correction.attempt_self_correction(
        src_id="src_042",
        target_erp="EBS",
        failure_message="Invoice Number Already Exists for this Supplier !",
        encoded_image_paths=["page_1.png"],
        mapping_path="mapping.xlsx",
    )

    assert result == {"attempted": False, "exception_type": "duplicate_invoice"}
    assert calls == []


def test_unparseable_rejection_reports_reason_without_guessing(monkeypatch):
    """An invalid_item message with no parseable 'label:VALUE' shape must
    stop cleanly rather than attempt a match against nothing."""
    calls = []
    monkeypatch.setattr(self_correction, "_read_stored_invoice", lambda *a, **k: calls.append("db") or (None, []))

    result = self_correction.attempt_self_correction(
        src_id="src_042",
        target_erp="EBS",
        failure_message="Item not found",  # no ":VALUE" suffix
        encoded_image_paths=["page_1.png"],
        mapping_path="mapping.xlsx",
    )

    assert result["attempted"] is False
    assert result["exception_type"] == "invalid_item"
    assert "could not parse" in result["reason"]
    assert calls == []


def test_reextraction_unchanged_does_not_retry_push(monkeypatch):
    """If the re-extraction reproduces the same (still-wrong) value, this
    must report changed=False and never retry the push -- no fabricated fix."""
    header, lines = _seeded_ebs_invoice()
    monkeypatch.setattr(self_correction, "_read_stored_invoice", lambda erp, src_id: (header, lines))
    monkeypatch.setattr(self_correction, "reextract_line_item", lambda **k: {"changed": False})

    push_calls = []
    monkeypatch.setitem(self_correction._PUSH_ROUTER, "EBS", lambda src_id: push_calls.append(src_id))

    result = self_correction.attempt_self_correction(
        src_id="src_042",
        target_erp="EBS",
        failure_message="Item not found!:WIDGET-X",
        encoded_image_paths=["page_1.png"],
        mapping_path="mapping.xlsx",
    )

    assert result == {"attempted": True, "exception_type": "invalid_item", "changed": False, "reason": "re-extraction did not produce a different value"}
    assert push_calls == []

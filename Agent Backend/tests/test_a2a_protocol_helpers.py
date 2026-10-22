"""Structured A2A message/task construction and parsing."""
from shared.a2a_protocol.helpers import build_task_message, completed_task, extract_task_text, failed_task
from shared.a2a_protocol.schemas import PartKind, Role, TaskState


def test_build_task_message_carries_text_and_context():
    message = build_task_message("Check the status of PO-1001", context_id="ctx-1")
    assert message.role == Role.USER
    assert message.contextId == "ctx-1"
    assert len(message.parts) == 1
    assert message.parts[0].kind == PartKind.TEXT
    assert message.parts[0].text == "Check the status of PO-1001"


def test_extract_task_text_round_trips():
    message = build_task_message("Approve voucher for SRC-9001")
    assert extract_task_text(message) == "Approve voucher for SRC-9001"


def test_extract_task_text_joins_multiple_text_parts():
    message = build_task_message("first line")
    message.parts.append(message.parts[0].model_copy(update={"text": "second line"}))
    assert extract_task_text(message) == "first line\nsecond line"


def test_extract_task_text_empty_when_no_text_parts():
    message = build_task_message("")
    assert extract_task_text(message) == ""


def test_completed_task_has_completed_state_and_artifact():
    task = completed_task("ctx-1", "check_purchase_order", {"status": "OPEN"}, history=[], metadata={"skillUsed": "check_purchase_order"})
    assert task.status.state == TaskState.COMPLETED
    assert task.artifacts[0].name == "check_purchase_order"
    assert task.artifacts[0].parts[0].data == {"status": "OPEN"}
    assert task.metadata["skillUsed"] == "check_purchase_order"


def test_failed_task_has_failed_state_and_error_metadata():
    task = failed_task("ctx-1", "not found", history=[], error_code="ERP_OPERATION_FAILED")
    assert task.status.state == TaskState.FAILED
    assert task.metadata["errorCode"] == "ERP_OPERATION_FAILED"
    assert task.status.message.parts[0].text == "not found"

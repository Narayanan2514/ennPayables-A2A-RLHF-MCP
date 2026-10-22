"""Tests for orchestrator/native_tools.py's apply_learned_correction -- the
executor that closes the gap DEFAULT_ACTION_SPACE's "auto_fix_line_item" label
previously had no implementation for. Exercises it the same way the
Orchestrator/Planner Agent would call it as a tool, against the real
api.repo.edit_and_reprocess write path that produces the replayable
correction it reads back. apply_learned_correction is self-contained (it
re-checks governance authorization and logs the outcome/bandit reward
itself), so these tests also need AUTONOMY_STAGE set high enough to actually
authorize -- the default "shadow" always refuses, by design.
"""
from db.legacy_schema import Source
from db.session import session_scope
from mcp_servers.common import legacy_repo
from orchestrator.native_tools import NATIVE_TOOL_HANDLERS, NATIVE_TOOL_SCHEMAS


def _seed_open_invoice_exception(src_id, supplier, po_number="673900", item_name=None, description=None):
    with session_scope() as session:
        session.add(Source(src_id=src_id, target="EBS", doc_type="invoice", channel="email"))
    lines = [{"line_number": "1", "item_name": item_name or "0001-0120H", "total": "100"}]
    legacy_repo.insert_invoice(
        src_id,
        {
            "supplier_name": supplier,
            "invoice_number": "24020",
            "customer_po_number": po_number,
            "currency_code": "USD",
            "total": "100.00",
        },
        lines,
    )
    legacy_repo.insert_log(src_id, "Failed", "EBS", description or f"PO Number not found!:{po_number}")


def _mock_ebs_success(monkeypatch):
    monkeypatch.setattr(
        "mcp_servers.oracle_ebs_server.call_create_invoice",
        lambda payload: {"status": "S", "invoice_number": "INV-1", "message": "AP Invoice processed successfully"},
    )


def test_apply_learned_correction_is_registered_as_a_tool():
    names = {schema["name"] for schema in NATIVE_TOOL_SCHEMAS}
    assert "apply_learned_correction" in names
    assert "apply_learned_correction" in NATIVE_TOOL_HANDLERS


def test_apply_learned_correction_refuses_in_shadow_mode_even_with_a_similar_case(monkeypatch, chroma_dir):
    """Default AUTONOMY_STAGE is "shadow" -- authorize_autonomous_action must
    unconditionally refuse, so apply_learned_correction must too, regardless
    of whether a similar past correction exists.
    """
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "shadow")
    get_settings.cache_clear()
    _mock_ebs_success(monkeypatch)

    _seed_open_invoice_exception("src_shadow_a", "Shadow Corp")
    api_repo.edit_and_reprocess("src_shadow_a", header_fields={"customer_po_number": "555111"})

    _seed_open_invoice_exception("src_shadow_b", "Shadow Corp")
    result = NATIVE_TOOL_HANDLERS["apply_learned_correction"](
        src_id="src_shadow_b", supplier_name="Shadow Corp", exception_type="invalid_po"
    )
    assert result["applied"] is False
    assert "not_authorized" in result["reason"]


def test_apply_learned_correction_refuses_without_a_similar_past_case(monkeypatch, chroma_dir):
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()

    _seed_open_invoice_exception("src_never_seen", "Nobody Corp")
    result = NATIVE_TOOL_HANDLERS["apply_learned_correction"](
        src_id="src_never_seen", supplier_name="Nobody Corp", exception_type="invalid_po"
    )
    assert result["applied"] is False
    assert result["reason"] == "no_sufficiently_similar_past_correction"


def test_apply_learned_correction_replays_a_past_header_fix(monkeypatch, chroma_dir):
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()
    _mock_ebs_success(monkeypatch)

    # A human fixes src_a's bad PO number and reprocesses -- this is the
    # correction apply_learned_correction should later find and replay.
    _seed_open_invoice_exception("src_native_a", "Zeta Supplies", po_number="000000")
    outcome = api_repo.edit_and_reprocess("src_native_a", header_fields={"customer_po_number": "555111"})
    assert outcome["success"] is True

    # A second, near-identical document for the same supplier hits the same
    # exception type -- the agent would call apply_learned_correction here
    # instead of fabricating a fix.
    _seed_open_invoice_exception("src_native_b", "Zeta Supplies", po_number="000000")

    result = NATIVE_TOOL_HANDLERS["apply_learned_correction"](
        src_id="src_native_b", supplier_name="Zeta Supplies", exception_type="invalid_po"
    )

    assert result["applied"] is True
    assert result["header_fields_applied"] == {"customer_po_number": "555111"}
    assert result["succeeded"] is True

    updated_header_b = legacy_repo.get_invoice_header("src_native_b")
    assert updated_header_b["customer_po_number"] == "555111"


def test_apply_learned_correction_replays_a_past_line_fix_by_value_not_position(monkeypatch, chroma_dir):
    """The exact scenario from the bug report: a supplier's item number
    'abc-x' should have been 'abc-1'. A human fixes it once via
    edit_and_reprocess; the next invoice from the same supplier with the
    same wrong item number should get auto-corrected -- matched by the
    line's VALUE, not by line_id/position, since a different document's
    lines have entirely different row ids.
    """
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()
    _mock_ebs_success(monkeypatch)

    _seed_open_invoice_exception(
        "src_line_a", "Acme Parts", item_name="abc-x", description="0001-0120xxx Item not found in the PO Number"
    )
    header_a = legacy_repo.get_invoice_header("src_line_a")
    line_a = legacy_repo.get_invoice_lines(header_a["id"])[0]

    outcome = api_repo.edit_and_reprocess(
        "src_line_a", line_edits=[{"line_id": line_a["id"], "field": "item_name", "value": "abc-1"}]
    )
    assert outcome["success"] is True
    assert outcome["line_fields_applied"] == [
        {"match_field": "item_name", "match_value": "abc-x", "set_field": "item_name", "set_value": "abc-1"}
    ]

    # A different document, with its own distinct line_id, hits the same
    # supplier + exception type with the same bad item number.
    _seed_open_invoice_exception(
        "src_line_b", "Acme Parts", item_name="abc-x", description="0001-0120xxx Item not found in the PO Number"
    )
    header_b = legacy_repo.get_invoice_header("src_line_b")
    line_b_before = legacy_repo.get_invoice_lines(header_b["id"])[0]
    assert line_b_before["id"] != line_a["id"]  # genuinely a different row

    result = NATIVE_TOOL_HANDLERS["apply_learned_correction"](
        src_id="src_line_b", supplier_name="Acme Parts", exception_type="invalid_item"
    )

    assert result["applied"] is True
    assert result["line_fields_applied"] == [
        {"line_id": line_b_before["id"], "match_field": "item_name", "match_value": "abc-x", "set_field": "item_name", "set_value": "abc-1"}
    ]
    updated_line_b = legacy_repo.get_invoice_lines(header_b["id"])[0]
    assert updated_line_b["item_name"] == "abc-1"


def test_escalate_to_human_is_registered_as_a_tool():
    names = {schema["name"] for schema in NATIVE_TOOL_SCHEMAS}
    assert "escalate_to_human" in names
    assert "escalate_to_human" in NATIVE_TOOL_HANDLERS


def test_escalate_to_human_writes_both_log_table_and_outcomes_log():
    """This is the exact gap that let a document get narrated as 'flagged
    for review' while never showing up in Manual Review: log_outcome
    (outcomes_log) and log_event (log_table) were two separate LLM-driven
    tool calls that could silently get split across turns. escalate_to_human
    must write both, in one call, every time.
    """
    from db.new_schema import OutcomesLog
    from db.session import session_scope
    from sqlalchemy import select

    _seed_open_invoice_exception("src_escalate_a", "Blocked Corp", description="Invoice Amount:2000 exceeds total receipt quantity value:1200")

    result = NATIVE_TOOL_HANDLERS["escalate_to_human"](
        src_id="src_escalate_a",
        supplier_name="Blocked Corp",
        exception_type="amount_overapply",
        action_recommended="request_po_correction",
        reason="System is in shadow mode: recommend only, human acts.",
    )
    assert result["escalated"] is True

    latest_log = legacy_repo.get_latest_log("src_escalate_a")
    assert latest_log["status"] == "Failed"
    assert latest_log["description"] == "System is in shadow mode: recommend only, human acts."

    with session_scope() as session:
        outcome = session.scalars(select(OutcomesLog).where(OutcomesLog.src_id == "src_escalate_a")).one()
    assert outcome.decided_by == "human"
    assert outcome.action_taken == "request_po_correction"


def test_escalate_to_human_can_hold_instead_of_fail():
    _seed_open_invoice_exception("src_escalate_hold", "Blocked Corp")
    NATIVE_TOOL_HANDLERS["escalate_to_human"](
        src_id="src_escalate_hold",
        supplier_name="Blocked Corp",
        exception_type="voucher_hold",
        action_recommended="auto_approve",
        reason="not authorized",
        hold=True,
    )
    assert legacy_repo.get_latest_log("src_escalate_hold")["status"] == "OnHold"


def test_apply_learned_email_is_registered_as_a_tool():
    names = {schema["name"] for schema in NATIVE_TOOL_SCHEMAS}
    assert "apply_learned_email" in names
    assert "apply_learned_email" in NATIVE_TOOL_HANDLERS


def test_apply_learned_email_refuses_without_a_similar_past_case(monkeypatch, chroma_dir):
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()

    _seed_open_invoice_exception("src_email_never_seen", "Nobody Corp")
    result = NATIVE_TOOL_HANDLERS["apply_learned_email"](
        src_id="src_email_never_seen", supplier_name="Nobody Corp", exception_type="amount_overapply"
    )
    assert result["applied"] is False
    assert result["reason"] == "no_sufficiently_similar_past_correction"


def test_apply_learned_email_refuses_in_shadow_mode_even_with_a_precedent(monkeypatch, chroma_dir):
    from db.legacy_schema import EmailRecord
    from db.session import session_scope
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "shadow")
    get_settings.cache_clear()

    _seed_open_invoice_exception("src_email_shadow_a", "Shadow Email Corp", description="Invoice Amount:2000 exceeds total receipt quantity value:1200")
    with session_scope() as session:
        session.add(EmailRecord(src_id="src_email_shadow_a", from_email="ap@shadow.example", subject="Invoice"))
    monkeypatch.setattr("mcp_servers.common.graph_client.send_mail", lambda *a, **kw: {"sent": True})
    first = api_repo.send_supplier_email("src_email_shadow_a", "subject", "<p>body</p>")
    assert first["success"] is True

    _seed_open_invoice_exception("src_email_shadow_b", "Shadow Email Corp", description="Invoice Amount:2000 exceeds total receipt quantity value:1200")
    result = NATIVE_TOOL_HANDLERS["apply_learned_email"](
        src_id="src_email_shadow_b", supplier_name="Shadow Email Corp", exception_type="amount_overapply"
    )
    assert result["applied"] is False
    assert "not_authorized" in result["reason"]


def test_apply_learned_email_replays_a_past_human_send(monkeypatch, chroma_dir):
    """The exact loop the user asked for: a human sends the supplier an
    email once (via api/repo.py:send_supplier_email, the frontend's "Send
    email now" action), and the next occurrence of the same
    (supplier, exception_type) gets auto-emailed by apply_learned_email.
    """
    from db.legacy_schema import EmailRecord
    from db.session import session_scope
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()
    sent_calls = []
    monkeypatch.setattr(
        "mcp_servers.common.graph_client.send_mail",
        lambda to, subject, body, conv=None, attachment_paths=None: sent_calls.append(to) or {"sent": True, "to": to},
    )

    description = "Invoice Amount:2000 exceeds total receipt quantity value:1200"
    _seed_open_invoice_exception("src_email_a", "Repeat Offender Co", description=description)
    with session_scope() as session:
        session.add(EmailRecord(src_id="src_email_a", from_email="ap@repeatoffender.example", subject="Invoice"))

    first = api_repo.send_supplier_email("src_email_a", "Correction needed", "<p>please fix</p>")
    assert first["success"] is True
    assert sent_calls == ["ap@repeatoffender.example"]

    _seed_open_invoice_exception("src_email_b", "Repeat Offender Co", description=description)
    with session_scope() as session:
        session.add(EmailRecord(src_id="src_email_b", from_email="ap@repeatoffender.example", subject="Invoice"))

    result = NATIVE_TOOL_HANDLERS["apply_learned_email"](
        src_id="src_email_b", supplier_name="Repeat Offender Co", exception_type="amount_overapply"
    )
    assert result["applied"] is True
    assert result["sent"] is True
    assert sent_calls == ["ap@repeatoffender.example", "ap@repeatoffender.example"]

    latest_log = legacy_repo.get_latest_log("src_email_b")
    assert latest_log["status"] == "OnHold"


def test_apply_learned_email_replays_after_a_prior_escalation_on_the_same_src_id(monkeypatch, chroma_dir):
    """Regression test for the exact bug report: src_412 got escalated first
    (bandit said "escalate", not an email action), a human then sent the
    supplier an email from Manual Review for that same src_id, and src_413
    -- a second occurrence for the same supplier/exception_type -- should
    then get auto-emailed. It didn't: escalate_to_human's own bookkeeping
    row (whatever `reason` text it was given, e.g. "bandit recommended
    escalate") was overwriting log_table's description, so
    send_supplier_email's classify_erp_error(latest_log) call reclassified
    the exception as "unknown" instead of "amount_overapply" when it logged
    the correction -- and the next document's apply_learned_email search
    (correctly) found no precedent under the real exception_type. Fixed by
    (a) having escalate_to_human/_send_and_log_email write stage="MCP" for
    their own bookkeeping rows instead of inheriting the ERP target, and (b)
    having api/repo.py classify against the last EBS/JDE-stage row instead
    of just the latest row overall.
    """
    from sqlalchemy import select

    from db.legacy_schema import EmailRecord
    from db.new_schema import Correction
    from db.session import session_scope
    from api import repo as api_repo
    from config.settings import get_settings

    monkeypatch.setenv("AUTONOMY_STAGE", "limited")
    get_settings.cache_clear()
    monkeypatch.setattr("mcp_servers.common.graph_client.send_mail", lambda *a, **kw: {"sent": True})

    description = "Invoice Amount:2000 exceeds total receipt quantity value: total_amount_received:1200"

    # First occurrence: the bandit recommends "escalate" and the agent calls
    # escalate_to_human -- exactly src_412's path, before any email precedent
    # exists yet.
    _seed_open_invoice_exception("src_escalate_then_email_a", "Advantage Corp", description=description)
    NATIVE_TOOL_HANDLERS["escalate_to_human"](
        src_id="src_escalate_then_email_a",
        supplier_name="Advantage Corp",
        exception_type="amount_overapply",
        action_recommended="escalate",
        reason="bandit recommended escalate",
    )

    # A human then sends the supplier an email for that same src_id from the
    # Manual Review page.
    with session_scope() as session:
        session.add(EmailRecord(src_id="src_escalate_then_email_a", from_email="ap@advantage.example", subject="Invoice"))
    sent = api_repo.send_supplier_email("src_escalate_then_email_a", "Correction needed", "<p>please fix</p>")
    assert sent["success"] is True

    with session_scope() as session:
        correction = session.scalars(
            select(Correction).where(Correction.src_id == "src_escalate_then_email_a")
        ).one()
    assert correction.exception_type == "amount_overapply"

    # A second, near-identical document for the same supplier hits the same
    # exception -- apply_learned_email should now find the precedent above.
    _seed_open_invoice_exception("src_escalate_then_email_b", "Advantage Corp", description=description)
    with session_scope() as session:
        session.add(EmailRecord(src_id="src_escalate_then_email_b", from_email="ap@advantage.example", subject="Invoice"))

    result = NATIVE_TOOL_HANDLERS["apply_learned_email"](
        src_id="src_escalate_then_email_b", supplier_name="Advantage Corp", exception_type="amount_overapply"
    )
    assert result["applied"] is True
    assert result["sent"] is True


def test_send_supplier_email_attaches_the_source_pdf(monkeypatch, tmp_path):
    """The email a human sends from Manual Review (and any auto-replayed
    one) should attach the invoice's own original file, resolved from
    source.folder_path/atch_nm, not require the sender to attach it by hand.
    """
    from db.legacy_schema import EmailRecord
    from db.session import session_scope as _session_scope
    from api import repo as api_repo

    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    _seed_open_invoice_exception("src_attach_email", "Acme Parts")
    with _session_scope() as session:
        source = session.query(Source).filter_by(src_id="src_attach_email").one()
        source.folder_path = str(tmp_path)
        source.atch_nm = "invoice.pdf"
        session.add(EmailRecord(src_id="src_attach_email", from_email="ap@acmeparts.example", subject="Invoice"))

    captured = {}
    monkeypatch.setattr(
        "mcp_servers.common.graph_client.send_mail",
        lambda *a, attachment_paths=None, **kw: captured.update(attachment_paths=attachment_paths) or {"sent": True},
    )

    result = api_repo.send_supplier_email("src_attach_email", "Correction needed", "<p>please fix</p>")

    assert result["success"] is True
    assert captured["attachment_paths"] == [str(tmp_path / "invoice.pdf")]

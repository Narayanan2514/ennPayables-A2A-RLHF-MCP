"""Tests for supplier_communication_server.send_email -- it must always send
to whoever the document actually arrived from (the `email` table row
email_module/service.py wrote on ingestion), never an address the caller
supplies, since an LLM-supplied recipient is exactly how a real email nearly
went to the wrong address in production.
"""
from db.legacy_schema import EmailRecord, Source
from db.session import session_scope
from mcp_servers import supplier_communication_server as scs


def _seed_source_with_email(src_id, from_email, conversation_id="conv-123"):
    with session_scope() as session:
        session.add(Source(src_id=src_id, target="EBS", doc_type="invoice", channel="email"))
        session.add(EmailRecord(src_id=src_id, from_email=from_email, subject="Invoice attached", coversationId=conversation_id))


def test_send_email_uses_the_real_sender_address_not_a_supplied_one(monkeypatch):
    _seed_source_with_email("src_email_1", "ap@realsupplier.com", conversation_id="conv-abc")

    captured = {}

    def fake_send_mail(to_address, subject, body_html, conversation_id=None, attachment_paths=None):
        captured["to_address"] = to_address
        captured["conversation_id"] = conversation_id
        captured["attachment_paths"] = attachment_paths
        return {"sent": True, "to": to_address, "subject": subject}

    monkeypatch.setattr(scs, "send_mail", fake_send_mail)

    result = scs.send_email(src_id="src_email_1", subject="PO correction needed", body_html="<p>please confirm PO</p>")

    assert captured["to_address"] == "ap@realsupplier.com"
    assert captured["conversation_id"] == "conv-abc"
    assert result["sent"] is True
    assert result["conversation_id"] == "conv-abc"


def test_send_email_attaches_the_documents_original_files(monkeypatch, tmp_path):
    """The supplier shouldn't have to go dig up their own copy of the
    invoice we're asking them about -- send_email should attach whatever
    file(s) this src_id's source row says it arrived with.
    """
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    with session_scope() as session:
        session.add(
            Source(
                src_id="src_email_attach",
                target="EBS",
                doc_type="invoice",
                channel="email",
                folder_path=str(tmp_path),
                atch_nm="invoice.pdf",
            )
        )
        session.add(EmailRecord(src_id="src_email_attach", from_email="ap@realsupplier.com", subject="Invoice attached"))

    captured = {}

    def fake_send_mail(to_address, subject, body_html, conversation_id=None, attachment_paths=None):
        captured["attachment_paths"] = attachment_paths
        return {"sent": True, "to": to_address, "subject": subject}

    monkeypatch.setattr(scs, "send_mail", fake_send_mail)

    scs.send_email(src_id="src_email_attach", subject="Correction needed", body_html="<p>please fix</p>")

    assert captured["attachment_paths"] == [str(tmp_path / "invoice.pdf")]


def test_send_email_refuses_when_no_sender_is_on_file(monkeypatch):
    with session_scope() as session:
        session.add(Source(src_id="src_email_no_record", target="EBS", doc_type="invoice", channel="email"))
    # No EmailRecord inserted -- the document has no known sender.

    called = {"count": 0}
    monkeypatch.setattr(scs, "send_mail", lambda *a, **k: called.update(count=called["count"] + 1))

    result = scs.send_email(src_id="src_email_no_record", subject="x", body_html="y")

    assert result["sent"] is False
    assert called["count"] == 0  # never attempted to send anywhere

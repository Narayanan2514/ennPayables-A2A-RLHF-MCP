from db.legacy_schema import Source
from db.session import session_scope
from mcp_servers.common import legacy_repo


def _seed_source(src_id="src_001", target="EBS", doc_type="invoice"):
    with session_scope() as session:
        session.add(Source(src_id=src_id, target=target, doc_type=doc_type, channel="email"))


def test_insert_and_get_invoice_round_trips():
    _seed_source()
    header_id = legacy_repo.insert_invoice(
        "src_001",
        {
            "supplier_name": "3M Health Care",
            "invoice_number": "24020",
            "customer_po_number": "6739",
            "currency_code": "USD",
            "total": "100.00",
            "payment_terms": "Immediate",
        },
        [
            {"line_number": "1", "item_name": "0001-0120H", "item_description": "SHACKLE 0001", "quantity": "1", "total": "50"},
            {"line_number": "2", "item_name": "0001-0120J", "item_description": "SHACKLE 0002", "quantity": "1", "total": "50"},
        ],
    )
    header = legacy_repo.get_invoice_header("src_001")
    assert header["id"] == header_id
    assert header["invoice_number"] == "24020"
    assert header["invoice_amount"] == 100.0

    lines = legacy_repo.get_invoice_lines(header_id)
    assert len(lines) == 2


def test_update_invoice_field_rejects_non_allowlisted_field():
    _seed_source()
    header_id = legacy_repo.insert_invoice("src_001", {"invoice_number": "1"}, [])
    try:
        legacy_repo.update_invoice_field(header_id, "bill_to", "hacked")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_update_invoice_field_allows_allowlisted_field():
    _seed_source()
    header_id = legacy_repo.insert_invoice("src_001", {"invoice_number": "1"}, [])
    assert legacy_repo.update_invoice_field(header_id, "invoice_number", "2") is True
    assert legacy_repo.get_invoice_header("src_001")["invoice_number"] == "2"


def test_log_event_deactivates_prior_rows_and_list_exceptions_sees_active():
    _seed_source(src_id="src_002")
    legacy_repo.insert_log("src_002", "Failed", "EBS", "PO Number not found!:673900")
    exceptions = legacy_repo.list_exceptions()
    assert any(e["entity_id"] == "src_002" and e["is_reviewed"] == "0" for e in exceptions)

    legacy_repo.insert_log("src_002", "Successful", "EBS", "reprocessed ok", is_reviewed="1", action_taken="Reprocessed")
    exceptions_after = legacy_repo.list_exceptions()
    assert not any(e["entity_id"] == "src_002" for e in exceptions_after)


def test_get_source_attachment_paths_resolves_existing_files_and_skips_missing(tmp_path):
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    # "cover.pdf" is listed in atch_nm (as download_attachments would record
    # every non-inline attachment) but was never actually written to disk --
    # get_source_attachment_paths must skip it rather than raising.
    with session_scope() as session:
        session.add(
            Source(
                src_id="src_attach_1",
                target="EBS",
                doc_type="invoice",
                channel="email",
                folder_path=str(tmp_path),
                atch_nm="invoice.pdf, cover.pdf",
            )
        )

    paths = legacy_repo.get_source_attachment_paths("src_attach_1")
    assert paths == [str(tmp_path / "invoice.pdf")]


def test_get_source_attachment_paths_returns_empty_when_no_attachments_recorded():
    _seed_source(src_id="src_attach_2")
    assert legacy_repo.get_source_attachment_paths("src_attach_2") == []

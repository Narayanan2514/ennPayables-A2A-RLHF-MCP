from learning.exemplar_refresh import get_active_exemplars, refresh_exemplars
from learning.feedback_logger import log_correction
from learning.vector_memory import search_similar_cases


def test_log_correction_persists_row_and_embedding(chroma_dir):
    correction_id = log_correction(
        src_id="src_100",
        supplier_name="Acme Corp",
        doc_type="invoice",
        exception_type="invalid_po",
        invoice_features={"invoice_amount": 500, "currency": "USD", "po_number": "6739"},
        ai_recommendation="request_po_correction",
        human_action="emailed supplier for corrected PO",
        ai_recommendation_correct=False,
        confidence_at_decision=0.6,
    )
    assert correction_id > 0


def test_search_similar_cases_finds_indexed_case(chroma_dir):
    log_correction(
        src_id="src_101",
        supplier_name="Acme Corp",
        doc_type="invoice",
        exception_type="invalid_po",
        invoice_features={"invoice_amount": 510, "currency": "USD", "po_number": "6739"},
        ai_recommendation="request_po_correction",
        human_action="emailed supplier for corrected PO",
        ai_recommendation_correct=False,
        confidence_at_decision=0.55,
    )

    results = search_similar_cases(
        supplier_name="Acme Corp",
        exception_type="invalid_po",
        features={"invoice_amount": 505, "currency": "USD", "po_number": "6739"},
    )
    assert len(results) >= 1
    assert results[0]["metadata"]["supplier_name"] == "Acme Corp"


def test_search_returns_empty_for_unseen_supplier(chroma_dir):
    results = search_similar_cases(
        supplier_name="Never Seen Before Inc",
        exception_type="invalid_po",
        features={"invoice_amount": 10},
    )
    assert results == []


def test_refresh_exemplars_only_uses_incorrect_recommendations(chroma_dir):
    log_correction(
        src_id="src_102",
        supplier_name="Beta LLC",
        doc_type="invoice",
        exception_type="invalid_item",
        invoice_features={"item_name": "0001-0120xxx"},
        ai_recommendation="0001-0120xxx",
        human_action="0001-0120H",
        ai_recommendation_correct=False,
    )
    log_correction(
        src_id="src_103",
        supplier_name="Beta LLC",
        doc_type="invoice",
        exception_type="invalid_item",
        invoice_features={"item_name": "0001-0120H"},
        ai_recommendation="0001-0120H",
        human_action="0001-0120H",
        ai_recommendation_correct=True,
    )

    summary = refresh_exemplars()
    assert summary["exemplars_written"] == 1

    exemplars = get_active_exemplars("Beta LLC", "invoice")
    assert len(exemplars) == 1
    assert exemplars[0]["correct_output"] == "0001-0120H"

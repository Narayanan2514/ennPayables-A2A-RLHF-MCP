from orchestrator.verifier_agent import Verdict, verify_invoice

HEADER = {
    "invoice_number": "24020",
    "supplier_name": "3M Health Care",
    "customer_po_number": "6739",
    "invoice_amount": 100.0,
}
LINES = [{"total": "50"}, {"total": "50"}]


def test_clean_invoice_passes():
    result = verify_invoice(
        "src_001", HEADER, LINES, po_match={"matched": True, "po_total": 200, "within_envelope": True}, supplier_known=True,
        use_llm_narration=False,
    )
    assert result.verdict == Verdict.PASS
    assert result.violations == []


def test_missing_invoice_number_blocks():
    header = {**HEADER, "invoice_number": ""}
    result = verify_invoice("src_002", header, LINES, po_match=None, supplier_known=True, use_llm_narration=False)
    assert result.verdict == Verdict.BLOCK
    assert any(v.rule == "missing_invoice_number" for v in result.violations)


def test_po_not_found_blocks():
    result = verify_invoice(
        "src_003", HEADER, LINES, po_match={"matched": False}, supplier_known=True, use_llm_narration=False
    )
    assert result.verdict == Verdict.BLOCK
    assert any(v.rule == "po_not_found" for v in result.violations)


def test_severe_amount_overapply_blocks():
    header = {**HEADER, "invoice_amount": 1000.0}
    result = verify_invoice(
        "src_004", header, LINES, po_match={"matched": True, "po_total": 200, "within_envelope": False},
        supplier_known=True, use_llm_narration=False,
    )
    assert result.verdict == Verdict.BLOCK
    assert any(v.rule == "amount_overapply_severe" for v in result.violations)


def test_unknown_supplier_flags_not_blocks():
    result = verify_invoice(
        "src_005", HEADER, LINES, po_match={"matched": True, "po_total": 200, "within_envelope": True},
        supplier_known=False, use_llm_narration=False,
    )
    assert result.verdict == Verdict.FLAG
    assert any(v.rule == "unknown_supplier" for v in result.violations)

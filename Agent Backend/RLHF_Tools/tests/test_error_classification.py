from mcp_servers.common.errors import ExceptionType, classify_erp_error


def test_invalid_item_message():
    result = classify_erp_error("0001-0120xxx Item not found in the PO Number")
    assert result.exception_type == ExceptionType.INVALID_ITEM


def test_invalid_po_message():
    result = classify_erp_error("PO Number not found!:673900")
    assert result.exception_type == ExceptionType.INVALID_PO


def test_duplicate_invoice_message():
    result = classify_erp_error("Invoice Number Already Exists for this Supplier !")
    assert result.exception_type == ExceptionType.DUPLICATE_INVOICE


def test_amount_overapply_message():
    result = classify_erp_error("Invoice Amount:2000 exceeds total receipt quantity value: total_amount_received:1200")
    assert result.exception_type == ExceptionType.AMOUNT_OVERAPPLY


def test_unknown_message_falls_back():
    result = classify_erp_error("some completely novel oracle error text")
    assert result.exception_type == ExceptionType.UNKNOWN
    assert result.action_space == ["escalate"]


def test_none_message_does_not_raise():
    result = classify_erp_error(None)
    assert result.exception_type == ExceptionType.UNKNOWN

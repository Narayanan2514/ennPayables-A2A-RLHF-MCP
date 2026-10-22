"""Document-Intelligence MCP Server (proposal Section 3).

"extract fields, classify document type, and return a confidence score per
field (see Section 4.1)."

Field lists below match ennvault-existing's proven prompts (audit section 4:
llm_service/inv_extract.py, po_extract.py, remit_extract.py, bdoc_extract.py)
so extraction quality doesn't regress -- only the confidence layer and
exemplar injection are new. Confidence comes from self-consistency sampling
(mcp_servers/common/llm_extraction.py), one of the three sources the proposal
names in Section 4.1.

Served over Streamable-HTTP with HTTP Basic Auth (see mcp_servers/common/auth.py).
Run standalone for local testing:
    python -m mcp_servers.document_intelligence_server
"""
from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP  # mcp>=2.0.0 renamed FastMCP -> MCPServer; alias kept for readability

from mcp_servers.common.llm_extraction import extract_with_confidence

mcp = FastMCP("document-intelligence")


def _build_system_prompt(role_description: str, header_fields: list[str], line_fields: list[str] | None, few_shot_exemplars: list[dict] | None) -> str:
    prompt = (
        f"You are an expert AP document-extraction assistant. {role_description}\n"
        f"Return ONLY a JSON object with these header fields: {header_fields}.\n"
    )
    if line_fields:
        prompt += f"Include a 'line_items' array where each item has: {line_fields}.\n"
    if few_shot_exemplars:
        prompt += "\nHere are examples of correct extractions for this supplier, learned from past human corrections:\n"
        for ex in few_shot_exemplars[:5]:
            prompt += f"- {ex}\n"
    return prompt


@mcp.tool()
def classify_document(image_paths: list[str]) -> dict[str, Any]:
    """Classify a document's type (invoice / purchase_order / remittance / bank)
    from its page image(s), replacing ennvault-existing's email-subject-only
    regex classifier (audit section 2) with content-based classification so
    documents with an ambiguous subject line aren't silently dropped.
    """
    system_prompt = (
        "Classify this business document into exactly one of: invoice, purchase_order, "
        "remittance, bank. Return JSON: {\"doc_type\": \"...\", \"reasoning\": \"...\"}."
    )
    result = extract_with_confidence(system_prompt, image_paths, n_samples=3)
    return {
        "doc_type": result.fields.get("doc_type", "unknown"),
        "confidence": result.field_confidence.get("doc_type", result.overall_confidence),
    }


@mcp.tool()
def extract_invoice(
    image_paths: list[str],
    target_erp: str = "EBS",
    few_shot_exemplars: list[dict] | None = None,
) -> dict[str, Any]:
    """Extract invoice header + line fields with per-field confidence scores.

    Field set matches ennvault-existing's EBS/JDE invoice prompts exactly
    (audit section 4) so downstream ERP payload mapping is a drop-in match.
    """
    if target_erp.upper() == "JDE":
        header_fields = ["company", "supplier_number", "invoice_number", "invoice_date"]
        line_fields = ["line_number", "purchase_order_number", "item_number", "description", "quantity", "unit_price", "gross_amount"]
    else:
        header_fields = [
            "bill_to", "ship_to", "customer_po_number", "invoice_date", "customer_name",
            "customer_number", "supplier_name", "invoice_number", "currency_code",
            "sales_order_number", "invoice_duedate", "subject", "total", "payment_terms",
            "shipping_point", "fob_point", "freight_carrier",
        ]
        line_fields = ["line_number", "item_name", "item_description", "ordered_quantity", "unit_of_measure", "price", "total"]

    system_prompt = _build_system_prompt(
        f"This is an accounts-payable invoice destined for {target_erp}.", header_fields, line_fields, few_shot_exemplars
    )
    result = extract_with_confidence(system_prompt, image_paths, n_samples=3)
    return {
        "fields": result.fields,
        "field_confidence": result.field_confidence,
        "overall_confidence": result.overall_confidence,
    }


@mcp.tool()
def extract_po(image_paths: list[str], few_shot_exemplars: list[dict] | None = None) -> dict[str, Any]:
    """Extract purchase-order header + line fields with per-field confidence.

    Matches ennvault-existing's po_extract.py field set (EBS-only today).
    """
    header_fields = [
        "po_number", "po_date", "customer_name", "customer_number", "payment_terms",
        "currency", "ship_method", "shipping_via", "freight_terms", "total_amount",
        "ship_to", "bill_to",
    ]
    line_fields = ["line_number", "item_number", "item_description", "quantity", "unit_of_measure", "unit_price", "net_amount", "requested_date"]
    system_prompt = _build_system_prompt("This is a purchase order.", header_fields, line_fields, few_shot_exemplars)
    result = extract_with_confidence(system_prompt, image_paths, n_samples=3)
    return {
        "fields": result.fields,
        "field_confidence": result.field_confidence,
        "overall_confidence": result.overall_confidence,
    }


@mcp.tool()
def extract_remit(
    image_paths: list[str],
    target_erp: str = "EBS",
    few_shot_exemplars: list[dict] | None = None,
) -> dict[str, Any]:
    """Extract remittance-advice header + line fields with per-field confidence."""
    header_fields = ["customer", "customer_number", "ref_number", "total_amnt", "currency", "date"]
    line_fields = ["l_ref_id", "date", "org_amnt", "disc_amnt"]
    system_prompt = _build_system_prompt(
        f"This is a remittance advice destined for {target_erp}.", header_fields, line_fields, few_shot_exemplars
    )
    result = extract_with_confidence(system_prompt, image_paths, n_samples=3)
    return {
        "fields": result.fields,
        "field_confidence": result.field_confidence,
        "overall_confidence": result.overall_confidence,
    }


@mcp.tool()
def extract_bank_doc(image_paths: list[str]) -> dict[str, Any]:
    """Extract bank-statement/reference-document fields (ref_num, bank_nm, amnt)
    used purely as the AR-matching counterpart to remittances.
    """
    header_fields = ["ref_num", "bank_nm", "amnt"]
    system_prompt = _build_system_prompt("This is a bank reference/ACH-credit document.", header_fields, None, None)
    result = extract_with_confidence(system_prompt, image_paths, n_samples=3)
    return {
        "fields": result.fields,
        "field_confidence": result.field_confidence,
        "overall_confidence": result.overall_confidence,
    }


if __name__ == "__main__":
    from config.settings import get_settings
    from mcp_servers.common.auth import run_streamable_http

    _settings = get_settings()
    run_streamable_http(
        mcp,
        host=_settings.mcp_host,
        port=_settings.document_intelligence_port,
        username=_settings.mcp_username,
        password=_settings.mcp_password,
    )

"""Vision-based invoice field extraction over Agent 2's PII-masked page
images, decoded back via decoder.decode_fields.

Exact port of ennVault_org_backend/modules/processing/entity_extractor/
llm_service/inv_extract.py: same two prompts (`build_inv_prompt_jde`/
`build_inv_prompt_ebs`), same GPT-4o vision call shape, same header/line
field taxonomy per ERP. Replaces this agent's former pypdf-text-only
extraction (which only ever produced the JDE taxonomy and had no vision
step at all) with the real per-ERP vision extraction org_backend uses --
see INV_ERP_ROUTER below, an exact port of inv_extract.py's own router.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

from openai import OpenAI

from .decoder import decode_fields
from shared.config.settings import OPENAI_API_KEY, OPENAI_VISION_MODEL


class ExtractionError(Exception):
    pass


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _human_content(encoded_images: list[str]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": "Extract invoice fields from the images."}]
    for b64 in encoded_images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return content


def _call_vision(system_prompt: str, encoded_images: list[str], temperature: float = 0) -> dict:
    if not OPENAI_API_KEY:
        raise ExtractionError("OPENAI_API_KEY is not configured -- required for invoice field extraction.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_VISION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _human_content(encoded_images)},
        ],
        temperature=temperature,
    )
    content = response.choices[0].message.content or ""
    cleaned = content.strip().strip("```json").strip("```")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Model did not return valid JSON: {exc}. Raw: {content[:500]}") from exc


def _correction_hint_block(correction_hint: str | None) -> str:
    """Appended to a prompt only on a self-correction retry (see
    extraction_service.reextract_line_item) -- never on a normal first-pass
    extraction, where correction_hint is None."""
    if not correction_hint:
        return ""
    return f"""

NOTE: a previous submission of this invoice was REJECTED by the ERP: {correction_hint}
Re-examine every line item's item number/description carefully -- do not assume your first
reading was correct. Look closely at the exact characters in the item field for the affected
line; a similar-looking but different value is a common misread.
"""



def build_inv_prompt_ebs(correction_hint: str | None = None) -> str:
    return """
You are an AI that extracts structured invoice data from encoded images.

Return ONLY a single valid JSON object in this exact structure:

{
  "header": {
    "bill_to": "",
    "ship_to": "",
    "customer_po_number": "",
    "invoice_date": "",
    "customer_name": "",
    "customer_number": "",
    "supplier_name": "",
    "invoice_number": "",
    "currency_code": "",
    "sales_order_number": "",
    "invoice_duedate": "",
    "subject": "",
    "total": "",
    "payment_terms": "",
    "shipping_point": "",
    "fob_point": "",
    "freight_carrier": ""
  },
  "line_items": [
    {
      "line_number": "",
      "item_name": "",
      "item_description": "",
      "ordered_quantity": "",
      "unit_of_measure": "",
      "price": "",
      "total": ""
    }
  ]
}

STRICT RULES:
- Output MUST be valid JSON only (no markdown, no explanation, no backticks)
- Always include both "header" and "line_items" keys even if empty
- If any field is not found -> return empty string ""
- Invoice number, customer PO number, Bill to and Ship to are MANDATORY to search carefully
- If invoice number is missing, still return JSON with empty string (do NOT omit key)
- Line numbers must be sequential if missing (1,2,3...)
- Do not confuse Customer Part No with Item Number
- Understand layout spatially (top-bottom + left-right alignment both matter)
- Multi-line headers must be mapped correctly based on vertical alignment
- supplier_name is usually in top header section
- Line item details with total are mandatory
- If line item exist, total in header should not be zero. It should be the total of line items total amount
- price and total fields must contain only numeric values without currency symbols or currency codes
- customer_po_number and currency_code are almost always adjacent, separate table columns (e.g. "PO Number" | "Currency Code"). Each field must contain ONLY the value from its own single column/cell -- never concatenate an adjacent column's value onto another field. If you see two short values side by side, put each in its own field, not both in one.
""" + _correction_hint_block(correction_hint)

def build_inv_prompt_jde(correction_hint: str | None = None) -> str:
    return """
You are an AI that extracts structured invoice data from encoded images.

Return JSON in JDE-compatible structure.

Header Fields:
- company name
- supplier_number
- invoice_number
- invoice_date


Line Items:
- line_number (generate sequentially if missing)
- Purchase order number
- item_number
- description
- quantity
- unit_price
- gross_amount


Structure MUST be:

{
  "header": {
    "company": "",
    "supplier_number": "",
    "invoice_number":"",
    "invoice_date": ""
  },
  "line_items": [
    {
      "line_number": "",
      "Purchase order number": "",
      "item_number": "",
      "description": "",
      "quantity": "",
      "unit_price": "",
      "gross_amount": ""
    }
  ]
}

IMPORTANT:
- Strict JSON only
- No explanations, no markdown
- Invoice and PO numbers are mandatory.
- Understand the layout properly, not everything exist as left- right key pairs, some keys can be top-bottom as well.
- When you encounter a table with hierarchical (multi-row) headers and a row data spread across multiple lines, Map values to columns by aligning their horizontal position with headers and assigning vertically stacked values in order based on the multi-line header structure.
- When the column header is multi-line(stacked headers), its important to map the values in exact order below it.
- Do not map Customer Part No as Item number.
- If field not found -> empty string
- Generate line number sequentially if missing
- Company/ Compay name is ususally present in the header ( left side)
- supplier_number is ususally present as Vendor Nbr
- Dont exact keys to be present as such in the encoded image, understand the meaning and match the most appropriate equivalent keys
""" + _correction_hint_block(correction_hint)


_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _split_merged_po_and_currency(header: dict[str, Any]) -> None:
    """Defends against a vision-extraction failure mode observed in
    practice: when 'PO Number' and 'Currency Code' sit in adjacent table
    columns, the model sometimes reads both cells as one value (e.g.
    "6739 USD" instead of "6739" + "USD" in their own fields) --
    decode_fields then decodes each masked token independently, so the
    symptom is a customer_po_number ending in a bare 3-letter uppercase
    code. Mutates `header` in place."""
    po = (header.get("customer_po_number") or "").strip()
    match = re.match(r"^(.*\S)\s+([A-Za-z]{3})$", po)
    if not match:
        return
    candidate_po, candidate_currency = match.group(1), match.group(2).upper()
    if not _ISO_CURRENCY_RE.match(candidate_currency):
        return
    header["customer_po_number"] = candidate_po
    if not (header.get("currency_code") or "").strip():
        header["currency_code"] = candidate_currency


def _renumber_lines_sequentially(lines: list[dict[str, Any]]) -> None:
    """The prompt asks for sequential line_number values, but the vision
    model isn't reliable about it (observed: a label word like "RG" bleeding
    into line_number instead of a sequence number) -- list order already
    reflects the document's own row order, so just enforce it here rather
    than trust the model's own numbering."""
    for i, line in enumerate(lines, start=1):
        line["line_number"] = str(i)


def _safe_int(val) -> int:
    try:
        if val in (None, "", "None", "null"):
            return 0
        return int(float(str(val).replace(",", "").strip()))
    except Exception:
        return 0


def extract_invoice_ebs(encoded_image_paths: list[str], mapping_path: str, correction_hint: str | None = None) -> dict[str, Any]:
    """Port of inv_extract.py's inv_extract_ebs (minus the DB insert, which
    the caller -- extraction_service.process_invoice -- does per target_erp).

    correction_hint is only set on a self-correction retry (see
    extraction_service.reextract_line_item) -- it both changes the prompt
    (asking the model to re-examine line items) and raises the sampling
    temperature above 0, since a hint at temperature=0 would just
    deterministically reproduce the identical (wrong) first reading.
    """
    encoded_images = [_encode_image(p) for p in encoded_image_paths]
    if not encoded_images:
        raise ExtractionError("No page images to extract from.")

    temperature = 0.2 if correction_hint else 0
    data = _call_vision(build_inv_prompt_ebs(correction_hint), encoded_images, temperature)
    header = data.get("header", {})
    for key in (
        "bill_to", "ship_to", "customer_po_number", "invoice_date", "customer_name", "customer_number",
        "supplier_name", "invoice_number", "currency_code", "sales_order_number", "invoice_duedate", "subject",
        "total", "payment_terms", "shipping_point", "fob_point", "freight_carrier",
    ):
        header[key] = (header.get(key) or "").strip()
    lines_raw = data.get("line_items", [])

    decoded_header = decode_fields(mapping_path, header)
    decoded_lines = [decode_fields(mapping_path, line) for line in lines_raw]

    if not decoded_header.get("invoice_number", "").strip():
        raise ExtractionError("Invoice number missing after extraction -- skipping.")

    _split_merged_po_and_currency(decoded_header)
    _renumber_lines_sequentially(decoded_lines)

    header_total = str(decoded_header.get("total", "")).strip()
    if header_total in ("", "None") and decoded_lines:
        computed_total = sum(_safe_int(line.get("total", "")) for line in decoded_lines)
        decoded_header["total"] = str(computed_total)

    return {"header": decoded_header, "line_items": decoded_lines}


def extract_invoice_jde(encoded_image_paths: list[str], mapping_path: str, correction_hint: str | None = None) -> dict[str, Any]:
    """Port of inv_extract.py's inv_extract_jde (minus the DB insert). See
    extract_invoice_ebs's docstring for what correction_hint does."""
    encoded_images = [_encode_image(p) for p in encoded_image_paths]
    if not encoded_images:
        raise ExtractionError("No page images to extract from.")

    temperature = 0.2 if correction_hint else 0
    data = _call_vision(build_inv_prompt_jde(correction_hint), encoded_images, temperature)
    header_raw = data.get("header", {})
    lines_raw = data.get("line_items", [])

    decoded_header = decode_fields(mapping_path, header_raw)
    decoded_lines = [decode_fields(mapping_path, line) for line in lines_raw]

    if not decoded_header.get("invoice_number", "").strip():
        raise ExtractionError("Invoice number missing after extraction -- skipping.")

    _renumber_lines_sequentially(decoded_lines)

    return {"header": decoded_header, "line_items": decoded_lines}


# Exact port of inv_extract.py's INV_ERP_ROUTER -- the single dict-factory
# gate that decides which taxonomy/prompt is used for a given TARGET_ERP.
INV_ERP_ROUTER = {
    "EBS": extract_invoice_ebs,
    "JDE": extract_invoice_jde,
}


def extract_invoice(
    target_erp: str, encoded_image_paths: list[str], mapping_path: str, correction_hint: str | None = None
) -> dict[str, Any]:
    func = INV_ERP_ROUTER.get(target_erp.upper())
    if not func:
        raise ExtractionError(f"Unsupported ERP: {target_erp}")
    return func(encoded_image_paths, mapping_path, correction_hint)

import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from modules.processing.entity_extractor.decoder import decode_fields
from modules.processing.entity_extractor.db import *

# ---------------- INIT ----------------

load_dotenv(Path(__file__).resolve().parents[4] / ".env")
target_erp = os.getenv("TARGET_ERP")


llm = ChatOpenAI(
    model="gpt-4o",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0
)

# ---------------- UTILS ----------------

def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def load_images(folder_path):
    images = []
    for f in sorted(os.listdir(folder_path)):
        if f.lower().endswith((".png", ".jpg", ".jpeg")):
            images.append(encode_image(os.path.join(folder_path, f)))
    return images


def build_human_content_default(encoded_images):
    content = [{"type": "text", "text": "Extract invoice fields from the images."}]
    for b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    return content



#--------------- EBS Implementation------------------ 

def inv_extract_ebs(image_folder_path, mapping_path, config, folder_path):
    print("📄 EBS Invoice Extraction started:", image_folder_path)

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    messages = [
        SystemMessage(content=build_inv_prompt_ebs()),
        HumanMessage(content=build_human_content_default(encoded_images))
    ]

    response = llm.invoke(messages)

    try:
        cleaned = response.content.strip("```json").strip("```")
        data = json.loads(cleaned)
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    print("📦 Raw LLM Output:", data)

    # ---------------- DEFAULTS ----------------

    header = data.get("header", {})

    # header["bill_to"] = header.get("bill_to") or "V1- New York City, Vision Operations HQ, 90 Fifth Avenue, New York, US 10022-3422"
    # header["ship_to"] = header.get("ship_to") or "V1- New York City, Vision Operations HQ, 90 Fifth Avenue, New York, US 10022-3422"
    # header["supplier_name"] = header.get("supplier_name") or "3G Communications, Inc."
    # header["currency_code"] = header.get("currency_code") or "$"
    # header["payment_terms"] = header.get("payment_terms") or "Net 30 Days"
    # header["shipping_point"] = header.get("shipping_point") or "SHIPPING POINT"
    # header["fob_point"] = header.get("fob_point") or "SHIPPING POINT"

    header_keys = [
                "bill_to",
                "ship_to",
                "customer_po_number",
                "invoice_date",
                "customer_name",
                "customer_number",
                "supplier_name",
                "invoice_number",
                "currency_code",
                "sales_order_number",
                "invoice_duedate",
                "subject",
                "total",
                "payment_terms",
                "shipping_point",
                "fob_point",
                "freight_carrier"
            ]

    for key in header_keys:
        header[key] = (header.get(key) or "").strip()

    lines_raw = data.get("line_items", [])

    # ---------------- DECODE ----------------

    decoded_header = decode_fields(mapping_path, header)
    decoded_lines = [decode_fields(mapping_path, l) for l in lines_raw]

    print("🔓 Decoded Header:", decoded_header)
    print("🔓 Decoded Lines:", decoded_lines)

    # ---------------- VALIDATION ----------------

    invoice_number = decoded_header.get("invoice_number", "").strip()

    if not invoice_number:
        print("❌ Invoice number missing → skipping insert")
        return
    
    #fall backkk 
    # def safe_int(val):
    #     try:
    #         if val is None:
    #             return 0
    #         val = str(val).replace(",", "").strip()
    #         return int(float(val)) if val else 0
    #     except:
    #         return 0
    # header_total = str(decoded_header.get("total", "")).strip()

    # if not header_total and decoded_lines:
    #     computed_total = 0

    #     for line in decoded_lines:
    #         line_total = (
    #             line.get("amount")
    #             or line.get("line_total")
    #             or line.get("extended_price")
    #             or 0
    #         )
    #         computed_total += safe_int(line_total)

    #     decoded_header["total"] = str(computed_total)

    #     print("🧮 Header total missing → computed from lines:", decoded_header["total"])

    def safe_int(val):
        try:
            if val in (None, "", "None", "null"):
                return 0
            val = str(val).replace(",", "").strip()
            return int(float(val))
        except:
            return 0

    print("--------header total type----------------",(decoded_header.get("total", "")),type(decoded_header.get("total", "")))
    header_total = str(decoded_header.get("total", "")).strip()

    if header_total in ("", "None") and decoded_lines:
        computed_total = 0

        for line in decoded_lines:
            line_total = line.get("total", "")
            computed_total += safe_int(line_total)

        decoded_header["total"] = str(computed_total)

        print("🧮 Header total computed from line totals:", decoded_header["total"])
    # ---------------- DB ----------------

    header_id = insert_inv_header(decoded_header, folder_path)

    if not header_id:
        print("❌ Header insert failed")
        return

    for line in decoded_lines:
        insert_inv_line(header_id, line)

    print("✅ EBS Invoice processed:", os.path.basename(folder_path))

#------------------JDE Implementation------------

def inv_extract_jde(image_folder_path, mapping_path, config, folder_path):

    print("📄 JDE Invoice Extraction started:", image_folder_path)

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    # ---------------- LLM ----------------
    messages = [
        SystemMessage(content=build_inv_prompt_jde()),
        HumanMessage(content=build_human_content_default(encoded_images))
    ]
    response = llm.invoke(messages)

    try:
        data = json.loads(response.content.strip("```json").strip("```"))
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    print("📦 Raw JDE Output:", data)

    # ---------------- DECODE ----------------
    header_raw = data.get("header", {})
    lines_raw = data.get("line_items", [])

    decoded_header = decode_fields(mapping_path, header_raw)
    decoded_lines = [decode_fields(mapping_path, l) for l in lines_raw]

    print("🔓 Decoded Header:", decoded_header)
    print("🔓 Decoded Lines:", decoded_lines)

    # ---------------- VALIDATION ----------------

    invoice_number = decoded_header.get("invoice_number", "").strip()

    if not invoice_number:
        print("❌ Invoice number missing → skipping insert")
        return

    # ---------------- DB ----------------

    header_id = insert_jde_inv_header(decoded_header, folder_path)

    if not header_id:
        print("❌ Header insert failed")
        return

    insert_jde_inv_lines(header_id, decoded_lines)

    print("✅ JDE Invoice processed:", os.path.basename(folder_path))



# ---------------- MAIN ----------------

INV_ERP_ROUTER = {
    "EBS": inv_extract_ebs,
    "JDE": inv_extract_jde
}

def inv_extract_main(image_folder_path, mapping_path, config, folder_path):
    if not target_erp:
        raise ValueError("target_erp not set in environment")

    func = INV_ERP_ROUTER.get(target_erp.upper())

    if not func:
        raise ValueError(f"❌ Unsupported ERP: {target_erp}")

    print(f"🏢 Routing to ERP: {target_erp}")

    return func(
        image_folder_path=image_folder_path,
        mapping_path=mapping_path,
        config=config,
        folder_path=folder_path
    )


# ---------------- PROMPTs ----------------

# def build_inv_prompt_ebs():
#     return """
# You are an AI that extracts structured invoice data from encoded images.

# Analyze the images and return a single valid JSON object with these keys:

# Header Fields (use empty strings if missing):
# - bill_to
# - ship_to
# - customer_po_number
# - invoice_date
# - customer_name
# - customer_number
# - supplier_name
# - invoice_number
# - currency_code
# - sales_order_number
# - invoice_duedate
# - subject
# - total
# - payment_terms
# - shipping_point
# - fob_point
# - freight_carrier

# Line Items: list of objects, each with:
# - line_number (generate sequentially if missing)
# - item_name
# - item_description
# - ordered_quantity
# - unit_of_measure
# - price
# - total

# IMPORTANT:
# - Strict JSON only
# - No explanations, no markdown
# - If field not found → empty string
# - Customer name is usually at top header
# - Invoice number can exist as Invoice #/ Invoice no./ Invvoice number
# - Invoice and PO numbers are mandatory.
# - Understand the layout properly, not everything exist as left- right key pairs, some keys can be top-bottom as well.
# - When you encounter a table with hierarchical (multi-row) headers and a row data spread across multiple lines,  Map values to columns by aligning their horizontal position with headers and assigning vertically stacked values in order based on the multi-line header structure.
# - When the column header is multi-line(stacked headers), its important to map the values in exact order below it.
# - Do not map Customer Part No as Item number.
# - If field not found → empty string
# - Generate line number sequentially if missing
# - Company/ Compay name is ususally present in the header of the layout
# - Dont exact keys to be present as such in the encoded image, understand the meaning and match the most appropriate equivalent keys
# """


def build_inv_prompt_ebs():
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
- If any field is not found → return empty string ""
- Invoice number, customer PO number, Bill to and Ship to are MANDATORY to search carefully
- If invoice number is missing, still return JSON with empty string (do NOT omit key)
- Line numbers must be sequential if missing (1,2,3...)
- Do not confuse Customer Part No with Item Number
- Understand layout spatially (top-bottom + left-right alignment both matter)
- Multi-line headers must be mapped correctly based on vertical alignment
- supplier_name is usually in top header section
- Line item details with total are mandatory
- If line item exist, total in header should not be zero. It should be the total of line items total amount
"""




def build_inv_prompt_jde():
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
    "invoice_date": "",
   
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
- When you encounter a table with hierarchical (multi-row) headers and a row data spread across multiple lines,  Map values to columns by aligning their horizontal position with headers and assigning vertically stacked values in order based on the multi-line header structure.
- When the column header is multi-line(stacked headers), its important to map the values in exact order below it.
- Do not map Customer Part No as Item number.
- If field not found → empty string
- Generate line number sequentially if missing
- Company/ Compay name is ususally present in the header ( left side)
- supplier_number is ususally present as Vendor Nbr
- Dont exact keys to be present as such in the encoded image, understand the meaning and match the most appropriate equivalent keys
 

"""
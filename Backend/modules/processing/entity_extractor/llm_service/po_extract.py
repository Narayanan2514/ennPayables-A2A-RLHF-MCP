import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from modules.processing.entity_extractor.decoder import decode_fields
from modules.processing.entity_extractor.db import insert_po_header, insert_po_line

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


def build_human_content(encoded_images):
    content = [{"type": "text", "text": "Extract PO fields from the images."}]

    for b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    return content


# ---------------- ADDRESS STRUCTURE ----------------

def structure_address(address_text):

    if not address_text:
        return {}

    if isinstance(address_text, dict):
        address_text = json.dumps(address_text)

    prompt = f"""
Structure this address into JSON.

Address:
{address_text}

Return ONLY valid JSON.

RULES:
- Do not hallucinate values
- If a field is missing, return empty string
- name = company/site name
- address lines = street/building/floor/suite info
- city/state/zip/country must be separated

FORMAT:
{{
    "name": "",
    "address_ln1": "",
    "address_ln2": "",
    "address_ln3": "",
    "address_ln4": "",
    "city": "",
    "state": "",
    "zip": "",
    "country": ""
}}
"""

    response = llm.invoke(prompt)

    try:
        cleaned = (
            response.content
            .strip()
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        return json.loads(cleaned)

    except Exception as e:
        print("❌ Address structuring failed:", e)
        return {}


# ---------------- MAIN EXTRACTION ----------------

def po_extract_ebs(image_folder_path, mapping_path, config, folder_path):

    print("📄 EBS PO Extraction started:", image_folder_path)

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    messages = [
        SystemMessage(content=build_po_prompt()),
        HumanMessage(content=build_human_content(encoded_images))
    ]

    response = llm.invoke(messages)

    try:
        cleaned = response.content.strip("```json").strip("```")
        data = json.loads(cleaned)
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    print("📦 Raw LLM Output:", data)

    # ---------------- HEADER ----------------

    header = data.get("purchase_order", {})

    header_keys = [
        "po_number",
        "po_date",
        "customer_name",
        "customer_number",
        "payment_terms",
        "currency",
        "ship_method",
        "shipping_via",
        "freight_terms",
        "total_amount",
        "ship_to",
        "bill_to"
    ]

    for key in header_keys:
        header[key] = (header.get(key) or "").strip()

    # ---------------- LINES ----------------

    lines_raw = data.get("line_items", [])
    # decoded_lines = [decode_fields(mapping_path, l) for l in lines_raw]

    decoded_lines = []

    for line in lines_raw:

        original_line_number = line.get("line_number")

        decoded_line = decode_fields(mapping_path, line)

        # preserve original line number
        decoded_line["line_number"] = original_line_number

        decoded_lines.append(decoded_line)
        
    # ---------------- DECODE HEADER ----------------

    decoded_header = decode_fields(mapping_path, header)

    # ---------------- VALIDATION ----------------

    po_number = decoded_header.get("po_number", "").strip()

    if not po_number:
        print("❌ PO number missing → skipping insert")
        return

    # ---------------- TOTAL FIX ----------------

    def safe_int(val):
        try:
            if val in (None, "", "None", "null"):
                return 0
            val = str(val).replace(",", "").strip()
            return int(float(val))
        except:
            return 0

    header_total = decoded_header.get("total_amount", "")

    if not header_total and decoded_lines:
        computed_total = sum(
            safe_int(l.get("net_amount", "")) for l in decoded_lines
        )
        decoded_header["total_amount"] = str(computed_total)

    # ---------------- ADDRESS STRUCTURE ----------------

    ship_to_struct = structure_address(decoded_header.get("ship_to", ""))
    bill_to_struct = structure_address(decoded_header.get("bill_to", ""))

    print("--------------ship_to------------------", ship_to_struct)
    print("--------------bill_to------------------", bill_to_struct)



 

    # flatten ship_to
    decoded_header.update({
        "ship_to_name": ship_to_struct.get("name", ""),
        "ship_to_address_ln1": ship_to_struct.get("address_ln1", "123, Innovation Drive"),
        "ship_to_address_ln2": ship_to_struct.get("address_ln2", "Tech City"),
        "ship_to_address_ln3": ship_to_struct.get("address_ln3", ""),
        "ship_to_address_ln4": ship_to_struct.get("address_ln4", ""),
        "ship_to_city": ship_to_struct.get("city", ""),
        "ship_to_state": ship_to_struct.get("state", "CA"),
        "ship_to_zip": ship_to_struct.get("zip", "90210"),
        "ship_to_country": ship_to_struct.get("country", ""),

        "bill_to_name": bill_to_struct.get("name", ""),
        "bill_to_address_ln1": bill_to_struct.get("address_ln1", "123, Innovation Drive"),
        "bill_to_address_ln2": bill_to_struct.get("address_ln2", "Tech City"),
        "bill_to_address_ln3": bill_to_struct.get("address_ln3", ""),
        "bill_to_address_ln4": bill_to_struct.get("address_ln4", ""),
        "bill_to_city": bill_to_struct.get("city", ""),
        "bill_to_state": bill_to_struct.get("state", "CA"),
        "bill_to_zip": bill_to_struct.get("zip", "90210"),
        "bill_to_country": bill_to_struct.get("country", "")
    })

    # ---------------- DB INSERT ----------------

    header_id = insert_po_header(decoded_header, folder_path)

    if not header_id:
        print("❌ Header insert failed")
        return

    for line in decoded_lines:
        insert_po_line(header_id, line)

    print("✅ PO processed:", os.path.basename(folder_path))


# ---------------- ROUTER ----------------

PO_ERP_ROUTER = {
    "EBS": po_extract_ebs
}


def po_extract_main(image_folder_path, mapping_path, config, folder_path):

    if not target_erp:
        raise ValueError("target_erp not set in environment")

    func = PO_ERP_ROUTER.get(target_erp.upper())

    if not func:
        raise ValueError(f"❌ Unsupported ERP: {target_erp}")

    print(f"🏢 Routing to ERP: {target_erp}")

    return func(
        image_folder_path=image_folder_path,
        mapping_path=mapping_path,
        config=config,
        folder_path=folder_path
    )


# ---------------- PROMPT ----------------

def build_po_prompt():
    return """
You are an AI specialized in extracting Purchase Order (PO) data from document images.

Return ONLY valid JSON.

RULES:
- Extract raw values exactly as seen
- Do NOT structure addresses
- Do NOT hallucinate values
- If field missing return null
- Do NOT return empty line items
- Generate sequential line numbers if missing
- Extract multi line values against the bill to/ ship to
- Customer name cannot be empty, Its ususally present at the top of the page in header
OUTPUT FORMAT:

{
  "purchase_order": {
    "po_number": null,
    "po_date": null,
    "customer_name": null,
    "customer_number": null,
    "payment_terms": null,
    "currency": null,
    "ship_method": null,
    "shipping_via": null,
    "freight_terms": null,
    "total_amount": null,
    "ship_to": null,
    "bill_to": null
  },
  "line_items": [
    {
      "line_number": null,
      "item_number": null,
      "item_description": null,
      "quantity": null,
      "unit_of_measure": null,
      "unit_price": null,
      "net_amount": null,
      "requested_date": null
    }
  ]
}
"""
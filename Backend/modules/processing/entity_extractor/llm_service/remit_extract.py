import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ERP.EBS.receipt_payload import push_to_ebs_ar
from modules.email_module.db import insert_log
from modules.processing.entity_extractor.decoder import decode_fields
from modules.processing.entity_extractor.db import *
from modules.processing.pairing_ar_module.match import *

# ------------------ INIT ------------------

load_dotenv(Path(__file__).resolve().parents[4] / ".env")
target_erp = os.getenv("TARGET_ERP")


llm = ChatOpenAI(
    model="gpt-4o",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0
)

# ------------------ UTILS ------------------

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
    content = [{"type": "text", "text": "Extract structured remittance data"}]

    for b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    return content

# ------------------ MAIN ------------------



def llm_remit_extract_jde(image_folder_path, mapping_path, config, folder_path):

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    messages = [
        SystemMessage(content=build_ra_prompt()),
        HumanMessage(content=build_human_content(encoded_images))
    ]

    response = llm.invoke(messages)

    try:
        data = json.loads(response.content.strip("```json").strip("```"))
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    header = decode_fields(mapping_path, data.get("header", {}))
    lines = [decode_fields(mapping_path, l) for l in data.get("lines", [])]

    h_id = insert_remit_header(header, folder_path)
    insert_remit_lines(h_id, lines)

    ref_number = header.get("ref_number", "").strip()

    if ref_number:
        bank_row = find_bank_doc_by_ref(ref_number)

        if bank_row:
            pair_docs(
                {"h_id": h_id, "ref_number": ref_number},
                bank_row
            )

    print("✅ Remittance processed:", os.path.basename(folder_path))

# def llm_remit_extract_ebs(image_folder_path, mapping_path, config, folder_path):

#     encoded_images = load_images(image_folder_path)

#     if not encoded_images:
#         print("❌ No images found")
#         return

#     messages = [
#         SystemMessage(content=build_ra_prompt()),
#         HumanMessage(content=build_human_content(encoded_images))
#     ]

#     response = llm.invoke(messages)

#     try:
#         data = json.loads(response.content.strip("```json").strip("```"))
#     except Exception:
#         print("❌ Invalid JSON:", response.content)
#         return

#     header = decode_fields(mapping_path, data.get("header", {}))
#     lines = [decode_fields(mapping_path, l) for l in data.get("lines", [])]

#     h_id, src_id = insert_remit_header_ebs(header, folder_path)
#     insert_remit_lines_ebs(h_id, lines)

#     ref_number = header.get("ref_number", "").strip()

#     if ref_number:
#         bank_row = find_bank_doc_by_ref(ref_number)

#         if bank_row:
#             pair_docs(
#                 {"h_id": h_id, "ref_number": ref_number},
#                 bank_row
#             )

#     print("✅ Remittance processed:", os.path.basename(folder_path))


def llm_remit_extract_ebs(image_folder_path, mapping_path, config, folder_path):

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    messages = [
        SystemMessage(content=build_ra_prompt()),
        HumanMessage(content=build_human_content(encoded_images))
    ]

    response = llm.invoke(messages)

    try:
        data = json.loads(response.content.strip("```json").strip("```"))
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    header = decode_fields(mapping_path, data.get("header", {}))
    lines = [decode_fields(mapping_path, l) for l in data.get("lines", [])]

    h_id, src_id = insert_remit_header_ebs(header, folder_path)
    insert_remit_lines_ebs(h_id, lines)

    ref_number = header.get("ref_number", "").strip()

    if not ref_number:
        print("⚠️ No bank reference found in remittance.")
        return

    bank_row = find_bank_doc_by_ref(ref_number)

    if not bank_row:
        print(f"⚠️ No matching bank document found for reference {ref_number}.")
        return


    # Pair the documents
    pair_docs(
        {"h_id": h_id, "ref_number": ref_number},
        bank_row
    )
    insert_case(src_id, bank_row["src_id"])
    
    print("🔗 Remittance and Bank Document paired successfully.")

    insert_log(
            src_id,
            "Successful",
            "LLM Extraction",
            "Entities extracted Successfully"
        )
    
    insert_log(
            src_id,
            "Successful",
            "LLM Extraction",
            "Remittance matched with respective bank reference"
        )
    # Push to Oracle EBS only after successful pairing
    result = push_to_ebs_ar(src_id)

    print("ERP Push Result:", result)

    print("✅ Remittance processed:", os.path.basename(folder_path))



# def llm_remit_extract_main(image_folder_path, mapping_path, config, folder_path):

#     encoded_images = load_images(image_folder_path)

#     if not encoded_images:
#         print("❌ No images found")
#         return

#     messages = [
#         SystemMessage(content=build_ra_prompt()),
#         HumanMessage(content=build_human_content(encoded_images))
#     ]

#     response = llm.invoke(messages)

#     try:
#         data = json.loads(response.content.strip("```json").strip("```"))
#     except Exception:
#         print("❌ Invalid JSON:", response.content)
#         return

#     header = decode_fields(mapping_path, data.get("header", {}))
#     lines = [decode_fields(mapping_path, l) for l in data.get("lines", [])]

#     h_id = insert_remit_header(header, folder_path)
#     insert_remit_lines(h_id, lines)

#     ref_number = header.get("ref_number", "").strip()

#     if ref_number:
#         bank_row = find_bank_doc_by_ref(ref_number)

#         if bank_row:
#             pair_docs(
#                 {"h_id": h_id, "ref_number": ref_number},
#                 bank_row
#             )

#     print("✅ Remittance processed:", os.path.basename(folder_path))


REMIT_ERP_ROUTER = {
    "JDE": llm_remit_extract_jde,
    "EBS": llm_remit_extract_ebs
}


def llm_remit_extract_main(image_folder_path, mapping_path, config, folder_path):

    if not target_erp:
        raise ValueError("target_erp not set")

    func = REMIT_ERP_ROUTER.get(target_erp.upper())

    if not func:
        raise ValueError(f"Unsupported ERP: {target_erp}")

    print(f"Routing Remittance to ERP : {target_erp}")

    return func(
        image_folder_path=image_folder_path,
        mapping_path=mapping_path,
        config=config,
        folder_path=folder_path
    )



def build_ra_prompt():
    return """
You are an AI that extracts structured Remittance Advice data from document images.
Each image contains encrypted numeric codes representing invoice and check details.

Return ONLY a valid JSON object in this exact format:

{
  "header": {
    "customer": "",
    "customer_number": "",
    "ref_number": "",
    "total_amnt": "",
    "currency": "",
    "date": ""
  },
  "lines": [
    {
      "l_ref_id": "",
      "date": "",
      "org_amnt": "",
      "disc_amnt": ""
    }
  ]
}

========================
EXTRACTION RULES
========================

HEADER:
- "customer": Usually at top of the header/ first line. He/She is the one making the payment.
- "customer_number": Payer’s customer ID if shown, else empty. Do not confuse it with Vendor. This is a mandatory field
- "ref_number": This is the CHECK NUMBER.
- "total_amnt": Total check amount.
- "currency": Default to "$" if missing.
- "date": Check/remittance date.

LINES:
- Each line represents an invoice being paid.
- "l_ref_id": Invoice number.
- "date": Invoice date.
- "org_amnt": Original invoice amount.
- "disc_amnt": Discount amount if present.

========================
IMPORTANT
========================
- Input images contain numeric codes representing each field.
- Use the exact key names and their synonymous meanings to extract values.
- Do NOT infer or fill fields from unrelated keys or values.
- If a field or its synonymous key is missing or cannot be found in the data, return an empty string "" for that field.
- Return only valid JSON.
- All values must be strings.
- Do NOT add explanations.
- Do NOT wrap response in markdown.
- If Customer number field/ key not present return that empty. Do not include it with vendor key or any other unrelated keys

"""
import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from modules.processing.entity_extractor.decoder import decode_fields
from modules.processing.entity_extractor.db import *
from modules.processing.pairing_ar_module.match import *

# ------------------ INIT ------------------

load_dotenv(Path(__file__).resolve().parents[4] / ".env")

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
    content = [{"type": "text", "text": "Extract structured bank document data"}]

    for b64 in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    return content

# ------------------ MAIN ------------------

def llm_bdoc_extract(image_folder_path, mapping_path, config, folder_path):

    # print("-----------------image bank path-------------------",image_folder_path)
    # print("-----------------mapping path-------------------",mapping_path)

    encoded_images = load_images(image_folder_path)

    if not encoded_images:
        print("❌ No images found")
        return

    messages = [
        SystemMessage(content=build_bdoc_prompt()),
        HumanMessage(content=build_human_content(encoded_images))
    ]

    response = llm.invoke(messages)

    try:
        data = json.loads(response.content.strip("```json").strip("```"))
        # print("-----------------extracted data by llm--------------", data)
    except Exception:
        print("❌ Invalid JSON:", response.content)
        return

    decoded = decode_fields(mapping_path, data)
    # print("---------------decoded bankdoc insert------------------", decoded)
    b_id = insert_bank_doc(decoded, folder_path)

    ref_num = decoded.get("ref_num", "").strip()

    if ref_num:
        remit_row = find_remit_by_ref(ref_num)

        if remit_row:
            pair_docs(
                remit_row,
                {"b_id": b_id, "ref_num": ref_num}
            )

    print("✅ Bank doc processed:", os.path.basename(folder_path))


def build_bdoc_prompt():
    return """
You are an AI that extracts Bank Document data.

Return ONLY valid JSON:

{
  "ref_num": "",
  "bank_nm": "",
  "amnt": ""
}

Field Definitions:

- ref_num:
  Extract the Payment Details Number OR Payment ID.
  This is usually labeled as:
  "Payment ID", "Payment Reference", "Payment Details", 
  "UTR", "Reference No", "Txn Ref", or similar.
  Return only the reference value, not the label.

- bank_nm:
  Extract the name of the bank shown in the document.

- amnt:
  Extract the total payment amount as a number.


Rules:
- Empty string if missing
- No explanations
- No markdown
- Only JSON
"""

# RETIRED -- do not run. Orphaned now that folder_listeners/to_process_listener.py
# (its only caller, run_parser()) has been retired -- see the deprecation
# note in that file (_deprecated/folder_listeners/to_process_listener.py)
# for why: this pipeline's extraction/DB-insert/ERP-push work is now done
# directly by Agent/agents (agent_1-4), and the archiving step this file
# also did needs a new, explicit trigger from that pipeline rather than a
# folder watcher. Moved here (not deleted) for reference; the hardcoded
# /home/opc/... paths below were also never fixed to use ENNVAULT_DATA_ROOT
# since nothing live reaches this code anymore.
#
# original path: modules/processing/pre_processor/prep.py

import os
import shutil
import json

from modules.processing.pre_processor.transform import *
from modules.processing.entity_extractor.llm_service.bdoc_extract import *
from modules.processing.entity_extractor.llm_service.inv_extract import *
from modules.processing.entity_extractor.llm_service.po_extract import *
from modules.processing.entity_extractor.llm_service.remit_extract import *
from modules.processing.pre_processor.db import *
from modules.email_module.db import *
from ERP.JDE.inv_payload import *
from ERP.EBS.inv_payload import *
from ERP.EBS.po_payload import *

from ERP.JDE.receipt_payload import *


# ---------------- BASE PATHS ----------------
TARGET_ERP = os.getenv("TARGET_ERP")


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("----base dir----", BASE_DIR)

TO_PROCESS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "doc_transition", "to_process")
# PROCESSED_DIR = os.path.join(BASE_DIR, "doc_transition", "processed")
# ARCHIVAL_DIR = os.path.join(BASE_DIR, "doc_transition", "archival")

# TO_PROCESS_DIR =r" C:\Users\Krithika A\Videos\POC\PO2SO\V6\Backend\doc_transition\to_process"
PROCESSED_DIR ="/home/opc/ennVault/ennPayables/backend/doc_transition/processed"
ARCHIVAL_DIR= "/home/opc/ennVault/ennPayables/backend/doc_transition/archival"

EXCLUSION_CONFIG_DIR = os.path.join(BASE_DIR, "processing", "exclusion_config")
print ("-----exclusion config path----", EXCLUSION_CONFIG_DIR)

# Ensure base dirs exist
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(ARCHIVAL_DIR, exist_ok=True)

# ---------------- CONFIG LOAD ----------------

def load_config(doc_type):
    mapping = {
        "bank": "bank.json",
        "inv": "inv_fields.json",
        "po": "po_fields.json",
        "remit": "ra_fields.json"
    }

    config_file = mapping.get(doc_type.lower())

    print("----config file path----", config_file)

    if not config_file:
        return None

    config_path = os.path.join(EXCLUSION_CONFIG_DIR, config_file)

    if not os.path.exists(config_path):
        print(f"❌ Config file missing: {config_path}")
        return None

    return json.load(open(config_path, encoding="utf-8"))

# ---------------- LLM ROUTER ----------------

LLM_ROUTER = {
    "bank": llm_bdoc_extract,
    "inv": inv_extract_main,
    "po": po_extract_main,
    "remit": llm_remit_extract_main
}

def run_llm_by_doc_type(image_folder_path, mapping_path, doc_type, config, folder_path):
    func = LLM_ROUTER.get(doc_type.lower())

    if not func:
        raise ValueError(f"❌ Unsupported doc_type: {doc_type}")

    print(f"🤖 Running {doc_type.upper()} LLM extraction...")

    return func(
        image_folder_path=image_folder_path,
        mapping_path=mapping_path,
        config=config,
        folder_path=folder_path
    )

def mark_folder_completed(processed_folder_path, doc_type):
    try:
        parent_dir = os.path.dirname(processed_folder_path)
        folder_name = os.path.basename(processed_folder_path)

        if not folder_name.endswith("_p"):
            print("⚠️ Not a _p folder, skipping rename")
            return processed_folder_path

        completed_name = folder_name.replace("_p", "_c")
        completed_path = os.path.join(parent_dir, completed_name)

        if os.path.exists(completed_path):
            print(f"⚠️ Already exists: {completed_name}")
            return completed_path

        os.rename(processed_folder_path, completed_path)

        # ✅ Update DB
        # update_processed_folder(
        #     old_path=f"doc_transition\\processed\\{doc_type}\\{folder_name}",
        #     new_path=f"doc_transition\\processed\\{doc_type}\\{completed_name}"
        # )

        # print(f"✅ Folder marked completed: {completed_name}")

        return completed_path

    except Exception as e:
        print("❌ Rename failed:", e)
        return processed_folder_path
    
# ---------------- PIPELINE ----------------

def run_parser(folder_path):
    print("🚀 Parser started for:", folder_path)

    # Extract doc_type from parent folder
    doc_type = os.path.basename(os.path.dirname(folder_path)).lower()
    folder_name = os.path.basename(folder_path)

    print(f"📑 Detected doc type: {doc_type}")

    # Load config
    config = load_config(doc_type)
    if not config:
        print("❌ Config not found for doc_type:", doc_type)

        src_id = get_src_id(folder_path)
    
        insert_log(
            src_id,
            "Failed",
            "Preprocessing",
            "Customer config not found"
        )
    
 
        return

    # Ensure subfolders exist
    os.makedirs(os.path.join(ARCHIVAL_DIR, doc_type), exist_ok=True)
    os.makedirs(os.path.join(PROCESSED_DIR, doc_type), exist_ok=True)

    # ---------------- 1️⃣ ARCHIVE ----------------
    archive_path = os.path.join(ARCHIVAL_DIR, doc_type, folder_name)

    try:
        shutil.copytree(folder_path, archive_path)
    except Exception as e:
        print("❌ Archival failed:", e)
        return

    # Update DB
    # update_archive_path_by_folder(
    #     folder_path=f"doc_transition\\to_process\\{doc_type}\\{folder_name}",
    #     archive_path=f"doc_transition\\archival\\{doc_type}\\{folder_name}"
    # )
    archive = update_archive_path_by_folder(
        folder_path=f"doc_transition/to_process/{doc_type}/{folder_name}",
        archive_path=f"doc_transition/archival/{doc_type}/{folder_name}"
    )
    if not archive:
        print("Stopping here arhive is none",archive)
        return

    # ---------------- 2️⃣ MOVE TO PROCESSED ----------------
    processed_folder_name = folder_name + "_p"
    processed_folder_path = os.path.join(PROCESSED_DIR, doc_type, processed_folder_name)

    os.makedirs(processed_folder_path, exist_ok=True)

    for file in os.listdir(folder_path):
        shutil.move(
            os.path.join(folder_path, file),
            os.path.join(processed_folder_path, file)
        )

    os.rmdir(folder_path)

    # ---------------- 3️⃣ TRANSFORM ----------------
    mapping_path = None  # ensure defined

    SUPPORTED_FILES = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")


    for file in os.listdir(processed_folder_path):
        # if not file.lower().endswith(".pdf"):
        if not file.lower().endswith(SUPPORTED_FILES):
            continue

        input_path = os.path.join(processed_folder_path, file)
        print("...................i/p for tranformation.....................",input_path)
        encoded_paths, mapping_path, success, dup_refs, format_ok, err_desc = transform(
            pdf_path=input_path,
            output_folder=processed_folder_path,
            config=config,
            doc_type=doc_type
        )

        # print("llm input path----------", encoded_paths)
        # print("mapping path----------", mapping_path)
        # print("--------folder path searching for src-------", folder_path)
        src_id = get_src_id(folder_path)

        # print("----active src id-----", src_id)
        if not success:
            print("❌ Skipping LLM, Transformation failed:", err_desc)

            insert_log(
                src_id,
                "Failed",
                "Preprocessing",
                err_desc or "Transformation failed"
            )

            return

    if not mapping_path:
        print("❌ No valid PDF found for processing")
        insert_log(
            src_id,
            "Failed",
            "Preprocessing",
            "No valid PDF found"
        )

        return

    insert_log(
            src_id,
            "Successful",
            "Preprocessing",
            "Attachments processed successfully"
        )
    # ---------------- 4️⃣ LLM ----------------
    try:
        run_llm_by_doc_type(
            image_folder_path=processed_folder_path,
            mapping_path=mapping_path,
            doc_type=doc_type,
            config=config,
            folder_path=folder_path
        )
        
        print("-------doc_type------", doc_type)

        # if doc_type != "remit": #only for ebs ar,,,, revert back when jde ar
        if TARGET_ERP == "JDE" or (TARGET_ERP == "EBS" and doc_type != "remit"):

            mark_folder_completed(processed_folder_path, doc_type)

            insert_log(
                src_id,
                "Successful",
                "LLM Extraction",
                "Entities extracted Successfully"
            )

            # return True #Need to change after demo
            if doc_type == "inv":
                # result = push_to_jde(src_id)
                if TARGET_ERP == "JDE":
                    result = push_to_jde(src_id)
                elif TARGET_ERP == "EBS":
                    result = push_to_ebs_inv(src_id)   
                else:
                    result = {
                        "status": "failed",
                        "message": f"Unsupported TARGET_ERP: {TARGET_ERP}"
                    }
            
                if result and result.get("status") == "success":
                    insert_log(
                        src_id,
                        "Successful",
                        # "JDE",
                        TARGET_ERP,
                        # result.get("message", "Invoice Pushed to JDE")
                        result.get("message", f"Invoice Pushed to{TARGET_ERP}")

                    )

            elif doc_type == "po":
                if TARGET_ERP == "EBS":
                    result = push_to_ebs_po(src_id)   
                # elif TARGET_ERP == "JDE":
                #     result = push_to_jde_po(src_id)
                else:
                    result = {
                        "status": "failed",
                        "message": f"Unsupported TARGET_ERP: {TARGET_ERP}"
                    }
            
                if result and result.get("status") == "success":
                    insert_log(
                        src_id,
                        "Successful",
                        TARGET_ERP,+
                        result.get("message", f"PO Pushed to{TARGET_ERP}")

                    )

            elif doc_type == "remit":
                result = push_remit_to_jde(src_id)
                # print("---------------------result from jde----------------", result)
                if result and result.get("status") == "success":
                    insert_log(
                        src_id,
                        "Successful",
                        # "JDE",
                        TARGET_ERP,
                        result.get("message", f"Remittance and Bank Ref Pushed to {TARGET_ERP}")
                    )
            else:
                result = {
                    "status": "failed",
                    "message": f"Unknown doc_type: {doc_type}"
                }

    except Exception as e:
        print("❌ LLM processing failed:", e)
        return

    print("🎉 Parsing completed for:", processed_folder_name)
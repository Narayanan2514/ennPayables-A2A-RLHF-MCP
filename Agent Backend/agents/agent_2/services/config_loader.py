"""Loads the per-doc-type customer exclusion/format config.

Exact port of ennVault_org_backend/modules/processing/pre_processor/prep.py's
`load_config(doc_type)` -- same doc_type -> filename mapping, same JSON
files (copied verbatim into ./exclusion_config alongside this module rather
than read from the old project's tree, so this pipeline has no runtime
dependency on ennVault_org_backend). Each file maps a known customer/vendor
name to the list of header/label words `transform_service.detect_invoice_format`
looks for in the PDF's OCR'd words to recognize that customer's layout.
"""
from __future__ import annotations

import json
import os

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclusion_config")

_DOC_TYPE_FILES = {
    "bdoc": "bdoc_fields.json",
    "inv": "inv_fields.json",
    "po": "po_fields.json",
    "remit": "ra_fields.json",
}

# Agent 1's intake record uses the long form (matching
# email_module.service.detect_doc_type's return values); org_backend's own
# folder-watcher used the short folder-code form (matching
# email_module.service.download_attachments' doc_folder_map). Accept either.
_LONG_FORM_ALIASES = {
    "invoice": "inv",
    "purchase_order": "po",
    "remittance": "remit",
}


def load_config(doc_type: str) -> dict | None:
    doc_type = _LONG_FORM_ALIASES.get(doc_type.lower(), doc_type.lower())
    config_file = _DOC_TYPE_FILES.get(doc_type)
    if not config_file:
        return None

    config_path = os.path.join(_CONFIG_DIR, config_file)
    if not os.path.exists(config_path):
        return None

    with open(config_path, encoding="utf-8") as f:
        return json.load(f)

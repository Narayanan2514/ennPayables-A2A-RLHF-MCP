"""Lightweight ERP-relevance classification for an incoming email.

Moved here, unchanged, from agents/agent_1/services/email_classifier.py now
that the supervisor (client/orchestrator/email_polling.py) does the
valid/invalid classification itself, before ever calling Agent 1 -- Agent 1
no longer classifies anything, it just acts on whatever message it's told
about. From-scratch recreation of the subject-keyword classifier pattern used
by the reference project's `email_module/service.py::detect_doc_type` (read
there only for the category taxonomy). This pipeline only carries `invoice`
documents through to JDE/EBS payload building (Agents 3/4); other detected
types are logged as relevant-but-out-of-scope rather than silently dropped.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_DOC_TYPE_PATTERNS: dict[str, list[str]] = {
    "invoice": [r"\binv\b", r"\binvoice\b", r"tax invoice"],
    "purchase_order": [r"\bpo\b", r"purchase order", r"p\.o\."],
    "remittance": [r"remittance", r"payment", r"cash application", r"remittance advice", r"receipt"],
    "bank": [r"bank statement", r"bank advice", r"statement of account", r"bank file", r"deposit report", r"payment confirmation", r"utr", r"transaction report", r"bank reference"],
}

_SIGNATURE_PATTERN = re.compile(
    r"(best regards[\s\S]*|regards[\s\S]*|thanks[\s\S]*|thank you[\s\S]*|sincerely[\s\S]*|--[\s\S]*|disclaimer[\s\S]*)",
    re.IGNORECASE,
)


def detect_doc_type(subject: str | None) -> str | None:
    if not subject:
        return None
    subject = subject.lower()
    for doc_type, patterns in _DOC_TYPE_PATTERNS.items():
        if any(re.search(p, subject) for p in patterns):
            return doc_type
    return None


def clean_body(html_content: str | None) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    signature = soup.find(id="Signature")
    if signature:
        signature.decompose()
    for tag in soup.find_all(["p", "div", "span"]):
        if tag.get_text(strip=True).lower().startswith("disclaimer"):
            tag.decompose()
    text = soup.get_text(separator="\n").replace("\r\n", "\n").replace("\xa0", " ").strip()
    return _SIGNATURE_PATTERN.sub("", text).strip()


def is_erp_relevant(doc_type: str | None) -> bool:
    return doc_type is not None


def is_pipeline_scope(doc_type: str | None) -> bool:
    """Only invoices are carried through Agents 2-4 in this pipeline; other
    ERP-relevant types (PO/remittance/bank) are logged but not extracted."""
    return doc_type == "invoice"


def is_valid_for_pipeline(subject: str | None) -> tuple[bool, str | None]:
    """The supervisor's single valid/invalid gate: classify by subject, then
    valid = ERP-relevant AND in this pipeline's scope (i.e. an invoice).
    Returns (is_valid, doc_type) -- doc_type is still returned even when
    invalid, for logging ("this was a purchase_order, not in scope").
    """
    doc_type = detect_doc_type(subject)
    valid = is_erp_relevant(doc_type) and is_pipeline_scope(doc_type)
    return valid, doc_type

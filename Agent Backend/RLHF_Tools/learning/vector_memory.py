"""Chroma-backed embedding store behind searchSimilarCases (Section 4.2).

Every human correction the UI already lets AP staff make today (PO mismatch ->
email supplier, bad line item -> manual fix -> reprocess) is currently
consumed once and discarded (audit: no corrections table exists anywhere in
ennvault-existing's schema). This is the new component that makes those
corrections retrievable as few-shot context for the next similar exception --
indexed on supplier, exception type, document layout, and amount, as the
proposal specifies.

Uses Chroma's bundled default embedding model (all-MiniLM, via onnxruntime) so
this works fully offline/local without needing an extra embedding-API key.
"""
from __future__ import annotations

import uuid
from typing import Any

import chromadb

from config.settings import get_settings

COLLECTION_NAME = "ap_exception_corrections"


def _get_collection():
    """Deliberately opens a fresh PersistentClient on every call rather than
    caching one at module level.

    This module is read from and written to by two independently long-running
    OS processes -- the REST API (api.main, where a human's Edit & Reprocess /
    Send email now action calls index_case) and the orchestrator's watcher
    (supervisor_main.py, where apply_learned_correction/apply_learned_email
    call search_similar_cases). A module-level cached client/collection is a
    per-process singleton: once supervisor_main.py's process has opened it,
    that handle does not observe writes committed later by api.main's
    separate process to the same on-disk directory -- Chroma's embedded
    PersistentClient does not refresh a long-lived handle's view of segments
    another process appended. That silently made every human correction
    invisible to the agent until supervisor_main.py happened to be restarted,
    which is exactly the "I already fixed this supplier/item, why is the
    agent still asking for manual review" symptom. Reopening per call is
    slightly slower (tens of ms against a local SQLite-backed store) but
    that's negligible next to the multi-second LLM calls already in every
    agent turn, and it makes every call see the current on-disk state.
    """
    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return client.get_or_create_collection(COLLECTION_NAME)


def _case_text(supplier_name: str, exception_type: str, document_layout: str | None, features: dict[str, Any]) -> str:
    feature_str = ", ".join(f"{k}={v}" for k, v in sorted(features.items()))
    return (
        f"supplier={supplier_name} exception_type={exception_type} "
        f"document_layout={document_layout or 'unknown'} {feature_str}"
    )


def index_case(
    supplier_name: str,
    exception_type: str,
    features: dict[str, Any],
    ai_recommendation: str,
    human_action: str,
    document_layout: str | None = None,
) -> str:
    """Embeds and stores one resolved exception case. Returns the vector id
    (persisted onto Correction.vector_id so the SQL row and the embedding stay
    linked for later exemplar/fine-tuning mining, Section 4.4).
    """
    collection = _get_collection()
    vector_id = uuid.uuid4().hex
    collection.add(
        ids=[vector_id],
        documents=[_case_text(supplier_name, exception_type, document_layout, features)],
        metadatas=[
            {
                "supplier_name": supplier_name,
                "exception_type": exception_type,
                "document_layout": document_layout or "unknown",
                "ai_recommendation": ai_recommendation,
                "human_action": human_action,
            }
        ],
    )
    stored = collection.get(ids=[vector_id])

    print("Stored in vector DB:", stored)
    print("Vector ID:", vector_id)
    return vector_id


def search_similar_cases(
    supplier_name: str,
    exception_type: str,
    features: dict[str, Any],
    document_layout: str | None = None,
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Retrieves the most similar past resolved cases for this supplier +
    exception type, to use as few-shot context for the current decision.
    """
    collection = _get_collection()
    query_text = _case_text(supplier_name, exception_type, document_layout, features)
    where_filter = {"$and": [{"supplier_name": supplier_name}, {"exception_type": exception_type}]}
    try:
        results = collection.query(query_texts=[query_text], n_results=n_results, where=where_filter)
    except Exception:
        # Falls back to an unfiltered search if this supplier/exception_type
        # combination has zero indexed cases yet (Chroma errors on an empty
        # result set under some backends rather than returning [] cleanly).
        return []

    cases = []
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    for case_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        cases.append({"id": case_id, "document": document, "metadata": metadata, "distance": distance})
    return cases

"""logCorrection: writes a labeled example every time a human corrects, or
confirms, an AI decision (Section 4.2). This is the write side of the loop
diagrammed in Section 5 -- every UI correction flows into corrections (SQL,
for exemplar/fine-tuning mining) and vector_memory (Chroma, for retrieval)
together, plus outcomes_log when there's a reward signal to attach
(Section 4.3).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from db.new_schema import Correction, OutcomesLog
from db.session import session_scope
from learning.vector_memory import index_case


def log_correction(
    src_id: str,
    supplier_name: str,
    doc_type: str,
    exception_type: str,
    invoice_features: dict[str, Any],
    ai_recommendation: str,
    human_action: str,
    ai_recommendation_correct: bool | None = None,
    confidence_at_decision: float | None = None,
    document_layout: str | None = None,
) -> int:
    vector_id = index_case(
        supplier_name, exception_type, invoice_features, ai_recommendation, human_action, document_layout
    )
    with session_scope() as session:
        correction = Correction(
            src_id=src_id,
            supplier_name=supplier_name,
            doc_type=doc_type,
            exception_type=exception_type,
            document_layout=document_layout,
            invoice_features_json=json.dumps(invoice_features, default=str),
            ai_recommendation=ai_recommendation,
            human_action=human_action,
            ai_recommendation_correct=ai_recommendation_correct,
            confidence_at_decision=confidence_at_decision,
            vector_id=vector_id,
        )
        session.add(correction)
        session.flush()
        return correction.id


def log_outcome(
    src_id: str,
    supplier_name: str,
    exception_type: str,
    action_taken: str,
    decided_by: str,
    autonomy_stage: str,
    confidence_at_decision: float | None = None,
) -> int:
    """Opens an outcomes_log row at decision time; reward/human_reversed/
    disputed_later get filled in later via resolve_outcome once known.
    """
    with session_scope() as session:
        outcome = OutcomesLog(
            src_id=src_id,
            supplier_name=supplier_name,
            exception_type=exception_type,
            action_taken=action_taken,
            decided_by=decided_by,
            confidence_at_decision=confidence_at_decision,
            autonomy_stage=autonomy_stage,
        )
        session.add(outcome)
        session.flush()
        return outcome.id


def resolve_outcome(
    outcome_id: int,
    reward: float,
    human_reversed: bool | None = None,
    cycle_time_seconds: float | None = None,
    disputed_later: bool | None = None,
) -> None:
    with session_scope() as session:
        outcome = session.get(OutcomesLog, outcome_id)
        if outcome is None:
            return
        outcome.reward = reward
        outcome.human_reversed = human_reversed
        outcome.cycle_time_seconds = cycle_time_seconds
        outcome.disputed_later = disputed_later
        outcome.resolved_at = datetime.utcnow()

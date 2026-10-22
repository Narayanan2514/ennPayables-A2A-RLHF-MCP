"""Periodic Fine-Tuning and Prompt-Library Refresh (Section 4.4).

"On a periodic cadence (e.g., monthly), use it to either fine-tune or
preference-tune (DPO) the extraction model, or -- cheaper, faster, and
lower-risk -- refresh a per-supplier few-shot exemplar library that is
injected into prompts at run time."

`refresh_exemplars` is the cheap path, run by supervisor_main.py's scheduler
(APScheduler) on a cadence set by the caller. `export_finetuning_dataset` is
the heavier path's data-prep step -- it stops at producing a JSONL file; wiring
an actual OpenAI/Anthropic fine-tune or DPO job is an infra decision (which
provider, which base model, whose budget) intentionally left as a follow-up,
not something to guess at silently here.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from db.new_schema import Correction, Exemplar
from db.session import session_scope


def refresh_exemplars(min_confidence_gap: float = 0.0, max_per_supplier_doctype: int = 20) -> dict[str, int]:
    """Mines corrections where the AI recommendation was wrong (or the human
    changed something) into a fresh, deduplicated few-shot exemplar set per
    (supplier, doc_type), replacing exemplars.active=1 rows for that pair.

    Returns {"suppliers_refreshed": N, "exemplars_written": M}.
    """
    with session_scope() as session:
        corrections = session.scalars(
            select(Correction).where(Correction.ai_recommendation_correct.is_(False))
        ).all()

        buckets: dict[tuple[str, str], list[Correction]] = defaultdict(list)
        for c in corrections:
            buckets[(c.supplier_name, c.doc_type)].append(c)

        exemplars_written = 0
        for (supplier_name, doc_type), rows in buckets.items():
            session.query(Exemplar).filter(
                Exemplar.supplier_name == supplier_name,
                Exemplar.doc_type == doc_type,
                Exemplar.active.is_(True),
            ).update({"active": False})

            for row in rows[-max_per_supplier_doctype:]:
                exemplar_payload = {
                    "input_snippet": json.loads(row.invoice_features_json or "{}"),
                    "wrong_ai_output": row.ai_recommendation,
                    "correct_output": row.human_action,
                    "exception_type": row.exception_type,
                }
                session.add(
                    Exemplar(
                        supplier_name=supplier_name,
                        doc_type=doc_type,
                        exemplar_json=json.dumps(exemplar_payload, default=str),
                        source_correction_id=row.id,
                        active=True,
                    )
                )
                exemplars_written += 1

        return {"suppliers_refreshed": len(buckets), "exemplars_written": exemplars_written}


def get_active_exemplars(supplier_name: str, doc_type: str, limit: int = 5) -> list[dict]:
    """What document_intelligence_server.py's few_shot_exemplars param is
    populated from before an extraction call.
    """
    with session_scope() as session:
        rows = session.scalars(
            select(Exemplar)
            .where(Exemplar.supplier_name == supplier_name, Exemplar.doc_type == doc_type, Exemplar.active.is_(True))
            .order_by(Exemplar.created_at.desc())
            .limit(limit)
        ).all()
        return [json.loads(r.exemplar_json) for r in rows]


def export_finetuning_dataset(output_path: str, min_examples: int = 50) -> dict[str, int | str]:
    """Data-prep step for the fine-tune/DPO path (Section 4.4). Writes a JSONL
    file of {prompt, chosen, rejected}-shaped records built from corrections
    where we have both the AI's (wrong) recommendation and the human's actual
    action -- the natural DPO preference-pair shape. Does not submit a
    fine-tuning job; that's a deliberate follow-up decision, not a default.
    """
    with session_scope() as session:
        corrections = session.scalars(
            select(Correction).where(Correction.ai_recommendation_correct.is_(False))
        ).all()

        if len(corrections) < min_examples:
            return {"status": "insufficient_data", "examples_available": len(corrections), "min_required": min_examples}

        records = [
            {
                "prompt": json.loads(c.invoice_features_json or "{}"),
                "rejected": c.ai_recommendation,
                "chosen": c.human_action,
                "supplier_name": c.supplier_name,
                "exception_type": c.exception_type,
            }
            for c in corrections
        ]

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")

    return {"status": "written", "examples_written": len(records), "path": str(path), "generated_at": datetime.utcnow().isoformat()}

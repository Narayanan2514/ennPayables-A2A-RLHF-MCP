"""Read-only governance dashboard (Section 8's metrics, surfaced for AP Ops /
Finance / architects to review before autonomy expands -- Section 4.7).

This is additive to, not a replacement for, ennvault-existing's dashboards
(audit section 9/10: /dashboard_ebs, /dashboard, /enncash_dashboard,
/dashboard_ennorder already exist and should keep serving day-to-day
Collections/Processed/Exceptions views). Mount this alongside them, e.g. at
/governance, rather than inside ennvault-existing's app.

Run standalone for local testing:
    uvicorn api.governance_dashboard:app --port 8010
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query
from sqlalchemy import select

from db.new_schema import GovernanceMetricSnapshot
from db.session import session_scope
from evaluation import metrics

router = APIRouter(tags=["governance"])
# Kept so `uvicorn api.governance_dashboard:app` still works standalone;
# api/main.py mounts `router` directly instead of this app.
app = FastAPI(title="Agentic AP Governance Dashboard")
app.include_router(router)


@router.get("/governance/snapshot")
def latest_snapshots(supplier_name: str | None = None, exception_type: str | None = None, limit: int = Query(50, le=500)):
    with session_scope() as session:
        stmt = select(GovernanceMetricSnapshot).order_by(GovernanceMetricSnapshot.created_at.desc()).limit(limit)
        if supplier_name:
            stmt = stmt.where(GovernanceMetricSnapshot.supplier_name == supplier_name)
        if exception_type:
            stmt = stmt.where(GovernanceMetricSnapshot.exception_type == exception_type)
        rows = session.scalars(stmt).all()
        return [
            {
                "supplier_name": r.supplier_name,
                "exception_type": r.exception_type,
                "sample_size": r.sample_size,
                "agreement_rate": r.agreement_rate,
                "dispute_rate": r.dispute_rate,
                "straight_through_rate": r.straight_through_rate,
                "confidence_calibration_error": r.confidence_calibration_error,
                "policy_regret": r.policy_regret,
                "recommended_autonomy_stage": r.recommended_autonomy_stage,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
            }
            for r in rows
        ]


@router.get("/governance/metrics/live")
def live_metrics(supplier_name: str | None = None, exception_type: str | None = None, window_days: int = 30):
    """Computes metrics on demand (rather than reading the last written
    snapshot) -- useful for ad hoc review between scheduled snapshot runs.
    """
    return {
        "agreement_rate": metrics.agreement_rate(supplier_name, exception_type, window_days),
        "dispute_rate": metrics.dispute_reversal_rate(supplier_name, exception_type, window_days),
        "straight_through_rate": metrics.straight_through_processing_rate(window_days),
        "confidence_calibration_error": metrics.confidence_calibration_error(supplier_name),
        "policy_regret": metrics.policy_regret(supplier_name, exception_type) if supplier_name and exception_type else None,
    }


@router.post("/governance/snapshot/refresh")
def refresh_snapshot(supplier_name: str, exception_type: str, window_days: int = 30):
    return metrics.write_governance_snapshot(supplier_name, exception_type, window_days)

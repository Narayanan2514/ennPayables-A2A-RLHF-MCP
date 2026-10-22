"""Appendix: Metrics to Instrument (Section 8).

"Recommendation: stand up the outcomes log and these metrics before building
the bandit policy or fine-tuning pipeline. Without a baseline agreement rate
and calibration curve, there is no way to demonstrate... that autonomy is
expanding because the model has earned it, rather than because a threshold
was moved."

`write_governance_snapshot` is the piece that actually gates Section 4.7:
it's what orchestrator/governance.py's `_latest_governance_snapshot` reads to
decide whether a supplier/exception_type pair has earned expanded autonomy.
Run it on a schedule (see supervisor_main.py) per (supplier, exception_type)
pair with enough volume to be meaningful.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from db.new_schema import BanditArmState, Correction, GovernanceMetricSnapshot, OutcomesLog
from db.session import session_scope

# Minimum sample size before a pair is even eligible to be considered for
# expanded autonomy -- avoids promoting on a lucky streak of 3 invoices.
MIN_SAMPLE_SIZE_FOR_EXPANSION = 30
EXPANSION_AGREEMENT_THRESHOLD = 0.95
EXPANSION_DISPUTE_THRESHOLD = 0.02
LIMITED_AGREEMENT_THRESHOLD = 0.85


def agreement_rate(supplier_name: str | None = None, exception_type: str | None = None, window_days: int = 30) -> dict:
    """% of AI recommendations the human did not override, per exception
    type/supplier. Owner: AP Ops.
    """
    since = datetime.utcnow() - timedelta(days=window_days)
    with session_scope() as session:
        stmt = select(Correction).where(Correction.created_at >= since)
        if supplier_name:
            stmt = stmt.where(Correction.supplier_name == supplier_name)
        if exception_type:
            stmt = stmt.where(Correction.exception_type == exception_type)
        rows = session.scalars(stmt).all()
        scored = [r for r in rows if r.ai_recommendation_correct is not None]
        if not scored:
            return {"agreement_rate": None, "sample_size": 0}
        rate = sum(1 for r in scored if r.ai_recommendation_correct) / len(scored)
        return {"agreement_rate": round(rate, 4), "sample_size": len(scored)}


def confidence_calibration_error(supplier_name: str | None = None, n_buckets: int = 5) -> dict:
    """Gap between stated confidence and observed accuracy (Expected
    Calibration Error over `n_buckets` equal-width confidence buckets).
    Owner: AI/ML team.
    """
    with session_scope() as session:
        stmt = select(Correction).where(
            Correction.confidence_at_decision.is_not(None), Correction.ai_recommendation_correct.is_not(None)
        )
        if supplier_name:
            stmt = stmt.where(Correction.supplier_name == supplier_name)
        rows = session.scalars(stmt).all()

    if not rows:
        return {"confidence_calibration_error": None, "sample_size": 0}

    buckets: list[list] = [[] for _ in range(n_buckets)]
    for row in rows:
        idx = min(int(row.confidence_at_decision * n_buckets), n_buckets - 1)
        buckets[idx].append(row)

    total = len(rows)
    ece = 0.0
    for bucket_rows in buckets:
        if not bucket_rows:
            continue
        avg_confidence = sum(r.confidence_at_decision for r in bucket_rows) / len(bucket_rows)
        observed_accuracy = sum(1 for r in bucket_rows if r.ai_recommendation_correct) / len(bucket_rows)
        ece += (len(bucket_rows) / total) * abs(avg_confidence - observed_accuracy)

    return {"confidence_calibration_error": round(ece, 4), "sample_size": total}


def straight_through_processing_rate(window_days: int = 30) -> dict:
    """% of invoices requiring zero human touch. Owner: AP Ops.

    Approximated from outcomes_log's decided_by/action_taken -- a production
    deployment should also count clean straight-through extractions that
    never generated an exception at all (tracked via log_table stage="MCP"),
    not only exception-handling outcomes.
    """
    since = datetime.utcnow() - timedelta(days=window_days)
    with session_scope() as session:
        rows = session.scalars(select(OutcomesLog).where(OutcomesLog.created_at >= since)).all()
        if not rows:
            return {"straight_through_rate": None, "sample_size": 0}
        stp = sum(1 for r in rows if r.decided_by == "policy" and r.action_taken == "straight_through")
        return {"straight_through_rate": round(stp / len(rows), 4), "sample_size": len(rows)}


def dispute_reversal_rate(supplier_name: str | None = None, exception_type: str | None = None, window_days: int = 30) -> dict:
    """% of autonomous actions later reversed or disputed. Owner: AP Ops + Finance."""
    since = datetime.utcnow() - timedelta(days=window_days)
    with session_scope() as session:
        stmt = select(OutcomesLog).where(OutcomesLog.decided_by == "policy", OutcomesLog.created_at >= since)
        if supplier_name:
            stmt = stmt.where(OutcomesLog.supplier_name == supplier_name)
        if exception_type:
            stmt = stmt.where(OutcomesLog.exception_type == exception_type)
        rows = session.scalars(stmt).all()
        resolved = [r for r in rows if r.human_reversed is not None or r.disputed_later is not None]
        if not resolved:
            return {"dispute_rate": None, "sample_size": 0}
        disputed = sum(1 for r in resolved if r.human_reversed or r.disputed_later)
        return {"dispute_rate": round(disputed / len(resolved), 4), "sample_size": len(resolved)}


def policy_regret(supplier_name: str, exception_type: str) -> dict:
    """Cumulative reward lost vs. best-known action, per bandit arm. Owner: AI/ML team."""
    with session_scope() as session:
        arms = session.scalars(
            select(BanditArmState).where(
                BanditArmState.supplier_name == supplier_name, BanditArmState.exception_type == exception_type
            )
        ).all()
        if not arms:
            return {"policy_regret": None}
        expected_values = {arm.action: arm.alpha / (arm.alpha + arm.beta) for arm in arms}
        best_value = max(expected_values.values())
        regret = sum((best_value - expected_values[arm.action]) * arm.trials for arm in arms)
        return {"policy_regret": round(regret, 4), "best_action": max(expected_values, key=expected_values.get)}


def write_governance_snapshot(supplier_name: str, exception_type: str, window_days: int = 30) -> dict:
    """Computes the rolling metrics for one (supplier, exception_type) pair and
    writes a GovernanceMetricSnapshot recommending shadow/limited/expanded --
    the recommendation orchestrator/governance.py's expanded-autonomy check
    reads. Promotion requires BOTH sample size and agreement/dispute
    thresholds, never just one lucky metric.
    """
    agreement = agreement_rate(supplier_name, exception_type, window_days)
    dispute = dispute_reversal_rate(supplier_name, exception_type, window_days)
    stp = straight_through_processing_rate(window_days)
    calibration = confidence_calibration_error(supplier_name)
    regret = policy_regret(supplier_name, exception_type)

    sample_size = agreement["sample_size"]
    recommended_stage = "shadow"
    if (
        sample_size >= MIN_SAMPLE_SIZE_FOR_EXPANSION
        and agreement["agreement_rate"] is not None
        and agreement["agreement_rate"] >= EXPANSION_AGREEMENT_THRESHOLD
        and (dispute["dispute_rate"] or 0) <= EXPANSION_DISPUTE_THRESHOLD
    ):
        recommended_stage = "expanded"
    elif agreement["agreement_rate"] is not None and agreement["agreement_rate"] >= LIMITED_AGREEMENT_THRESHOLD:
        recommended_stage = "limited"

    with session_scope() as session:
        snapshot = GovernanceMetricSnapshot(
            supplier_name=supplier_name,
            exception_type=exception_type,
            window_start=datetime.utcnow() - timedelta(days=window_days),
            window_end=datetime.utcnow(),
            sample_size=sample_size,
            agreement_rate=agreement["agreement_rate"],
            dispute_rate=dispute["dispute_rate"],
            straight_through_rate=stp["straight_through_rate"],
            confidence_calibration_error=calibration["confidence_calibration_error"],
            policy_regret=regret.get("policy_regret"),
            recommended_autonomy_stage=recommended_stage,
        )
        session.add(snapshot)
        session.flush()
        return {"snapshot_id": snapshot.id, "recommended_autonomy_stage": recommended_stage, **agreement, **dispute}

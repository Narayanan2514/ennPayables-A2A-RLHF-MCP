"""Governance and Staged Autonomy Rollout (Section 4.7).

"no mechanism above should be allowed to act autonomously without a staged
rollout: shadow mode, where the policy recommends but a human still acts and
agreement is logged; limited autonomy, where auto-action is permitted only
above a confidence threshold and below a dollar/volume blast-radius cap; and
expanded autonomy, granted per supplier and exception type only once
agreement and dispute-rate metrics justify it."

This is the single gate every autonomous action (auto-fix, auto-approve,
auto-send-email, auto-submit-to-ERP) must pass through before it is allowed
to actually execute rather than merely be recommended. It is deliberately
conservative on missing data: no governance snapshot yet for a
supplier/exception_type pair means "not yet earned expanded autonomy," not
"assume the best."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select

from config.settings import get_settings
from db.new_schema import GovernanceMetricSnapshot, OutcomesLog
from db.session import session_scope


class AutonomyStage(str, Enum):
    SHADOW = "shadow"
    LIMITED = "limited"
    EXPANDED = "expanded"


@dataclass
class AuthorizationResult:
    allowed: bool
    stage_used: AutonomyStage
    reason: str


def _daily_autonomous_action_count() -> int:
    since = datetime.utcnow() - timedelta(days=1)
    with session_scope() as session:
        count = session.scalar(
            select(func.count())
            .select_from(OutcomesLog)
            .where(OutcomesLog.decided_by == "policy", OutcomesLog.created_at >= since)
        )
        return count or 0


def _latest_governance_snapshot(supplier_name: str, exception_type: str) -> GovernanceMetricSnapshot | None:
    with session_scope() as session:
        return session.scalar(
            select(GovernanceMetricSnapshot)
            .where(
                GovernanceMetricSnapshot.supplier_name == supplier_name,
                GovernanceMetricSnapshot.exception_type == exception_type,
            )
            .order_by(GovernanceMetricSnapshot.created_at.desc())
        )


def authorize_autonomous_action(
    supplier_name: str,
    exception_type: str,
    confidence: float,
    amount: float | None = None,
) -> AuthorizationResult:
    """The gate. Called immediately before executing any action a human isn't
    directly initiating (an auto-fix, an auto-approve, an auto-sent email, an
    autonomous ERP submission). Returns allowed=False for the global system
    stage of "shadow" unconditionally -- shadow mode's entire point is that
    the policy recommends and a human still acts.
    """
    settings = get_settings()
    global_stage = AutonomyStage(settings.autonomy_stage)

    if global_stage == AutonomyStage.SHADOW:
        return AuthorizationResult(False, AutonomyStage.SHADOW, "System is in shadow mode: recommend only, human acts.")

    snapshot = _latest_governance_snapshot(supplier_name, exception_type)
    effective_stage = global_stage
    if global_stage == AutonomyStage.EXPANDED:
        # Expanded autonomy is earned per supplier/exception_type, not granted
        # globally -- fall back to limited-autonomy rules until this specific
        # pair's metrics have actually justified it.
        if snapshot is None or snapshot.recommended_autonomy_stage != AutonomyStage.EXPANDED.value:
            effective_stage = AutonomyStage.LIMITED

    if confidence < settings.auto_correct_confidence_threshold:
        return AuthorizationResult(
            False, effective_stage, f"confidence {confidence} below floor {settings.auto_correct_confidence_threshold}"
        )

    if amount is not None and amount > settings.blast_radius_max_amount:
        return AuthorizationResult(
            False,
            effective_stage,
            f"amount {amount} exceeds blast-radius cap {settings.blast_radius_max_amount}",
        )

    daily_count = _daily_autonomous_action_count()
    if daily_count >= settings.blast_radius_max_daily_count:
        return AuthorizationResult(
            False,
            effective_stage,
            f"daily autonomous-action count {daily_count} at/over cap {settings.blast_radius_max_daily_count}",
        )

    if effective_stage == AutonomyStage.EXPANDED:
        return AuthorizationResult(True, effective_stage, "expanded autonomy earned for this supplier/exception_type")

    return AuthorizationResult(True, effective_stage, "within limited-autonomy confidence and blast-radius bounds")

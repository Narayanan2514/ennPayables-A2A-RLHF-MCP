"""Persistence for the contextual bandit's per-arm Beta posteriors (Section 4.3).

Tracked separately per (supplier, exception_type, action) -- "a pattern that
is safe to auto-resolve for one supplier may not be for another." The
sampling algorithm itself lives in orchestrator/bandit.py; this module is
just get/update against bandit_arm_state.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from db.new_schema import BanditArmState
from db.session import session_scope
from mcp_servers.common.errors import DEFAULT_ACTION_SPACE, ExceptionType


def get_arm_states(supplier_name: str, exception_type: str) -> dict[str, dict[str, float]]:
    """Returns {action: {alpha, beta, trials, successes}} for every action in
    this exception type's action space, creating fresh Beta(1,1) priors for
    any action not yet seen for this supplier.
    """
    try:
        action_space = DEFAULT_ACTION_SPACE[ExceptionType(exception_type)]
    except ValueError:
        action_space = DEFAULT_ACTION_SPACE[ExceptionType.UNKNOWN]

    with session_scope() as session:
        rows = session.scalars(
            select(BanditArmState).where(
                BanditArmState.supplier_name == supplier_name,
                BanditArmState.exception_type == exception_type,
            )
        ).all()
        existing = {row.action: row for row in rows}

        result = {}
        for action in action_space:
            row = existing.get(action)
            if row is None:
                row = BanditArmState(
                    supplier_name=supplier_name,
                    exception_type=exception_type,
                    action=action,
                    alpha=1.0,
                    beta=1.0,
                    trials=0,
                    successes=0,
                )
                session.add(row)
                session.flush()
            result[action] = {
                "alpha": row.alpha,
                "beta": row.beta,
                "trials": row.trials,
                "successes": row.successes,
            }
        return result


def update_arm(supplier_name: str, exception_type: str, action: str, success: bool) -> None:
    """Bayesian update on a Bernoulli reward (success = the action held: no
    human reversal, no later dispute). Beta-Bernoulli conjugacy: alpha += 1 on
    success, beta += 1 on failure.
    """
    with session_scope() as session:
        row = session.scalar(
            select(BanditArmState).where(
                BanditArmState.supplier_name == supplier_name,
                BanditArmState.exception_type == exception_type,
                BanditArmState.action == action,
            )
        )
        if row is None:
            row = BanditArmState(
                supplier_name=supplier_name,
                exception_type=exception_type,
                action=action,
                alpha=1.0,
                beta=1.0,
                trials=0,
                successes=0,
            )
            session.add(row)

        row.trials += 1
        if success:
            row.alpha += 1
            row.successes += 1
        else:
            row.beta += 1
        row.last_updated = datetime.utcnow()

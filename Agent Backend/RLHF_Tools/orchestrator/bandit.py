"""Contextual Bandit Policy for Exception Actions (Section 4.3).

"Model 'what should we do about this failure' as a contextual bandit rather
than a prompt decision... Using an algorithm such as Thompson sampling or
epsilon-greedy, the policy starts conservative -- escalating almost
everything -- and shifts weight toward autonomous actions as evidence
accumulates, tracked separately per supplier and per exception type."

Thompson sampling: draw one sample from each arm's Beta(alpha, beta)
posterior, pick the arm with the highest sample. With fresh Beta(1,1) priors
(uniform), and "escalate" always present in the action space, this naturally
starts conservative -- a fresh non-escalate arm has the same prior as
escalate, so ties are broken conservatively (see `_pick_arm`), and it takes
real evidence for a risky arm's posterior to pull ahead.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from learning import bandit_store

ESCALATE = "escalate"


@dataclass
class BanditDecision:
    action: str
    sampled_values: dict[str, float]
    arm_states: dict[str, dict[str, float]]


def _pick_arm(sampled_values: dict[str, float]) -> str:
    """Ties (e.g. all-fresh-prior arms) resolve to `escalate` if it's tied for
    the top score -- "starts conservative" is a tie-break rule, not just an
    emergent property of the priors.
    """
    best_value = max(sampled_values.values())
    tied = [action for action, value in sampled_values.items() if value == best_value]
    if ESCALATE in tied:
        return ESCALATE
    return tied[0]


def choose_action(supplier_name: str, exception_type: str, rng: np.random.Generator | None = None) -> BanditDecision:
    rng = rng or np.random.default_rng()
    arm_states = bandit_store.get_arm_states(supplier_name, exception_type)

    sampled_values = {
        action: float(rng.beta(state["alpha"], state["beta"])) for action, state in arm_states.items()
    }
    action = _pick_arm(sampled_values)
    return BanditDecision(action=action, sampled_values=sampled_values, arm_states=arm_states)


def record_outcome(supplier_name: str, exception_type: str, action: str, success: bool) -> None:
    bandit_store.update_arm(supplier_name, exception_type, action, success)


def expected_value(state: dict[str, float]) -> float:
    """Posterior mean, used for reporting/dashboards (not for arm selection --
    that always samples, per Thompson sampling)."""
    return state["alpha"] / (state["alpha"] + state["beta"])


def best_action_by_expected_value(arm_states: dict[str, dict[str, float]]) -> str:
    """Deterministic, stable recommendation for display/logging purposes --
    the arm with the highest posterior MEAN, not a fresh Thompson sample.

    choose_action's live sample is for actually *selecting* an action under
    exploration; it is expected (and correct) to vary run to run. But the
    same live sample was also being reused as the human-facing "suggested
    action" on the exception detail page, which meant a document with fresh,
    untrained Beta(1,1) priors on every arm could show a different
    recommendation on every page reload -- indistinguishable from random to
    the human deciding what to do. Reuses `_pick_arm`'s escalate-wins-ties
    rule so this stays exactly as conservative as choose_action's own
    tie-break when no arm has real evidence yet.
    """
    expected_values = {action: expected_value(state) for action, state in arm_states.items()}
    return _pick_arm(expected_values)

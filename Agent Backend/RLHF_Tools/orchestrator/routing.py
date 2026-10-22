"""Confidence-Aware Routing (Section 4.1).

"A routing layer then decides straight-through processing, auto-correction, or
human escalation based on thresholds -- and those thresholds, not a fixed
prompt, become the first tunable decision point in the system."

Thresholds are config-driven (config/settings.py), not hardcoded, so they can
be tuned per the governance dashboard (Section 8) without a code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.settings import get_settings


class RoutingAction(str, Enum):
    STRAIGHT_THROUGH = "straight_through"
    AUTO_CORRECT = "auto_correct"
    ESCALATE = "escalate"


@dataclass
class RoutingDecision:
    action: RoutingAction
    overall_confidence: float
    low_confidence_fields: list[str]
    reason: str


def route_extraction(
    overall_confidence: float,
    field_confidence: dict[str, float],
    field_confidence_floor: float = 0.2#0.5,
) -> RoutingDecision:
    """Decide what to do with a just-extracted document based on its
    confidence profile. A single very-low-confidence field (e.g. invoice
    amount) can force escalation even if the overall average looks fine --
    the floor check exists so one bad field doesn't get averaged away.
    """
    settings = get_settings()
    low_fields = [field for field, conf in field_confidence.items() if conf < field_confidence_floor]

    if low_fields:
        return RoutingDecision(
            RoutingAction.ESCALATE,
            overall_confidence,
            low_fields,
            f"Field(s) below floor confidence {field_confidence_floor}: {low_fields}",
        )

    if overall_confidence >= settings.stp_confidence_threshold:
        return RoutingDecision(
            RoutingAction.STRAIGHT_THROUGH,
            overall_confidence,
            [],
            f"overall_confidence {overall_confidence} >= STP threshold {settings.stp_confidence_threshold}",
        )

    if overall_confidence >= settings.auto_correct_confidence_threshold:
        return RoutingDecision(
            RoutingAction.AUTO_CORRECT,
            overall_confidence,
            [],
            f"overall_confidence {overall_confidence} >= auto-correct threshold "
            f"{settings.auto_correct_confidence_threshold}, below STP threshold",
        )

    return RoutingDecision(
        RoutingAction.ESCALATE,
        overall_confidence,
        [],
        f"overall_confidence {overall_confidence} below auto-correct threshold "
        f"{settings.auto_correct_confidence_threshold}",
    )

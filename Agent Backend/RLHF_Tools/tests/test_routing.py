from orchestrator.routing import RoutingAction, route_extraction


def test_high_confidence_goes_straight_through():
    decision = route_extraction(overall_confidence=0.97, field_confidence={"invoice_number": 1.0, "total": 0.95})
    assert decision.action == RoutingAction.STRAIGHT_THROUGH


def test_mid_confidence_goes_auto_correct():
    decision = route_extraction(overall_confidence=0.80, field_confidence={"invoice_number": 0.8, "total": 0.8})
    assert decision.action == RoutingAction.AUTO_CORRECT


def test_low_confidence_escalates():
    decision = route_extraction(overall_confidence=0.5, field_confidence={"invoice_number": 0.5, "total": 0.5})
    assert decision.action == RoutingAction.ESCALATE


def test_single_low_field_forces_escalation_even_with_high_overall():
    decision = route_extraction(
        overall_confidence=0.96,
        field_confidence={"invoice_number": 1.0, "invoice_amount": 0.2, "supplier_name": 1.0},
    )
    assert decision.action == RoutingAction.ESCALATE
    assert "invoice_amount" in decision.low_confidence_fields

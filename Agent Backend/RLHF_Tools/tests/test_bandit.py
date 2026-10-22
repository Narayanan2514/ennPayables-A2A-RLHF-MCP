import numpy as np

from orchestrator import bandit


def test_fresh_arms_are_uniform_prior_and_ties_favor_escalate():
    decision = bandit.choose_action("Acme Corp", "invalid_po", rng=np.random.default_rng(0))
    assert decision.action in decision.arm_states
    for state in decision.arm_states.values():
        assert state["alpha"] == 1.0
        assert state["beta"] == 1.0


def test_recording_successes_shifts_the_posterior_toward_that_arm():
    supplier, exception_type = "Acme Corp", "invalid_item"
    action = "auto_fix_line_item"

    for _ in range(20):
        bandit.record_outcome(supplier, exception_type, action, success=True)

    states = bandit.choose_action(supplier, exception_type, rng=np.random.default_rng(1)).arm_states
    assert bandit.expected_value(states[action]) > 0.9


def test_repeated_failures_suppress_an_arm():
    supplier, exception_type = "Acme Corp", "amount_overapply"
    action = "email_supplier"

    for _ in range(20):
        bandit.record_outcome(supplier, exception_type, action, success=False)

    states = bandit.choose_action(supplier, exception_type, rng=np.random.default_rng(2)).arm_states
    assert bandit.expected_value(states[action]) < 0.15


def test_duplicate_invoice_action_space_is_escalate_only():
    decision = bandit.choose_action("Acme Corp", "duplicate_invoice", rng=np.random.default_rng(3))
    assert set(decision.arm_states.keys()) == {"escalate"}
    assert decision.action == "escalate"

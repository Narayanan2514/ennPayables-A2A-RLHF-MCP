from db.new_schema import Correction, OutcomesLog
from db.session import session_scope
from evaluation import metrics


def _seed_corrections(n_correct, n_incorrect, supplier="Acme Corp", exception_type="invalid_po", confidence=0.9):
    with session_scope() as session:
        for i in range(n_correct):
            session.add(
                Correction(
                    src_id=f"src_ok_{i}",
                    supplier_name=supplier,
                    doc_type="invoice",
                    exception_type=exception_type,
                    ai_recommendation="x",
                    human_action="x",
                    ai_recommendation_correct=True,
                    confidence_at_decision=confidence,
                )
            )
        for i in range(n_incorrect):
            session.add(
                Correction(
                    src_id=f"src_bad_{i}",
                    supplier_name=supplier,
                    doc_type="invoice",
                    exception_type=exception_type,
                    ai_recommendation="x",
                    human_action="y",
                    ai_recommendation_correct=False,
                    confidence_at_decision=confidence,
                )
            )


def test_agreement_rate_computes_correctly():
    _seed_corrections(n_correct=8, n_incorrect=2)
    result = metrics.agreement_rate("Acme Corp", "invalid_po")
    assert result["sample_size"] == 10
    assert result["agreement_rate"] == 0.8


def test_agreement_rate_none_when_no_data():
    result = metrics.agreement_rate("Nobody Inc", "invalid_po")
    assert result["agreement_rate"] is None
    assert result["sample_size"] == 0


def test_write_governance_snapshot_recommends_expanded_when_metrics_justify_it():
    _seed_corrections(n_correct=48, n_incorrect=1, supplier="Trusted Supplier Inc", confidence=0.95)
    with session_scope() as session:
        for i in range(49):
            session.add(
                OutcomesLog(
                    src_id=f"src_{i}",
                    supplier_name="Trusted Supplier Inc",
                    exception_type="invalid_po",
                    action_taken="request_po_correction",
                    decided_by="policy",
                    human_reversed=False,
                    disputed_later=False,
                )
            )

    snapshot = metrics.write_governance_snapshot("Trusted Supplier Inc", "invalid_po")
    assert snapshot["recommended_autonomy_stage"] == "expanded"


def test_write_governance_snapshot_recommends_shadow_with_low_agreement():
    # Small, mixed-quality sample: high agreement alone earns "limited" even at
    # low volume (limited mode still has its own confidence/blast-radius caps),
    # but agreement below LIMITED_AGREEMENT_THRESHOLD must stay at "shadow"
    # regardless of sample size.
    _seed_corrections(n_correct=1, n_incorrect=2, supplier="New Supplier LLC", confidence=0.95)
    snapshot = metrics.write_governance_snapshot("New Supplier LLC", "invalid_po")
    assert snapshot["recommended_autonomy_stage"] == "shadow"


def test_write_governance_snapshot_recommends_limited_with_high_agreement_but_low_volume():
    _seed_corrections(n_correct=3, n_incorrect=0, supplier="New Supplier LLC", confidence=0.95)
    snapshot = metrics.write_governance_snapshot("New Supplier LLC", "invalid_po")
    assert snapshot["recommended_autonomy_stage"] == "limited"

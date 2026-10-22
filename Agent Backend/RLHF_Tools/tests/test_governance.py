from datetime import datetime, timedelta

from config.settings import get_settings
from db.new_schema import GovernanceMetricSnapshot, OutcomesLog
from db.session import session_scope
from orchestrator.governance import AutonomyStage, authorize_autonomous_action


def _set_stage(monkeypatch, stage: str):
    monkeypatch.setenv("AUTONOMY_STAGE", stage)
    get_settings.cache_clear()


def test_shadow_mode_never_allows_autonomous_action(monkeypatch):
    _set_stage(monkeypatch, "shadow")
    result = authorize_autonomous_action("Acme Corp", "invalid_po", confidence=0.99, amount=10)
    assert result.allowed is False
    assert result.stage_used == AutonomyStage.SHADOW


def test_limited_mode_allows_within_bounds(monkeypatch):
    _set_stage(monkeypatch, "limited")
    result = authorize_autonomous_action("Acme Corp", "invalid_po", confidence=0.99, amount=100)
    assert result.allowed is True
    assert result.stage_used == AutonomyStage.LIMITED


def test_limited_mode_blocks_low_confidence(monkeypatch):
    _set_stage(monkeypatch, "limited")
    result = authorize_autonomous_action("Acme Corp", "invalid_po", confidence=0.2, amount=100)
    assert result.allowed is False


def test_limited_mode_blocks_over_blast_radius_amount(monkeypatch):
    _set_stage(monkeypatch, "limited")
    settings = get_settings()
    result = authorize_autonomous_action(
        "Acme Corp", "invalid_po", confidence=0.99, amount=settings.blast_radius_max_amount + 1
    )
    assert result.allowed is False
    assert "blast-radius" in result.reason


def test_limited_mode_blocks_over_daily_count_cap(monkeypatch):
    _set_stage(monkeypatch, "limited")
    settings = get_settings()
    with session_scope() as session:
        for _ in range(settings.blast_radius_max_daily_count):
            session.add(
                OutcomesLog(
                    src_id="src_test",
                    supplier_name="Acme Corp",
                    exception_type="invalid_po",
                    action_taken="request_po_correction",
                    decided_by="policy",
                    autonomy_stage="limited",
                )
            )
    result = authorize_autonomous_action("Acme Corp", "invalid_po", confidence=0.99, amount=10)
    assert result.allowed is False
    assert "daily" in result.reason


def test_expanded_global_stage_falls_back_to_limited_without_snapshot(monkeypatch):
    _set_stage(monkeypatch, "expanded")
    result = authorize_autonomous_action("New Supplier LLC", "invalid_po", confidence=0.99, amount=10)
    assert result.allowed is True
    assert result.stage_used == AutonomyStage.LIMITED


def test_expanded_stage_honored_once_earned(monkeypatch):
    _set_stage(monkeypatch, "expanded")
    with session_scope() as session:
        session.add(
            GovernanceMetricSnapshot(
                supplier_name="Trusted Supplier Inc",
                exception_type="invalid_po",
                window_start=datetime.utcnow() - timedelta(days=30),
                window_end=datetime.utcnow(),
                sample_size=50,
                agreement_rate=0.98,
                dispute_rate=0.0,
                recommended_autonomy_stage="expanded",
            )
        )
    result = authorize_autonomous_action("Trusted Supplier Inc", "invalid_po", confidence=0.99, amount=10)
    assert result.allowed is True
    assert result.stage_used == AutonomyStage.EXPANDED

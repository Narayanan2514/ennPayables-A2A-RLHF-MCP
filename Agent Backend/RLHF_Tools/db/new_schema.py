"""Net-new tables backing the feedback loop (Document 4.1-4.7, Section 5, Section 8).

None of these exist in ennvault-existing today (audit section 13: "no
confidence-score column exists anywhere in the schema... no dedicated
exceptions or corrections table exists either"). They are purely additive --
see db/migrations/001_add_agentic_tables.sql for the raw DDL that would run
against the *same* MySQL database ennvault-existing uses, without touching any
existing table.

Everything here keys off `source.src_id` (legacy_schema.Source) via a plain
string column -- deliberately a soft reference, same convention log_table
already uses, so this stays compatible with however src_id values are minted.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class NewBase(DeclarativeBase):
    pass


class OutcomesLog(NewBase):
    """Reward signal for the contextual bandit (Section 4.3) and dashboard metrics (Section 8).

    One row per exception action taken (autonomously or by a human), with the
    downstream outcome filled in once it's known (cycle time, reversal, dispute).
    """

    __tablename__ = "outcomes_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20), nullable=False, index=True)
    supplier_name = Column(String(255), index=True)
    exception_type = Column(String(100), index=True)  # e.g. po_mismatch, bad_line_item, duplicate
    action_taken = Column(String(100))  # auto_fix_line_item | request_po_correction | email_supplier | auto_approve | escalate
    decided_by = Column(String(20))  # 'policy' | 'human'
    confidence_at_decision = Column(Float, nullable=True)
    reward = Column(Float, nullable=True)  # filled in once outcome is known; None while pending
    human_reversed = Column(Boolean, nullable=True)
    cycle_time_seconds = Column(Float, nullable=True)
    disputed_later = Column(Boolean, nullable=True)
    autonomy_stage = Column(String(20))  # shadow | limited | expanded, at time of decision
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class Correction(NewBase):
    """A labeled training example: {features, exception_type, AI recommendation,
    human action, outcome} -- Section 4.2. This is what searchSimilarCases
    retrieves few-shot context from, and what exemplar_refresh.py (Section 4.4)
    mines to refresh per-supplier exemplars or build a fine-tuning dataset.
    """

    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20), nullable=False, index=True)
    supplier_name = Column(String(255), index=True)
    doc_type = Column(String(50))
    exception_type = Column(String(100), index=True)
    document_layout = Column(String(100), nullable=True)
    invoice_features_json = Column(Text)  # JSON blob: amount, currency, po_number, field snapshot, etc.
    ai_recommendation = Column(Text)
    human_action = Column(Text)
    ai_recommendation_correct = Column(Boolean, nullable=True)
    confidence_at_decision = Column(Float, nullable=True)
    vector_id = Column(String(64), nullable=True)  # id of the matching embedding in Chroma
    created_at = Column(DateTime, default=datetime.utcnow)


class BanditArmState(NewBase):
    """Per (supplier, exception_type, action) Beta(alpha, beta) posterior for
    Thompson sampling (Section 4.3). Tracked separately per supplier and
    exception type deliberately -- "a pattern safe to auto-resolve for one
    supplier may not be for another."
    """

    __tablename__ = "bandit_arm_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_name = Column(String(255), index=True)
    exception_type = Column(String(100), index=True)
    action = Column(String(100), index=True)
    alpha = Column(Float, default=1.0)  # Beta prior successes
    beta = Column(Float, default=1.0)  # Beta prior failures
    trials = Column(Integer, default=0)
    successes = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow)


class Exemplar(NewBase):
    """Few-shot exemplar library refreshed periodically from Correction rows
    (Section 4.4, the "cheaper, faster, lower-risk" alternative to fine-tuning).
    """

    __tablename__ = "exemplars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_name = Column(String(255), index=True)
    doc_type = Column(String(50))
    field_name = Column(String(100), nullable=True)
    exemplar_json = Column(Text)  # {"input_snippet":..., "correct_output":..., "note":...}
    source_correction_id = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GovernanceMetricSnapshot(NewBase):
    """Rolling per-(supplier, exception_type) metrics that gate autonomy
    expansion (Section 4.7, Section 8). Written by evaluation/metrics.py on a
    schedule; read by orchestrator/governance.py before permitting an
    autonomous action.
    """

    __tablename__ = "governance_metric_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_name = Column(String(255), index=True)
    exception_type = Column(String(100), index=True)
    window_start = Column(DateTime)
    window_end = Column(DateTime)
    sample_size = Column(Integer, default=0)
    agreement_rate = Column(Float, nullable=True)
    dispute_rate = Column(Float, nullable=True)
    straight_through_rate = Column(Float, nullable=True)
    confidence_calibration_error = Column(Float, nullable=True)
    policy_regret = Column(Float, nullable=True)
    recommended_autonomy_stage = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentLog(NewBase):
    """One row per step the Orchestrator/Planner Agent takes while driving a
    src_id (Section 3) -- narration text, each tool call plus its result, and
    a start/end marker per process_document() invocation. This is the
    "traces" view the frontend renders on a document's detail page; it's
    purely an audit/observability record, not read by any policy logic (that
    still runs off log_table, outcomes_log, verifier_findings, etc.).

    `run_id` groups every row from one process_document() call together --
    a src_id can be run more than once (retry after a fix, a human re-running
    it from the UI), and each run's steps shouldn't interleave with another's.
    """

    __tablename__ = "agent_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20), nullable=False, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    turn = Column(Integer, nullable=False)
    step_type = Column(String(20), nullable=False)  # 'run_start' | 'text' | 'tool_call' | 'run_end'
    tool_name = Column(String(150), nullable=True)
    tool_input_json = Column(Text, nullable=True)
    tool_output_json = Column(Text, nullable=True)
    is_error = Column(Boolean, default=False)
    message = Column(Text, nullable=True)  # narration text, or the run's final status at run_end
    created_at = Column(DateTime, default=datetime.utcnow)


class VerifierFinding(NewBase):
    """Verifier/Critic agent output (Section 4.5) attached to every proposed
    EBS/JDE payload before submission. A human override on a finding is itself
    a training signal fed back into Correction/Exemplar refresh.
    """

    __tablename__ = "verifier_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20), nullable=False, index=True)
    verdict = Column(String(20))  # 'pass' | 'flag' | 'block'
    reasoning_trace = Column(Text)
    rule_violations_json = Column(Text, nullable=True)
    overridden_by_human = Column(Boolean, default=False)
    override_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

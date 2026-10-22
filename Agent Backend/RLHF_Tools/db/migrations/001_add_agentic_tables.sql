-- Additive migration for the agentic feedback loop (proposal Sections 4.1-4.7, 5, 8).
-- Run this against the SAME ennvault MySQL database ennvault-existing uses.
-- It does not ALTER or DROP any existing table -- inv_header, po_header,
-- log_table, source, etc. are untouched. All new tables use a plain
-- VARCHAR(20) src_id column as a soft reference to source.src_id, matching
-- the convention log_table already uses (no formal FK), so this stays
-- compatible regardless of how src_id values are minted.

CREATE TABLE IF NOT EXISTS outcomes_log (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    src_id                  VARCHAR(20) NOT NULL,
    supplier_name           VARCHAR(255),
    exception_type          VARCHAR(100),
    action_taken            VARCHAR(100),
    decided_by              VARCHAR(20),
    confidence_at_decision  FLOAT,
    reward                  FLOAT,
    human_reversed          TINYINT(1),
    cycle_time_seconds      FLOAT,
    disputed_later          TINYINT(1),
    autonomy_stage          VARCHAR(20),
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at             DATETIME NULL,
    INDEX idx_outcomes_src (src_id),
    INDEX idx_outcomes_supplier_exc (supplier_name, exception_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS corrections (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    src_id                      VARCHAR(20) NOT NULL,
    supplier_name               VARCHAR(255),
    doc_type                    VARCHAR(50),
    exception_type              VARCHAR(100),
    document_layout             VARCHAR(100),
    invoice_features_json       TEXT,
    ai_recommendation           TEXT,
    human_action                TEXT,
    ai_recommendation_correct   TINYINT(1),
    confidence_at_decision      FLOAT,
    vector_id                   VARCHAR(64),
    created_at                  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_corrections_src (src_id),
    INDEX idx_corrections_supplier_exc (supplier_name, exception_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS bandit_arm_state (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    supplier_name   VARCHAR(255),
    exception_type  VARCHAR(100),
    action          VARCHAR(100),
    alpha           FLOAT DEFAULT 1.0,
    beta            FLOAT DEFAULT 1.0,
    trials          INT DEFAULT 0,
    successes       INT DEFAULT 0,
    last_updated    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bandit_arm (supplier_name, exception_type, action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS exemplars (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    supplier_name           VARCHAR(255),
    doc_type                VARCHAR(50),
    field_name              VARCHAR(100),
    exemplar_json           TEXT,
    source_correction_id    INT,
    active                  TINYINT(1) DEFAULT 1,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_exemplars_supplier_doctype (supplier_name, doc_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS governance_metric_snapshots (
    id                              INT AUTO_INCREMENT PRIMARY KEY,
    supplier_name                   VARCHAR(255),
    exception_type                  VARCHAR(100),
    window_start                   DATETIME,
    window_end                     DATETIME,
    sample_size                    INT DEFAULT 0,
    agreement_rate                 FLOAT,
    dispute_rate                   FLOAT,
    straight_through_rate          FLOAT,
    confidence_calibration_error   FLOAT,
    policy_regret                  FLOAT,
    recommended_autonomy_stage     VARCHAR(20),
    created_at                     DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_governance_supplier_exc (supplier_name, exception_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verifier_findings (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    src_id                  VARCHAR(20) NOT NULL,
    verdict                 VARCHAR(20),
    reasoning_trace         TEXT,
    rule_violations_json    TEXT,
    overridden_by_human     TINYINT(1) DEFAULT 0,
    override_reason         TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_verifier_src (src_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

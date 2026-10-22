-- Additive migration: per-step trace log for the Orchestrator/Planner Agent.
-- Run this against the SAME ennvault MySQL database 001_add_agentic_tables.sql
-- already ran against. Does not touch any existing table.

CREATE TABLE IF NOT EXISTS agent_log (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    src_id              VARCHAR(20) NOT NULL,
    run_id              VARCHAR(36) NOT NULL,
    turn                INT NOT NULL,
    step_type           VARCHAR(20) NOT NULL,
    tool_name           VARCHAR(150),
    tool_input_json     TEXT,
    tool_output_json    TEXT,
    is_error            TINYINT(1) DEFAULT 0,
    message             TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent_log_src (src_id),
    INDEX idx_agent_log_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

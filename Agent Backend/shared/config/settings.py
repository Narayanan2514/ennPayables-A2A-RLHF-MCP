"""Environment-driven configuration shared by the orchestrator and agents."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


CLIENT_PORT = _env_int("CLIENT_PORT", 8000)
CLIENT_HOST = _env_str("CLIENT_HOST", "0.0.0.0")

AGENT_1_PORT = _env_int("AGENT_1_PORT", 8001)
AGENT_1_URL = _env_str("AGENT_1_URL", f"http://localhost:{AGENT_1_PORT}")

AGENT_2_PORT = _env_int("AGENT_2_PORT", 8002)
AGENT_2_URL = _env_str("AGENT_2_URL", f"http://localhost:{AGENT_2_PORT}")

AGENT_3_PORT = _env_int("AGENT_3_PORT", 8003)
AGENT_3_URL = _env_str("AGENT_3_URL", f"http://localhost:{AGENT_3_PORT}")

AGENT_4_PORT = _env_int("AGENT_4_PORT", 8004)
AGENT_4_URL = _env_str("AGENT_4_URL", f"http://localhost:{AGENT_4_PORT}")

REGISTERED_AGENT_URLS = [AGENT_1_URL, AGENT_2_URL, AGENT_3_URL, AGENT_4_URL]

AGENT_DISCOVERY_TIMEOUT_SECONDS = _env_float("AGENT_DISCOVERY_TIMEOUT_SECONDS", 5)
AGENT_REQUEST_TIMEOUT_SECONDS = _env_float("AGENT_REQUEST_TIMEOUT_SECONDS", 60)
AGENT_MAX_RETRIES = _env_int("AGENT_MAX_RETRIES", 2)

CORS_ORIGINS = _env_str("CORS_ORIGINS", "*").split(",")

# Each agent is a CrewAI agent that reasons and picks its own tool using this LLM.
OPENAI_API_KEY = _env_str("OPENAI_API_KEY", "")
OPENAI_MODEL = _env_str("OPENAI_MODEL", "gpt-4o-mini")
# Agent 3's vision extraction needs an actual vision-capable model (matches
# ennVault_org_backend's ChatOpenAI(model="gpt-4o", ...) in inv_extract.py).
OPENAI_VISION_MODEL = _env_str("OPENAI_VISION_MODEL", "gpt-4o")

# --- Microsoft Graph (mailbox) -- shared/graph_client.py, used by both the
# supervisor (listing unread mail) and Agent 1 (attachments/read-state) -----
TENANT_ID = _env_str("TENANT_ID", "")
CLIENT_ID = _env_str("CLIENT_ID", "")
CLIENT_SECRET = _env_str("CLIENT_SECRET", "")
TARGET_USER_EMAIL = _env_str("TARGET_USER_EMAIL", "")

# --- Shared attachment data root -- the SAME physical folder tree Backend's
# doc_transition/ owns (must match ENNVAULT_DATA_ROOT in Backend/.env and
# Agent/RLHF_Tools/.env -- see the comment next to it in Agent/.env). When
# set, attachments are downloaded straight into Backend's to_process/ folder
# instead of a separate Agent-local copy, so Backend can find them without
# any cross-machine/cross-cwd path translation. Falls back to the old
# Agent-local relative default only if ENNVAULT_DATA_ROOT is left blank.
ENNVAULT_DATA_ROOT = _env_str("ENNVAULT_DATA_ROOT", "")
EMAIL_ATTACHMENT_DIR = (
    os.path.join(ENNVAULT_DATA_ROOT, "to_process")
    if ENNVAULT_DATA_ROOT
    else _env_str("EMAIL_ATTACHMENT_DIR", "./data/to_process")
)

# --- Client-side pipeline watcher -----------------------------------------
# Single interval governing the supervisor's poll -> classify -> dispatch ->
# pipeline loop (client/orchestrator/email_polling.py + orchestrator.py).
# Replaces the old two-loop setup (Agent 1's own EMAIL_POLL_INTERVAL_SECONDS
# poller + this watcher draining its queue) now that Agent 1 no longer polls.
PIPELINE_WATCH_INTERVAL_SECONDS = _env_int("PIPELINE_WATCH_INTERVAL_SECONDS", 5)

# --- Shared pipeline-tools MCP server (../mcp_server, sibling to this
# repo's Agent/ folder) -- hosts the 5 tools agent_1-4's own CrewAI tools
# call instead of running their own in-process copy of intake_service/
# validation_service/extraction_service/ebs_push/jde_push (Phase 1 of
# consolidating them; Phase 2 adds the RLHF-backed exception-handling
# tools onto the same server). This venv can't install the `mcp` SDK
# directly -- its starlette/pydantic/uvicorn pins break the FastAPI version
# every agent's own A2A service needs -- so shared/mcp_tools/client.py
# shells out to that server's own venv instead of importing mcp here.
PIPELINE_MCP_SERVER_DIR = _env_str(
    "PIPELINE_MCP_SERVER_DIR", str(Path(__file__).resolve().parents[3] / "mcp_server")
)
PIPELINE_MCP_CALL_TIMEOUT_SECONDS = _env_int("PIPELINE_MCP_CALL_TIMEOUT_SECONDS", 300)

# --- Backend (ennPayables) API -- Agent 3 hits its /internal/source-ready
# endpoint right after committing a `source` row, so Backend can archive
# the attachment folder (see agents/agent_3/services/extraction_service.py
# and Backend/app/api/internal/service.py's archive_source). Replaces the
# retired to_process_listener.py's filesystem-watch trigger. Default
# matches Backend/.env's APP_PORT=8010.
BACKEND_API_URL = _env_str("BACKEND_API_URL", "http://localhost:8010")
BACKEND_API_TIMEOUT_SECONDS = _env_float("BACKEND_API_TIMEOUT_SECONDS", 30)

# --- RLHF exception-handling API (ennvault_RLHF_with_Tools), used by
# client/orchestrator/exception_handling.py after an ERP-push failure to call
# the same self-contained policy tools (apply_learned_correction,
# apply_learned_email, escalate_to_human, choose_bandit_action) that RLHF's
# own orchestrator/agent.py LLM loop uses -- see that module's docstring.
RLHF_API_URL = _env_str("RLHF_API_URL", "http://localhost:8010")
RLHF_API_TIMEOUT_SECONDS = _env_float("RLHF_API_TIMEOUT_SECONDS", 30)

# --- Agent 3: ennvault MySQL DB (same DB the legacy backend/ app uses) ---
DB_HOST = _env_str("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_USER = _env_str("DB_USER", "root")
DB_PASSWORD = _env_str("DB_PASSWORD", "")
DB_NAME = _env_str("DB_NAME", "ennvault")
DB_URL_OVERRIDE = _env_str("DB_URL_OVERRIDE", "")  # e.g. sqlite:///./dev.db for offline/dev/test


def database_url() -> str:
    if DB_URL_OVERRIDE:
        return DB_URL_OVERRIDE
    from urllib.parse import quote_plus

    return f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


# --- Agent 3/4: JDE / Oracle EBS REST endpoints --------------------------
JDE_BASE_URL = _env_str("JDE_BASE_URL", "")
JDE_USERNAME = _env_str("JDE_USERNAME", "")
JDE_PASSWORD = _env_str("JDE_PASSWORD", "")
JDE_VERIFY_TLS = _env_bool("JDE_VERIFY_TLS", True)
JDE_DEFAULT_BUSINESS_UNIT = _env_str("JDE_DEFAULT_BUSINESS_UNIT", "")
# Optional: force every voucher-approval email to one test inbox instead of
# the real approver (see agents/agent_4/services/mailer.py's docstring for
# why this is opt-in rather than the reference project's hardcoded default).
JDE_APPROVAL_EMAIL_OVERRIDE = _env_str("JDE_APPROVAL_EMAIL_OVERRIDE", "")

EBS_BASE_URL = _env_str("EBS_BASE_URL", "")
EBS_USERNAME = _env_str("EBS_USERNAME", "")
EBS_PASSWORD = _env_str("EBS_PASSWORD", "")
EBS_VERIFY_TLS = _env_bool("EBS_VERIFY_TLS", True)

# --- Agent 2: OCR (word-level PII masking before any page image is sent
# to the vision LLM) -- pytesseract shells out to the `tesseract` binary,
# which is NOT a pip package; install Tesseract-OCR separately and either
# put it on PATH or point TESSERACT_CMD at tesseract.exe.
TESSERACT_CMD = _env_str("TESSERACT_CMD", "")

# --- Which ERP this deployment targets for the automatic email pipeline --
# Mirrors ennVault_org_backend's TARGET_ERP env var (read there via
# os.getenv("TARGET_ERP") in prep.py/inv_extract.py): a single switch that
# decides which ERP-specific branch the pipeline takes for a given run, so
# only one ERP ever receives a live submission for the same record. "JDE"
# or "EBS"; threaded through every stage as an argument -- Agent 3's
# extraction-taxonomy router and Agent 4's push router are what actually
# branch on it (client/orchestrator/orchestrator.py just forwards it).
TARGET_ERP = _env_str("TARGET_ERP", "EBS").strip().upper()

# --- Durable workflow_session (client/orchestrator): a single stable
# identity for this running worker process, used to claim/own sessions --
# never generated per-email. Set WORKER_NODE_ID explicitly (e.g. "worker-01")
# when running multiple worker processes so ownership is meaningful; a
# random one is fine for a single-process dev setup.
WORKER_NODE_ID = _env_str("WORKER_NODE_ID", "") or f"worker-{uuid.uuid4().hex[:8]}"

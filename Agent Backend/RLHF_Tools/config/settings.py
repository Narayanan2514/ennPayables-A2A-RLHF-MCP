from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to this file's own location rather than a bare ".env" (which
# pydantic-settings resolves relative to the CURRENT WORKING DIRECTORY) --
# a caller importing this module from any other CWD (e.g. the shared
# mcp_server/ process in Phase 2, which never runs from inside RLHF_Tools/)
# would otherwise silently get every setting's hardcoded default instead of
# RLHF_Tools/.env's real values (DB creds, autonomy stage, thresholds, ...).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
_RLHF_ROOT = _ENV_FILE.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "pass123"
    db_name: str = "ennvault"
    db_url_override: str = ""

    # LLM providers
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_vision_model: str = "gpt-4o"

    # Oracle EBS
    ebs_base_url: str = ""
    ebs_username: str = ""
    ebs_password: str = ""
    ebs_verify_tls: bool = True

    # JDE Orchestrator
    jde_base_url: str = ""
    jde_username: str = ""
    jde_password: str = ""
    jde_verify_tls: bool = True

    # Microsoft Graph / supplier communication
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    target_user_email: str = ""

    # Vector memory. A relative value (the default, and what .env sets) is
    # resolved against RLHF_Tools/ itself, not the caller's CWD -- otherwise
    # a process running from anywhere else (e.g. the shared mcp_server/
    # process Phase 2 added) silently reads/writes a SEPARATE, empty Chroma
    # store instead of the real one, making every past correction invisible
    # to apply_learned_correction/apply_learned_email (confirmed: this
    # silently created mcp_server/data/chroma alongside the real
    # RLHF_Tools/data/chroma).
    chroma_persist_dir: str = "./data/chroma"

    @field_validator("chroma_persist_dir")
    @classmethod
    def _resolve_chroma_persist_dir(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = _RLHF_ROOT / path
        return str(path)

    # MCP servers (Streamable HTTP transport, HTTP Basic Auth)
    mcp_host: str = "127.0.0.1"
    mcp_username: str = "admin"
    mcp_password: str = "pass123"
    invoice_db_port: int = 9001
    document_intelligence_port: int = 9002
    oracle_ebs_port: int = 9003
    jde_port: int = 9004
    supplier_communication_port: int = 9005
    memory_policy_port: int = 9006

    # Governance / staged autonomy
    autonomy_stage: str = "limited"
    stp_confidence_threshold: float = 0.92
    auto_correct_confidence_threshold: float = 0.75
    blast_radius_max_amount: float = 2500.0
    blast_radius_max_daily_count: int = 25

    @property
    def database_url(self) -> str:
        if self.db_url_override:
            return self.db_url_override

        encoded_password = quote_plus(self.db_password)

        return (
            f"mysql+pymysql://{self.db_user}:{encoded_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
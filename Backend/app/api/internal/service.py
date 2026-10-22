"""Archives the attachment folder Agent's pipeline already extracted from.

This is the one piece of the old prep.py/run_parser pipeline (retired --
see _deprecated/modules/processing/pre_processor/prep.py) that's still
genuinely needed: something has to copy the ingested folder into
archival/ and record that on source.archive, since Agent's own pipeline
(Agent/agents/agent_3/services/extraction_service.py) does extraction and
the DB insert itself but never archives (always inserts archive=None).

Called from a new internal endpoint (routes.py) that Agent 3 hits right
after it commits its `source` row -- an explicit, synchronous handoff
replacing the retired folder-watcher's filesystem polling.
"""
import os
import shutil

from app.setttings.config import DATA_ROOT
from app.api.ennPayables.EBS.db import db_connection

# NOTE: deliberately NOT app.setttings.config.get_db_connection -- that one
# connects with hardcoded literal credentials (wrong password in this
# environment, raises "Access denied for user 'root'@'localhost'") instead
# of reading HOST/DB_USER/PASSWORD/DATABASE_NAME from .env like every other
# live EBS endpoint does via this db_connection().


def _get_source_row(src_id: str) -> dict:
    conn = db_connection()
    if conn is None:
        raise ValueError("Could not connect to the database")
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT src_id, folder_path, archive FROM source WHERE src_id = %s",
            (src_id,),
        )
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"No source row found for src_id={src_id!r}")
    return row


def _update_archive(src_id: str, archive_path: str) -> None:
    conn = db_connection()
    if conn is None:
        raise ValueError("Could not connect to the database")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE source SET archive = %s WHERE src_id = %s",
            (archive_path, src_id),
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()


def _archive_relative_path(folder_path: str) -> str:
    """"to_process/inv/upload_20260909_..." -> "archival/inv/upload_20260909_...".

    folder_path is stored relative to DATA_ROOT (see ENNVAULT_DATA_ROOT) --
    swaps the leading to_process segment for archival, keeping the rest of
    the structure (doc-type subfolder + upload folder name) unchanged.
    """
    parts = [p for p in os.path.normpath(folder_path).split(os.sep) if p not in ("", ".")]
    if parts and parts[0] == "to_process":
        parts = parts[1:]
    return os.path.join("archival", *parts) if parts else "archival"


def archive_source(src_id: str) -> dict:
    if not DATA_ROOT:
        raise ValueError("ENNVAULT_DATA_ROOT is not configured")

    row = _get_source_row(src_id)

    # Idempotent: a retried handoff call (e.g. Agent's request timed out but
    # actually succeeded) shouldn't re-copy or error.
    existing_archive = row.get("archive")
    if existing_archive and os.path.isdir(os.path.join(DATA_ROOT, existing_archive)):
        return {"src_id": src_id, "archive": existing_archive, "status": "already_archived"}

    folder_path = row.get("folder_path")
    if not folder_path:
        raise ValueError(f"source row for src_id={src_id!r} has no folder_path")

    source_full_path = os.path.normpath(os.path.join(DATA_ROOT, folder_path))
    if not os.path.isdir(source_full_path):
        raise FileNotFoundError(f"to_process folder not found: {source_full_path}")

    archive_relative = _archive_relative_path(folder_path)
    archive_full_path = os.path.join(DATA_ROOT, archive_relative)

    # Copy rather than move: source.folder_path keeps pointing at a real
    # folder, since RLHF_Tools' supplier-email attachment flow
    # (legacy_repo.get_source_attachment_paths) reads the original from
    # there, not from archive.
    os.makedirs(os.path.dirname(archive_full_path), exist_ok=True)
    shutil.copytree(source_full_path, archive_full_path, dirs_exist_ok=True)

    _update_archive(src_id, archive_relative)

    return {"src_id": src_id, "archive": archive_relative, "status": "archived"}

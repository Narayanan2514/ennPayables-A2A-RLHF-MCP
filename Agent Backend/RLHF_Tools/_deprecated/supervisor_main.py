"""RETIRED -- do not run.

Confirmed superseded: the one real supervisor is Agent/api/main/main.py
(client/orchestrator API + `orchestrator.watch_email_pipeline()`), which
drives Agents 1-4 directly. This file was this project's earlier
predecessor design -- same role `Backend/folder_listeners/to_process_listener.py`
played for the old ennvault-existing pipeline -- and was never the live
front door. RLHF_Tools itself is just the MCP tool servers used for RLHF
actions (correction/escalation/etc.), not a pipeline supervisor.

Moved here (out of the module search path) rather than deleted, so the
watchdog-trigger design and the periodic learning-refresh/governance-snapshot
jobs it bundled remain available for reference if either is ever wired up
for real. If the learning-refresh/governance-snapshot jobs are still
needed, they should be scheduled from somewhere in the live pipeline
instead of resurrecting this file as-is.

Original docstring follows, unmodified:
---
Supervisor entrypoint: the new front door replacing ennvault-existing's
`folder_listeners/to_process_listener.py` -> `prep.run_parser()` hardcoded
sequence with a call into the Orchestrator/Planner Agent (Section 3, 4.6).

What this deliberately does NOT re-implement: ennvault-existing's
pre-processing stage (modules/processing/pre_processor/transform.py) --
format detection against exclusion_config/*.json, PDF word-tokenization/
redaction, and OCR fallback for scanned documents. That privacy/de-identification
layer is orthogonal to the agentic-architecture rework this proposal asks
for, and rebuilding it isn't necessary to demonstrate the MCP/orchestrator/
feedback-loop design -- it should keep running as-is (or be migrated
separately) upstream of this entrypoint, dropping ready-to-extract page
images into WATCH_DIR the same way it does today, folder-per-document.

Two things run here:
1. A watchdog observer on WATCH_DIR (env-configurable -- ennvault-existing
   hardcodes `/home/opc/ennVault/Backend/doc_transition/to_process`, audit
   section 1) that resolves the folder to a src_id and hands off to
   orchestrator.agent.process_document.
2. An APScheduler background scheduler running the periodic learning jobs
   (Section 4.4's exemplar refresh, Section 8's governance snapshots).

Run with:
    python supervisor_main.py
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from db.session import session_scope
from db.new_schema import Correction
from evaluation.metrics import write_governance_snapshot
from learning.exemplar_refresh import refresh_exemplars
from orchestrator.agent import process_document

WATCH_DIR = os.getenv("AGENTIC_WATCH_DIR", "./data/to_process")
EXEMPLAR_REFRESH_INTERVAL_HOURS = int(os.getenv("EXEMPLAR_REFRESH_INTERVAL_HOURS", "24"))
GOVERNANCE_SNAPSHOT_INTERVAL_HOURS = int(os.getenv("GOVERNANCE_SNAPSHOT_INTERVAL_HOURS", "24"))

# email_module/service.py writes attachment files to folder_path (via
# download_attachments) BEFORE it commits the matching `source` row (via
# insert_source) -- watchdog's on_created fires the instant the first
# attachment file is written, which is routinely *before* that commit lands,
# not just occasionally. Retrying for a few seconds closes this cross-process
# race instead of treating every normal ingestion as a hard failure.
SRC_ID_RESOLVE_RETRIES = int(os.getenv("SRC_ID_RESOLVE_RETRIES", "15"))
SRC_ID_RESOLVE_RETRY_DELAY_SECONDS = float(os.getenv("SRC_ID_RESOLVE_RETRY_DELAY_SECONDS", "1.0"))

_processing_folders: set[str] = set()
_lock = threading.Lock()


def _resolve_src_id_for_folder(folder_path: str) -> str | None:
    """Same resolution ennvault-existing's prep.py does today: the folder was
    populated by the ingestion step (email poller or any future channel)
    which already minted a src_id and recorded folder_path on `source`.
    """
    from sqlalchemy import select

    from db.legacy_schema import Source
    from db.session import session_scope as _session_scope

    with _session_scope() as session:
        row = session.scalar(select(Source).where(Source.folder_path == folder_path))
        return row.src_id if row else None


def _handle_ready_folder(folder_path: str) -> None:
    with _lock:
        if folder_path in _processing_folders:
            return
        _processing_folders.add(folder_path)
    try:
        print("Searching src_id for", folder_path)
        src_id = None
        for attempt in range(1, SRC_ID_RESOLVE_RETRIES + 1):
            src_id = _resolve_src_id_for_folder(folder_path)
            if src_id is not None:
                break
            time.sleep(SRC_ID_RESOLVE_RETRY_DELAY_SECONDS)
        print("Src_id", src_id)
        if src_id is None:
            # Still no matching `source` row after retrying through the
            # ingestion race above -- this folder was never actually
            # ingested (e.g. a stray file dropped by hand), so there's no
            # real src_id to attach an audit row to. log_table's entity_id
            # column is only 20 chars (source.src_id-sized); a folder name
            # like "upload_20260904_112213" overflows it and previously
            # crashed this thread on every occurrence of the race above --
            # this is deliberately just a console message, not a DB write.
            print(f"[supervisor] no source row found for folder {folder_path} after "
                  f"{SRC_ID_RESOLVE_RETRIES} retries -- skipping (not a recognized document)")
            return
        result = asyncio.run(process_document(src_id))
        print(f"[supervisor] processed {src_id}: {result.get('status')}")
    finally:
        with _lock:
            _processing_folders.discard(folder_path)


class ReadyFolderHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        folder_path = str(Path(event.src_path).parent)
        threading.Thread(target=_handle_ready_folder, args=(folder_path,), daemon=True).start()


def _distinct_supplier_exception_pairs() -> list[tuple[str, str]]:
    with session_scope() as session:
        rows = session.query(Correction.supplier_name, Correction.exception_type).distinct().all()
        return [(r[0], r[1]) for r in rows if r[0] and r[1]]


def _run_scheduled_jobs() -> None:
    print("[supervisor] refreshing few-shot exemplar library...")
    print(refresh_exemplars())

    for supplier_name, exception_type in _distinct_supplier_exception_pairs():
        snapshot = write_governance_snapshot(supplier_name, exception_type)
        print(f"[supervisor] governance snapshot {supplier_name}/{exception_type}: {snapshot['recommended_autonomy_stage']}")


def main() -> None:
    Path(WATCH_DIR).mkdir(parents=True, exist_ok=True)

    scheduler = BackgroundScheduler()
    scheduler.add_job(_run_scheduled_jobs, "interval", hours=EXEMPLAR_REFRESH_INTERVAL_HOURS, id="learning_refresh")
    scheduler.start()

    observer = Observer()
    observer.schedule(ReadyFolderHandler(), WATCH_DIR, recursive=True)
    observer.start()
    print(f"[supervisor] watching {WATCH_DIR} for ready-to-extract documents...")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
        scheduler.shutdown()
    observer.join()


if __name__ == "__main__":
    main()

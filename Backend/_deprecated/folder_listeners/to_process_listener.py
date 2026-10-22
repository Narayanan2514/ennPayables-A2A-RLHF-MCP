# RETIRED -- do not run.
#
# Confirmed superseded: this Backend-side watcher + its `prep.run_parser()`
# pipeline (extraction, DB insert, ERP push, archiving) was the old
# predecessor of what is now the Agent/agents (agent_1-4) multi-agent
# structure -- Agent 1 does intake, Agent 2 validates, Agent 3 extracts +
# writes to the same `source`/`inv_header`/etc. tables, Agent 4 pushes to
# ERP. Backend's live role is now read-only: serve the frontend's document
# list and `fetch-invoice-file-ebs` from what Agent already wrote to the DB
# and filesystem (see app/api/ennPayables/EBS/services.py, db.py).
#
# Moved here (out of the module search path) rather than deleted, so the
# original archive/move/transform/LLM-extraction/ERP-push logic remains
# available for reference. The one piece that's still genuinely needed --
# archiving a file after Agent's pipeline finishes with it, since Agent
# itself never does that (see agents/agent_3/services/extraction_service.py)
# -- should be reimplemented as a small, explicit endpoint Agent calls after
# it commits its `source` row, not by resurrecting this folder-watcher.
#
# folder_listeners/to_process_listener.py (original path)

import time
import os
import threading
from modules.processing.pre_processor.prep import *
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ---------------- GLOBAL PROCESSING TRACKER ----------------

processing_folders = set()
processing_lock = threading.Lock()

# ---------------- CONFIG ----------------

TO_PROCESS_DIR = "/home/opc/ennVault/ennPayables/backend/doc_transition/to_process"

# ---------------- HELPER ----------------

def wait_until_file_ready(file_path):
    last_size = -1
    while True:
        if not os.path.exists(file_path):
            return

        size = os.path.getsize(file_path)

        if size == last_size:
            return

        last_size = size
        time.sleep(1)


# ---------------- HANDLER ----------------

class ToProcessHandler(FileSystemEventHandler):

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            print(f"📄 New file detected: {file_path}")

            threading.Thread(
                target=self.handle_file,
                args=(file_path,),
                daemon=True
            ).start()

    def handle_file(self, file_path):
        folder_path = os.path.dirname(file_path)

        with processing_lock:
            if folder_path in processing_folders:
                print(f"⚠ Already processing: {folder_path}")
                return

            processing_folders.add(folder_path)

        try:
            print(f"📂 Processing folder: {folder_path}")

            # Wait for all files in folder to finish copying
            for file_name in os.listdir(folder_path):
                file_full_path = os.path.join(folder_path, file_name)

                print(f"⏳ Waiting for file copy to complete: {file_name}")
                wait_until_file_ready(file_full_path)
                print(f"✅ File copy completed: {file_name}")

            print(f"🚀 Starting parser for folder: {folder_path}")
            run_parser(folder_path)

            print(f"🏁 Finished processing: {folder_path}")

        finally:
            with processing_lock:
                processing_folders.remove(folder_path)


# ---------------- START LISTENER ----------------

def start_listener():
    os.makedirs(TO_PROCESS_DIR, exist_ok=True)

    event_handler = ToProcessHandler()
    observer = Observer()
    observer.schedule(event_handler, TO_PROCESS_DIR, recursive=True)
    observer.start()

    print("👂 to_process_listener started...")
    print(f"👀 Watching: {TO_PROCESS_DIR}")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start_listener()

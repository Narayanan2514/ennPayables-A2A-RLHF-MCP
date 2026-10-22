import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

AGENT_ID = "erp-push-agent"
AGENT_NAME = "ERP Push Agent"
AGENT_VERSION = "1.0.0"
AGENT_PORT = int(os.getenv("AGENT_4_PORT", 8004))
AGENT_URL = os.getenv("AGENT_4_URL", f"http://localhost:{AGENT_PORT}")

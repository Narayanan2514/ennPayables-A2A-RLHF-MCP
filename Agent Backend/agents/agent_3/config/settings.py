import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

AGENT_ID = "extraction-agent"
AGENT_NAME = "Extraction Agent"
AGENT_VERSION = "1.0.0"
AGENT_PORT = int(os.getenv("AGENT_3_PORT", 8003))
AGENT_URL = os.getenv("AGENT_3_URL", f"http://localhost:{AGENT_PORT}")

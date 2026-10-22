import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

AGENT_ID = "email-intake-agent"
AGENT_NAME = "Email Intake Agent"
AGENT_VERSION = "2.0.0"
AGENT_PORT = int(os.getenv("AGENT_1_PORT", 8001))
AGENT_URL = os.getenv("AGENT_1_URL", f"http://localhost:{AGENT_PORT}")

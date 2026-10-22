import sys
from pathlib import Path

# Ensure `backend/` (this file's directory) is importable as the root for
# `shared`, `client`, `agents` and `api`, regardless of pytest's import mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))

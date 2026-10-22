"""Importing `settings` (the package root's own module, not this tests/
package) puts Agent/ and Agent/RLHF_Tools/ on sys.path as a side effect --
see ../settings.py -- which every tools/*.py module needs before it can
import agents.*/mcp_servers.*/learning.*. Must happen before test
collection imports any tools module.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings  # noqa: E402,F401

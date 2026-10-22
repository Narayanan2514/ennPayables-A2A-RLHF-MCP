"""Structured output contract for this agent's crew.

Re-exported from `shared.crew.schemas` since every agent's crew fills in the
same tool-result envelope; kept as a local import so each agent's package is
self-describing without another agent needing to know this indirection.
"""
from __future__ import annotations

from shared.crew.schemas import ToolResultOutput

__all__ = ["ToolResultOutput"]

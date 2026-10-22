"""Structured output contract every agent's crew must fill in.

CrewAI forces the final Task output to validate against this model
(`Task(output_pydantic=ToolResultOutput)`), so the executor gets a reliable
structured result regardless of how much the LLM 'talks' along the way.

Deliberately NOT using `from __future__ import annotations` here: CrewAI's
`generate_model_description` (crewai/utilities/converter.py) reads
`model.__annotations__` directly and expects real type objects, not the
stringified annotations PEP 563 would produce -- with the future import,
every field type came through as a plain `str` and crashed CrewAI's
`describe_field` with `AttributeError: 'str' object has no attribute
'__name__'` on every single crew.kickoff() call.
"""
from typing import Any, Optional

from pydantic import BaseModel


class ToolResultOutput(BaseModel):
    skill_used: str
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None

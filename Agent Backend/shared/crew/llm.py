"""Shared LLM factory for the three CrewAI agents.

This is infrastructure wiring (which model/provider powers each crew's
reasoning), not business logic -- each agent still defines its own role,
goal, backstory and tools independently.
"""
from __future__ import annotations

from crewai import LLM

from shared.config.settings import OPENAI_API_KEY, OPENAI_MODEL


def build_llm() -> LLM:
    # temperature=0: CrewAI's tool-call argument parser is a ReAct-style
    # text parser (not native OpenAI function calling) that has to emit
    # exactly-valid JSON as free text -- a lower temperature measurably cuts
    # down on malformed "Action Input" output that would otherwise burn
    # through the agent's retry budget.
    return LLM(
        model=f"openai/{OPENAI_MODEL}" if not OPENAI_MODEL.startswith("openai/") else OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0,
    )

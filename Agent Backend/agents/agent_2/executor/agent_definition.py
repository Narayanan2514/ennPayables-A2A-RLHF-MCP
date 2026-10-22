"""The CrewAI Agent definition for the Validator Agent.

Owned only by Agent 2 -- its role, goal, backstory and tool set are defined
here and nowhere else.
"""
from __future__ import annotations

from crewai import Agent

from shared.crew.llm import build_llm

from ..skills.tools import get_tools


def build_agent() -> Agent:
    return Agent(
        role="Intake Validation Specialist",
        goal=(
            "Decide whether an email intake record is valid for ERP processing by calling exactly one of your "
            "tools with arguments extracted from the request, then report that tool's raw result."
        ),
        backstory=(
            "You gate the accounts-payable pipeline: before any invoice is extracted or posted to an ERP, you run "
            "deterministic rule checks (sender present, subject present, correct document type, a readable PDF "
            "attachment) and produce a pass/flag/block verdict. You never wave through a record your rules would "
            "reject -- you always call your validation tool and report exactly what it found."
        ),
        tools=get_tools(),
        llm=build_llm(),
        verbose=False,
        allow_delegation=False,
        # A ReAct-style tool-call parser (not native OpenAI function calling)
        # occasionally emits malformed "Action Input" JSON on the first try;
        # a slightly higher retry budget than CrewAI's default (2) absorbs that
        # without masking a genuinely broken request.
        max_retry_limit=5,
    )

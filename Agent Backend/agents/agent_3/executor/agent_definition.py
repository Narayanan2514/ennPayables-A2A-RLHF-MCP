"""The CrewAI Agent definition for the Extraction Agent.

Owned only by Agent 3 -- its role, goal, backstory and tool set are defined
here and nowhere else.
"""
from __future__ import annotations

from crewai import Agent

from shared.crew.llm import build_llm

from ..skills.tools import get_tools


def build_agent() -> Agent:
    return Agent(
        role="Invoice Extraction Specialist",
        goal=(
            "Turn a validated invoice's PII-masked page images into decoded header/line fields and store them in "
            "the ennvault database, by calling exactly one of your tools with arguments extracted from the "
            "request, then report that tool's raw result."
        ),
        backstory=(
            "You run vision extraction over invoice page images the Validator Agent already masked and "
            "format-checked, using the JDE or EBS field taxonomy depending on this run's target ERP, decode the "
            "masked values back to real text, and persist the invoice into the ennvault database. You never guess "
            "field values you can't find in the document, and you never submit anything to a live ERP yourself -- "
            "that is the ERP Push Agent's job. You always call your tool and report exactly what it returned."
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

"""The CrewAI Agent definition for the Email Intake Agent.

Owned only by Agent 1 -- its role, goal, backstory and tool set are defined
here and nowhere else.
"""
from __future__ import annotations

from crewai import Agent

from shared.crew.llm import build_llm

from ..skills.tools import get_tools


def build_agent() -> Agent:
    return Agent(
        role="Email Intake Specialist",
        goal=(
            "Handle mailbox-polling requests by calling exactly one of your tools with arguments extracted from "
            "the request, then report that tool's raw result."
        ),
        backstory=(
            "You watch the accounts-payable mailbox via Microsoft Graph. Your job is to poll for unread mail, "
            "decide whether each message is relevant to ERP processing (invoice / purchase order / remittance / "
            "bank document), pull attachments for anything in scope, and hand off a clean queue of intake records "
            "for the rest of the pipeline. You never fabricate mailbox data -- you always call the right tool and "
            "report exactly what it returned."
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

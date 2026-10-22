"""The CrewAI Agent definition for the ERP Push Agent.

Owned only by Agent 4 -- its role, goal, backstory and tool set are defined
here and nowhere else.
"""
from __future__ import annotations

from crewai import Agent

from shared.crew.llm import build_llm

from ..skills.tools import get_tools


def build_agent() -> Agent:
    return Agent(
        role="ERP Push Specialist",
        goal=(
            "Push a stored invoice to whichever live ERP this run targets by calling exactly one of your tools "
            "with arguments extracted from the request, then report that tool's raw result."
        ),
        backstory=(
            "You are the last stop before an invoice reaches a live ERP. For JDE you run the full "
            "CheckPO -> AddSupplierInvoice -> (approval-hold-and-email if required) -> RunVMADriverUBE sequence; "
            "for EBS you post the create_invoices REST call. You always read the invoice back from the ennvault "
            "database by src_id -- you never invent header or line values yourself, and you never push to the "
            "wrong ERP for this run's target_erp."
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

"""MCP tools backing ennvault's ERP-exception-handling sequence.

Thin wrappers over RLHF_Tools' existing, self-contained policy handlers
(orchestrator/native_tools.py) -- imported in place from the sibling
Agent/RLHF_Tools folder, not duplicated here. RLHF's own orchestrator/agent.py
(the run-agent feature Agent Frontend's dashboard triggers) keeps calling
these same handlers locally/unchanged; this just gives ennvault's own
pipeline (client/orchestrator/exception_handling.py) an MCP-native way to
reach the same four actions instead of RLHF's separate REST API.
"""
from __future__ import annotations

from typing import Any

from orchestrator.native_tools import (
    _apply_learned_correction,
    _apply_learned_email,
    _choose_bandit_action,
    _escalate_to_human,
)


def register(mcp) -> None:
    @mcp.tool()
    def choose_bandit_action(supplier_name: str, exception_type: str) -> dict[str, Any]:
        """Contextual bandit (Thompson sampling over a per supplier +
        exception_type Beta posterior): returns the recommended
        exception-handling action for this pair."""
        return _choose_bandit_action(supplier_name, exception_type)

    @mcp.tool()
    def apply_learned_correction(src_id: str, supplier_name: str, exception_type: str) -> dict[str, Any]:
        """Executes the 'auto_fix_line_item' action for real, and is fully
        self-contained -- it loads the invoice itself, re-checks
        authorization itself, and logs the outcome and bandit reward
        itself. It replays the closest past human field-correction for
        this supplier + exception_type (from vector memory) onto this
        document's header/lines, then resubmits to the ERP. Returns
        applied=false (never guesses, never fabricates a value) if it
        isn't currently authorized to act, or no sufficiently similar past
        correction exists -- treat applied=false as a signal to escalate
        to a human instead."""
        return _apply_learned_correction(src_id, supplier_name, exception_type)

    @mcp.tool()
    def apply_learned_email(src_id: str, supplier_name: str, exception_type: str) -> dict[str, Any]:
        """Executes the 'email_supplier'/'request_po_correction' action for
        real, and is fully self-contained -- it only sends when a human has
        already resolved this exact (supplier_name, exception_type) by
        emailing the supplier once before, re-checks authorization itself,
        and logs the outcome and bandit reward itself. Returns
        applied=false (never invents a recipient or drafts a fix from
        nothing) if there's no such past precedent yet, or it isn't
        currently authorized -- treat applied=false as a signal to
        escalate to a human instead."""
        return _apply_learned_email(src_id, supplier_name, exception_type)

    @mcp.tool()
    def escalate_to_human(
        src_id: str,
        supplier_name: str,
        exception_type: str,
        action_recommended: str,
        reason: str,
        hold: bool = False,
    ) -> dict[str, Any]:
        """Marks a case as NOT resolved and puts it in front of a human,
        atomically -- writes both outcomes_log (decided_by='human') and
        log_table (status='Failed' or 'OnHold') in one call, so it's
        guaranteed to actually show up in the Manual Review queue. Call
        this whenever authorize_autonomous_action would return
        allowed=false, the recommended action is literally 'escalate', or
        apply_learned_correction / apply_learned_email returned
        applied=false. hold=true for a hold-for-approval case
        (status=OnHold); false for status=Failed."""
        return _escalate_to_human(src_id, supplier_name, exception_type, action_recommended, reason, hold)

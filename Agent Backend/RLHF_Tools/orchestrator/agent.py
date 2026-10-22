"""The Orchestrator/Planner Agent (Section 3, and Section 4.6's "MCP-Based
Restructuring of the Pipeline").

"Rather than three agents wired together in a fixed sequence, the target
architecture introduces an orchestrating agent that plans its own next action
by calling tools -- exposed through MCP servers -- rather than being
hardcoded to call Agent 2 after Agent 1... decisions about sequencing and
tool use are made by the model at run time, constrained by the tools
available and the policies described in Section 4."

An OpenAI model (gpt-4o by default, via OPENAI_MODEL) drives a standard
function-calling loop over the full registry: the six MCP servers
(mcp_client.py) plus the deterministic policy tools (native_tools.py:
routing, bandit, governance, verifier). The model decides *when* to call
what; the policy math those native tools run is fixed, tested Python, not
something re-derived from a prompt each time.

Entry point: `asyncio.run(process_document("src_042"))`.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import openai

from config.settings import get_settings
from mcp_servers.common import legacy_repo
from orchestrator.mcp_client import MCPToolRegistry
from orchestrator.native_tools import NATIVE_TOOL_HANDLERS, NATIVE_TOOL_SCHEMAS
from orchestrator.trace_logger import log_step

# --- Previous SYSTEM_PROMPT (superseded -- kept for reference) -------------
# Step 3 let the model pass po_match into run_verifier without ever actually
# looking the PO up, so it would invent {} or None -- producing inconsistent
# verdicts for the identical PO across runs (an empty {} reads as "not
# matched" and blocks, while None skips the check entirely and passes). See
# the src_306 vs src_309 run comparison that surfaced this.
#
# SYSTEM_PROMPT = """\
# You are the Orchestrator/Planner Agent for an accounts-payable invoice pipeline.
#
# Your job for a given src_id is to drive it from "just ingested" to a terminal
# state (successfully submitted to the ERP, on hold pending human review, or
# escalated as an exception) by choosing which tools to call and in what order.
# You are not following a fixed script -- decide the next action based on what
# each tool call tells you.
#
# Hard rules you must follow:
# 1. Always call get_source first to learn the doc_type and target ERP.
# 2. For an invoice: extract with the document-intelligence server, then call
#    decide_extraction_routing on the result. Persist the extracted fields via
#    invoice_db's insert_invoice regardless of the routing outcome (a human
#    needs to see them even on escalation). If routing says "escalate", log the
#    event and stop -- do not attempt ERP submission.
# 3. Before ANY create_invoice call (EBS or JDE), you must call run_verifier
#    with the current header/lines/po_match. If the verdict is "block", do not
#    submit -- treat it as an exception instead (step 4).
# 4. If ERP submission fails, or the verifier blocks: classify what kind of
#    exception it is, call choose_bandit_action to get a recommended action,
#    then call authorize_autonomous_action before actually executing that
#    action yourself. If authorize_autonomous_action returns allowed=false,
#    log the recommendation and escalate to a human instead of acting.
# 5. Call log_outcome once you've made a decision (whether autonomous or
#    escalated to a human), and log_event (invoice_db server) at every stage
#    transition so the existing audit trail (log_table) stays accurate.
# 6. Never fabricate field values. If required data is missing, escalate.
#
# Work step by step, calling one tool at a time, and narrate your reasoning
# briefly before each call.
# """
# -----------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Orchestrator/Planner Agent for an accounts-payable invoice pipeline.

Your job for a given src_id is to drive it from "just ingested" to a terminal
state (successfully submitted to the ERP, on hold pending human review, or
escalated as an exception) by choosing which tools to call and in what order.
You are not following a fixed script -- decide the next action based on what
each tool call tells you.

Hard rules you must follow:
1. Always call get_source first to learn the doc_type and target ERP.
2. For an invoice: extract with the document-intelligence server, then call
   decide_extraction_routing on the result. Persist the extracted fields via
   invoice_db's insert_invoice regardless of the routing outcome (a human
   needs to see them even on escalation). If routing says "escalate", log the
   event and stop -- do not attempt ERP submission.
3. Before calling run_verifier, you must resolve the real PO match -- never
   invent, guess, or pass po_match as an empty object or None:
   - For an EBS target: call oracle_ebs__match_po with the invoice's
     customer_po_number (and invoice_amount if known), and pass its exact
     result as po_match.
   - For a JDE target: call jde__check_purchase_order with the order number,
     and translate its result into the same po_match shape run_verifier
     expects (matched: false if error_code == "2", true otherwise).
   If the PO lookup itself fails or the PO number is missing, that is a
   po_not_found condition -- pass po_match={"matched": false} rather than
   skipping the lookup.
4. Before ANY create_invoice call (EBS or JDE), you must call run_verifier
   with the current header/lines/po_match (populated per step 3). If the
   verdict is "block", do not submit -- treat it as an exception instead
   (step 5).
5. If ERP submission fails, or the verifier blocks, follow this exact
   sequence -- do not skip steps or improvise a different order. Steps b
   and c (the learned-replay tools) are ALWAYS attempted, for every
   exception, regardless of what step a's bandit recommends -- the bandit
   is a Thompson-sampled *guess* that can land on "escalate" purely by
   chance (fresh arms are close to a coin flip), even when a real,
   previously-confirmed human precedent exists for a different action.
   Gating the replay tools on the bandit's specific sample would mean a
   known precedent silently never gets checked half the time -- always try
   the replay tools first; only fall back to the bandit's recommendation
   once both have genuinely found nothing to replay.
   a. Call choose_bandit_action with the classified exception_type (the
      failed create_invoice call's own response already includes
      exception_type -- use that, don't re-derive it yourself). Keep its
      `action` for later -- it's what you'll pass to escalate_to_human as
      action_recommended if steps b and c both come back empty -- but do
      NOT use it to decide whether to call apply_learned_correction or
      apply_learned_email; always call both regardless.
   b. ALWAYS call apply_learned_correction(src_id, supplier_name,
      exception_type) next, no matter what choose_bandit_action returned.
      It is fully self-contained -- it only replays a fix when a human has
      already resolved this exact (supplier_name, exception_type) once
      before via Edit & Reprocess, checks authorization, applies the fix,
      resubmits, and logs the outcome/bandit reward itself. Do NOT also
      call authorize_autonomous_action or log_outcome yourself for this
      path; apply_learned_correction already did it.
      - If it returns applied=true and succeeded=true: you are done with
        this exception -- move on (there is nothing further to log).
      - If it returns applied=true but succeeded=false: the replayed fix
        was applied but did NOT resolve it (the resubmission itself still
        failed) -- this is a second failure, not a first one. Do not
        retry the same fix again. Go straight to step c, and only
        escalate if that also fails.
      - If it returns applied=false: there is no safe correction to
        replay or it isn't currently authorized. Go straight to step c --
        do not retry it, do not guess a fix yourself.
   c. ALWAYS call apply_learned_email(src_id, supplier_name,
      exception_type) next (whether you arrived here from step b or
      straight from step a), no matter what choose_bandit_action
      returned. It is fully self-contained -- it only sends when a human
      has already resolved this exact (supplier_name, exception_type)
      once before by emailing the supplier via the Manual Review UI, and
      it checks authorization, sends, and logs the outcome/bandit reward
      itself. Do NOT also call authorize_autonomous_action, send_email,
      or log_outcome yourself for this path.
      - If it returns applied=true: you are done with this exception --
        move on.
      - If it returns applied=false: there is no past precedent for
        emailing this supplier about this exception type yet (or for
        auto-fixing it, from step b), or neither is currently authorized.
        Go to step d.
   d. Neither learned-replay tool found (or was authorized to act on) a
      precedent for this (supplier_name, exception_type) pair -- this is
      genuinely the first time (or governance isn't cleared yet), so it's
      a human's turn. If choose_bandit_action's action was "auto_approve"
      (voucher_hold's only non-escalate action -- there's no learned-email
      or learned-fix concept for it): call authorize_autonomous_action
      yourself first.
      - If allowed=true: call jde__approve_voucher, then log_outcome with
        decided_by="policy", then log_event reflecting its real result
        ("Successful" if approved, "Failed" otherwise).
      - If allowed=false: call escalate_to_human(src_id, supplier_name,
        exception_type, action_recommended="auto_approve",
        reason=authorize_autonomous_action's own `reason`, hold=true) and
        stop.
      Otherwise (any other exception type, or auto_approve wasn't
      authorized): call escalate_to_human(src_id, supplier_name,
      exception_type, action_recommended=choose_bandit_action's action
      from step a, reason=apply_learned_email's own `reason` from step c)
      and stop. A human will act on this from the Manual Review queue --
      and whatever they do there (Edit & Reprocess, or Send email now)
      becomes the precedent steps b/c find and replay automatically next
      time this exact supplier hits this exact exception type. Never call
      log_outcome and log_event separately for an escalation -- always use
      escalate_to_human so both are guaranteed to happen together.
6. log_event's `status` MUST be exactly "Successful", "Failed", or
   "OnHold" -- never a free-text description of what happened (the tool
   itself rejects anything else). Put the human-readable explanation in
   `description`. Every dashboard, count, and queue in this system matches
   on these exact three strings; anything else makes your own work
   invisible to the humans who need to review it.
7. Never fabricate field values. If required data is missing, escalate
   (per step 5d) rather than guessing.

Work step by step, calling one tool at a time, and narrate your reasoning
briefly before each call.
"""


def _openai_tool_schemas(neutral_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap the registry's neutral {name, description, input_schema} tool
    shape into OpenAI's {"type": "function", "function": {...}} calling
    convention.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema["description"],
                "parameters": schema["input_schema"],
            },
        }
        for schema in neutral_schemas
    ]


def _merge_tool_schemas(registry: MCPToolRegistry) -> list[dict[str, Any]]:
    return _openai_tool_schemas(registry.tool_schemas() + NATIVE_TOOL_SCHEMAS)


async def _dispatch_tool(registry: MCPToolRegistry, name: str, arguments: dict[str, Any]) -> Any:
    if name in NATIVE_TOOL_HANDLERS:
        return NATIVE_TOOL_HANDLERS[name](**arguments)
    return await registry.call(name, arguments)


def _run_outcome(src_id: str, any_tool_error: bool) -> tuple[bool, str | None]:
    """Whether this run should be flagged as an error for the dashboard/trace
    (AgentLog.is_error), plus the document's actual terminal status.

    A run finishing its turn loop cleanly (no raised tool exception) says
    nothing about whether the *document* actually got resolved -- the
    document's own status in log_table (Successful/Failed/OnHold) is the
    real outcome. Without this check, `is_error` was always False for
    `run_end` regardless of what happened during the run (e.g. an EBS
    create_invoice failure), which is why "Recent Agent Activity" could show
    a failed run as if it succeeded.
    """
    final_log = legacy_repo.get_latest_log(src_id)
    final_status = final_log["status"] if final_log else None
    run_failed = any_tool_error or final_status != "Successful"
    return run_failed, final_status


async def process_document(src_id: str, max_turns: int = 20) -> dict[str, Any]:
    settings = get_settings()
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    run_id = str(uuid.uuid4())

    print(f"[agent] src_id={src_id}: starting run (model={settings.openai_model}, max_turns={max_turns})")
    log_step(src_id, run_id, turn=0, step_type="run_start", message=f"model={settings.openai_model}, max_turns={max_turns}")

    async with MCPToolRegistry() as registry:
        tools = _merge_tool_schemas(registry)
        print(f"[agent] src_id={src_id}: tool registry ready ({len(tools)} tools)")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Process src_id={src_id} through to a terminal state."},
        ]
        transcript: list[dict[str, Any]] = []
        any_tool_error = False

        for turn in range(1, max_turns + 1):
            print(f"[agent] src_id={src_id}: turn {turn}/{max_turns} -- requesting next action")
            response = await client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=2000,
                tools=tools,
                messages=messages,
            )
            choice = response.choices[0]
            message = choice.message
            tool_calls = message.tool_calls or []

            print(
                f"[agent] src_id={src_id}: turn {turn} response -- finish_reason={choice.finish_reason} "
                f"text={(message.content or '').strip()!r} "
                f"tool_calls={[tc.function.name for tc in tool_calls]}"
            )
            if (message.content or "").strip():
                log_step(src_id, run_id, turn=turn, step_type="text", message=message.content.strip())

            assistant_message: dict[str, Any] = {"role": "assistant", "content": message.content}
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_message)

            turn_record: dict[str, Any] = {
                "finish_reason": choice.finish_reason,
                "text": message.content or "",
                "tool_calls": [
                    {"name": tc.function.name, "input": json.loads(tc.function.arguments)}
                    for tc in tool_calls
                ],
                "tool_results": [],
            }
            transcript.append(turn_record)

            if choice.finish_reason != "tool_calls":
                print(f"[agent] src_id={src_id}: completed after {turn} turn(s) -- finish_reason={choice.finish_reason}")
                run_failed, final_status = _run_outcome(src_id, any_tool_error)
                log_step(
                    src_id, run_id, turn=turn, step_type="run_end", is_error=run_failed,
                    message=f"completed ({choice.finish_reason}) -- document status: {final_status or 'none logged'}",
                )
                return {"src_id": src_id, "status": "completed", "transcript": transcript}

            for tc in tool_calls:
                arguments = json.loads(tc.function.arguments)
                print(f"[agent] src_id={src_id}: turn {turn} -> calling {tc.function.name}({arguments})")
                try:
                    result = await _dispatch_tool(registry, tc.function.name, arguments)
                    content = json.dumps(result, default=str)
                    print(f"[agent] src_id={src_id}: turn {turn} <- {tc.function.name} OK -- {content}")
                    turn_record["tool_results"].append({"name": tc.function.name, "ok": True, "output": result})
                    log_step(
                        src_id, run_id, turn=turn, step_type="tool_call",
                        tool_name=tc.function.name, tool_input=arguments, tool_output=result, is_error=False,
                    )
                except Exception as exc:  # noqa: BLE001 -- surfaced to the model, not swallowed silently
                    content = f"ERROR: {exc}"
                    print(f"[agent] src_id={src_id}: turn {turn} <- {tc.function.name} ERROR -- {exc}")
                    turn_record["tool_results"].append({"name": tc.function.name, "ok": False, "error": str(exc)})
                    any_tool_error = True
                    log_step(
                        src_id, run_id, turn=turn, step_type="tool_call",
                        tool_name=tc.function.name, tool_input=arguments, is_error=True, message=str(exc),
                    )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

        print(f"[agent] src_id={src_id}: stopped -- max_turns_exceeded ({max_turns})")
        _, final_status = _run_outcome(src_id, any_tool_error)
        log_step(
            src_id, run_id, turn=max_turns, step_type="run_end", is_error=True,
            message=f"max_turns_exceeded -- document status: {final_status or 'none logged'}",
        )
        return {"src_id": src_id, "status": "max_turns_exceeded", "transcript": transcript}

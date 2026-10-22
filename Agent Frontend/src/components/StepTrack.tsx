import type { WorkflowStep } from "../api/types";

const PIPELINE_STAGES = [
  { agentId: "email-intake-agent", label: "Intake" },
  { agentId: "validator-agent", label: "Validate" },
  { agentId: "extraction-agent", label: "Extract" },
  { agentId: "erp-push-agent", label: "Push to ERP" },
  // Only present on runs where the ERP push failed with an "item not
  // found" rejection and the supervisor's bounded self-correction loop ran
  // (see client/orchestrator/self_correction.py) -- most runs won't have
  // it, and most runs that DO have it never reach exception-handler below,
  // since a successful self-correction resolves the run right here.
  { agentId: "self-correction", label: "Self-Correction" },
  // Only present on runs where the ERP push failed and Phase 2's
  // learned-replay-then-escalate sequence ran (see
  // client/orchestrator/exception_handling.py) -- most runs won't have it.
  { agentId: "exception-handler", label: "Exception Handling" },
];

const CONDITIONAL_STAGES = new Set(["self-correction", "exception-handler"]);

const STATUS_ICON: Record<string, string> = { completed: "✓", running: "●", warning: "⚠", failed: "✗", pending: "○" };

type VisualStatus = "completed" | "running" | "warning" | "failed" | "pending";

/** A2A-level "completed" only means the agent's call itself didn't error --
 * several agents (most notably erp-push-agent, which never raises for a
 * normal ERP rejection) report a genuine business failure INSIDE a
 * completed task's data instead. That distinction matters server-side
 * (client/orchestrator/orchestrator.py's exception-handling routing keys
 * off it), so it isn't something to change there -- but showing a plain
 * green tick for "PO Number not found!" is misleading here. Recognizes the
 * couple of known "completed but actually didn't succeed" data shapes and
 * downgrades those to a warning chip instead. */
export function hasBusinessFailure(data: unknown): boolean {
  if (!data || typeof data !== "object") return false;
  const record = data as Record<string, unknown>;
  if (typeof record.status === "string" && !["success", "s", "on hold", "onhold", "on_hold"].includes(record.status.toLowerCase())) {
    return true;
  }
  if (record.is_valid === false) return true;
  return false;
}

function normalizeStatus(status: string | undefined, data?: unknown): VisualStatus {
  if (status === "completed") return hasBusinessFailure(data) ? "warning" : "completed";
  if (status === "running" || status === "selected") return "running";
  if (status === "failed") return "failed";
  return "pending";
}

function StepChip({ label, status, data }: { label: string; status: string | undefined; data?: unknown }) {
  const cls = normalizeStatus(status, data);
  return (
    <span className={`step-chip ${cls}`}>
      <span className="icon">{STATUS_ICON[cls]}</span>
      {label}
    </span>
  );
}

export function PipelineTrack({ steps }: { steps: WorkflowStep[] }) {
  const byAgent = Object.fromEntries(steps.map((s) => [s.agentId, s]));
  // The exception-handler stage only shows up on runs where it actually ran
  // (an ERP-push failure) -- unlike the other 4 fixed stages, it should not
  // render as a "pending" chip on every normal, successful run.
  const stages = PIPELINE_STAGES.filter((stage) => !CONDITIONAL_STAGES.has(stage.agentId) || byAgent[stage.agentId]);
  return (
    <div className="step-track">
      {stages.map((stage, i) => (
        <span key={stage.agentId}>
          <StepChip label={stage.label} status={byAgent[stage.agentId]?.status} data={byAgent[stage.agentId]?.data} />
          {i < stages.length - 1 && <span className="step-arrow">&rarr;</span>}
        </span>
      ))}
    </div>
  );
}

export function ChatTrack({ steps, agentNames }: { steps: WorkflowStep[]; agentNames: Record<string, string> }) {
  if (!steps.length) return <span className="muted">No agent calls.</span>;
  return (
    <div className="step-track">
      {steps.map((s, i) => (
        <span key={`${s.agentId}-${i}`}>
          <StepChip label={agentNames[s.agentId] || s.agentId} status={s.status} data={s.data} />
          {i < steps.length - 1 && <span className="step-arrow">&rarr;</span>}
        </span>
      ))}
    </div>
  );
}

import { useState } from "react";
import type { ReactNode } from "react";
import type { WorkflowRecord } from "../api/types";
import { hasBusinessFailure } from "./StepTrack";

function fmtJson(value: unknown): string {
  if (value === undefined || value === null) return "—";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function RunCard({
  run,
  agentNames,
  track,
}: {
  run: WorkflowRecord;
  agentNames: Record<string, string>;
  track: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const title = run.title || run.userText || run.workflowId;
  const started = new Date(run.startedAt).toLocaleTimeString();

  return (
    <div className="run-card">
      <div className="run-card-top">
        <div>
          <div className="run-title">{title}</div>
          <div className="run-meta">
            {run.workflowId} &middot; started {started}
            {run.sessionId && (
              <>
                {" "}
                &middot; session <code>{run.sessionId}</code>
              </>
            )}
          </div>
        </div>
        <span className={`run-status ${run.status}`}>{run.status}</span>
      </div>
      <div>{track}</div>
      <button className="run-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide details" : "Show details"}
      </button>
      {open && (
        <div className="run-details open">
          {run.finalResponse?.summary && <p className="muted">{run.finalResponse.summary}</p>}
          <table>
            <tbody>
              {run.steps.map((s, i) => (
                <tr key={i}>
                  <th>{agentNames[s.agentId] || s.agentId}</th>
                  <td>
                    status:{" "}
                    <strong className={s.status === "completed" && hasBusinessFailure(s.data) ? "text-warning" : undefined}>
                      {s.status === "completed" && hasBusinessFailure(s.data) ? "completed (business failure)" : s.status}
                    </strong>
                    {s.skillUsed && (
                      <>
                        {" "}
                        &middot; skill: <code>{s.skillUsed}</code>
                      </>
                    )}
                    {s.durationMs !== undefined && <> &middot; {s.durationMs} ms</>}
                    <pre>{s.data !== undefined ? fmtJson(s.data) : s.error ? s.error : "—"}</pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

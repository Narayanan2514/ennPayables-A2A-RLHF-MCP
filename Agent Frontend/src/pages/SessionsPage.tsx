import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pipelineApi } from "../api/pipelineClient";
import type { SessionStatus, WorkflowSession } from "../api/types";

const STATUS_ORDER: SessionStatus[] = ["CREATED", "RUNNING", "RETRY", "SUCCESS", "FAILED"];

const STATUS_LABELS: Record<string, string> = {
  CREATED: "Created",
  RUNNING: "Running",
  RETRY: "Retry pending",
  SUCCESS: "Success",
  FAILED: "Failed",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function ClaimControl({ session, onClaimed }: { session: WorkflowSession; onClaimed: () => void }) {
  const [workerId, setWorkerId] = useState("");
  const claim = useMutation({
    mutationFn: () => pipelineApi.claimSession(session.sessionId, workerId.trim() || undefined),
    onSuccess: onClaimed,
  });

  const claimable = session.status === "CREATED" || session.status === "RETRY";
  if (!claimable) return <span className="muted">—</span>;

  return (
    <div className="session-claim">
      <input
        className="cell-input"
        placeholder="worker id (optional)"
        value={workerId}
        onChange={(e) => setWorkerId(e.target.value)}
      />
      <button className="btn btn-sm btn-ghost" disabled={claim.isPending} onClick={() => claim.mutate()}>
        {claim.isPending ? "Claiming…" : "Claim"}
      </button>
      {claim.data && (
        <span className={`muted session-claim-result ${claim.data.claimed ? "ok" : "conflict"}`}>
          {claim.data.claimed ? `claimed by ${claim.data.workerId}` : "already claimed (lost the race)"}
        </span>
      )}
    </div>
  );
}

export function SessionsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("");

  const sessions = useQuery({
    queryKey: ["sessions", statusFilter],
    queryFn: () => pipelineApi.sessions(statusFilter || undefined, 200),
    refetchInterval: 3000,
  });

  const rows = sessions.data?.sessions ?? [];
  const counts = STATUS_ORDER.reduce<Record<string, number>>((acc, s) => {
    acc[s] = rows.filter((r) => r.status === s).length;
    return acc;
  }, {});

  return (
    <section>
      <div className="panel-header">
        <h2>Workflow Sessions</h2>
        <span className="muted">
          Durable DB session state (workflow_session) &middot; this process is{" "}
          <code>{sessions.data?.workerId ?? "…"}</code>
        </span>
      </div>

      <div className="tile-row">
        {STATUS_ORDER.map((s) => (
          <button
            key={s}
            className="tile tile-clickable"
            onClick={() => setStatusFilter((cur) => (cur === s ? "" : s))}
            style={{ outline: statusFilter === s ? "2px solid var(--accent)" : "none", cursor: "pointer", textAlign: "left" }}
          >
            <div className="tile-value">{counts[s] ?? 0}</div>
            <div className="tile-label">{STATUS_LABELS[s]}</div>
          </button>
        ))}
      </div>

      {statusFilter && (
        <p className="muted" style={{ marginTop: -8, marginBottom: 12 }}>
          Filtering to <strong>{STATUS_LABELS[statusFilter] ?? statusFilter}</strong> &middot;{" "}
          <button className="run-toggle" onClick={() => setStatusFilter("")}>
            clear filter
          </button>
        </p>
      )}

      {sessions.isLoading && <p className="muted">Loading sessions…</p>}
      {!sessions.isLoading && !rows.length && (
        <p className="muted">
          No workflow sessions yet. A session is created the moment an in-scope email is found by the poller &mdash;
          before Agent 1 even runs &mdash; so it will show up here as soon as one is processed.
        </p>
      )}

      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Src ID</th>
                <th>Status</th>
                <th>Current step</th>
                <th>Retries</th>
                <th>Worker</th>
                <th>Created</th>
                <th>Last update</th>
                <th>Finished</th>
                <th>Claim</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.sessionId}>
                  <td>
                    <code>{s.sessionId}</code>
                  </td>
                  <td>{s.srcId?.startsWith("pnd_") ? <span className="muted">pending&hellip;</span> : s.srcId}</td>
                  <td>
                    <span className={`run-status session-status-${s.status.toLowerCase()}`}>{s.status}</span>
                  </td>
                  <td>
                    <code>{s.currentStep}</code>
                  </td>
                  <td>{s.retryCount}</td>
                  <td>{s.workerId ?? <span className="muted">unclaimed</span>}</td>
                  <td className="muted">{fmtTime(s.createdAt)}</td>
                  <td className="muted">{fmtTime(s.statusAt)}</td>
                  <td className="muted">{fmtTime(s.finishedAt)}</td>
                  <td>
                    <ClaimControl session={s} onClaimed={() => queryClient.invalidateQueries({ queryKey: ["sessions"] })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

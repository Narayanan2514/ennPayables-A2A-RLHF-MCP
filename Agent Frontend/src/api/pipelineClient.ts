import type {
  AgentsResponse,
  ClaimSessionResponse,
  PipelineConfig,
  SessionsResponse,
  WorkflowMode,
  WorkflowRecord,
  WorkflowSession,
} from "./types";

const API = import.meta.env.VITE_PIPELINE_API_BASE || "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}`);
  return res.json();
}

export const pipelineApi = {
  health: () => get<{ status: string; service: string }>("/health"),
  config: () => get<PipelineConfig>("/api/config"),
  agents: () => get<AgentsResponse>("/api/agents"),
  agentCard: (agentId: string) => get<Record<string, unknown>>(`/api/agents/${encodeURIComponent(agentId)}/card`),
  history: (kind: "chat" | "email_pipeline", limit = 50) =>
    get<{ workflows: WorkflowRecord[] }>(`/api/history?kind=${kind}&limit=${limit}`),
  chat: (text: string, mode: WorkflowMode) => post<WorkflowRecord>("/api/chat", { text, mode }),
  pollNow: () => post<{ workflows: WorkflowRecord[] }>("/api/pipeline/poll-now"),
  refreshDiscovery: () => post<{ agents: string[]; errors: Record<string, string> }>("/api/discovery/refresh"),
  sessions: (status?: string, limit = 100) =>
    get<SessionsResponse>(`/api/sessions?limit=${limit}${status ? `&status=${status}` : ""}`),
  session: (sessionId: string) => get<WorkflowSession>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  claimSession: (sessionId: string, workerId?: string) =>
    post<ClaimSessionResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/claim`, workerId ? { workerId } : {}),
};

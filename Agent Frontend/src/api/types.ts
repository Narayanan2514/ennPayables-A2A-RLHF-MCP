// ---- A2A client/orchestrator (port 8000) -----------------------------------

export type WorkflowMode = "auto" | "sequential" | "parallel";
export type WorkflowKind = "chat" | "email_pipeline";

export interface WorkflowStep {
  agentId: string;
  taskText: string;
  status: "selected" | "running" | "completed" | "failed" | string;
  reason?: string;
  durationMs?: number;
  skillUsed?: string;
  data?: unknown;
  error?: string;
}

export interface WorkflowRecord {
  workflowId: string;
  kind: WorkflowKind;
  title: string | null;
  userText: string;
  mode: WorkflowMode;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  steps: WorkflowStep[];
  finalResponse: { summary?: string; overallStatus?: string; [key: string]: unknown } | null;
  sessionId: string | null;
}

// ---- Durable workflow_session (DB-backed control state) -------------------

export type SessionStatus = "CREATED" | "RUNNING" | "RETRY" | "SUCCESS" | "FAILED";

export interface WorkflowSession {
  sessionId: string;
  workerId: string | null;
  srcId: string;
  status: SessionStatus | string;
  currentStep: string;
  retryCount: number;
  createdAt: string;
  statusAt: string;
  finishedAt: string | null;
}

export interface SessionsResponse {
  sessions: WorkflowSession[];
  workerId: string;
}

export interface ClaimSessionResponse {
  claimed: boolean;
  workerId: string;
  session: WorkflowSession;
}

export interface AgentSummary {
  agentId: string;
  name: string;
  baseUrl: string;
  status: "available" | "unavailable" | string;
  skillCount: number;
}

export interface AgentsResponse {
  agents: AgentSummary[];
  errors: Record<string, string>;
}

export interface PipelineConfig {
  // Single interval now -- the supervisor's poll/classify/dispatch loop
  // replaced the old separate Agent-1-poller + watcher-drain setup.
  pipelineWatchIntervalSeconds: number;
}

// ---- RLHF agentic API (port 8010) ------------------------------------------

export type ExceptionType =
  | "invalid_item"
  | "invalid_po"
  | "duplicate_invoice"
  | "amount_overapply"
  | "voucher_hold"
  | "unmatched_remittance"
  | "unknown";

export interface ArmState {
  alpha: number;
  beta: number;
  trials: number;
  successes: number;
}

export interface Recommendation {
  exception_type: ExceptionType;
  action_space: string[];
  suggested_action: string;
  arm_states: Record<string, ArmState>;
  autonomy_check: { allowed: boolean; stage_used: string; reason: string };
}

export interface LatestStatus {
  status: string;
  stage: string;
  description: string | null;
  is_reviewed: string;
  action_taken: string;
  log_time: string | null;
}

export interface DocumentSummary {
  src_id: string;
  doc_type: string;
  target: string;
  channel: string;
  timestamp: string | null;
  status: string | null;
  stage: string | null;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_amount: number | null;
}

export interface ExceptionRow extends DocumentSummary {
  recommendation: Recommendation | null;
  latest_status: LatestStatus | null;
}

export interface InvoiceHeader {
  id: number;
  src_id: string;
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  invoice_duedate: string | null;
  customer_po_number: string | null;
  currency_code: string | null;
  invoice_amount: number | null;
  payment_terms: string | null;
  supplier_site: string | null;
  bill_to: string | null;
  ship_to: string | null;
}

export interface InvoiceLine {
  id: number;
  line_number: string | null;
  item_name: string | null;
  item_desc: string | null;
  ordered_quantity: string | null;
  unit_of_measure: string | null;
  total: string | number | null;
}

export interface DocumentDetail {
  source: { src_id: string; target: string; doc_type: string; channel: string; timestamp: string | null };
  header: InvoiceHeader | null;
  lines: InvoiceLine[];
  history: LatestStatus[];
  latest_status: LatestStatus | null;
  verifier_finding: unknown;
  is_open_exception: boolean;
  recommendation: Recommendation | null;
  supplier_email: { src_id: string; from_email: string; subject: string; conversation_id: string | null } | null;
}

export interface DashboardSummary {
  total_received: number;
  runs_completed: number;
  processed_successfully: number;
  exceptions_human_review: number;
  exceptions_agent_handled: number;
  recent_transactions: Array<{
    run_id: string;
    src_id: string;
    supplier_name: string | null;
    doc_type: string | null;
    run_outcome: string | null;
    is_error: boolean;
    status: string | null;
    completed_at: string | null;
  }>;
}

export interface LineEdit {
  line_id: number;
  field: string;
  value: string | number;
}

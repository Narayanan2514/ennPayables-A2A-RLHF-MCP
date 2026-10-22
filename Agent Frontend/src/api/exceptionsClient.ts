import type { DashboardSummary, DocumentDetail, ExceptionRow, LineEdit } from "./types";

const API = import.meta.env.VITE_EXCEPTIONS_API_BASE || "http://localhost:8010";

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
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `POST ${path} -> ${res.status}`);
  }
  return res.json();
}

export const exceptionsApi = {
  health: () => get<{ status: string; autonomy_stage: string; openai_configured: boolean; ebs_configured: boolean; jde_configured: boolean }>(
    "/api/health"
  ),
  listExceptions: (limit = 100) => get<ExceptionRow[]>(`/api/exceptions?limit=${limit}`),
  dashboardSummary: () => get<DashboardSummary>("/api/dashboard/summary"),
  documentDetail: (srcId: string) => get<DocumentDetail>(`/api/documents/${encodeURIComponent(srcId)}`),

  sendSupplierEmail: (srcId: string, subject: string, bodyHtml: string) =>
    post<{ sent: boolean; to?: string; subject?: string; reason?: string; correction_id?: number }>(
      `/api/documents/${encodeURIComponent(srcId)}/send-supplier-email`,
      { subject, body_html: bodyHtml }
    ),

  editAndReprocess: (srcId: string, headerFields: Record<string, unknown>, lineEdits: LineEdit[]) =>
    post<{ success: boolean; erp_result: { status: string; message: string }; correction_id: number }>(
      `/api/documents/${encodeURIComponent(srcId)}/edit-and-reprocess`,
      { header_fields: headerFields, line_edits: lineEdits }
    ),

  escalate: (srcId: string, exceptionType: string, supplierName: string | null) =>
    post<{ correction_id: number; recorded: boolean }>(`/api/documents/${encodeURIComponent(srcId)}/feedback`, {
      human_action: "escalate",
      correct: false,
      exception_type: exceptionType,
      supplier_name: supplierName,
    }),
};

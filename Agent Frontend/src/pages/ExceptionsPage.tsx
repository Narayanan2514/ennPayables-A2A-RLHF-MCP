import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { exceptionsApi } from "../api/exceptionsClient";

const EXCEPTION_LABELS: Record<string, string> = {
  invalid_item: "Item not found",
  invalid_po: "PO not found",
  duplicate_invoice: "Duplicate invoice",
  amount_overapply: "Amount overapply",
  voucher_hold: "Voucher hold",
  unmatched_remittance: "Unmatched remittance",
  unknown: "Unclassified",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function ExceptionsPage() {
  const summary = useQuery({ queryKey: ["dashboard-summary"], queryFn: exceptionsApi.dashboardSummary, refetchInterval: 15000 });
  const exceptions = useQuery({ queryKey: ["exceptions"], queryFn: () => exceptionsApi.listExceptions(200), refetchInterval: 8000 });

  const rows = exceptions.data ?? [];

  return (
    <section>
      <div className="panel-header">
        <h2>Exceptions</h2>
        <span className="muted">ERP-push failures, classified and ready for review</span>
      </div>

      {summary.data && (
        <div className="tile-row">
          <div className="tile">
            <div className="tile-value">{summary.data.total_received}</div>
            <div className="tile-label">Total received</div>
          </div>
          <div className="tile">
            <div className="tile-value">{summary.data.processed_successfully}</div>
            <div className="tile-label">Processed successfully</div>
          </div>
          <div className="tile">
            <div className="tile-value">{summary.data.exceptions_human_review}</div>
            <div className="tile-label">Needs human review</div>
          </div>
          <div className="tile">
            <div className="tile-value">{summary.data.exceptions_agent_handled}</div>
            <div className="tile-label">Agent-handled</div>
          </div>
        </div>
      )}

      {exceptions.isLoading && <p className="muted">Loading exceptions…</p>}
      {!exceptions.isLoading && !rows.length && <p className="muted">No open exceptions. Nice.</p>}

      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Src ID</th>
                <th>Supplier</th>
                <th>Exception</th>
                <th>Invoice #</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Age</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const excType = row.recommendation?.exception_type ?? "unknown";
                return (
                  <tr key={row.src_id}>
                    <td>
                      <Link className="row-link" to={`/exceptions/${row.src_id}`}>
                        {row.src_id}
                      </Link>
                    </td>
                    <td>{row.supplier_name ?? "—"}</td>
                    <td>
                      <span className={`badge badge-${excType}`}>{EXCEPTION_LABELS[excType] ?? excType}</span>
                    </td>
                    <td>{row.invoice_number ?? "—"}</td>
                    <td>{row.invoice_amount ?? "—"}</td>
                    <td>
                      <span className={`run-status ${row.status === "Failed" ? "failed" : "blocked"}`}>{row.status}</span>
                    </td>
                    <td className="muted">{timeAgo(row.latest_status?.log_time ?? row.timestamp)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

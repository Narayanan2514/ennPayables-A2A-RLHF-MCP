import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { exceptionsApi } from "../api/exceptionsClient";
import type { ExceptionType, InvoiceHeader, InvoiceLine, LineEdit } from "../api/types";

// Which exception types get a "Send Supplier Email" option. Item-not-found
// gets both this AND the inline edit-and-reprocess flow below, since a bad
// item can be either fixed locally or need the supplier to confirm it.
const EMAIL_ACTION_TYPES: ExceptionType[] = ["duplicate_invoice", "invalid_po", "invalid_item"];
// Which exception types get the inline "Edit" button on the Invoice card.
const EDIT_ACTION_TYPES: ExceptionType[] = ["invalid_item"];

const HEADER_ALLOWED_FIELDS: Array<{ key: keyof InvoiceHeader; label: string }> = [
  { key: "supplier_name", label: "Supplier name" },
  { key: "invoice_number", label: "Invoice number" },
  { key: "customer_po_number", label: "PO number" },
  { key: "currency_code", label: "Currency" },
  { key: "invoice_amount", label: "Invoice amount" },
  { key: "payment_terms", label: "Payment terms" },
];

const LINE_ALLOWED_FIELDS: Array<{ key: keyof InvoiceLine; label: string }> = [
  { key: "item_name", label: "Item name" },
  { key: "item_desc", label: "Item description" },
  { key: "ordered_quantity", label: "Ordered qty" },
  { key: "unit_of_measure", label: "UOM" },
  { key: "total", label: "Total" },
];

function asStr(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function buildEmailTemplate(invoiceNumber: string | null, poNumber: string | null, amount: number | null, exceptionType: string) {
  const subject = `Correction needed: invoice ${invoiceNumber ?? ""}`;
  const body =
    `Hello,\n\nOur system flagged invoice ${invoiceNumber ?? ""} ` +
    `(PO ${poNumber || "n/a"}, amount ${amount ?? ""}) ` +
    `for a ${exceptionType.replace(/_/g, " ")} exception during processing.\n\n` +
    `Could you please confirm the correct details, or issue a corrected invoice/PO, at your earliest convenience?\n\nThanks.`;
  return { subject, body };
}

export function ExceptionDetailPage() {
  const { srcId } = useParams<{ srcId: string }>();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["document-detail", srcId],
    queryFn: () => exceptionsApi.documentDetail(srcId as string),
    enabled: !!srcId,
  });

  const [emailSubject, setEmailSubject] = useState<string | null>(null);
  const [emailBody, setEmailBody] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const [editMode, setEditMode] = useState(false);
  const [editedHeader, setEditedHeader] = useState<Record<string, string>>({});
  const [editedLines, setEditedLines] = useState<Record<number, Record<string, string>>>({});

  const header = detail.data?.header;
  const lines = useMemo(() => detail.data?.lines ?? [], [detail.data]);
  const excType = detail.data?.recommendation?.exception_type;

  // Reset any in-progress edit whenever we land on a different document.
  useEffect(() => {
    setEditMode(false);
    setEditedHeader({});
    setEditedLines({});
    setActionResult(null);
  }, [srcId]);

  function startEdit() {
    const h: Record<string, string> = {};
    for (const f of HEADER_ALLOWED_FIELDS) h[f.key] = asStr(header?.[f.key]);
    setEditedHeader(h);

    const l: Record<number, Record<string, string>> = {};
    for (const line of lines) {
      const row: Record<string, string> = {};
      for (const f of LINE_ALLOWED_FIELDS) row[f.key] = asStr(line[f.key]);
      l[line.id] = row;
    }
    setEditedLines(l);
    setEditMode(true);
  }

  function cancelEdit() {
    setEditMode(false);
    setEditedHeader({});
    setEditedLines({});
  }

  const isDirty = useMemo(() => {
    if (!header) return false;
    const headerChanged = HEADER_ALLOWED_FIELDS.some((f) => (editedHeader[f.key] ?? "") !== asStr(header[f.key]));
    const lineChanged = lines.some((line) =>
      LINE_ALLOWED_FIELDS.some((f) => (editedLines[line.id]?.[f.key] ?? "") !== asStr(line[f.key]))
    );
    return headerChanged || lineChanged;
  }, [editedHeader, editedLines, header, lines]);

  const sendEmail = useMutation({
    mutationFn: () => {
      const subject = emailSubject ?? defaultEmail.subject;
      const body = emailBody ?? defaultEmail.body;
      return exceptionsApi.sendSupplierEmail(srcId as string, subject, body.replace(/\n/g, "<br/>"));
    },
    onSuccess: (res) => {
      setActionResult(res.sent ? `Email sent to ${res.to}.` : `Not sent: ${res.reason}`);
      queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      queryClient.invalidateQueries({ queryKey: ["document-detail", srcId] });
    },
    onError: (err: Error) => setActionResult(`Error: ${err.message}`),
  });

  const editAndReprocess = useMutation({
    mutationFn: () => {
      if (!header) throw new Error("No header loaded");
      const headerFields: Record<string, string> = {};
      for (const f of HEADER_ALLOWED_FIELDS) {
        const value = editedHeader[f.key] ?? "";
        if (value !== asStr(header[f.key])) headerFields[f.key] = value;
      }
      const lineEdits: LineEdit[] = [];
      for (const line of lines) {
        for (const f of LINE_ALLOWED_FIELDS) {
          const value = editedLines[line.id]?.[f.key] ?? "";
          if (value !== asStr(line[f.key])) lineEdits.push({ line_id: line.id, field: f.key, value });
        }
      }
      return exceptionsApi.editAndReprocess(srcId as string, headerFields, lineEdits);
    },
    onSuccess: (res) => {
      setActionResult(res.success ? `Reprocessed successfully: ${res.erp_result?.message ?? ""}` : `Reprocess failed: ${res.erp_result?.message ?? ""}`);
      cancelEdit();
      queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      queryClient.invalidateQueries({ queryKey: ["document-detail", srcId] });
    },
    onError: (err: Error) => setActionResult(`Error: ${err.message}`),
  });

  const escalate = useMutation({
    mutationFn: () => exceptionsApi.escalate(srcId as string, excType ?? "unknown", header?.supplier_name ?? null),
    onSuccess: () => {
      setActionResult("Escalated for manual review.");
      queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      queryClient.invalidateQueries({ queryKey: ["document-detail", srcId] });
    },
    onError: (err: Error) => setActionResult(`Error: ${err.message}`),
  });

  const defaultEmail = useMemo(() => {
    if (!header) return { subject: "", body: "" };
    return buildEmailTemplate(header.invoice_number, header.customer_po_number, header.invoice_amount, excType ?? "unknown");
  }, [header, excType]);

  if (!srcId) return null;
  if (detail.isLoading) return <p className="muted">Loading…</p>;
  if (detail.isError || !detail.data) return <p className="muted" style={{ color: "var(--accent-red)" }}>Could not load {srcId}.</p>;

  const d = detail.data;
  const canEdit = !!excType && EDIT_ACTION_TYPES.includes(excType);
  const canEmail = !!excType && EMAIL_ACTION_TYPES.includes(excType);

  return (
    <section>
      <div className="panel-header">
        <h2>
          <Link to="/exceptions" className="row-link">
            Exceptions
          </Link>{" "}
          / {srcId}
        </h2>
        {d.recommendation && (
          <span className={`badge badge-${d.recommendation.exception_type}`}>{d.recommendation.exception_type}</span>
        )}
      </div>

      <div className="detail-grid">
        <div className="detail-card">
          <div className="card-title-row">
            <h3 className="card-title">Invoice</h3>
            {canEdit && !editMode && (
              <button className="btn btn-sm" onClick={startEdit}>
                Edit
              </button>
            )}
            {canEdit && editMode && (
              <div className="card-title-actions">
                <button className="btn btn-sm" onClick={cancelEdit} disabled={editAndReprocess.isPending}>
                  Cancel
                </button>
                <button
                  className="btn btn-sm btn-primary"
                  disabled={!isDirty || editAndReprocess.isPending}
                  onClick={() => editAndReprocess.mutate()}
                >
                  {editAndReprocess.isPending ? "Reprocessing…" : "Save & Reprocess"}
                </button>
              </div>
            )}
          </div>

          {editMode ? (
            <div className="kv-edit">
              {HEADER_ALLOWED_FIELDS.map((f) => (
                <div key={f.key} className="kv-edit-row">
                  <label>{f.label}</label>
                  <input
                    type="text"
                    value={editedHeader[f.key] ?? ""}
                    onChange={(e) => setEditedHeader((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  />
                </div>
              ))}
            </div>
          ) : (
            <dl className="kv">
              <dt>Supplier</dt>
              <dd>{header?.supplier_name ?? "—"}</dd>
              <dt>Invoice #</dt>
              <dd>{header?.invoice_number ?? "—"}</dd>
              <dt>PO #</dt>
              <dd>{header?.customer_po_number ?? "—"}</dd>
              <dt>Amount</dt>
              <dd>
                {header?.invoice_amount ?? "—"} {header?.currency_code ?? ""}
              </dd>
              <dt>Payment terms</dt>
              <dd>{header?.payment_terms ?? "—"}</dd>
            </dl>
          )}

          <h3>Lines</h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Item</th>
                  <th>Description</th>
                  <th>Qty</th>
                  <th>UOM</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {d.lines.map((l) =>
                  editMode ? (
                    <tr key={l.id}>
                      <td>{l.line_number}</td>
                      {LINE_ALLOWED_FIELDS.map((f) => (
                        <td key={f.key}>
                          <input
                            type="text"
                            className="cell-input"
                            value={editedLines[l.id]?.[f.key] ?? ""}
                            onChange={(e) =>
                              setEditedLines((prev) => ({
                                ...prev,
                                [l.id]: { ...prev[l.id], [f.key]: e.target.value },
                              }))
                            }
                          />
                        </td>
                      ))}
                    </tr>
                  ) : (
                    <tr key={l.id}>
                      <td>{l.line_number}</td>
                      <td>{l.item_name}</td>
                      <td>{l.item_desc}</td>
                      <td>{l.ordered_quantity}</td>
                      <td>{l.unit_of_measure}</td>
                      <td>{l.total}</td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
          {editMode && (
            <p className="muted" style={{ marginTop: 8 }}>
              {isDirty ? "Unsaved changes — click Save & Reprocess above to apply and resubmit." : "Change a field to enable Save & Reprocess."}
            </p>
          )}

          <h3>History</h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {d.history.map((h, i) => (
                  <tr key={i}>
                    <td className="muted">{h.log_time}</td>
                    <td>{h.stage}</td>
                    <td>{h.status}</td>
                    <td>{h.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="detail-card">
          <h3>Recommendation</h3>
          {d.recommendation ? (
            <>
              <p className="muted">
                Bandit suggests <strong>{d.recommendation.suggested_action}</strong> (informational only — no
                autonomous action is taken in this phase; a human decides).
              </p>
              <p className="muted">
                Autonomy gate: {d.recommendation.autonomy_check.allowed ? "allowed" : "blocked"} (
                {d.recommendation.autonomy_check.reason})
              </p>
            </>
          ) : (
            <p className="muted">This document has no open exception.</p>
          )}

          {canEmail && (
            <div className="action-form">
              <h4>Send Supplier Email</h4>
              <label>Subject</label>
              <input
                type="text"
                value={emailSubject ?? defaultEmail.subject}
                onChange={(e) => setEmailSubject(e.target.value)}
              />
              <label>Body</label>
              <textarea
                rows={6}
                value={emailBody ?? defaultEmail.body}
                onChange={(e) => setEmailBody(e.target.value)}
              />
              <button
                className="btn btn-primary"
                disabled={sendEmail.isPending}
                onClick={() => sendEmail.mutate()}
              >
                {sendEmail.isPending ? "Sending…" : "Send Email"}
              </button>
            </div>
          )}

          {excType && canEdit && (
            <p className="muted" style={{ marginTop: 16 }}>
              Use the <strong>Edit</strong> button on the Invoice card to correct the line item(s) and reprocess.
            </p>
          )}

          {excType && !canEmail && !canEdit && (
            <div className="action-form">
              <h4>No automated action wired up yet for &ldquo;{excType}&rdquo;</h4>
              <p className="muted">Escalate this for manual handling outside the app for now.</p>
              <button className="btn" disabled={escalate.isPending} onClick={() => escalate.mutate()}>
                {escalate.isPending ? "Escalating…" : "Escalate"}
              </button>
            </div>
          )}

          {actionResult && <p className="muted" style={{ marginTop: 12 }}>{actionResult}</p>}
        </div>
      </div>
    </section>
  );
}

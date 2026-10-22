"""Read/write helpers against the ennvault-existing schema (db/legacy_schema.py).

Consolidates what used to be scattered, copy-pasted per-domain `db.py` files in
ennvault-existing (app/api/ennPayables/EBS/db.py, .../JDE/db.py,
entity_extractor/db.py, ERP/db.py -- audit sections 4, 8, 9) into one place
that both the Invoice-DB MCP server and the ERP MCP servers import, so a
schema fact (e.g. how "processed" is defined) is expressed once.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import func, select

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# Same value as ENNVAULT_DATA_ROOT in Agent/.env and Backend/.env --
# source.folder_path (written by agent_3/services/extraction_service.py) is
# stored relative to this root, not as a directly-openable path.
ENNVAULT_DATA_ROOT = os.getenv("ENNVAULT_DATA_ROOT", "")

from db.legacy_schema import (
    EmailRecord,
    InvHeader,
    InvLine,
    JdeInvHeader,
    JdeInvLines,
    LogTable,
    PoHeader,
    PoLine,
    Source,
)
from db.session import session_scope

# log_table.status is a free Text/String column, but every reader in this
# codebase (list_open_exceptions, count_sources_by_status, the dashboard, the
# Manual Review queue, governance metrics) checks for these exact strings.
# insert_log's entity_id/status/stage triple is also the one write path the
# LLM-driven agent calls directly (via invoice_db__log_event, with no schema
# constraint of its own) -- without enforcement here, a free-text status like
# "Escalated for review" or "amount_overapply exception" silently vanishes
# from every one of those queries even though the row exists. "OnHold" and
# "ON_HOLD" both stay valid since existing code already treats them as
# synonyms everywhere else.
VALID_LOG_STATUSES = {"Successful", "Failed", "OnHold", "ON_HOLD"}

# Extracted invoice dates arrive in whatever format the source document
# uses (e.g. "11/8/2025") -- inv_header.invoice_date/invoice_duedate are SQL
# DATE columns, so a non-ISO string passed straight through raises a raw
# pymysql OperationalError (1292) instead of a usable insert. Try the
# formats real invoices show up in.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%B %d, %Y",
    "%b %d, %Y",
)


def _parse_date(value: Any) -> date | None:
    """Best-effort parse of an extracted date field into a `date`. Gives up
    to None (NULL) rather than raising, so one unparseable date doesn't
    block the whole invoice insert.
    """
    if value is None or isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def insert_invoice(src_id: str, header_fields: dict[str, Any], lines: list[dict[str, Any]]) -> int:
    """Persist a freshly-extracted invoice into inv_header/inv_line -- the
    "insert" half of the Invoice-DB server's mandate. Same target tables
    ennvault-existing's entity_extractor/db.py writes to (insert_inv_header /
    insert_inv_line), reimplemented fresh here rather than imported.
    """
    with session_scope() as session:
        header = InvHeader(
            src_id=src_id,
            bill_to=header_fields.get("bill_to"),
            ship_to=header_fields.get("ship_to"),
            supplier_name=header_fields.get("supplier_name"),
            invoice_number=header_fields.get("invoice_number"),
            invoice_date=_parse_date(header_fields.get("invoice_date")),
            payment_terms=header_fields.get("payment_terms"),
            customer_number=header_fields.get("customer_number"),
            invoice_duedate=_parse_date(header_fields.get("invoice_duedate")),
            customer_po_number=header_fields.get("customer_po_number") or header_fields.get("po_number"),
            so_number=header_fields.get("sales_order_number"),
            shipping_point=header_fields.get("shipping_point"),
            currency_code=header_fields.get("currency_code"),
            invoice_amount=header_fields.get("total") or header_fields.get("invoice_amount"),
            supplier_site=header_fields.get("supplier_site_name") or header_fields.get("supplier_site"),
        )
        session.add(header)
        session.flush()
        for line in lines:
            session.add(
                InvLine(
                    header_id=header.id,
                    line_number=line.get("line_number"),
                    item_name=line.get("item_name"),
                    item_desc=line.get("item_description") or line.get("item_desc"),
                    ordered_quantity=line.get("ordered_quantity") or line.get("quantity"),
                    unit_of_measure=line.get("unit_of_measure"),
                    total=line.get("total") or line.get("price"),
                )
            )
        return header.id


def get_source(src_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalar(select(Source).where(Source.src_id == src_id))
        if row is None:
            return None
        return {
            "src_id": row.src_id,
            "target": row.target,
            "doc_type": row.doc_type,
            "atch_nm": row.atch_nm,
            "archive": row.archive,
            "channel": row.channel,
            "folder_path": row.folder_path,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }


def get_source_attachment_paths(src_id: str) -> list[str]:
    """Full filesystem paths to every attachment this document arrived with,
    resolved from `source.folder_path` + `source.atch_nm` -- a
    comma-separated list of the original filenames email_module/service.py's
    download_attachments saved into that same folder on ingestion. Used to
    attach the original invoice PDF when emailing the supplier back about
    it, so the recipient doesn't have to go dig up their own copy.

    Skips any name whose file no longer exists on disk (e.g. archived or
    moved) rather than failing the whole lookup -- an email that arrives
    with one fewer attachment than expected is far better than one that
    silently never gets sent at all.
    """
    source = get_source(src_id)
    if not source or not source.get("folder_path") or not source.get("atch_nm"):
        return []
    folder = (
        os.path.join(ENNVAULT_DATA_ROOT, source["folder_path"])
        if ENNVAULT_DATA_ROOT
        else source["folder_path"]
    )
    names = [name.strip() for name in source["atch_nm"].split(",") if name.strip()]
    paths = [os.path.join(folder, name) for name in names]
    return [path for path in paths if os.path.isfile(path)]


def get_source_email(src_id: str) -> dict[str, Any] | None:
    """The `email` row (from_email, subject, conversation id) captured when
    this document first arrived -- the one and only source of truth for
    "who do we reply to" (email_module/service.py:process_email writes it on
    ingestion). Nothing about this should ever be guessed or improvised by a
    caller: a supplier-facing email always goes to whoever this document
    actually came from.
    """
    with session_scope() as session:
        row = session.scalar(select(EmailRecord).where(EmailRecord.src_id == src_id))
        if row is None:
            return None
        return {
            "src_id": row.src_id,
            "from_email": row.from_email,
            "subject": row.subject,
            "conversation_id": row.coversationId,
        }


def get_invoice_header(src_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalar(select(InvHeader).where(InvHeader.src_id == src_id))
        if row is None:
            return None
        return {
            "id": row.id,
            "src_id": row.src_id,
            "supplier_name": row.supplier_name,
            "invoice_number": row.invoice_number,
            "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
            "invoice_duedate": row.invoice_duedate.isoformat() if row.invoice_duedate else None,
            "customer_po_number": row.customer_po_number,
            "currency_code": row.currency_code,
            "invoice_amount": float(row.invoice_amount) if row.invoice_amount is not None else None,
            "payment_terms": row.payment_terms,
            "supplier_site": row.supplier_site,
            "bill_to": row.bill_to,
            "ship_to": row.ship_to,
        }


def get_invoice_header_by_po_number(po_number: str) -> dict[str, Any] | None:
    """Find the most recently inserted inv_header row referencing this PO
    number. Used by oracle_ebs__match_po as its PO source of truth: po_header
    only fills from a separately-emailed "po" document, which most invoices
    (this pipeline's normal case: an invoice email with no matching PO
    document ever ingested) will never have. inv_header, by contrast, is
    always populated -- insert_invoice runs before match_po in every
    orchestrator turn -- so a PO number the current invoice itself extracted
    is treated as sufficient evidence the PO exists.
    """
    with session_scope() as session:
        row = session.scalar(
            select(InvHeader)
            .where(InvHeader.customer_po_number == po_number)
            .order_by(InvHeader.id.desc())
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "src_id": row.src_id,
            "customer_po_number": row.customer_po_number,
            "invoice_amount": float(row.invoice_amount) if row.invoice_amount is not None else None,
        }


def get_invoice_lines(header_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(InvLine).where(InvLine.header_id == header_id)).all()
        return [
            {
                "id": r.id,
                "line_number": r.line_number,
                "item_name": r.item_name,
                "item_desc": r.item_desc,
                "ordered_quantity": r.ordered_quantity,
                "unit_of_measure": r.unit_of_measure,
                "total": r.total,
            }
            for r in rows
        ]


def get_po_header_by_number(po_number: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalar(select(PoHeader).where(PoHeader.po_number == po_number))
        if row is None:
            return None
        return {
            "id": row.id,
            "src_id": row.src_id,
            "po_number": row.po_number,
            "c_name": row.c_name,
            "currency_code": row.currency_code,
            "payment_terms": row.payment_terms,
        }


def get_po_lines(header_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(PoLine).where(PoLine.header_id == header_id)).all()
        return [
            {
                "id": r.id,
                "line_number": r.line_number,
                "item_number": r.item_number,
                "ordered_quantity": r.ordered_quantity,
                "total": r.total,
            }
            for r in rows
        ]


def get_jde_invoice(src_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.scalar(select(JdeInvHeader).where(JdeInvHeader.src_id == src_id))
        if row is None:
            return None
        lines = session.scalars(select(JdeInvLines).where(JdeInvLines.header_id == row.id)).all()
        return {
            "id": row.id,
            "src_id": row.src_id,
            "company": row.company,
            "supplier_number": row.supplier_number,
            "invoice_number": row.invoice_number,
            "invoice_date": row.invoice_date,
            "business_unit": row.business_unit,
            "batch_number": row.batch_number,
            "approval_required": row.approval_required,
            "lines": [
                {
                    "id": l.id,
                    "gross_amount": float(l.gross_amount) if l.gross_amount is not None else None,
                    "order_number": l.order_number,
                    "item_number": l.item_number,
                }
                for l in lines
            ],
        }


def update_invoice_field(header_id: int, field: str, value: Any) -> bool:
    """Allow-listed field update on inv_header, mirroring the allow-list guard
    ennvault-existing's request_approval_ebs_db already enforces (audit §9) so
    an agent can't blindly overwrite arbitrary columns.
    """
    allowed_fields = {
        "supplier_name",
        "invoice_number",
        "customer_po_number",
        "currency_code",
        "invoice_amount",
        "payment_terms",
    }
    if field not in allowed_fields:
        raise ValueError(f"field '{field}' is not editable via update_invoice_field")
    with session_scope() as session:
        row = session.get(InvHeader, header_id)
        if row is None:
            return False
        setattr(row, field, value)
        return True


def update_invoice_line_field(line_id: int, field: str, value: Any) -> bool:
    """Allow-listed field update on a single inv_line row -- the line-level
    counterpart to update_invoice_field, for exceptions caused by a bad line
    field (e.g. invalid_item's wrong item_name) rather than a bad header
    field.
    """
    allowed_fields = {"item_name", "item_desc", "ordered_quantity", "unit_of_measure", "total"}
    if field not in allowed_fields:
        raise ValueError(f"field '{field}' is not editable via update_invoice_line_field")
    with session_scope() as session:
        row = session.get(InvLine, line_id)
        if row is None:
            return False
        setattr(row, field, value)
        return True


def list_exceptions(target_erp: str = "EBS", limit: int = 50) -> list[dict[str, Any]]:
    """Mirrors fetch_exception_records_db (audit §9): status in
    (Failed, OnHold, ON_HOLD), stage in (EBS, JDE), only the active log row.
    """
    with session_scope() as session:
        stmt = (
            select(LogTable)
            .where(LogTable.stage.in_(["EBS", "JDE"]))
            .where(LogTable.status.in_(["Failed", "OnHold", "ON_HOLD"]))
            .where((LogTable.is_active == "1") | (LogTable.is_active.is_(None)))
            .order_by(LogTable.log_time.desc())
            .limit(limit)
        )
        rows = session.scalars(stmt).all()
        return [
            {
                "entity_id": r.entity_id,
                "status": r.status,
                "stage": r.stage,
                "description": r.description,
                "is_reviewed": r.is_reviewed,
                "action_taken": r.action_taken,
                "log_time": r.log_time.isoformat() if r.log_time else None,
            }
            for r in rows
        ]


def update_jde_header_from_po_check(header_id: int, company_no: str, business_unit: str) -> None:
    with session_scope() as session:
        row = session.get(JdeInvHeader, header_id)
        if row is not None:
            row.company_no = company_no
            row.business_unit = business_unit


def update_jde_batch_number(header_id: int, batch_number: str, approval_required: str = "N") -> None:
    with session_scope() as session:
        row = session.get(JdeInvHeader, header_id)
        if row is not None:
            row.batch_number = batch_number
            row.approval_required = approval_required


def get_latest_log(entity_id: str) -> dict[str, Any] | None:
    """The log_table row this entity_id's current status/stage/etc. is taken
    from. Ordered by `id` (the autoincrement PK, guaranteed monotonic with
    insertion order within this table) rather than `log_time`: log_time's
    column default is `datetime.utcnow`, but other write paths into this
    table (e.g. the email-ingestion "Collection" row) can stamp it from a
    different clock/timezone. When that happens, an earlier-inserted row can
    carry a *later* log_time than a row inserted after it -- ordering by
    log_time would then silently resurrect a stale status (e.g. "Successful"
    from ingestion) over the row insert_log's own is_active bookkeeping
    already marked as current (is_active='1'), which is exactly what made an
    agent's real escalate_to_human write invisible to Manual Review even
    though the row itself was correct. `id` has no such ambiguity.
    """
    with session_scope() as session:
        row = session.scalar(
            select(LogTable).where(LogTable.entity_id == entity_id).order_by(LogTable.id.desc())
        )
        if row is None:
            return None
        return {
            "status": row.status,
            "stage": row.stage,
            "description": row.description,
            "is_reviewed": row.is_reviewed,
            "action_taken": row.action_taken,
            "log_time": row.log_time.isoformat() if row.log_time else None,
        }


def get_log_history(entity_id: str) -> list[dict[str, Any]]:
    """Every log_table row for this entity_id, oldest first. Ordered by `id`
    rather than `log_time` for the same reason get_latest_log is -- see its
    docstring; a status-history view built on a clock-skewed sort would show
    events out of order.
    """
    with session_scope() as session:
        rows = session.scalars(
            select(LogTable).where(LogTable.entity_id == entity_id).order_by(LogTable.id.asc())
        ).all()
        return [
            {
                "status": r.status,
                "stage": r.stage,
                "description": r.description,
                "is_reviewed": r.is_reviewed,
                "action_taken": r.action_taken,
                "log_time": r.log_time.isoformat() if r.log_time else None,
            }
            for r in rows
        ]


def list_recent_sources(limit: int = 100) -> list[dict[str, Any]]:
    """Backs the frontend's document list -- every ingested document
    (`source` row) with its latest status folded in, and the invoice
    header's supplier/amount when one has been extracted.
    """
    with session_scope() as session:
        sources = session.scalars(select(Source).order_by(Source.timestamp.desc()).limit(limit)).all()
        results = []
        for source in sources:
            latest_log = get_latest_log(source.src_id)
            header = session.scalar(select(InvHeader).where(InvHeader.src_id == source.src_id))
            results.append(
                {
                    "src_id": source.src_id,
                    "doc_type": source.doc_type,
                    "target": source.target,
                    "channel": source.channel,
                    "timestamp": source.timestamp.isoformat() if source.timestamp else None,
                    "status": latest_log["status"] if latest_log else None,
                    "stage": latest_log["stage"] if latest_log else None,
                    "supplier_name": header.supplier_name if header else None,
                    "invoice_number": header.invoice_number if header else None,
                    "invoice_amount": float(header.invoice_amount) if header and header.invoice_amount is not None else None,
                }
            )
        return results


def list_sources_by_status(
    statuses: list[str], target: str | None = None, stages: list[str] | None = None, limit: int | None = 200
) -> list[dict[str, Any]]:
    """Every `source` row whose *current* status is one of `statuses`,
    optionally restricted to one ERP target and/or one of `stages`, with the
    invoice header's supplier/amount folded in when one exists. Backs the
    dashboard's Processed drill-down (statuses=["Successful"],
    stages=["EBS", "JDE"] -- status="Successful" alone isn't enough, since
    stage="Collection"/"Successful" only means the email was received, not
    that the invoice was ever actually posted to an ERP).

    "Current status" here deliberately means the same thing
    list_recent_sources/get_latest_log already mean by it (the log_table row
    with the latest log_time for that entity_id) rather than list_exceptions's
    separate is_active-flag convention -- the two are supposed to agree, but
    using get_latest_log keeps this function's notion of "current" identical
    to what the Documents/Processed/Exceptions screens already display for
    the same document, rather than risking a second, possibly divergent
    opinion. `limit=None` returns every match, for an accurate count.
    """
    with session_scope() as session:
        stmt = select(Source).order_by(Source.timestamp.desc())
        if target:
            stmt = stmt.where(Source.target == target)
        sources = session.scalars(stmt).all()

        results = []
        for source in sources:
            latest_log = get_latest_log(source.src_id)
            if not latest_log or latest_log["status"] not in statuses:
                continue
            if stages is not None and latest_log["stage"] not in stages:
                continue
            header = session.scalar(select(InvHeader).where(InvHeader.src_id == source.src_id))
            results.append(
                {
                    "src_id": source.src_id,
                    "doc_type": source.doc_type,
                    "target": source.target,
                    "channel": source.channel,
                    "timestamp": source.timestamp.isoformat() if source.timestamp else None,
                    "status": latest_log["status"],
                    "stage": latest_log["stage"],
                    "description": latest_log["description"],
                    "log_time": latest_log["log_time"],
                    "supplier_name": header.supplier_name if header else None,
                    "invoice_number": header.invoice_number if header else None,
                    "invoice_amount": float(header.invoice_amount) if header and header.invoice_amount is not None else None,
                }
            )
            if limit is not None and len(results) >= limit:
                break
        return results


def count_sources_by_status(statuses: list[str], target: str | None = None, stages: list[str] | None = None) -> int:
    """Count of `source` rows whose current status is one of `statuses`,
    optionally restricted to one ERP target and/or stage. See
    list_sources_by_status for what "current" means here.
    """
    return len(list_sources_by_status(statuses, target=target, stages=stages, limit=None))


def count_sources() -> int:
    """Total number of `source` rows -- every document/email ever ingested,
    regardless of its current status or stage. This is the dashboard's "Total
    Mails Received" figure; it is intentionally independent of
    count_sources_by_status so a document still mid-pipeline (no terminal
    status yet) doesn't silently disappear from the total the way it can from
    the Processed/Exceptions buckets.
    """
    with session_scope() as session:
        return session.scalar(select(func.count()).select_from(Source)) or 0


def insert_log(
    entity_id: str,
    status: str,
    stage: str,
    description: str,
    is_reviewed: str = "0",
    action_taken: str = "",
    what_modified: str = "",
) -> None:
    """Same semantics as ennvault-existing's insert_log (audit §2): deactivate
    prior rows for this entity, then insert the new active row. The new
    pipeline writes into stage="MCP" here -- the audit found the existing
    codebase already anticipates this stage name in its own mapping dicts, so
    this is integration with the existing audit trail, not a parallel one.

    Raises ValueError for any status outside VALID_LOG_STATUSES -- see that
    constant's docstring for why this is enforced rather than accepting
    arbitrary description-shaped text.
    """
    if status not in VALID_LOG_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(VALID_LOG_STATUSES)}, got {status!r} -- "
            "put the human-readable explanation in `description`, not `status`."
        )
    with session_scope() as session:
        rows = session.scalars(select(LogTable).where(LogTable.entity_id == entity_id)).all()
        for row in rows:
            row.is_active = "0"
        session.add(
            LogTable(
                entity_id=entity_id,
                status=status,
                stage=stage,
                description=description,
                is_active="1",
                is_reviewed=is_reviewed,
                action_taken=action_taken,
                what_modified=what_modified,
                log_time=datetime.utcnow(),
            )
        )

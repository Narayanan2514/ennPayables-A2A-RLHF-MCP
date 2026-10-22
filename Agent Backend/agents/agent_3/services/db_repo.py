"""Writes extracted invoice data into the same `ennvault` MySQL database
ennVault_org_backend uses, into its existing tables -- and reads it back
for Agent 4's ERP-push stage.

Port of the insert/update/read patterns in ennVault_org_backend's
`modules/email_module/db.py` (source/email/log_table),
`modules/processing/entity_extractor/db.py` (jde_inv_header/jde_inv_lines,
inv_header/inv_line) and `ERP/db.py` (extract_inv_data/extract_inv_data_ebs,
update_company_number/update_order_line_items/update_voucher_approval/
update_batch_number) -- exact column names, matched to the live schema
those modules already write into. Uses SQLAlchemy Core (parameterized
`text()` statements) rather than an ORM, since we're writing into tables
this app does not own or migrate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shared.config import settings
from shared.utilities.logging import get_logger

logger = get_logger("agent_3.db_repo")

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if settings.database_url().startswith("sqlite") else {}
        _engine = create_engine(settings.database_url(), pool_pre_ping=True, connect_args=connect_args)
    return _engine


def _now_ist() -> datetime:
    """The legacy `log_table.log_time` convention: naive IST timestamp, to
    avoid a 5:30 skew against the column's own MySQL-side default."""
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


def insert_source(channel: str, target: str, doc_type: str, atch_nm: str, archive: str | None, folder_path: str) -> str:
    """Inserts a `source` row and returns the DB-generated `src_id` (a MySQL
    trigger on this table populates src_id from the autoincrement id)."""
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO source (channel, target, doc_type, atch_nm, archive, folder_path) "
                "VALUES (:channel, :target, :doc_type, :atch_nm, :archive, :folder_path)"
            ),
            {"channel": channel, "target": target, "doc_type": doc_type, "atch_nm": atch_nm, "archive": archive, "folder_path": folder_path},
        )
        new_id = result.lastrowid
        row = conn.execute(text("SELECT src_id FROM source WHERE id = :id"), {"id": new_id}).first()
        return row[0] if row else str(new_id)


def insert_email(src_id: str, from_email: str, subject: str, body: str, conversation_id: str, message_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO email (src_id, from_email, subject, body, coversationId, messageId) "
                "VALUES (:src_id, :from_email, :subject, :body, :conversation_id, :message_id)"
            ),
            {"src_id": src_id, "from_email": from_email, "subject": subject, "body": body, "conversation_id": conversation_id, "message_id": message_id},
        )


def insert_log(entity_id: str, status: str, stage: str, description: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE log_table SET is_active = '0' WHERE entity_id = :entity_id"), {"entity_id": entity_id})
        conn.execute(
            text(
                "INSERT INTO log_table (entity_id, status, stage, description, is_active, is_reviewed, action_taken, what_modified, log_time) "
                "VALUES (:entity_id, :status, :stage, :description, '1', '0', '', '', :log_time)"
            ),
            {"entity_id": entity_id, "status": status, "stage": stage, "description": description, "log_time": _now_ist()},
        )


def _parse_date_safe(date_str: Any) -> Any:
    """Port of ERP/db.py's normalize_date_dmY/parse_date_safe: vision
    extraction can hand back a date in several formats, but Agent 4's push
    stage (jde_push.py/ebs_push.py) reads this column back and expects
    ISO 'YYYY-MM-DD' -- store it normalized, not verbatim, or that later
    `datetime.strptime(..., '%Y-%m-%d')` call fails on a record that
    otherwise extracted fine."""
    if not date_str:
        return None
    for fmt in ("%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except ValueError:
            continue
    return None


def insert_jde_invoice_header(
    src_id: str,
    company: str,
    supplier_number: str,
    invoice_number: str,
    invoice_date: str,
    gl_date: str,
    business_unit: str,
    batch_number: str = "",
) -> int:
    # Matches ERP/db.py's insert_jde_inv_header: GLDate is always "now",
    # regardless of what's passed -- the caller-supplied `gl_date` is kept
    # only so this signature doesn't silently drop a positional argument.
    del gl_date
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO jde_inv_header (src_id, company, supplier_number, invoice_number, invoice_date, gl_date, business_unit, batch_number) "
                "VALUES (:src_id, :company, :supplier_number, :invoice_number, :invoice_date, :gl_date, :business_unit, :batch_number)"
            ),
            {
                "src_id": src_id,
                "company": company,
                "supplier_number": supplier_number,
                "invoice_number": invoice_number,
                "invoice_date": _parse_date_safe(invoice_date),
                "gl_date": datetime.now().strftime("%m/%d/%Y"),
                "business_unit": business_unit,
                "batch_number": batch_number,
            },
        )
        return result.lastrowid


def _extract_po_number(order_number: str) -> str:
    """Port of ERP/db.py's extract_po_number: JDE order numbers sometimes
    carry an 'OP...' suffix (order-type/line qualifier) that CheckPO
    doesn't expect -- strip it."""
    if not order_number:
        return ""
    return order_number.split("OP")[0]


def insert_jde_invoice_line(header_id: int, line: dict[str, Any]) -> int:
    order_number_raw = line.get("order_number") or line.get("purchase_order_number") or line.get("Purchase order number") or ""
    order_number = _extract_po_number(order_number_raw)
    gross_amount = str(line.get("gross_amount") or "").replace("$", "").strip()

    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO jde_inv_lines (header_id, gross_amount, remark, automation_flag, order_number, order_company, order_type, item_number) "
                "VALUES (:header_id, :gross_amount, :remark, :automation_flag, :order_number, :order_company, :order_type, :item_number)"
            ),
            {
                "header_id": header_id,
                "gross_amount": gross_amount,
                "remark": line.get("remark") or line.get("description") or "",
                "automation_flag": line.get("automation_flag", 1),
                "order_number": order_number,
                "order_company": line.get("order_company"),
                "order_type": line.get("order_type"),
                "item_number": line.get("item_number"),
            },
        )
        return result.lastrowid


# --------------------------------------------------------------------------
# EBS taxonomy tables (inv_header/inv_line) -- used when TARGET_ERP=EBS.
# Port of ERP/db.py's insert_inv_header/insert_inv_line.
# --------------------------------------------------------------------------


def _parse_float_safe(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def insert_inv_header(decoded_header: dict[str, Any], src_id: str) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO inv_header (src_id, bill_to, ship_to, supplier_name, invoice_number, invoice_date, "
                "payment_terms, customer_number, invoice_duedate, customer_po_number, so_number, shipping_point, "
                "currency_code, invoice_amount) "
                "VALUES (:src_id, :bill_to, :ship_to, :supplier_name, :invoice_number, :invoice_date, "
                ":payment_terms, :customer_number, :invoice_duedate, :customer_po_number, :so_number, :shipping_point, "
                ":currency_code, :invoice_amount)"
            ),
            {
                "src_id": src_id,
                "bill_to": decoded_header.get("bill_to", ""),
                "ship_to": decoded_header.get("ship_to", ""),
                "supplier_name": decoded_header.get("supplier_name", ""),
                "invoice_number": decoded_header.get("invoice_number", ""),
                "invoice_date": _parse_date_safe(decoded_header.get("invoice_date")),
                "payment_terms": decoded_header.get("payment_terms", "Immediate"),
                "customer_number": decoded_header.get("customer_number", ""),
                "invoice_duedate": _parse_date_safe(decoded_header.get("invoice_duedate")),
                "customer_po_number": decoded_header.get("customer_po_number", ""),
                "so_number": decoded_header.get("sales_order_number", ""),
                "shipping_point": decoded_header.get("shipping_point", ""),
                "currency_code": decoded_header.get("currency_code", "$"),
                "invoice_amount": _parse_float_safe(decoded_header.get("total", "")),
            },
        )
        return result.lastrowid


def insert_inv_line(header_id: int, line_item: dict[str, Any]) -> int:
    with get_engine().begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO inv_line (header_id, line_number, item_name, item_desc, ordered_quantity, "
                "unit_of_measure, total, fob_point, freight_carrier) "
                "VALUES (:header_id, :line_number, :item_name, :item_desc, :ordered_quantity, "
                ":unit_of_measure, :total, :fob_point, :freight_carrier)"
            ),
            {
                "header_id": header_id,
                "line_number": line_item.get("line_number", ""),
                "item_name": line_item.get("item_name", ""),
                "item_desc": line_item.get("item_description", ""),
                "ordered_quantity": line_item.get("ordered_quantity", ""),
                "unit_of_measure": line_item.get("unit_of_measure", ""),
                "total": _parse_float_safe(line_item.get("total", "")),
                "fob_point": line_item.get("fob_point", ""),
                "freight_carrier": line_item.get("freight_carrier", ""),
            },
        )
        return result.lastrowid


# --------------------------------------------------------------------------
# ERP-push read-back + status updates (Agent 4). Port of ERP/db.py.
# --------------------------------------------------------------------------


def extract_inv_data(src_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """JDE taxonomy read-back, for jde_push.push_to_jde."""
    with get_engine().begin() as conn:
        header = conn.execute(text("SELECT * FROM jde_inv_header WHERE src_id = :src_id"), {"src_id": src_id}).mappings().first()
        if not header:
            return None, []
        lines = conn.execute(text("SELECT * FROM jde_inv_lines WHERE header_id = :header_id"), {"header_id": header["id"]}).mappings().all()
        return dict(header), [dict(line) for line in lines]


def extract_inv_data_ebs(src_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """EBS taxonomy read-back, for ebs_push.push_to_ebs_inv."""
    with get_engine().begin() as conn:
        header = conn.execute(text("SELECT * FROM inv_header WHERE src_id = :src_id"), {"src_id": src_id}).mappings().first()
        if not header:
            return None, []
        lines = conn.execute(text("SELECT * FROM inv_line WHERE header_id = :header_id"), {"header_id": header["id"]}).mappings().all()
        return dict(header), [dict(line) for line in lines]


def update_company_number(company_no: str, cost_center: str, src_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE jde_inv_header SET company_no = :company_no, business_unit = :cost_center WHERE src_id = :src_id"),
            {"company_no": company_no, "cost_center": cost_center, "src_id": src_id},
        )


def update_order_line_items(order_company: str, order_type: str, src_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE jde_inv_lines l JOIN jde_inv_header h ON l.header_id = h.id "
                "SET l.order_company = :order_company, l.order_type = :order_type WHERE h.src_id = :src_id"
            ),
            {"order_company": order_company, "order_type": order_type, "src_id": src_id},
        )


def update_voucher_approval(src_id: str, approval_required: str, approver_name: str, approver_email: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE jde_inv_header SET approval_required = :approval_required, approver_name = :approver_name, "
                "approver_email = :approver_email WHERE src_id = :src_id"
            ),
            {"approval_required": approval_required, "approver_name": approver_name, "approver_email": approver_email, "src_id": src_id},
        )


def update_batch_number(batch_number: str, src_id: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE jde_inv_header SET batch_number = :batch_number WHERE src_id = :src_id"), {"batch_number": batch_number, "src_id": src_id})


# --------------------------------------------------------------------------
# Self-correction line-field updates (extraction_service.reextract_line_item).
# Allow-listed fields + parameterized UPDATE -- same discipline as RLHF's
# legacy_repo.update_invoice_field/update_invoice_line_field -- field name
# is never taken from free-form input.
# --------------------------------------------------------------------------

_EBS_LINE_ALLOWED_FIELDS = {"item_name", "item_desc"}
_JDE_LINE_ALLOWED_FIELDS = {"item_number"}


def update_ebs_line_field(line_id: int, field: str, value: Any) -> None:
    if field not in _EBS_LINE_ALLOWED_FIELDS:
        raise ValueError(f"field '{field}' is not editable via update_ebs_line_field")
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE inv_line SET {field} = :value WHERE id = :line_id"), {"value": value, "line_id": line_id})


def update_jde_line_field(line_id: int, field: str, value: Any) -> None:
    if field not in _JDE_LINE_ALLOWED_FIELDS:
        raise ValueError(f"field '{field}' is not editable via update_jde_line_field")
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE jde_inv_lines SET {field} = :value WHERE id = :line_id"), {"value": value, "line_id": line_id})

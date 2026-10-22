"""Reads back what Agent 3 stored, and updates ERP-push status columns.

Port of ennVault_org_backend's ERP/db.py (extract_inv_data,
extract_inv_data_ebs, update_company_number, update_order_line_items,
update_voucher_approval, update_batch_number) and the log_table half of
modules/email_module/db.py's insert_log. Deliberately independent of
agents/agent_3/services/db_repo.py -- this process never imports Agent 3
code (see main/main.py) -- even though both read/write the same
`ennvault` MySQL tables Agent 3 already wrote into.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shared.config import settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {"check_same_thread": False} if settings.database_url().startswith("sqlite") else {}
        _engine = create_engine(settings.database_url(), pool_pre_ping=True, connect_args=connect_args)
    return _engine


def _now_ist() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)


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


def extract_inv_data(src_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    with get_engine().begin() as conn:
        header = conn.execute(text("SELECT * FROM jde_inv_header WHERE src_id = :src_id"), {"src_id": src_id}).mappings().first()
        if not header:
            return None, []
        lines = conn.execute(text("SELECT * FROM jde_inv_lines WHERE header_id = :header_id"), {"header_id": header["id"]}).mappings().all()
        return dict(header), [dict(line) for line in lines]


def extract_inv_data_ebs(src_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
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

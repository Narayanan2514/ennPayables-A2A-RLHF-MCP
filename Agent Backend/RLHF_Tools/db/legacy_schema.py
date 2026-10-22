"""Read/write ORM mirror of the ennvault-existing MySQL schema.

This does NOT create or migrate these tables -- they already exist, owned by
ennvault-existing (see ../ennvault-existing/DB_Scripts/*.sql and
EXISTING_SYSTEM_AUDIT.md section 13). The Invoice-DB MCP server, the ERP
servers, and the legacy bridge all read/write through these models so the new
agentic pipeline stays on the *same* source-of-truth tables the existing UI's
Collections/Processed/Exceptions tabs already read from -- new agents show up
as just another writer to `log_table` (stage="MCP"), not a parallel system of
record.

`remit_header_ebs` / `remit_line_ebs` have no .sql file in ennvault-existing
(flagged in the audit, section 13) -- columns below are reconstructed from
usage in ERP/db.py and entity_extractor/db.py. Confirm against the real DDL
before relying on any column not already exercised by existing code.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class LegacyBase(DeclarativeBase):
    pass


class Source(LegacyBase):
    """The dimension/master table -- every doc-processing entity hangs off src_id."""

    __tablename__ = "source"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20), unique=True, nullable=False)  # trg_source_src_id trigger: src_NNN
    target = Column(String(20))  # 'EBS' | 'JDE'
    doc_type = Column(String(50))  # 'invoice' | 'purchase_order' | 'po' | 'remittance' | 'bank'
    atch_nm = Column(String(500))
    archive = Column(String(1000))
    channel = Column(String(50))  # 'email'
    folder_path = Column(String(1000))
    timestamp = Column(DateTime, default=datetime.utcnow)


class EmailRecord(LegacyBase):
    __tablename__ = "email"

    src_id = Column(String(20), primary_key=True)
    from_email = Column(String(255))
    subject = Column(String(500))
    body = Column(Text)
    coversationId = Column(Text)  # sic -- typo preserved from existing schema


class LogTable(LegacyBase):
    """The de facto status/exception/audit table (see audit section 13 & 9).

    Only the latest row per entity_id is `is_active='1'`; there is no
    confidence column here today -- the new architecture adds one via
    OutcomesLog (db/new_schema.py) rather than overloading this table.
    """

    __tablename__ = "log_table"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(20))  # soft ref -> source.src_id, no FK in production
    status = Column(String(100))  # 'Successful' | 'Failed' | 'OnHold' | 'ON_HOLD'
    stage = Column(String(100))  # 'Collection' | 'Preprocessing' | 'LLM Extraction' | 'EBS' | 'JDE' | 'Reprocess' | 'MCP'
    description = Column(Text)
    is_active = Column(String(10))
    is_reviewed = Column(String(10))
    action_taken = Column(String(255))
    what_modified = Column(Text)
    log_time = Column(DateTime, default=datetime.utcnow)


class InvHeader(LegacyBase):
    __tablename__ = "inv_header"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20))
    bill_to = Column(String(2000))
    ship_to = Column(String(2000))
    supplier_name = Column(String(500))
    invoice_number = Column(String(100))
    invoice_date = Column(Date)
    payment_terms = Column(String(100))
    customer_number = Column(String(100))
    invoice_duedate = Column(Date)
    customer_po_number = Column(String(100))
    so_number = Column(String(100))
    shipping_point = Column(String(255))
    currency_code = Column(String(10))
    invoice_amount = Column(Numeric(15, 2))
    supplier_site = Column(String(255))


class InvLine(LegacyBase):
    __tablename__ = "inv_line"

    id = Column(Integer, primary_key=True, autoincrement=True)
    header_id = Column(Integer)
    line_number = Column(String(50))
    item_name = Column(String(2000))
    ordered_quantity = Column(String(100))
    unit_of_measure = Column(String(50))
    total = Column(String(255))
    fob_point = Column(String(255))
    freight_carrier = Column(String(255))
    item_desc = Column(Text)


class PoHeader(LegacyBase):
    __tablename__ = "po_header"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20))
    bill_to = Column(String(2000))
    ship_to = Column(String(2000))
    po_number = Column(String(100))
    date = Column(String(2000))
    currency_code = Column(String(10))
    c_name = Column(String(255))
    c_number = Column(String(100))
    freight_terms = Column(String(255))
    payment_terms = Column(String(100))
    ship_method = Column(String(255))
    shipping_via = Column(String(255))
    so_number = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class PoLine(LegacyBase):
    __tablename__ = "po_line"

    id = Column(Integer, primary_key=True, autoincrement=True)
    header_id = Column(Integer)
    line_number = Column(String(50))
    item_number = Column(String(2000))
    ordered_quantity = Column(String(100))
    unit_of_measure = Column(String(50))
    total = Column(String(255))
    item_description = Column(Text)
    req_date = Column(Date)


class RemitHeaderEbs(LegacyBase):
    """AR (EBS) remittance header -- reconstructed, no .sql in ennvault-existing."""

    __tablename__ = "remit_header_ebs"

    h_id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20))
    customer_name = Column(String(255))
    customer_number = Column(String(100))
    receipt_number = Column(String(100))
    receipt_method = Column(String(100))
    receipt_date = Column(Date)
    receipt_amount = Column(Numeric(15, 2))
    currency_code = Column(String(10))
    reference_number = Column(String(100))
    org_id = Column(String(50))


class RemitLineEbs(LegacyBase):
    __tablename__ = "remit_line_ebs"

    l_id = Column(Integer, primary_key=True, autoincrement=True)
    h_id = Column(Integer)
    invoice_number = Column(String(100))
    invoice_date = Column(Date)
    invoice_amount = Column(Numeric(15, 2))
    amount_paid = Column(Numeric(15, 2))
    discount_amount = Column(Numeric(15, 2))
    customer_trx_id = Column(String(100))
    status = Column(String(100))
    error_message = Column(Text)
    outstanding = Column(Numeric(15, 2))
    org_invoice_amount = Column(Numeric(15, 2))


class JdeInvHeader(LegacyBase):
    __tablename__ = "jde_inv_header"

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20))
    company = Column(String(100))
    supplier_number = Column(String(100))
    invoice_number = Column(String(100))
    invoice_date = Column(String(100))
    gl_date = Column(String(100))
    business_unit = Column(String(100))
    company_no = Column(String(100))
    batch_number = Column(String(100))
    approval_required = Column(String(10))
    approver_name = Column(String(255))
    approver_email = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)


class JdeInvLines(LegacyBase):
    __tablename__ = "jde_inv_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    header_id = Column(Integer)
    gross_amount = Column(Numeric(15, 2))
    remark = Column(String(500))
    automation_flag = Column(String(10))
    order_number = Column(String(100))
    order_company = Column(String(100))
    order_type = Column(String(50))
    item_number = Column(String(100))


class BankDoc(LegacyBase):
    __tablename__ = "bank_doc"

    b_id = Column(Integer, primary_key=True, autoincrement=True)
    src_id = Column(String(20))
    ref_num = Column(String(100))
    bank_nm = Column(String(255))
    amnt = Column(Numeric(15, 2))


class CaseTable(LegacyBase):
    __tablename__ = "case_table"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(20), unique=True)
    src_grp = Column(String(100))  # comma-joined pair of src_ids, e.g. "src_100,src_200"

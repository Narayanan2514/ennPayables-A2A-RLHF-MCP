"""Dev convenience: populate a local sqlite database with a handful of
realistic documents so the frontend has something to show while you wire up
real DB/EBS/JDE/LLM credentials. Not a runtime "mock mode" for the app itself
-- just seed data, the same way tests/conftest.py seeds a scratch DB for
pytest. Safe to re-run (drops and recreates the sqlite file).

Run with:
    python scripts/seed_dev_data.py
Then, in one terminal: uvicorn api.main:app --reload --port 8010
And in another: cd frontend && npm run dev
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_URL_OVERRIDE", "sqlite:///./data/dev.db")
os.environ.setdefault("CHROMA_PERSIST_DIR", "./data/chroma")

from db.legacy_schema import Source  # noqa: E402
from db.new_schema import GovernanceMetricSnapshot  # noqa: E402
from db.session import create_legacy_tables_for_tests, create_new_tables, session_scope  # noqa: E402
from mcp_servers.common import legacy_repo  # noqa: E402

create_legacy_tables_for_tests()
create_new_tables()

DOCS = [
    dict(src_id="src_1001", supplier="3M Health Care", invoice_number="24020", po_number="6739", amount=100.00, outcome="ok"),
    dict(src_id="src_1002", supplier="Advantage Corp", invoice_number="35003", po_number="6743", amount=2000.00, outcome="amount_overapply"),
    dict(src_id="src_1003", supplier="BigSteel Inc", invoice_number="88213", po_number="999999", amount=450.00, outcome="invalid_po"),
    dict(src_id="src_1004", supplier="Adobe Systems", invoice_number="55210", po_number="7712", amount=75.50, outcome="ok"),
]

with session_scope() as session:
    session.query(Source).delete()

for doc in DOCS:
    with session_scope() as session:
        session.add(Source(src_id=doc["src_id"], target="EBS", doc_type="invoice", channel="email",
                            timestamp=datetime.utcnow() - timedelta(hours=len(DOCS))))

    header_id = legacy_repo.insert_invoice(
        doc["src_id"],
        {
            "supplier_name": doc["supplier"],
            "invoice_number": doc["invoice_number"],
            "customer_po_number": doc["po_number"],
            "currency_code": "USD",
            "total": str(doc["amount"]),
            "payment_terms": "Immediate",
        },
        [{"line_number": "1", "item_name": "0001-0120H", "item_description": "Line item", "ordered_quantity": "1", "total": str(doc["amount"])}],
    )

    legacy_repo.insert_log(doc["src_id"], "Successful", "Collection", "Email received")
    legacy_repo.insert_log(doc["src_id"], "Successful", "Preprocessing", "Attachments processed")
    legacy_repo.insert_log(doc["src_id"], "Successful", "LLM Extraction", "Fields extracted")

    if doc["outcome"] == "ok":
        legacy_repo.insert_log(doc["src_id"], "Successful", "EBS", "AP Invoice processed successfully")
    elif doc["outcome"] == "amount_overapply":
        legacy_repo.insert_log(
            doc["src_id"], "Failed", "EBS",
            f"Invoice Amount:{doc['amount']:.0f} exceeds total receipt quantity value: total_amount_received:1200",
        )
    elif doc["outcome"] == "invalid_po":
        legacy_repo.insert_log(doc["src_id"], "Failed", "EBS", f"PO Number not found!:{doc['po_number']}")

with session_scope() as session:
    session.add(
        GovernanceMetricSnapshot(
            supplier_name="3M Health Care",
            exception_type="invalid_po",
            window_start=datetime.utcnow() - timedelta(days=30),
            window_end=datetime.utcnow(),
            sample_size=42,
            agreement_rate=0.97,
            dispute_rate=0.01,
            straight_through_rate=0.88,
            confidence_calibration_error=0.04,
            recommended_autonomy_stage="expanded",
        )
    )
    session.add(
        GovernanceMetricSnapshot(
            supplier_name="BigSteel Inc",
            exception_type="invalid_po",
            window_start=datetime.utcnow() - timedelta(days=30),
            window_end=datetime.utcnow(),
            sample_size=6,
            agreement_rate=0.66,
            dispute_rate=0.15,
            straight_through_rate=0.40,
            confidence_calibration_error=0.18,
            recommended_autonomy_stage="shadow",
        )
    )

print(f"Seeded {len(DOCS)} documents into ./data/dev.db")

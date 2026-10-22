"""MCP tool backing Agent 2 (Validation Agent).

Thin wrapper over agents.agent_2.services.validation_service, imported in
place from the sibling Agent/ folder -- not duplicated here.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agents.agent_2.services import validation_service as svc


def register(mcp) -> None:
    @mcp.tool()
    def validate_intake_record(
        from_email: str = "",
        subject: str = "",
        doc_type: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Runs deterministic rule checks (sender, subject, doc type, PDF
        readability, then the customer-format/exclusion-config gate) on an
        email intake record and returns a pass/flag/block verdict plus
        is_valid, the readable PDF's path, and -- if it passed -- the
        PII-masked page images + mapping_path extract_and_store_invoice
        needs next."""
        result = svc.validate_intake_record(from_email, subject, doc_type or None, attachments or [])
        return {
            "verdict": result.verdict,
            "is_valid": result.is_valid,
            "violations": [asdict(v) for v in result.violations],
            "pdf_path": result.pdf_path,
            "encoded_image_paths": result.encoded_image_paths,
            "mapping_path": result.mapping_path,
        }

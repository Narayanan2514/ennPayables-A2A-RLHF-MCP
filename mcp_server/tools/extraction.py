"""MCP tool backing Agent 3 (Extraction Agent).

Thin wrapper over agents.agent_3.services.extraction_service, imported in
place from the sibling Agent/ folder -- not duplicated here. That service's
own DB insert + Backend archive handoff (see extraction_service.py's
_notify_backend_source_ready) run exactly as before; only where this code
executes changes.
"""
from __future__ import annotations

from typing import Any

from agents.agent_3.services.extraction_service import Agent3OperationError, process_invoice
from agents.agent_3.services.vision_extraction import ExtractionError
from shared.config import settings as agent_settings


def register(mcp) -> None:
    @mcp.tool()
    def extract_and_store_invoice(
        encoded_image_paths: list[str],
        mapping_path: str,
        pdf_path: str = "",
        from_email: str = "",
        subject: str = "",
        body_text: str = "",
        conversation_id: str = "",
        message_id: str = "",
        target_erp: str = "",
    ) -> dict[str, Any]:
        """Runs vision-based extraction over validate_intake_record's
        PII-masked page images (JDE or EBS taxonomy, per target_erp),
        decodes the masked values back, and stores the invoice in the
        ennvault DB (source, email, log_table, plus jde_inv_header/lines or
        inv_header/line). Does not submit to a live ERP -- that's
        push_invoice_to_erp's job. target_erp defaults to this deployment's
        TARGET_ERP setting when left blank."""
        try:
            return process_invoice(
                encoded_image_paths,
                mapping_path,
                pdf_path,
                from_email,
                subject,
                body_text,
                conversation_id,
                message_id,
                target_erp or agent_settings.TARGET_ERP,
            )
        except (ExtractionError, Agent3OperationError) as exc:
            return {"error": str(exc)}
        except Exception as exc:  # DB/connectivity failures surface as a business failure, not a crash
            return {"error": f"Extraction/storage failed: {exc}"}

from fastapi import APIRouter, Form, HTTPException

from app.api.internal.service import archive_source

router = APIRouter()


@router.post("/source-ready")
def source_ready(src_id: str = Form(...)):
    """Called by Agent's pipeline right after it commits a `source` row for
    a newly-extracted document -- archives the attachment folder and
    records the archive path on `source.archive`, replacing the retired
    to_process_listener.py's filesystem-watch trigger with an explicit,
    synchronous handoff.
    """
    try:
        return archive_source(src_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

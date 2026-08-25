"""Source-capture endpoint for the world model (design S3.1, S3.2).

Source capture is a DATA-PLANE step, not an agent tool: the bytes travel here
(multipart upload), not through an MCP tool call, and no model judgment is
involved. This endpoint stores the immutable raw revision plus its rendered
page images in MinIO and records the SourceRevision + views. The ingestion
agent never calls it — it only reads the rendered pages through read_source.

Mounted at /api/v1/sources (NOT under /api/v1/world, which is the world MCP
mount). Upload a PDF: office documents render via the deferred editor, so
convert to PDF out-of-band until the editor lands.
"""
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.world import sources as world_sources

router = APIRouter()


@router.post("")
async def capture_world_source(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    issuer: Optional[str] = Form(None),
    actor: str = Form("_ingestion"),
):
    """Capture one source: store raw bytes + rendered page images in MinIO and
    record the revision + page views. Returns the source_revision_id + view
    count. Idempotent on the content sha256 within the source."""
    data = await file.read()
    media_type = file.content_type or "application/octet-stream"
    try:
        return await world_sources.capture_source_bytes(
            project_id=project_id, filename=file.filename or "source",
            media_type=media_type, data=data, title=title, issuer=issuer,
            actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

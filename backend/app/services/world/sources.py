"""Source capture — the data-plane ingestion step (design S3.1, S3.2).

Capturing a source is NOT an agent tool and NOT a model decision: it hashes
the bytes, stores the immutable raw revision plus its rendered page images in
object storage (MinIO), and records the SourceRevision and its ordered
SourceViews. The ingestion agent never calls this — the upload/ingestion path
(POST /api/v1/sources) does, before any run exists. The agent only ever reads
the rendered pages through read_source and asserts.

Rendering: a PDF renders to page images directly via PyMuPDF (baked into the
image, no dependency). Office documents (DOCX/PPTX/XLSX) render through the
editor's convert-to-PDF hop (extract._office_to_pdf), which is DEFERRED in the
one-container build, so office sources must be converted to PDF out-of-band and
uploaded as PDF until the editor lands. read_source serves the stored page
images one page per call.
"""
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.session import async_session
from app.models.world import Source, SourceRevision, SourceView
from app.services.products import artifacts
from app.services.graph_ingest.extract import _render_pdf_pages


def raw_key(revision_id, filename: str) -> str:
    """Object-storage key for a revision's immutable raw bytes."""
    return f"sources/{revision_id}/raw/{filename}"


def page_key(revision_id, ordinal: int) -> str:
    """Object-storage key for one rendered page image (read_source derives
    the same key from the view's revision + ordinal — no key column needed)."""
    return f"sources/{revision_id}/pages/{ordinal:04d}.jpg"


async def capture_source_bytes(*, project_id: str, filename: str,
                               media_type: str, data: bytes,
                               title: str | None = None,
                               issuer: str | None = None,
                               actor: str = "_ingestion") -> dict:
    """Capture an immutable source revision from raw bytes: store the bytes and
    every rendered page image in MinIO, then record the SourceRevision + ordered
    page SourceViews. Idempotent on the content sha256 within a source."""
    if not data:
        raise ValueError("empty source bytes")
    lower = (filename or "").lower()
    is_pdf = (lower.endswith(".pdf")
              or (media_type or "").lower() == "application/pdf")
    if not is_pdf:
        raise ValueError(
            "source capture renders PDF page images directly; office documents "
            "need the editor's convert-to-PDF (deferred in this build) — convert "
            "to PDF out-of-band and upload the PDF")
    pages = _render_pdf_pages(data)  # list[JPEG bytes], one per page
    if not pages:
        raise ValueError("no pages rendered from the source")
    digest = hashlib.sha256(data).hexdigest()
    pid = UUID(project_id)
    async with async_session() as db:
        src = (await db.execute(select(Source).where(
            Source.project_id == pid, Source.title == (title or filename)))
        ).scalar_one_or_none()
        if src is None:
            src = Source(id=uuid4(), project_id=pid, title=(title or filename),
                         issuer=issuer, created_by=actor)
            db.add(src)
            await db.flush()
        rev = (await db.execute(select(SourceRevision).where(
            SourceRevision.source_id == src.id,
            SourceRevision.sha256 == digest))).scalar_one_or_none()
        if rev is not None:
            return {"outcome": "noop", "source_revision_id": str(rev.id),
                    "views": len(pages)}
        rev_id = uuid4()
        rk = raw_key(rev_id, filename)
        artifacts.put_bytes(rk, data, media_type or "application/pdf")
        for i, jpg in enumerate(pages):
            artifacts.put_bytes(page_key(rev_id, i), jpg, "image/jpeg")
        rev = SourceRevision(
            id=rev_id, source_id=src.id, object_ref=rk, sha256=digest,
            media_type=media_type, filename=filename, size_bytes=len(data),
            title=title, issuer=issuer, capture_actor=actor,
            rendering_version="pymupdf-1000px-q72")
        db.add(rev)
        await db.flush()
        for i in range(len(pages)):
            db.add(SourceView(id=uuid4(), source_revision_id=rev_id,
                              kind="page", ordinal=i, label=f"Page {i + 1}"))
        await db.commit()
        return {"outcome": "captured", "source_revision_id": str(rev_id),
                "views": len(pages)}

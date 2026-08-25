"""
Custom user-uploaded symbols (PNG/SVG).

Global scope — every user/workspace shares one library. Files are stored on
disk under data/uploads/custom_symbols/ and served back through GET /file
so the frontend can drop them on the map as <img> markers.
"""

import os
import re
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.custom_symbol import CustomSymbol

router = APIRouter()

UPLOAD_DIR = Path("/app/data/uploads/custom_symbols")
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Bare (non-container) dev runs can't create /app — the upload
    # handler retries the mkdir per-request, so imports must not die.
    pass

MAX_BYTES = 4 * 1024 * 1024  # 4 MB per icon

ALLOWED_FORMATS = {
    "png": ("png", "image/png"),
    "svg": ("svg", "image/svg+xml"),
}

# SVG active-content detection. REJECT, never strip: regex-rewriting
# HTML is bypassable by construction (browsers accept end-tag variants
# like `</script\t\nfoo>` that a "balanced element" pattern misses —
# CodeQL py/bad-tag-filter flagged exactly that on the earlier strip
# version), whereas detection only needs the OPENING construct, which
# has no such variance. An icon with any of these vectors gets a 400
# telling the analyst what to remove; a clean icon uploads unchanged.
_SVG_ACTIVE_CONTENT_RES = (
    # Any script element opening (also catches uppercase / namespaced
    # forms via IGNORECASE + \s*).
    re.compile(rb"<\s*script\b", re.IGNORECASE),
    # Inline event handlers (onload=, onclick=, …).
    re.compile(rb"\son[a-zA-Z]+\s*=", re.IGNORECASE),
    # javascript: hrefs.
    re.compile(rb"(href|xlink:href)\s*=\s*(\"|')\s*javascript:", re.IGNORECASE),
    # Embedded foreign documents that can carry their own script.
    re.compile(rb"<\s*foreignObject\b", re.IGNORECASE),
)

# Sniff width/height from SVG root. Falls back to viewBox extents when the
# attributes aren't pixel-valued (e.g. `width="100%"`).
_SVG_WH_RE = re.compile(rb'<svg\b[^>]*?\bwidth\s*=\s*"([\d.]+)"[^>]*?\bheight\s*=\s*"([\d.]+)"', re.IGNORECASE)
_SVG_VIEWBOX_RE = re.compile(rb'\bviewBox\s*=\s*"\s*[\d.\-]+\s+[\d.\-]+\s+([\d.]+)\s+([\d.]+)', re.IGNORECASE)

# PNG signature + IHDR layout.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


class CustomSymbolOut(BaseModel):
    id: uuid.UUID
    name: str
    file_format: str
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    url: str

    @classmethod
    def from_model(cls, m: CustomSymbol) -> "CustomSymbolOut":
        return cls(
            id=m.id,
            name=m.name,
            file_format=m.file_format,
            mime_type=m.mime_type,
            width=m.width,
            height=m.height,
            url=f"/api/v1/custom-symbols/{m.id}/file",
        )


def _sniff_png_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    # PNG: 8-byte signature, then IHDR chunk: 4 len, 4 type, 4 width, 4 height.
    if len(data) < 24 or data[:8] != _PNG_SIG or data[12:16] != b"IHDR":
        return None, None
    return (
        int.from_bytes(data[16:20], "big"),
        int.from_bytes(data[20:24], "big"),
    )


def _sniff_svg_size(data: bytes) -> tuple[Optional[int], Optional[int]]:
    head = data[:2048]
    for pattern in (_SVG_WH_RE, _SVG_VIEWBOX_RE):
        m = pattern.search(head)
        if m:
            try:
                return int(float(m.group(1))), int(float(m.group(2)))
            except ValueError:
                continue
    return None, None


def _reject_active_svg(data: bytes) -> None:
    """400 when an uploaded SVG carries active content (script elements,
    inline event handlers, javascript: hrefs, foreignObject). Rejection
    replaces the earlier regex STRIPPING, which was bypassable (see the
    detection-pattern comment above)."""
    for pattern in _SVG_ACTIVE_CONTENT_RES:
        if pattern.search(data):
            raise HTTPException(
                status_code=400,
                detail=(
                    "SVG contains active content (script, event handler, "
                    "javascript: link, or embedded foreign document). "
                    "Export the icon as plain static SVG and re-upload."
                ),
            )


async def _get_or_404(db: AsyncSession, symbol_id: uuid.UUID) -> CustomSymbol:
    result = await db.execute(select(CustomSymbol).where(CustomSymbol.id == symbol_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Symbol not found")
    return record


@router.post("", response_model=CustomSymbolOut)
async def upload_custom_symbol(
    file: UploadFile = File(...),
    user_id: str = Query("demo"),
    db: AsyncSession = Depends(get_db),
):
    filename = (file.filename or "symbol").strip() or "symbol"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="Only PNG and SVG are supported")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_BYTES} bytes")

    file_format, mime_type = ALLOWED_FORMATS[ext]
    if file_format == "svg":
        _reject_active_svg(data)
        width, height = _sniff_svg_size(data)
    else:
        width, height = _sniff_png_size(data)

    symbol_id = uuid.uuid4()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = UPLOAD_DIR / f"{symbol_id}.{file_format}"
    storage_path.write_bytes(data)

    record = CustomSymbol(
        id=symbol_id,
        name=filename,
        file_format=file_format,
        mime_type=mime_type,
        storage_uri=str(storage_path),
        width=width,
        height=height,
        created_by=user_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return CustomSymbolOut.from_model(record)


@router.get("", response_model=List[CustomSymbolOut])
async def list_custom_symbols(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CustomSymbol).order_by(CustomSymbol.created_at.desc())
    )
    return [CustomSymbolOut.from_model(m) for m in result.scalars().all()]


@router.get("/{symbol_id}/file")
async def get_custom_symbol_file(
    symbol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    record = await _get_or_404(db, symbol_id)
    if not os.path.isfile(record.storage_uri):
        raise HTTPException(status_code=410, detail="Symbol file missing on disk")
    return FileResponse(
        record.storage_uri,
        media_type=record.mime_type,
        filename=record.name,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete("/{symbol_id}")
async def delete_custom_symbol(
    symbol_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    record = await _get_or_404(db, symbol_id)
    # Row deletion is the source of truth; the file is best-effort.
    try:
        if os.path.isfile(record.storage_uri):
            os.remove(record.storage_uri)
    except OSError:
        pass
    await db.delete(record)
    await db.commit()
    return {"deleted": True}

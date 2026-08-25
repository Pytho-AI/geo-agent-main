from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.db.session import get_db
from app.schemas.overlay import OverlayResponse, OverlayCreate, OverlayUpdate, OverlayKind
from app.services.knowledge.spatial_query import (
    create_overlay,
    get_overlay_by_id,
    update_overlay,
    delete_overlay
)

router = APIRouter()


@router.get("/kinds", response_model=List[str])
async def list_overlay_kinds():
    """Get all available overlay kinds"""
    return [kind.value for kind in OverlayKind]


@router.get("/{overlay_id}", response_model=OverlayResponse)
async def get_overlay(
    overlay_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single overlay by ID"""
    overlay = await get_overlay_by_id(db, overlay_id)
    if not overlay:
        raise HTTPException(status_code=404, detail="Overlay not found")
    return overlay


@router.post("", response_model=OverlayResponse)
async def create_new_overlay(
    overlay: OverlayCreate,
    map_id: UUID = Query(...),
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new overlay"""
    return await create_overlay(db, overlay, map_id, user_id)


@router.put("/{overlay_id}", response_model=OverlayResponse)
async def update_existing_overlay(
    overlay_id: UUID,
    overlay_data: OverlayUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing overlay"""
    overlay = await update_overlay(db, overlay_id, overlay_data)
    if not overlay:
        raise HTTPException(status_code=404, detail="Overlay not found")
    return overlay


@router.delete("/{overlay_id}")
async def delete_existing_overlay(
    overlay_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an overlay by ID"""
    success = await delete_overlay(db, overlay_id)
    if not success:
        raise HTTPException(status_code=404, detail="Overlay not found")
    return {"status": "deleted", "id": str(overlay_id)}

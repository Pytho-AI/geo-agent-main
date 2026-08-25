from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db.session import get_db
from app.schemas.entity import EntityResponse, EntityCreate, EntityUpdate
from app.services.knowledge.spatial_query import (
    get_entity_by_id, create_entity, update_entity, delete_entity
)

router = APIRouter()


@router.get("/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single entity by ID"""
    return await get_entity_by_id(db, entity_id)


@router.post("", response_model=EntityResponse)
async def create_new_entity(
    entity: EntityCreate,
    map_id: UUID = Query(...),
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new entity"""
    return await create_entity(db, entity, map_id, user_id)


@router.put("/{entity_id}", response_model=EntityResponse)
async def update_existing_entity(
    entity_id: UUID,
    entity_update: EntityUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing entity (geometry, attrs, or confidence)"""
    result = await update_entity(
        db,
        entity_id,
        geom=entity_update.geom.model_dump() if entity_update.geom else None,
        attrs=entity_update.attrs,
        confidence=entity_update.confidence,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@router.delete("/{entity_id}")
async def delete_existing_entity(
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete an entity by ID"""
    success = await delete_entity(db, entity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"status": "deleted", "id": str(entity_id)}

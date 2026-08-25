from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.db.session import get_db
from app.models.map import Map
from app.schemas.cop import COPGenerateRequest, COPGenerateResponse, COPGetResponse, COAMapRequest, COAMapResponse
from app.services.cop.service import generate_cop
from app.services.cop.coa_map import generate_coa_map
from app.services.view.map_state import get_map_state

router = APIRouter()


@router.post("/generate", response_model=COPGenerateResponse)
async def generate_cop_endpoint(
    request: COPGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a Common Operational Picture from a world state narrative.

    Creates a new map, extracts all military entities, overlays, and
    routes from the narrative via LLM, and returns the structured COP.
    """
    return await generate_cop(db, request)


@router.get("/{map_id}", response_model=COPGetResponse)
async def get_cop(
    map_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the current COP for an existing map."""
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    state = await get_map_state(db, map_id)

    bbox = None
    if map_obj.bbox_west is not None:
        bbox = [
            map_obj.bbox_west,
            map_obj.bbox_south,
            map_obj.bbox_east,
            map_obj.bbox_north,
        ]

    return COPGetResponse(
        map_id=map_id,
        bbox=bbox,
        entities=state["entities"],
        overlays=state["overlays"],
        routes=state["routes"],
        meta=state["meta"],
    )


@router.post("/generate-coa-map", response_model=COAMapResponse)
async def generate_coa_map_endpoint(
    request: COAMapRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a COA-specific map from a COP base map.

    Clones all entities from the source COP map into a new map, then
    extracts tactical overlays (phase lines, avenues of approach,
    objectives, etc.) from the COA brief content via LLM.
    """
    return await generate_coa_map(db, request)

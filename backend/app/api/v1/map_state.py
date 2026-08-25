from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.db.session import get_db
from app.services.view.map_state import get_map_state

router = APIRouter()


@router.get("/state")
async def get_state(
    map_id: UUID = Query(...),
    bbox: Optional[str] = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    kinds: Optional[str] = Query(None, description="Comma-separated list of kinds"),
    as_of: Optional[datetime] = Query(
        None,
        description="Timeline scrub: paint graph features at their "
                    "latest observation at or before this time "
                    "(ISO 8601). Omit for the live newest-wins state."),
    include_draft_of: Optional[UUID] = Query(
        None,
        description="Product-record id whose DRAFT layer rows join "
                    "the painted picture — the record's own artifact "
                    "figure is a draft layer's only consumer."),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get combined map state (entities + overlays) for rendering"""
    bbox_list = [float(x) for x in bbox.split(",")] if bbox else None
    kinds_list = kinds.split(",") if kinds else None
    return await get_map_state(db, map_id, bbox_list, kinds_list, as_of=as_of,
                               include_draft_of=include_draft_of)


@router.get("/state/track-frames")
async def get_track_frames(
    map_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """DATED point observations per MOVABLE unit, oldest-first — the
    client-side data for the timeline scrubber. Dragging resolves each
    unit's position locally per tick (a scrubber must track the thumb,
    not a network round trip); the authoritative as_of fetch reconciles
    on release. Timeless features (control measures, fixed sites, units
    with no dated history) are absent — the client leaves them be."""
    from sqlalchemy import func, select
    from app.models.graph import GRAPHIC_TYPES, GraphNode, GraphNodePosition

    rows = (await db.execute(
        select(GraphNodePosition.node_id,
               GraphNodePosition.observed_at,
               func.ST_X(GraphNodePosition.geom),
               func.ST_Y(GraphNodePosition.geom))
        .join(GraphNode, GraphNode.id == GraphNodePosition.node_id)
        .where(GraphNode.project_id == map_id,
               GraphNode.entity_type.notin_(list(GRAPHIC_TYPES)),
               GraphNodePosition.observed_at.isnot(None),
               GraphNodePosition.geom.isnot(None),
               func.ST_GeometryType(GraphNodePosition.geom) == "ST_Point")
        .order_by(GraphNodePosition.node_id,
                  GraphNodePosition.observed_at))).all()
    frames: Dict[str, list] = {}
    for node_id, observed, lon, lat in rows:
        frames.setdefault(str(node_id), []).append(
            [observed.isoformat(), lon, lat])
    return {"frames": frames}

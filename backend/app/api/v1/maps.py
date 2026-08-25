import time

from fastapi import APIRouter, Body, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.db.session import get_db
from app.models.map import Map
from app.utils.sidc import ensure_mil_unit_sidc
from app.schemas.map import MapCreate, MapUpdate, MapResponse, MapListResponse

router = APIRouter()


@router.get("", response_model=MapListResponse)
async def list_maps(
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all maps, optionally filtered by user_id"""
    query = select(Map)
    if user_id:
        query = query.where(Map.user_id == user_id)
    query = query.order_by(Map.updated_at.desc())
    
    result = await db.execute(query)
    maps = result.scalars().all()
    
    return MapListResponse(maps=maps, total=len(maps))


@router.get("/{map_id}", response_model=MapResponse)
async def get_map(
    map_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a map by ID, creating a blank one if it doesn't exist.

    Maps are scoped per project/event and the map id IS the projectId
    (consumer contract), so the first open of a new project's map
    materializes the blank record right here — no consumer needs a
    separate "create the project map" step and the frontend carries no
    default-map fallback. Viewport columns stay NULL so the client
    resolves its normal chain (saved viewport → offline region →
    /config defaultView → neutral world view) until the first viewport
    save or producer push supplies one.
    """
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()

    if not map_obj:
        map_obj = Map(id=map_id, name="Operations Map", user_id="unknown", attrs={})
        db.add(map_obj)
        try:
            await db.commit()
        except IntegrityError:
            # Two first-opens raced; the other insert won — serve its row.
            await db.rollback()
            result = await db.execute(select(Map).where(Map.id == map_id))
            map_obj = result.scalar_one()
        else:
            await db.refresh(map_obj)

    return map_obj


@router.post("", response_model=MapResponse)
async def create_map(
    map_data: MapCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new map"""
    map_obj = Map(
        name=map_data.name,
        user_id=map_data.user_id,
        bbox_west=map_data.bbox_west,
        bbox_south=map_data.bbox_south,
        bbox_east=map_data.bbox_east,
        bbox_north=map_data.bbox_north,
        center_lng=map_data.center_lng,
        center_lat=map_data.center_lat,
        zoom=map_data.zoom,
        attrs=map_data.attrs,
    )
    
    db.add(map_obj)
    await db.commit()
    await db.refresh(map_obj)
    
    return map_obj


@router.put("/{map_id}", response_model=MapResponse)
async def update_or_create_map(
    map_id: UUID,
    map_data: MapUpdate,
    user_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing map or create it if it doesn't exist (upsert)"""
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()

    if not map_obj:
        # Create new map with the specified ID
        map_obj = Map(
            id=map_id,
            name=map_data.name or "Operations Map",
            user_id=user_id or "unknown",
            bbox_west=map_data.bbox_west,
            bbox_south=map_data.bbox_south,
            bbox_east=map_data.bbox_east,
            bbox_north=map_data.bbox_north,
            center_lng=map_data.center_lng,
            center_lat=map_data.center_lat,
            zoom=map_data.zoom or 8,
            attrs=map_data.attrs or {},
        )
        db.add(map_obj)
    else:
        # Update existing map
        if map_data.name is not None:
            map_obj.name = map_data.name
        if map_data.bbox_west is not None:
            map_obj.bbox_west = map_data.bbox_west
        if map_data.bbox_south is not None:
            map_obj.bbox_south = map_data.bbox_south
        if map_data.bbox_east is not None:
            map_obj.bbox_east = map_data.bbox_east
        if map_data.bbox_north is not None:
            map_obj.bbox_north = map_data.bbox_north
        if map_data.center_lng is not None:
            map_obj.center_lng = map_data.center_lng
        if map_data.center_lat is not None:
            map_obj.center_lat = map_data.center_lat
        if map_data.zoom is not None:
            map_obj.zoom = map_data.zoom
        if map_data.attrs is not None:
            # Merge new attrs with existing attrs to preserve other keys
            # Create a new dict to ensure SQLAlchemy detects the change
            merged_attrs = {**(map_obj.attrs or {}), **map_data.attrs}
            map_obj.attrs = merged_attrs
    
    await db.commit()
    await db.refresh(map_obj)
    
    return map_obj


@router.post("/{map_id}/clear")
async def clear_map(
    map_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Clear all entities, overlays, and routes from a map (keeps the map itself)"""
    from sqlalchemy import delete
    from app.models.entity import Entity
    from app.models.overlay import Overlay
    from app.models.route import Route

    # Verify map exists
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    # Delete all entities, overlays, and routes (route_paths cascade-deleted)
    entities_result = await db.execute(delete(Entity).where(Entity.map_id == map_id))
    overlays_result = await db.execute(delete(Overlay).where(Overlay.map_id == map_id))
    routes_result = await db.execute(delete(Route).where(Route.map_id == map_id))

    await db.commit()

    return {
        "status": "cleared",
        "map_id": str(map_id),
        "entities_deleted": entities_result.rowcount,
        "overlays_deleted": overlays_result.rowcount,
        "routes_deleted": routes_result.rowcount,
    }


@router.post("/{map_id}/sync")
async def sync_map_layer(
    map_id: UUID,
    payload: Dict[str, Any] = Body(...),
    source: str = Query(
        "live_oob",
        description=(
            "Tag matched against attrs.source. The endpoint deletes every "
            "overlay+entity on this map whose attrs.source equals this value, "
            "then inserts the payload rows. Non-matching rows (e.g. roads "
            "seeded from OSM with attrs.source='osm') are untouched. Every "
            "production caller passes this explicitly (live_oob, "
            "scenario_terrain, opord, writer, or a product key)."
        ),
    ),
    user_id: str = Query("sync"),
    db: AsyncSession = Depends(get_db),
):
    """Atomic replace of one tagged layer on a map.

    One live operating picture per AOR: pytho-app's producers (the
    live_oob order-of-battle push, scenario ingest, per-product writer
    mirrors) POST full source-tagged snapshots here. Delete-by-source +
    insert run in a single transaction; partial-success states aren't
    observable.

    Request body:
        {
          "overlays": [
            {"kind": "<str>", "name": "<str?>", "geom": <GeoJSON>,
             "attrs": {"source": "<source tag>", "source_kbid": "...", ...}},
            ...
          ],
          "entities": [
            {"kind": "<str>", "name": "<str?>", "geom": <GeoJSON>,
             "attrs": {...}, "confidence": <float?>},
            ...
          ]
        }

    Returns:
        {
          "map_id": "<uuid>", "source": "<tag>",
          "overlays_deleted": N, "overlays_inserted": M,
          "entities_deleted": N, "entities_inserted": M,
          "duration_ms": <int>
        }

    Validation: every row must have a `kind` recognized by
    get_overlay_kinds() (for overlays) or get_entity_kinds() (for entities),
    and a non-null `geom`. Rejected rows return 422 with offending indices —
    the transaction is NOT committed if any row fails validation, so the
    map keeps its previous state.

    The `attrs.source` field on incoming rows is REPLACED with the query-
    param `source` value before insert so the tag is always authoritative
    (a buggy caller can't smuggle in rows tagged as a different source)."""
    from sqlalchemy import delete
    from shapely.geometry import shape
    from geoalchemy2.shape import from_shape
    from app.models.entity import Entity
    from app.models.overlay import Overlay
    from app.constants import get_overlay_kinds, get_entity_kinds

    started_at = time.monotonic()

    overlay_rows = payload.get("overlays") or []
    entity_rows = payload.get("entities") or []
    if not isinstance(overlay_rows, list) or not isinstance(entity_rows, list):
        raise HTTPException(
            status_code=422,
            detail="payload.overlays and payload.entities must be arrays",
        )

    # Validate map exists.
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    valid_overlay_kinds = set(get_overlay_kinds())
    valid_entity_kinds = set(get_entity_kinds())

    overlay_errors: List[Dict[str, Any]] = []
    entity_errors: List[Dict[str, Any]] = []

    # Pre-validate. We compute shape() up front so a malformed geom rejects
    # before we touch the DB.
    parsed_overlays: List[Dict[str, Any]] = []
    for i, ov in enumerate(overlay_rows):
        if not isinstance(ov, dict):
            overlay_errors.append({"index": i, "error": "row must be an object"})
            continue
        kind = ov.get("kind")
        geom = ov.get("geom")
        if not kind or kind not in valid_overlay_kinds:
            overlay_errors.append({"index": i, "kind": kind, "error": "unknown overlay kind"})
            continue
        if not geom or not isinstance(geom, dict) or not geom.get("type"):
            overlay_errors.append({"index": i, "kind": kind, "error": "missing or malformed geom"})
            continue
        try:
            parsed_geom = from_shape(shape(geom), srid=4326)
        except Exception as e:
            overlay_errors.append({"index": i, "kind": kind, "error": f"geom parse failed: {e}"})
            continue
        attrs = dict(ov.get("attrs") or {})
        attrs["source"] = source  # enforced — see docstring
        parsed_overlays.append({
            "kind": kind,
            "name": ov.get("name"),
            "geom": parsed_geom,
            "attrs": attrs,
        })

    parsed_entities: List[Dict[str, Any]] = []
    for i, en in enumerate(entity_rows):
        if not isinstance(en, dict):
            entity_errors.append({"index": i, "error": "row must be an object"})
            continue
        kind = en.get("kind")
        geom = en.get("geom")
        if not kind or kind not in valid_entity_kinds:
            entity_errors.append({"index": i, "kind": kind, "error": "unknown entity kind"})
            continue
        if not geom or not isinstance(geom, dict) or not geom.get("type"):
            entity_errors.append({"index": i, "kind": kind, "error": "missing or malformed geom"})
            continue
        try:
            parsed_geom = from_shape(shape(geom), srid=4326)
        except Exception as e:
            entity_errors.append({"index": i, "kind": kind, "error": f"geom parse failed: {e}"})
            continue
        attrs = dict(en.get("attrs") or {})
        attrs["source"] = source  # enforced
        # Symbol coding is geo-agent's responsibility: producers send
        # unit semantics; a mil_unit arriving without a SIDC gets a
        # 2525E one built from affiliation/echelon/category. Rows that
        # carry a SIDC (KG-authored, incl. legacy 2525C letters) keep
        # it — upstream branch detail beats the category-derived icon.
        if kind == "mil_unit":
            ensure_mil_unit_sidc(attrs)
        parsed_entities.append({
            "kind": kind,
            "geom": parsed_geom,
            "attrs": attrs,
            "confidence": en.get("confidence", 1.0),
        })

    if overlay_errors or entity_errors:
        raise HTTPException(
            status_code=422,
            detail={"overlay_errors": overlay_errors, "entity_errors": entity_errors},
        )

    # Single transaction: delete rows tagged with this source, then insert
    # the snapshot. AsyncSession is single-connection so the begin/commit
    # bracket below is the transaction boundary.
    overlays_deleted_result = await db.execute(
        delete(Overlay).where(
            Overlay.map_id == map_id,
            Overlay.attrs["source"].astext == source,
        )
    )
    entities_deleted_result = await db.execute(
        delete(Entity).where(
            Entity.map_id == map_id,
            Entity.attrs["source"].astext == source,
        )
    )

    for row in parsed_overlays:
        db.add(Overlay(
            kind=row["kind"], name=row["name"], geom=row["geom"],
            attrs=row["attrs"], map_id=map_id, created_by=user_id,
        ))
    for row in parsed_entities:
        db.add(Entity(
            kind=row["kind"], geom=row["geom"], attrs=row["attrs"],
            confidence=row["confidence"], map_id=map_id, created_by=user_id,
        ))

    await db.commit()

    # Broadcast sync_complete so every connected client (pytho-app's
    # useGeoAgentRealtime hook on the operations map page) bumps its
    # mapRefreshTrigger and rehydrates entities/overlays from PostGIS.
    # Without this, a live_oob-driven snapshot replace (typical: intel_agent
    # publishes red disposition after a signal-report consume) lands silently
    # in the DB and the analyst stares at a stale map until they refresh
    # the page. session_id == str(map_id) by ws.py convention.
    try:
        from app.services.realtime.manager import manager
        await manager.notify_change(
            str(map_id),
            "sync_complete",
            {
                "map_id": str(map_id),
                "source": source,
            },
        )
    except Exception:
        # Broadcast is best-effort. A broken realtime channel must never
        # roll back the sync itself — the DB is already committed.
        import logging
        logging.getLogger(__name__).exception(
            "sync_map_layer: notify_change broadcast failed for map %s source %s",
            map_id, source,
        )

    return {
        "map_id": str(map_id),
        "source": source,
        "overlays_deleted": overlays_deleted_result.rowcount,
        "overlays_inserted": len(parsed_overlays),
        "entities_deleted": entities_deleted_result.rowcount,
        "entities_inserted": len(parsed_entities),
        "duration_ms": int((time.monotonic() - started_at) * 1000),
    }


@router.delete("/{map_id}")
async def delete_map(
    map_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a map and all its entities/overlays"""
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    
    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")
    
    await db.delete(map_obj)
    await db.commit()
    
    return {"status": "deleted", "id": str(map_id)}

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID
import json

from app.db.session import get_db
from app.models.map import Map
from app.models.entity import Entity
from app.models.overlay import Overlay
from app.models.artifact import Artifact
from app.models.history import MapHistory
from app.schemas.history import (
    SnapshotCreate,
    SnapshotResponse,
    SnapshotListItem,
    SnapshotListResponse,
)

router = APIRouter()


async def get_map_or_404(map_id: UUID, db: AsyncSession) -> Map:
    """Helper to get a map or raise 404"""
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")
    return map_obj


async def serialize_map(map_obj: Map) -> dict:
    """Serialize map to dict for snapshot"""
    return {
        "id": str(map_obj.id),
        "name": map_obj.name,
        "user_id": map_obj.user_id,
        "bbox_west": map_obj.bbox_west,
        "bbox_south": map_obj.bbox_south,
        "bbox_east": map_obj.bbox_east,
        "bbox_north": map_obj.bbox_north,
        "center_lng": map_obj.center_lng,
        "center_lat": map_obj.center_lat,
        "zoom": map_obj.zoom,
        "attrs": map_obj.attrs,
        "created_at": map_obj.created_at.isoformat() if map_obj.created_at else None,
        "updated_at": map_obj.updated_at.isoformat() if map_obj.updated_at else None,
    }


async def fetch_entities_snapshot(map_id: UUID, db: AsyncSession) -> list:
    """Fetch all entities for a map with geometry as GeoJSON"""
    query = select(
        Entity.id,
        Entity.kind,
        func.ST_AsGeoJSON(Entity.geom).label("geom"),
        Entity.attrs,
        Entity.confidence,
        Entity.created_by,
        Entity.created_at,
        Entity.updated_at,
    ).where(Entity.map_id == map_id)
    
    result = await db.execute(query)
    entities = []
    for row in result.all():
        entities.append({
            "id": str(row.id),
            "kind": row.kind,
            "geom": json.loads(row.geom) if row.geom else None,
            "attrs": row.attrs,
            "confidence": row.confidence,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return entities


async def fetch_overlays_snapshot(map_id: UUID, db: AsyncSession) -> list:
    """Fetch all overlays for a map with geometry as GeoJSON"""
    query = select(
        Overlay.id,
        Overlay.kind,
        Overlay.name,
        func.ST_AsGeoJSON(Overlay.geom).label("geom"),
        Overlay.attrs,
        Overlay.created_by,
        Overlay.created_at,
        Overlay.updated_at,
    ).where(Overlay.map_id == map_id)
    
    result = await db.execute(query)
    overlays = []
    for row in result.all():
        overlays.append({
            "id": str(row.id),
            "kind": row.kind,
            "name": row.name,
            "geom": json.loads(row.geom) if row.geom else None,
            "attrs": row.attrs,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return overlays


async def fetch_artifacts_snapshot(map_id: UUID, db: AsyncSession) -> list:
    """Fetch all artifact metadata for a map"""
    query = select(Artifact).where(Artifact.map_id == map_id)
    result = await db.execute(query)
    artifacts = []
    for artifact in result.scalars().all():
        artifacts.append({
            "id": str(artifact.id),
            "filename": artifact.filename,
            "file_type": artifact.file_type,
            "storage_uri": artifact.storage_uri,
            "status": artifact.status,
            "file_meta": artifact.file_meta,
            "created_by": artifact.created_by,
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        })
    return artifacts


async def fetch_routes_snapshot(map_id: UUID, db: AsyncSession) -> list:
    """Fetch all routes and their paths for a map with geometry as GeoJSON"""
    from app.models.route import Route, RoutePath
    from geoalchemy2.functions import ST_AsGeoJSON

    query = select(Route).where(Route.map_id == map_id)
    result = await db.execute(query)
    routes = []
    for route in result.scalars().all():
        start_json = await db.scalar(ST_AsGeoJSON(route.start_geom))
        end_json = await db.scalar(ST_AsGeoJSON(route.end_geom))

        # Fetch paths for this route
        paths_query = select(RoutePath).where(RoutePath.route_id == route.id).order_by(RoutePath.rank)
        paths_result = await db.execute(paths_query)
        paths = []
        for path in paths_result.scalars().all():
            path_geom = await db.scalar(ST_AsGeoJSON(path.geom))
            paths.append({
                "id": str(path.id),
                "rank": path.rank,
                "label": path.label,
                "geom": json.loads(path_geom) if path_geom else None,
                "selected": path.selected,
                "analysis": path.analysis,
            })

        routes.append({
            "id": str(route.id),
            "name": route.name,
            "start_geom": json.loads(start_json) if start_json else None,
            "end_geom": json.loads(end_json) if end_json else None,
            "route_mode": route.route_mode,
            "status": route.status,
            "attrs": route.attrs,
            "paths": paths,
        })
    return routes


async def get_next_version(map_id: UUID, db: AsyncSession) -> int:
    """Get the next version number for a map's snapshot"""
    query = select(func.coalesce(func.max(MapHistory.version), 0)).where(
        MapHistory.map_id == map_id
    )
    result = await db.execute(query)
    current_max = result.scalar()
    return current_max + 1


@router.post("/{map_id}/snapshots", response_model=SnapshotResponse)
async def create_snapshot(
    map_id: UUID,
    snapshot_data: SnapshotCreate = SnapshotCreate(),
    db: AsyncSession = Depends(get_db),
):
    """Create a snapshot of the current map state"""
    # Get the map
    map_obj = await get_map_or_404(map_id, db)
    
    # Collect all snapshot data
    map_snapshot = await serialize_map(map_obj)
    entities_snapshot = await fetch_entities_snapshot(map_id, db)
    overlays_snapshot = await fetch_overlays_snapshot(map_id, db)
    artifacts_snapshot = await fetch_artifacts_snapshot(map_id, db)
    routes_snapshot = await fetch_routes_snapshot(map_id, db)
    
    # Get next version number
    version = await get_next_version(map_id, db)
    
    # Create the snapshot
    history = MapHistory(
        map_id=map_id,
        version=version,
        label=snapshot_data.label,
        map_snapshot=map_snapshot,
        entities_snapshot=entities_snapshot,
        overlays_snapshot=overlays_snapshot,
        artifacts_snapshot=artifacts_snapshot,
        routes_snapshot=routes_snapshot,
        created_by=snapshot_data.created_by,
    )
    
    db.add(history)
    await db.commit()
    await db.refresh(history)
    
    return history


@router.get("/{map_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    map_id: UUID,
    user_id: Optional[str] = Query(
        None,
        description=(
            "Snapshots are PERSONAL save points of the shared event map: "
            "pass the analyst id to list only that analyst's snapshots "
            "(created_by match). Restoring one still applies to the shared "
            "map — the snapshot LIST is per-user, the map is not. No "
            "user_id returns every snapshot on the map (backend tooling)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """List snapshots for a map, scoped to one analyst when user_id is given"""
    # Verify map exists
    await get_map_or_404(map_id, db)

    query = (
        select(MapHistory)
        .where(MapHistory.map_id == map_id)
        .order_by(MapHistory.version.desc())
    )
    if user_id:
        query = query.where(MapHistory.created_by == user_id)
    
    result = await db.execute(query)
    snapshots = result.scalars().all()
    
    return SnapshotListResponse(
        snapshots=[
            SnapshotListItem(
                id=s.id,
                map_id=s.map_id,
                version=s.version,
                label=s.label,
                created_at=s.created_at,
                created_by=s.created_by,
            )
            for s in snapshots
        ],
        total=len(snapshots),
    )


@router.get("/{map_id}/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    map_id: UUID,
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific snapshot by ID"""
    # Verify map exists
    await get_map_or_404(map_id, db)
    
    query = select(MapHistory).where(
        MapHistory.map_id == map_id,
        MapHistory.id == snapshot_id,
    )
    
    result = await db.execute(query)
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    return snapshot


@router.post("/{map_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    map_id: UUID,
    snapshot_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Restore a map to a previous snapshot state"""
    from sqlalchemy import delete
    from geoalchemy2.functions import ST_GeomFromGeoJSON
    
    # Verify map exists
    map_obj = await get_map_or_404(map_id, db)
    
    # Get the snapshot
    query = select(MapHistory).where(
        MapHistory.map_id == map_id,
        MapHistory.id == snapshot_id,
    )
    result = await db.execute(query)
    snapshot = result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    # Delete all current entities, overlays, and routes for this map
    from app.models.route import Route
    await db.execute(delete(Entity).where(Entity.map_id == map_id))
    await db.execute(delete(Overlay).where(Overlay.map_id == map_id))
    await db.execute(delete(Route).where(Route.map_id == map_id))
    
    # Restore entities from snapshot
    entities_restored = 0
    if snapshot.entities_snapshot:
        for entity_data in snapshot.entities_snapshot:
            geom_geojson = json.dumps(entity_data.get("geom")) if entity_data.get("geom") else None
            entity = Entity(
                id=UUID(entity_data["id"]),
                map_id=map_id,
                kind=entity_data.get("kind"),
                geom=ST_GeomFromGeoJSON(geom_geojson) if geom_geojson else None,
                attrs=entity_data.get("attrs"),
                confidence=entity_data.get("confidence"),
                created_by=entity_data.get("created_by"),
            )
            db.add(entity)
            entities_restored += 1
    
    # Restore overlays from snapshot
    overlays_restored = 0
    if snapshot.overlays_snapshot:
        for overlay_data in snapshot.overlays_snapshot:
            geom_geojson = json.dumps(overlay_data.get("geom")) if overlay_data.get("geom") else None
            overlay = Overlay(
                id=UUID(overlay_data["id"]),
                map_id=map_id,
                kind=overlay_data.get("kind"),
                name=overlay_data.get("name"),
                geom=ST_GeomFromGeoJSON(geom_geojson) if geom_geojson else None,
                attrs=overlay_data.get("attrs"),
                created_by=overlay_data.get("created_by"),
            )
            db.add(overlay)
            overlays_restored += 1
    
    # Restore routes from snapshot
    routes_restored = 0
    if getattr(snapshot, 'routes_snapshot', None):
        from app.models.route import Route, RoutePath
        from geoalchemy2.functions import ST_GeomFromGeoJSON as RouteGeomFromGeoJSON
        for route_data in snapshot.routes_snapshot:
            start_geojson = json.dumps(route_data.get("start_geom")) if route_data.get("start_geom") else None
            end_geojson = json.dumps(route_data.get("end_geom")) if route_data.get("end_geom") else None
            route = Route(
                id=UUID(route_data["id"]),
                map_id=map_id,
                name=route_data.get("name"),
                start_geom=RouteGeomFromGeoJSON(start_geojson) if start_geojson else None,
                end_geom=RouteGeomFromGeoJSON(end_geojson) if end_geojson else None,
                route_mode=route_data.get("route_mode", "mixed"),
                status=route_data.get("status", "completed"),
                attrs=route_data.get("attrs", {}),
            )
            db.add(route)
            await db.flush()
            for path_data in route_data.get("paths", []):
                path_geojson = json.dumps(path_data.get("geom")) if path_data.get("geom") else None
                path = RoutePath(
                    id=UUID(path_data["id"]),
                    route_id=route.id,
                    rank=path_data.get("rank", 1),
                    label=path_data.get("label"),
                    geom=RouteGeomFromGeoJSON(path_geojson) if path_geojson else None,
                    selected=path_data.get("selected", 0),
                    analysis=path_data.get("analysis", {}),
                )
                db.add(path)
            routes_restored += 1

    # Restore map viewport and attrs from snapshot
    if snapshot.map_snapshot:
        map_state = snapshot.map_snapshot
        map_obj.center_lng = map_state.get("center_lng")
        map_obj.center_lat = map_state.get("center_lat")
        map_obj.zoom = map_state.get("zoom")
        map_obj.bbox_west = map_state.get("bbox_west")
        map_obj.bbox_south = map_state.get("bbox_south")
        map_obj.bbox_east = map_state.get("bbox_east")
        map_obj.bbox_north = map_state.get("bbox_north")
        # Restore attrs (includes layer preferences like base_map_style, layer_visibility)
        if map_state.get("attrs") is not None:
            map_obj.attrs = map_state.get("attrs")
    
    await db.commit()
    
    return {
        "success": True,
        "message": f"Restored to snapshot v{snapshot.version}",
        "entities_restored": entities_restored,
        "overlays_restored": overlays_restored,
        "routes_restored": routes_restored,
    }

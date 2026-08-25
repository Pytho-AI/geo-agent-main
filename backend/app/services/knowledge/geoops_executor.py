from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from typing import List
from uuid import UUID
import logging

from app.models.entity import Entity
from app.models.overlay import Overlay
from app.models.event import Event
from app.schemas.geoops import (
    GeoOpsRequest, GeoOpsResponse, GeoOpsResult,
    CreateEntity, MoveEntity, UpdateEntity, DeleteEntity,
    CreateOverlay, DeleteOverlay,
    CreateRoute, DeleteRoute,
)
from app.schemas.common import GeoJSON
from app.schemas.route import (
    RouteCreate, RoutePathCreate, RouteUpdate, RouteStatus, RouteMode,
)
from app.services.knowledge.route_query import (
    create_route as db_create_route,
    delete_route as db_delete_route,
    add_path_to_route,
    update_route as db_update_route,
)
from app.services.knowledge.routing import plan_routes, PlanRequest, RoutePreferences
from app.services.realtime.manager import manager

logger = logging.getLogger(__name__)


async def execute_geoops(db: AsyncSession, request: GeoOpsRequest) -> GeoOpsResponse:
    """Execute a batch of geo operations"""
    results: List[GeoOpsResult] = []
    
    for op in request.ops:
        try:
            if isinstance(op, CreateEntity):
                result = await _create_entity(db, op, request.user_id, request.map_id)
            elif isinstance(op, MoveEntity):
                result = await _move_entity(db, op)
            elif isinstance(op, UpdateEntity):
                result = await _update_entity(db, op)
            elif isinstance(op, DeleteEntity):
                result = await _delete_entity(db, op)
            elif isinstance(op, CreateOverlay):
                result = await _create_overlay(db, op, request.user_id, request.map_id)
            elif isinstance(op, DeleteOverlay):
                result = await _delete_overlay(db, op)
            elif isinstance(op, CreateRoute):
                result = await _create_route(db, op, request.user_id, request.map_id)
            elif isinstance(op, DeleteRoute):
                result = await _delete_route(db, op)
            else:
                result = GeoOpsResult(op=op.op, success=False, error="Unknown operation")
            
            # Log event (use mode='json' to serialize UUIDs as strings)
            event = Event(
                op_type=op.op,
                payload=op.model_dump(mode='json'),
                actor=request.user_id,
                map_id=request.map_id,
            )
            db.add(event)
            
            results.append(result)
            
            # Notify via WebSocket
            if result.success and request.map_id:
                await manager.notify_change(
                    str(request.map_id),
                    op.op,
                    {"id": str(result.id) if result.id else None, **op.model_dump(mode='json')}
                )
        except Exception as e:
            results.append(GeoOpsResult(op=op.op, success=False, error=str(e)))
    
    await db.commit()
    return GeoOpsResponse(results=results)


async def _create_entity(db, op: CreateEntity, user_id: str, map_id: UUID) -> GeoOpsResult:
    geom = shape(op.geom.model_dump())
    entity = Entity(
        kind=op.kind,
        geom=from_shape(geom, srid=4326),
        attrs=op.attrs,
        map_id=map_id,
        created_by=user_id,
    )
    db.add(entity)
    await db.flush()
    return GeoOpsResult(op="create_entity", success=True, id=entity.id)


async def _move_entity(db: AsyncSession, op: MoveEntity) -> GeoOpsResult:
    result = await db.execute(select(Entity).where(Entity.id == op.id))
    entity = result.scalar_one_or_none()
    if not entity:
        return GeoOpsResult(op="move_entity", success=False, error="Entity not found")
    
    geom = shape(op.geom.model_dump())
    entity.geom = from_shape(geom, srid=4326)
    return GeoOpsResult(op="move_entity", success=True, id=entity.id)


async def _update_entity(db: AsyncSession, op: UpdateEntity) -> GeoOpsResult:
    result = await db.execute(select(Entity).where(Entity.id == op.id))
    entity = result.scalar_one_or_none()
    if not entity:
        return GeoOpsResult(op="update_entity", success=False, error="Entity not found")
    
    # Merge attrs
    current_attrs = entity.attrs or {}
    current_attrs.update(op.attrs)
    entity.attrs = current_attrs
    return GeoOpsResult(op="update_entity", success=True, id=entity.id)


async def _delete_entity(db: AsyncSession, op: DeleteEntity) -> GeoOpsResult:
    result = await db.execute(delete(Entity).where(Entity.id == op.id))
    if result.rowcount == 0:
        return GeoOpsResult(op="delete_entity", success=False, error="Entity not found")
    return GeoOpsResult(op="delete_entity", success=True, id=op.id)


async def _create_overlay(db, op: CreateOverlay, user_id: str, map_id: UUID) -> GeoOpsResult:
    geom = shape(op.geom.model_dump())
    overlay = Overlay(
        kind=op.kind,
        name=op.name,
        geom=from_shape(geom, srid=4326),
        attrs=op.attrs,
        map_id=map_id,
        created_by=user_id,
    )
    db.add(overlay)
    await db.flush()
    return GeoOpsResult(op="create_overlay", success=True, id=overlay.id)


async def _delete_overlay(db: AsyncSession, op: DeleteOverlay) -> GeoOpsResult:
    result = await db.execute(delete(Overlay).where(Overlay.id == op.id))
    if result.rowcount == 0:
        return GeoOpsResult(op="delete_overlay", success=False, error="Overlay not found")
    return GeoOpsResult(op="delete_overlay", success=True, id=op.id)


async def _create_route(db: AsyncSession, op: CreateRoute, user_id: str, map_id: UUID) -> GeoOpsResult:
    """Plan and create a route using A* pathfinding."""
    start_coords = op.start_geom.coordinates
    end_coords = op.end_geom.coordinates

    # Parse route mode
    mode_str = op.route_mode or "mixed"
    try:
        route_mode = RouteMode(mode_str)
    except ValueError:
        route_mode = RouteMode.MIXED

    # Extract planning preferences from attrs
    attrs = op.attrs or {}
    preferences = RoutePreferences(
        slope_weight=attrs.get("slope_weight", 1.0),
        threat_weight=attrs.get("threat_weight", 1.0),
        concealment_weight=attrs.get("concealment_weight", 0.0),
        max_slope_pct=attrs.get("max_slope_pct", 58.0),
        preferred_terrain=attrs.get("preferred_terrain", []),
        avoid_terrain=attrs.get("avoid_terrain", []),
    )

    request = PlanRequest(
        start_lat=start_coords[1],
        start_lon=start_coords[0],
        end_lat=end_coords[1],
        end_lon=end_coords[0],
        route_mode=route_mode.value,
        map_id=map_id,
        preferences=preferences,
    )

    logger.info(f"GeoOps: Planning route '{op.name}' in {route_mode.value} mode")

    path_results, diagnostic = await plan_routes(db, request)

    if not path_results:
        # Planning failed — don't save to DB, just return diagnostic
        message = f"No {route_mode.value.replace('_', ' ')} route found"
        detail = None
        if diagnostic:
            message += f" ({'; '.join(diagnostic.suggestions)})" if diagnostic.suggestions else ""
            detail = {
                "reachable_from_start": diagnostic.reachable_from_start,
                "total_tiles": diagnostic.total_tiles,
                "blocking_counts": diagnostic.blocking_counts,
                "frontier_counts": diagnostic.frontier_counts,
                "impassable_terrain_types": diagnostic.impassable_terrain_types,
                "suggestions": diagnostic.suggestions,
            }
        return GeoOpsResult(op="create_route", success=False, error=message, detail=detail)

    # Planning succeeded — save route + paths to DB
    route_data = RouteCreate(
        name=op.name,
        start_geom=op.start_geom,
        end_geom=op.end_geom,
        route_mode=route_mode,
        attrs=attrs,
    )
    saved_route = await db_create_route(db, route_data, map_id)
    await db_update_route(db, saved_route.id, RouteUpdate(status=RouteStatus.COMPLETED))
    for pr in path_results:
        await add_path_to_route(
            db, saved_route.id,
            RoutePathCreate(
                rank=pr.rank,
                label=pr.label,
                geom=GeoJSON(type="LineString", coordinates=pr.coords),
                selected=1 if pr.rank == 1 else 0,
                analysis=pr.analysis,
            ),
        )
    return GeoOpsResult(op="create_route", success=True, id=saved_route.id)


async def _delete_route(db: AsyncSession, op: DeleteRoute) -> GeoOpsResult:
    """Delete a route and all its paths."""
    success = await db_delete_route(db, op.id)
    if not success:
        return GeoOpsResult(op="delete_route", success=False, error="Route not found")
    return GeoOpsResult(op="delete_route", success=True, id=op.id)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from geoalchemy2.functions import ST_MakeEnvelope, ST_Intersects, ST_AsGeoJSON
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from types import SimpleNamespace
from typing import List, Optional
from uuid import UUID
import json

from app.models.route import Route, RoutePath
from app.schemas.route import RouteCreate, RouteUpdate, RoutePathCreate, RoutePathUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _path_ns(p, geom_json):
    """Build a SimpleNamespace for a RoutePath."""
    return SimpleNamespace(
        id=p.id, route_id=p.route_id, rank=p.rank, label=p.label,
        geom=geom_json, selected=p.selected, analysis=p.analysis or {},
    )


def _route_ns(r, start_json, end_json, paths):
    """Build a SimpleNamespace for a Route."""
    return SimpleNamespace(
        id=r.id, map_id=r.map_id, name=r.name,
        start_geom=json.loads(start_json), end_geom=json.loads(end_json),
        route_mode=r.route_mode, status=r.status, attrs=r.attrs or {},
        paths=paths,
        created_at=r.created_at, updated_at=r.updated_at,
    )


# ---------------------------------------------------------------------------
# Route reads
# ---------------------------------------------------------------------------

async def get_routes(
    db: AsyncSession,
    map_id: UUID,
    status: Optional[str] = None,
    bbox: Optional[List[float]] = None,
) -> list:
    """Get routes for a map, optionally filtered by status or bounding box."""
    query = select(
        Route,
        ST_AsGeoJSON(Route.start_geom).label("start_json"),
        ST_AsGeoJSON(Route.end_geom).label("end_json"),
    ).where(Route.map_id == map_id)

    if status:
        query = query.where(Route.status == status)

    if bbox:
        envelope = ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)
        query = query.where(
            ST_Intersects(Route.start_geom, envelope)
            | ST_Intersects(Route.end_geom, envelope)
        )

    result = await db.execute(query)
    route_rows = result.all()

    if not route_rows:
        return []

    route_ids = [r.id for r, _, _ in route_rows]

    # Fetch all paths in a single query
    path_result = await db.execute(
        select(RoutePath, ST_AsGeoJSON(RoutePath.geom).label("path_json"))
        .where(RoutePath.route_id.in_(route_ids))
        .order_by(RoutePath.rank)
    )

    paths_by_route = {}
    for p, pj in path_result.all():
        paths_by_route.setdefault(p.route_id, []).append(
            _path_ns(p, json.loads(pj))
        )

    return [
        _route_ns(r, sj, ej, paths_by_route.get(r.id, []))
        for r, sj, ej in route_rows
    ]


async def get_route_by_id(db: AsyncSession, route_id: UUID):
    """Get a single route with all its paths."""
    result = await db.execute(
        select(
            Route,
            ST_AsGeoJSON(Route.start_geom).label("start_json"),
            ST_AsGeoJSON(Route.end_geom).label("end_json"),
        ).where(Route.id == route_id)
    )
    row = result.one_or_none()
    if not row:
        return None

    r, sj, ej = row

    path_result = await db.execute(
        select(RoutePath, ST_AsGeoJSON(RoutePath.geom).label("path_json"))
        .where(RoutePath.route_id == route_id)
        .order_by(RoutePath.rank)
    )
    paths = [_path_ns(p, json.loads(pj)) for p, pj in path_result.all()]

    return _route_ns(r, sj, ej, paths)


async def get_path_by_id(db: AsyncSession, path_id: UUID):
    """Get a single route path."""
    result = await db.execute(
        select(RoutePath, ST_AsGeoJSON(RoutePath.geom).label("path_json"))
        .where(RoutePath.id == path_id)
    )
    row = result.one_or_none()
    if not row:
        return None
    p, pj = row
    return _path_ns(p, json.loads(pj))


# ---------------------------------------------------------------------------
# Route writes
# ---------------------------------------------------------------------------

async def create_route(
    db: AsyncSession,
    route_data: RouteCreate,
    map_id: UUID,
) -> SimpleNamespace:
    """Create a route with optional initial paths."""
    start = from_shape(shape(route_data.start_geom.model_dump()), srid=4326)
    end = from_shape(shape(route_data.end_geom.model_dump()), srid=4326)

    route = Route(
        map_id=map_id,
        name=route_data.name,
        start_geom=start,
        end_geom=end,
        route_mode=route_data.route_mode.value,
        status="pending",
        attrs=route_data.attrs or {},
    )

    path_inputs = []
    for p in (route_data.paths or []):
        path_geom = from_shape(shape(p.geom.model_dump()), srid=4326)
        rp = RoutePath(
            rank=p.rank, label=p.label, geom=path_geom,
            selected=p.selected or 0, analysis=p.analysis or {},
        )
        route.paths.append(rp)
        path_inputs.append(p)

    db.add(route)
    await db.commit()
    await db.refresh(route, attribute_names=["paths"])

    # Build response from input data (geom already GeoJSON) + generated IDs
    path_namespaces = [
        SimpleNamespace(
            id=route.paths[i].id, route_id=route.id,
            rank=path_inputs[i].rank, label=path_inputs[i].label,
            geom=path_inputs[i].geom.model_dump(),
            selected=path_inputs[i].selected or 0,
            analysis=path_inputs[i].analysis or {},
        )
        for i in range(len(path_inputs))
    ]

    return SimpleNamespace(
        id=route.id, map_id=route.map_id, name=route.name,
        start_geom=route_data.start_geom.model_dump(),
        end_geom=route_data.end_geom.model_dump(),
        route_mode=route.route_mode, status=route.status,
        attrs=route.attrs or {}, paths=path_namespaces,
        created_at=route.created_at, updated_at=route.updated_at,
    )


async def update_route(
    db: AsyncSession,
    route_id: UUID,
    route_data: RouteUpdate,
):
    """Update route metadata (not paths)."""
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        return None

    if route_data.name is not None:
        route.name = route_data.name
    if route_data.start_geom is not None:
        route.start_geom = from_shape(shape(route_data.start_geom.model_dump()), srid=4326)
    if route_data.end_geom is not None:
        route.end_geom = from_shape(shape(route_data.end_geom.model_dump()), srid=4326)
    if route_data.route_mode is not None:
        route.route_mode = route_data.route_mode.value
    if route_data.status is not None:
        route.status = route_data.status.value
    if route_data.attrs is not None:
        route.attrs = route_data.attrs

    await db.commit()

    # Re-read cleanly using the efficient read path
    return await get_route_by_id(db, route_id)


async def delete_route(db: AsyncSession, route_id: UUID) -> bool:
    """Delete a route and all its paths (cascade)."""
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    if not route:
        return False
    await db.delete(route)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# RoutePath writes
# ---------------------------------------------------------------------------

async def add_path_to_route(
    db: AsyncSession,
    route_id: UUID,
    path_data: RoutePathCreate,
):
    """Add a new path alternative to an existing route."""
    result = await db.execute(select(Route).where(Route.id == route_id))
    if not result.scalar_one_or_none():
        return None

    path = RoutePath(
        route_id=route_id,
        rank=path_data.rank,
        label=path_data.label,
        geom=from_shape(shape(path_data.geom.model_dump()), srid=4326),
        selected=path_data.selected or 0,
        analysis=path_data.analysis or {},
    )
    db.add(path)
    await db.commit()
    await db.refresh(path)

    return SimpleNamespace(
        id=path.id, route_id=path.route_id,
        rank=path.rank, label=path.label,
        geom=path_data.geom.model_dump(),
        selected=path.selected, analysis=path.analysis or {},
    )


async def update_path(
    db: AsyncSession,
    path_id: UUID,
    path_data: RoutePathUpdate,
):
    """Update a route path (geometry, analysis, selection, etc.)."""
    result = await db.execute(select(RoutePath).where(RoutePath.id == path_id))
    path = result.scalar_one_or_none()
    if not path:
        return None

    if path_data.label is not None:
        path.label = path_data.label
    if path_data.geom is not None:
        path.geom = from_shape(shape(path_data.geom.model_dump()), srid=4326)
    if path_data.selected is not None:
        path.selected = path_data.selected
    if path_data.analysis is not None:
        path.analysis = path_data.analysis

    await db.commit()

    # Re-read cleanly
    return await get_path_by_id(db, path_id)


async def select_path(db: AsyncSession, route_id: UUID, path_id: UUID) -> bool:
    """Mark one path as selected and deselect all others on the same route."""
    result = await db.execute(
        select(RoutePath).where(RoutePath.route_id == route_id)
    )
    paths = result.scalars().all()
    if not paths:
        return False

    found = False
    for p in paths:
        if p.id == path_id:
            p.selected = 1
            found = True
        else:
            p.selected = 0

    if not found:
        return False

    await db.commit()
    return True


async def delete_path(db: AsyncSession, path_id: UUID) -> bool:
    """Delete a single route path."""
    result = await db.execute(select(RoutePath).where(RoutePath.id == path_id))
    path = result.scalar_one_or_none()
    if not path:
        return False
    await db.delete(path)
    await db.commit()
    return True

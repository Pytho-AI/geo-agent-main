import logging

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.db.session import get_db
from app.schemas.route import (
    RouteResponse,
    RouteCreate,
    RouteUpdate,
    RoutePathResponse,
    RoutePathCreate,
    RoutePathUpdate,
    RouteMode,
    RouteStatus,
    AnalyzeEditRequest,
)
from app.schemas.common import GeoJSON
from app.services.knowledge.route_query import (
    get_routes,
    get_route_by_id,
    create_route,
    update_route,
    delete_route,
    add_path_to_route,
    update_path,
    select_path,
    delete_path,
)
from app.services.knowledge.routing import plan_routes, analyze_drawn_route, PlanRequest, RoutePreferences
from app.services.knowledge.routing.corridor_discovery import discover_mobility_corridors
from app.services.knowledge.routing.tile_graph import create_tile_grid, populate_tiles
from app.services.knowledge.routing.data_fetch import fetch_viewport_data, extract_threats
from app.services.knowledge.routing.mcoo_terrain import (
    DEFAULT_CELL_M,
    TerminalSpec,
    resolve_force_profile,
    synthesize_mcoo,
)
from app.services.knowledge.landcover import LAND_COVER_CLASSES

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Route endpoints
# ---------------------------------------------------------------------------

@router.get("/options")
async def list_route_options():
    """Get available route modes."""
    return {
        "route_modes": [m.value for m in RouteMode],
    }


@router.get("", response_model=List[RouteResponse])
async def list_routes(
    map_id: UUID = Query(...),
    status: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None, description="min_lon,min_lat,max_lon,max_lat"),
    db: AsyncSession = Depends(get_db),
):
    """Get routes for a map, optionally filtered by status or bounding box."""
    bbox_list = [float(x) for x in bbox.split(",")] if bbox else None
    return await get_routes(db, map_id, status, bbox_list)


@router.post("/discover-corridors")
async def discover_corridors(
    bbox: str = Query(..., description="W,S,E,N bbox (lon/lat decimal degrees)"),
    force_type: str = Query("mechanized"),
    min_class: str = Query("company"),
    map_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Discover doctrinal mobility corridors in a bounding box via
    connected-component analysis on the cost-surface canalization mask.

    Per ATP 2-01.3 §4-24, mobility corridors are "areas relatively free
    of obstacles where a force will be canalized." Each returned corridor
    is one connected region of passable terrain bounded by obstacles;
    corridors are GEOGRAPHICALLY NON-OVERLAPPING by construction (each
    tile belongs to exactly one corridor). Per §4-27 + Table 4-2 each
    corridor is classified by its medial-axis perpendicular width.

    Used by pytho-app MCOO enrichment to build the doctrinal AA list
    (groups of corridors sharing an objective) and to render each
    corridor as a `mobility_corridor` overlay alongside the AA chevrons.

    bbox query string: "W,S,E,N" (e.g. "24.238,57.092,28.614,58.634").
    """
    try:
        parts = [float(v) for v in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("expected 4 values")
        w, s, e, n = parts
    except (ValueError, TypeError) as ex:
        raise HTTPException(status_code=422, detail=f"Invalid bbox: {ex}")

    # tile_grid bbox convention is (south, west, north, east).
    grid_bbox = (s, w, n, e)
    logger.info(f"discover_corridors: bbox={grid_bbox} force_type={force_type}")
    tile_grid = create_tile_grid(grid_bbox)
    threats, no_go, _ = await extract_threats(db, map_id, grid_bbox)
    # Off-road viewport data — corridor canalization is a terrain
    # property, independent of the road network. (Roads are a SEPARATE
    # dimension that the per-route on-road analysis covers.)
    viewport_data = await fetch_viewport_data(grid_bbox, tile_grid, str(map_id), "off_road")
    tile_grid = populate_tiles(tile_grid, viewport_data, threats, no_go)
    try:
        corridors = discover_mobility_corridors(
            tile_grid, force_type=force_type, min_class=min_class
        )
    except Exception as exc:
        logger.exception("Corridor discovery failed")
        raise HTTPException(status_code=500, detail=f"discovery failed: {exc}")

    return {
        "bbox": [w, s, e, n],
        "force_type": force_type,
        "min_class": min_class,
        "corridor_count": len(corridors),
        "corridors": corridors,
    }


@router.post("/synthesize-mcoo")
async def synthesize_mcoo_endpoint(
    body: dict,
    map_id: UUID = Query(...),
):
    """Synthesize the full Modified Combined Obstacle Overlay product set
    for an AO using the doctrinal GVD + circuit-theory pipeline.

    Body shape:
        {
          "bbox": [W, S, E, N],
          "force_type": "mechanized" | "dismounted",
          "primary_echelon": "division" | "brigade" | "battalion",
          "cell_m": 100,                      # optional, default 100
          "terminal_pairs": [
             {
               "origin":    {"name": "Cimza",   "lon": 24.83, "lat": 57.55, "side": "friendly"},
               "objective": {"name": "Kopu",    "lon": 24.83, "lat": 58.27, "side": "threat"}
             },
             ...
          ]
        }

    Returns the full MCOO product set:
        - mobility_corridors: GVD edge LineStrings with width/class
        - avenues_of_approach: per terminal-pair multi-tail bundles with
          central axis, tail corridor ids, envelope polygon
        - engagement_areas: GVD-vertex-derived disruption points
        - defensible_terrain: flanked GVD vertices
        - nogo_obstacles: extracted NO-GO polygons (for renderer context)

    Every record carries GEOMETRY + STRUCTURED FACTS only (counts,
    distances, scores). No prose: analyst-facing Rationale text is
    composed by the consuming product layer (pytho-app MCOO enrichment),
    never authored here — geo-agent is the map service, not a document
    writer.
    """
    try:
        bbox = body.get("bbox") or []
        if len(bbox) != 4:
            raise ValueError("bbox must be [W, S, E, N]")
        w, s, e, n = (float(v) for v in bbox)
        force_type = str(body.get("force_type") or "mechanized")
        primary_echelon = str(body.get("primary_echelon") or "division")
        cell_m = float(body.get("cell_m") or DEFAULT_CELL_M)
        raw_pairs = body.get("terminal_pairs") or []
        terminal_pairs = []
        for p in raw_pairs:
            o = p.get("origin") or {}
            d = p.get("objective") or {}
            terminal_pairs.append((
                TerminalSpec(name=str(o.get("name") or "origin"),
                             lon=float(o["lon"]), lat=float(o["lat"]),
                             side=str(o.get("side") or "friendly"),
                             role="origin"),
                TerminalSpec(name=str(d.get("name") or "objective"),
                             lon=float(d["lon"]), lat=float(d["lat"]),
                             side=str(d.get("side") or "threat"),
                             role="objective"),
            ))
    except (KeyError, TypeError, ValueError) as ex:
        raise HTTPException(status_code=422, detail=f"Invalid body: {ex}")

    profile = resolve_force_profile(force_type)
    logger.info(
        "synthesize_mcoo: bbox=[%.3f,%.3f,%.3f,%.3f] force=%s primary_echelon=%s "
        "cell_m=%g terminals=%d", w, s, e, n, force_type, primary_echelon,
        cell_m, len(terminal_pairs),
    )

    import asyncio
    try:
        products = await asyncio.to_thread(
            synthesize_mcoo,
            west=w, south=s, east=e, north=n,
            terminal_pairs=terminal_pairs,
            force_profile=profile,
            primary_echelon=primary_echelon,
            cell_m=cell_m,
        )
    except Exception as exc:
        logger.exception("synthesize_mcoo failed")
        raise HTTPException(status_code=500, detail=f"synthesis failed: {exc}")

    # ------------------------------------------------------------------
    # Serialize products to GeoJSON-friendly dicts
    # ------------------------------------------------------------------
    def _poly_to_geojson(poly):
        if poly is None or getattr(poly, "is_empty", False):
            return None
        if poly.geom_type == "Polygon":
            return {
                "type": "Polygon",
                "coordinates": [list(map(list, poly.exterior.coords))]
                                + [list(map(list, r.coords)) for r in poly.interiors],
            }
        if poly.geom_type == "MultiPolygon":
            return {
                "type": "MultiPolygon",
                "coordinates": [
                    [list(map(list, sub.exterior.coords))]
                    + [list(map(list, r.coords)) for r in sub.interiors]
                    for sub in poly.geoms
                ],
            }
        return None

    # Per-corridor records. Display filters (NOT applied to the internal
    # GVD that drives circuit / EA / defensible scoring — that's kept
    # dense). For doctrinal clarity we surface ONLY the corridors that
    # form a tail in at least one synthesized avenue of approach — the
    # full GVD has thousands of trafficable bisectors but most are not
    # operationally relevant (lake-shore + urban-edge fragments, etc.).
    # This matches ATP 2-01.3 ¶4-22 which says avenues "consist of a
    # series of mobility corridors"; the painted corridors are exactly
    # those series, nothing else.
    avenue_corridor_ids: set = set()
    for bundle in products.avenues:
        avenue_corridor_ids.update(int(x) for x in bundle.tail_edge_ids)
    DISPLAY_MIN_LEN_M = 400.0  # also drop ultra-tiny segments within a bundle
    corridor_records = []
    for edge in products.gvd.edges:
        if int(edge.id) not in avenue_corridor_ids:
            continue
        if edge.length_m < DISPLAY_MIN_LEN_M:
            continue
        corridor_records.append({
            "id": int(edge.id),
            "coords": [[float(x), float(y)] for x, y in edge.coords],
            "length_m": round(float(edge.length_m), 1),
            "width_m": round(float(edge.width_m), 1),
            "class": edge.class_(profile),
        })

    # Per-avenue records
    avenue_records = []
    for bundle in products.avenues:
        avenue_records.append({
            # "AA" is the doctrinal avenue-of-approach abbreviation — these
            # ids surface in pytho-app's MCOO enrichment as user-visible
            # overlay identifiers.
            "id": f"AA-{bundle.side[:3].upper()}-{bundle.origin_name[:8].upper()}"
                  f"-TO-{bundle.objective_name[:8].upper()}",
            "side": bundle.side,
            "echelon": bundle.echelon,
            "origin_name": bundle.origin_name,
            "origin_lonlat": list(map(float, bundle.origin_lonlat)),
            "objective_name": bundle.objective_name,
            "objective_lonlat": list(map(float, bundle.objective_lonlat)),
            "central_axis_corridor_ids": [int(x) for x in bundle.central_axis_edge_ids],
            "central_axis_polyline": [[float(x), float(y)]
                                       for x, y in bundle.central_axis_polyline_lonlat]
                                      if bundle.central_axis_polyline_lonlat else [],
            "tail_corridor_ids": [int(x) for x in bundle.tail_edge_ids],
            "envelope_polygon": [[float(x), float(y)]
                                 for x, y in bundle.envelope_polygon_lonlat]
                                if bundle.envelope_polygon_lonlat else [],
            "bundle_halfwidth_m": float(bundle.bundle_halfwidth_m),
        })

    # Engagement areas — structured siting facts, no prose.
    ea_records = []
    for ea in products.engagement_areas:
        ea_records.append({
            "id": ea.id,
            "centre_lonlat": list(map(float, ea.centre_lonlat)),
            "polygon": [[float(x), float(y)] for x, y in ea.polygon_lonlat],
            "score": round(float(ea.score), 3),
            "corridors_converging": int(ea.corridors_converging),
            "throughput_drop_pct": round(float(ea.throughput_drop_pct), 1),
        })

    # Defensible terrain — structured siting facts, no prose.
    def_records = []
    for d in products.defensible_areas:
        def_records.append({
            "id": d.id,
            "centre_lonlat": list(map(float, d.centre_lonlat)),
            "polygon": [[float(x), float(y)] for x, y in d.polygon_lonlat],
            "score": round(float(d.score), 3),
            "flanks_protected": int(d.flanks_protected),
            "protection_radius_km": round(float(d.protection_radius_km), 2),
            "threat_origin_count": int(d.threat_origin_count),
        })

    # NO-GO obstacles (sample at most 100 to keep payload size sane)
    nogo_records = []
    for i, poly in enumerate(products.nogo_polys[:200]):
        geom = _poly_to_geojson(poly)
        if geom:
            nogo_records.append({"id": int(i), "geometry": geom})

    return {
        "bbox": [w, s, e, n],
        "force_type": force_type,
        "primary_echelon": primary_echelon,
        "cell_m": cell_m,
        "mobility_corridors": corridor_records,
        "avenues_of_approach": avenue_records,
        "engagement_areas": ea_records,
        "defensible_terrain": def_records,
        "nogo_obstacles": nogo_records,
        "stats": {
            "corridor_count": len(corridor_records),
            "avenue_count": len(avenue_records),
            "engagement_area_count": len(ea_records),
            "defensible_count": len(def_records),
            "nogo_polygon_count": len(products.nogo_polys),
        },
    }


@router.post("/analyze-edit")
async def analyze_edit(
    body: AnalyzeEditRequest,
    map_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze user-edited route coordinates using the off-road code path.
    Returns terrain analysis without saving anything to the DB.
    """
    coords = [tuple(c) for c in body.coordinates]
    if len(coords) < 2:
        raise HTTPException(status_code=422, detail="Need at least 2 coordinates")

    try:
        analysis = await analyze_drawn_route(db, map_id, coords)
    except Exception as e:
        logger.exception("Route edit analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    if not analysis:
        raise HTTPException(status_code=422, detail="Could not analyze route")

    return analysis


@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single route with all its paths."""
    route = await get_route_by_id(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.post("", response_model=RouteResponse)
async def create_new_route(
    route: RouteCreate,
    map_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Create a new route (optionally with initial paths)."""
    return await create_route(db, route, map_id)


@router.post("/plan", response_model=RouteResponse)
async def plan_new_route(
    route: RouteCreate,
    map_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Plan a route: runs the planner first, only saves to DB on success.
    """
    # 1. Run the planner (no DB writes yet)
    start_coords = route.start_geom.coordinates
    end_coords = route.end_geom.coordinates

    # Extract and validate planning preferences from attrs
    attrs = route.attrs or {}
    preferences = RoutePreferences(
        slope_weight=attrs.get("slope_weight", 1.0),
        threat_weight=attrs.get("threat_weight", 1.0),
        concealment_weight=attrs.get("concealment_weight", 0.0),
        max_slope_pct=attrs.get("max_slope_pct", 58.0),
        preferred_terrain=attrs.get("preferred_terrain", []),
        avoid_terrain=attrs.get("avoid_terrain", []),
        rate_of_advance_mph=float(attrs.get("rate_of_advance", 0) or 0),
        weather_weight=float(attrs.get("weather_weight", 1.0)),
        force_type=str(attrs.get("force_type", "mechanized")),
    )

    # Validate weights
    for name, val in [("slope_weight", preferences.slope_weight),
                      ("threat_weight", preferences.threat_weight),
                      ("concealment_weight", preferences.concealment_weight)]:
        if val < 0:
            raise HTTPException(status_code=422, detail=f"{name} must be non-negative")
    if preferences.max_slope_pct <= 0:
        raise HTTPException(status_code=422, detail="max_slope_pct must be positive")

    # Validate terrain names
    valid_terrain = {v for v in LAND_COVER_CLASSES.values() if v != "no_data"}
    for t in preferences.preferred_terrain:
        if t not in valid_terrain:
            raise HTTPException(status_code=422, detail=f"Unknown terrain type in preferred_terrain: '{t}'. Valid: {sorted(valid_terrain)}")
    for t in preferences.avoid_terrain:
        if t not in valid_terrain:
            raise HTTPException(status_code=422, detail=f"Unknown terrain type in avoid_terrain: '{t}'. Valid: {sorted(valid_terrain)}")
    overlap = set(preferences.preferred_terrain) & set(preferences.avoid_terrain)
    if overlap:
        raise HTTPException(status_code=422, detail=f"Terrain types cannot be both preferred and avoided: {overlap}")

    request = PlanRequest(
        start_lat=start_coords[1],
        start_lon=start_coords[0],
        end_lat=end_coords[1],
        end_lon=end_coords[0],
        route_mode=route.route_mode.value,
        map_id=map_id,
        preferences=preferences,
    )

    logger.info(f"Planning route in {route.route_mode.value} mode")

    try:
        path_results, diagnostic = await plan_routes(db, request)
    except Exception as e:
        logger.exception("Route planning failed")
        raise HTTPException(status_code=500, detail=f"Route planning failed: {str(e)}")

    if not path_results:
        message = f"No {route.route_mode.value.replace('_', ' ')} route found between these points."
        detail: dict = {"message": message}
        if diagnostic:
            detail["diagnostic"] = {
                "reachable_from_start": diagnostic.reachable_from_start,
                "total_tiles": diagnostic.total_tiles,
                "blocking_counts": diagnostic.blocking_counts,
                "frontier_counts": diagnostic.frontier_counts,
                "impassable_terrain_types": diagnostic.impassable_terrain_types,
                "suggestions": diagnostic.suggestions,
            }
        raise HTTPException(status_code=422, detail=detail)

    # 2. Success — save route + paths to DB
    saved_route = await create_route(db, route, map_id)
    await update_route(db, saved_route.id, RouteUpdate(status=RouteStatus.COMPLETED))

    for pr in path_results:
        await add_path_to_route(db, saved_route.id, RoutePathCreate(
            rank=pr.rank,
            label=pr.label,
            geom=GeoJSON(type="LineString", coordinates=pr.coords),
            selected=1 if pr.rank == 1 else 0,
            analysis=pr.analysis,
        ))

    return await get_route_by_id(db, saved_route.id)


@router.put("/{route_id}", response_model=RouteResponse)
async def update_existing_route(
    route_id: UUID,
    route_data: RouteUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update route metadata (start, end, mode, etc.)."""
    route = await update_route(db, route_id, route_data)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


@router.delete("/{route_id}")
async def delete_existing_route(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a route and all its paths."""
    success = await delete_route(db, route_id)
    if not success:
        raise HTTPException(status_code=404, detail="Route not found")
    return {"status": "deleted", "id": str(route_id)}


# ---------------------------------------------------------------------------
# RoutePath endpoints
# ---------------------------------------------------------------------------

@router.get("/{route_id}/paths", response_model=List[RoutePathResponse])
async def list_route_paths(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all paths for a route."""
    route = await get_route_by_id(db, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return route.paths


@router.post("/{route_id}/paths", response_model=RoutePathResponse)
async def add_new_path(
    route_id: UUID,
    path: RoutePathCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new alternative path to an existing route."""
    result = await add_path_to_route(db, route_id, path)
    if not result:
        raise HTTPException(status_code=404, detail="Route not found")
    return result


@router.put("/{route_id}/paths/{path_id}", response_model=RoutePathResponse)
async def update_existing_path(
    route_id: UUID,
    path_id: UUID,
    path_data: RoutePathUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a route path (geometry, analysis, etc.)."""
    path = await update_path(db, path_id, path_data)
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    return path


@router.post("/{route_id}/paths/{path_id}/select")
async def select_route_path(
    route_id: UUID,
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Select a path as the chosen route (deselects all others)."""
    success = await select_path(db, route_id, path_id)
    if not success:
        raise HTTPException(status_code=404, detail="Route or path not found")
    return {"status": "selected", "route_id": str(route_id), "path_id": str(path_id)}


@router.delete("/{route_id}/paths/{path_id}")
async def delete_existing_path(
    route_id: UUID,
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single path from a route."""
    success = await delete_path(db, path_id)
    if not success:
        raise HTTPException(status_code=404, detail="Path not found")
    return {"status": "deleted", "id": str(path_id)}

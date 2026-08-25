"""Route planner orchestrator. Wires all modules together."""

import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.geo_utils import haversine
from .models import (
    Node, TileNode, PlanRequest, PathResult, NoPathDiagnostic,
    METERS_PER_MILE, TILE_SIZE_DEG,
)
from .data_fetch import extract_threats, fetch_viewport_data
from .tile_graph import create_tile_grid, populate_tiles, build_tile_edges, build_bridge_edges
from .road_graph import build_road_graph
from .search import astar, unified_neighbors, unified_heuristic, find_nearest_road_node, find_nearest_tile_node
from .geometry import collect_path_geometry
from .analysis import analyze_route, analyze_route_with_weather
from .weather import populate_tile_weather

logger = logging.getLogger(__name__)

_DIRECTIONS_8 = [
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
]


def _diagnose_no_path(
    tile_grid, visited: set, prefs=None,
) -> NoPathDiagnostic:
    """Analyse the A* visited set to determine why no path was found.

    Examines blocked tiles at the *frontier* (neighbours of reachable tiles
    that the search could not enter) and classifies them by block reason.
    """
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    total = rows * cols

    reachable_tiles = {n for n in visited if n.kind == "tile"}

    # Block reasons across the whole grid
    blocking_counts: Dict[str, int] = {"nogo_zone": 0, "nogo_line": 0, "slope": 0, "impassable": 0}
    for r in range(rows):
        for c in range(cols):
            for reason in tile_grid[r][c].block_reason.reasons:
                blocking_counts[reason] += 1

    # Block reasons at the search frontier — the tiles that actually walled
    # off the search, not every blocked tile in the grid.
    frontier_counts: Dict[str, int] = {"nogo_zone": 0, "nogo_line": 0, "slope": 0, "impassable": 0}
    seen_frontier: set = set()
    for node in reachable_tiles:
        for dr, dc in _DIRECTIONS_8:
            nr, nc = node.row + dr, node.col + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            nb = TileNode("tile", nr, nc)
            if nb not in reachable_tiles and nb not in seen_frontier:
                seen_frontier.add(nb)
                for reason in tile_grid[nr][nc].block_reason.reasons:
                    frontier_counts[reason] += 1

    # Land cover breakdown for impassable frontier tiles
    impassable_terrain_types: Dict[str, int] = {}
    for n in seen_frontier:
        tile = tile_grid[n.row][n.col]
        if tile.block_reason.impassable:
            lc = tile.dominant_land_cover
            impassable_terrain_types[lc] = impassable_terrain_types.get(lc, 0) + 1

    # Build human-readable suggestions (user-facing — percentages, no jargon)
    frontier_total = max(len(seen_frontier), 1)
    suggestions: List[str] = []
    if frontier_counts["slope"] > 0:
        pct = round(frontier_counts["slope"] / frontier_total * 100)
        frontier_slopes = [
            tile_grid[n.row][n.col].max_slope_pct
            for n in seen_frontier
            if tile_grid[n.row][n.col].block_reason.slope
        ]
        if frontier_slopes:
            min_needed = min(frontier_slopes)
            current = prefs.max_slope_pct if prefs else 58
            suggestions.append(
                f"{pct}% of the boundary blocked by slope — "
                f"raising max slope from {current:.0f}% to >{min_needed:.0f}% "
                f"would open the nearest path"
            )
    if frontier_counts["nogo_zone"] > 0:
        pct = round(frontier_counts["nogo_zone"] / frontier_total * 100)
        suggestions.append(
            f"{pct}% of the boundary blocked by no-go zones"
        )
    if frontier_counts["nogo_line"] > 0:
        pct = round(frontier_counts["nogo_line"] / frontier_total * 100)
        suggestions.append(
            f"{pct}% of the boundary blocked by no-go lines"
        )
    if frontier_counts["impassable"] > 0:
        pct = round(frontier_counts["impassable"] / frontier_total * 100)
        lc_detail = ", ".join(name for name, _ in
                              sorted(impassable_terrain_types.items(), key=lambda x: -x[1]))
        suggestions.append(
            f"{pct}% of the boundary has impassable terrain: {lc_detail}"
        )
    if not suggestions:
        suggestions.append(
            "No obstacles detected at the boundary — start or goal may be isolated "
            "or the search area may be too small"
        )

    return NoPathDiagnostic(
        reachable_from_start=len(reachable_tiles),
        total_tiles=total,
        blocking_counts=blocking_counts,
        frontier_counts=frontier_counts,
        impassable_terrain_types=impassable_terrain_types,
        suggestions=suggestions,
    )


async def plan_routes(
    db: AsyncSession, request: PlanRequest,
) -> Tuple[List[PathResult], Optional[NoPathDiagnostic]]:
    """Plan a route.

    Returns ``(results, None)`` on success or ``([], diagnostic)`` when no
    path can be found.
    """
    mode = request.route_mode
    logger.info(f"Route planner [{mode}]: ({request.start_lat:.4f}, {request.start_lon:.4f}) -> ({request.end_lat:.4f}, {request.end_lon:.4f})")

    # Bbox with buffer
    straight = haversine(request.start_lat, request.start_lon, request.end_lat, request.end_lon)
    straight_miles = straight / METERS_PER_MILE

    # LONG on-road legs route over the planet-tile road hierarchy
    # (tile_router): coarse tiles carry only the through network, so a
    # corridor query touches dozens of tiles, not a continental Overpass
    # fetch — the dense-graph engine below loads the FULL bbox road set
    # and is for the tactical ranges it was built for (it took the
    # staging box down when handed a corridor leg). Falls open to a
    # no-path diagnostic, never to the dense engine, above its range.
    _TILE_ROUTER_KM = 40.0
    if mode == "on_road" and straight / 1000.0 > _TILE_ROUTER_KM:
        from .tile_router import route_on_road_hierarchical
        coords = await route_on_road_hierarchical(
            request.start_lat, request.start_lon,
            request.end_lat, request.end_lon)
        if coords:
            return [PathResult(
                rank=1, label="on_road (corridor)", coords=list(coords),
                analysis={"engine": "tile_hierarchy",
                          "straight_km": round(straight / 1000.0, 1)},
            )], None
        return [], NoPathDiagnostic(
            reachable_from_start=0, total_tiles=0,
            blocking_counts={}, frontier_counts={},
            impassable_terrain_types={},
            suggestions=[
                f"no corridor road path found for a "
                f"{straight / 1000.0:.0f} km on_road leg; the major-road "
                "network may be disconnected across this corridor",
            ])
    MAX_ROUTE_MILES = 500
    if straight_miles > MAX_ROUTE_MILES:
        logger.error(f"Route distance {straight_miles:.0f} mi exceeds {MAX_ROUTE_MILES} mi limit")
        raise ValueError(
            f"Route too long: {straight_miles:.0f} miles straight-line distance "
            f"exceeds the {MAX_ROUTE_MILES}-mile limit. Check that coordinates are correct."
        )
    buf = max(TILE_SIZE_DEG * 3, straight / 111000 * 0.4)
    bbox = (
        min(request.start_lat, request.end_lat) - buf,
        min(request.start_lon, request.end_lon) - buf,
        max(request.start_lat, request.end_lat) + buf,
        max(request.start_lon, request.end_lon) + buf,
    )

    # 1. Fetch data
    tile_grid = create_tile_grid(bbox)
    threats, no_go, no_go_lines = await extract_threats(db, request.map_id, bbox)
    viewport_data = await fetch_viewport_data(bbox, tile_grid, str(request.map_id), mode)
    logger.info(f"Data: {len(viewport_data.roads)} roads, {len(viewport_data.sample_coords)} terrain samples")

    # 2. Populate tiles with terrain
    prefs = request.preferences
    tile_grid = populate_tiles(tile_grid, viewport_data, threats, no_go, prefs, no_go_lines)

    # 2b. Populate tiles with weather (time-aware: uses straight-line distance for ETA)
    if mode in ("off_road", "mixed"):
        await populate_tile_weather(
            tile_grid,
            start_lat=request.start_lat,
            start_lon=request.start_lon,
            rate_of_advance_mph=prefs.rate_of_advance_mph,
        )

    # 3. Build graphs
    road_adj: Dict[Node, List[Tuple[Node, float]]] = {}
    draw_data: Dict[Tuple[Node, Node], List[Tuple[float, float]]] = {}
    node_pos: Dict[Node, Tuple[float, float]] = {}

    if mode in ("on_road", "mixed") and viewport_data.roads:
        road_adj, draw_data, node_pos = build_road_graph(viewport_data.roads, threats, no_go, prefs, no_go_lines)

    tile_adj = build_tile_edges(tile_grid, prefs) if mode in ("off_road", "mixed") else {}
    bridge_adj = build_bridge_edges(node_pos, tile_grid) if mode == "mixed" and node_pos else {}

    # 4. Pick start/end nodes
    if mode == "on_road":
        if not node_pos:
            logger.warning("No roads found in the search area")
            return [], NoPathDiagnostic(
                reachable_from_start=0, total_tiles=0,
                blocking_counts={}, frontier_counts={},
                impassable_terrain_types={},
                suggestions=["No roads found in this area — try selecting points closer to roads, or switch to off-road or mixed mode"],
            )
        start_node = find_nearest_road_node(request.start_lat, request.start_lon, node_pos)
        goal_node = find_nearest_road_node(request.end_lat, request.end_lon, node_pos)
    elif mode == "off_road":
        start_node = find_nearest_tile_node(request.start_lat, request.start_lon, tile_grid, bbox)
        goal_node = find_nearest_tile_node(request.end_lat, request.end_lon, tile_grid, bbox)
    else:  # mixed
        start_node = find_nearest_tile_node(request.start_lat, request.start_lon, tile_grid, bbox)
        goal_node = find_nearest_tile_node(request.end_lat, request.end_lon, tile_grid, bbox)

    if not start_node or not goal_node or start_node == goal_node:
        suggestions = []
        if mode == "on_road":
            suggestions.append("No roads found in this area — try selecting points closer to roads, or switch to off-road or mixed mode")
        return [], NoPathDiagnostic(
            reachable_from_start=0, total_tiles=0,
            blocking_counts={}, frontier_counts={},
            impassable_terrain_types={},
            suggestions=suggestions,
        )

    # 5. Run A*
    neighbors_fn = unified_neighbors(road_adj, tile_adj, bridge_adj, mode)
    heuristic_fn = unified_heuristic(request.end_lat, request.end_lon, node_pos, tile_grid, prefs)

    path, visited = astar(start_node, goal_node, neighbors_fn, heuristic_fn)
    if not path:
        if mode == "on_road":
            # On-road: diagnose from road graph, not tile grid
            reachable_road = {n for n in (visited or set()) if n.kind == "road"}
            total_road = len(node_pos)
            reach_pct = round(len(reachable_road) / max(total_road, 1) * 100)
            suggestions = []
            if reach_pct < 30:
                suggestions.append(
                    f"Only {reach_pct}% of the road network was reachable from the start — "
                    "the start point may be on an isolated road segment"
                )
            else:
                suggestions.append(
                    f"Reached {reach_pct}% of the road network but the destination is not connected — "
                    "try switching to mixed mode to bridge gaps off-road"
                )
            diag = NoPathDiagnostic(
                reachable_from_start=len(reachable_road),
                total_tiles=total_road,
                blocking_counts={}, frontier_counts={},
                impassable_terrain_types={},
                suggestions=suggestions,
            )
        else:
            diag = _diagnose_no_path(tile_grid, visited or set(), prefs)
        logger.warning(f"No path found. Reachable {diag.reachable_from_start}/{diag.total_tiles}. "
                       f"Frontier blocks: {diag.frontier_counts}")
        return [], diag

    # 6. Geometry + analysis (includes weather when OWM_API_KEY is set)
    coords = collect_path_geometry(path, draw_data, node_pos, tile_grid,
                                   request.start_lat, request.start_lon,
                                   request.end_lat, request.end_lon)
    analysis = await analyze_route_with_weather(
        tile_grid, coords, threats, mode,
        rate_of_advance_mph=prefs.rate_of_advance_mph,
        force_type=prefs.force_type,
        path=path,
        roads=viewport_data.roads,
    )

    logger.info(f"Route: {analysis.get('distance_mi', '?')} mi, {len(path)} nodes")
    return [PathResult(rank=1, label="Route", coords=coords, analysis=analysis)], None


async def analyze_drawn_route(db: AsyncSession, map_id, coords: List[Tuple[float, float]]) -> dict:
    """
    Analyze a user-drawn or user-edited route.
    Takes raw (lon, lat) coordinates, builds a tile grid around them,
    fetches terrain data, and runs off-road analysis.
    No pathfinding — the geometry is taken as-is from the user's drawing.
    """
    if not coords or len(coords) < 2:
        return {}

    # Compute bbox from the coordinates with buffer
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    buf = TILE_SIZE_DEG * 2
    bbox = (
        min(lats) - buf,
        min(lons) - buf,
        max(lats) + buf,
        max(lons) + buf,
    )

    logger.info(f"Analyze drawn route: {len(coords)} coords, bbox {bbox}")

    # 1. Build tile grid and fetch terrain data (off-road path — no roads needed)
    tile_grid = create_tile_grid(bbox)
    threats, no_go, _no_go_lines = await extract_threats(db, map_id, bbox)
    viewport_data = await fetch_viewport_data(bbox, tile_grid, str(map_id), "off_road")

    # 2. Populate tiles with terrain properties
    tile_grid = populate_tiles(tile_grid, viewport_data, threats, no_go)

    # 3. Run analysis on the user-provided coordinates (includes weather)
    analysis = await analyze_route_with_weather(tile_grid, coords, threats, "off_road")

    logger.info(f"Drawn route analysis: {analysis.get('distance_mi', '?')} mi")
    return analysis

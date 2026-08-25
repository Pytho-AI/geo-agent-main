"""Generic A*, unified neighbors/heuristic, and snap helpers."""

import heapq
from typing import Callable, Dict, List, Optional, Tuple

from app.services.knowledge.geo_utils import haversine
from .models import (
    Node, RoadNode, TileNode, MacroTile,
    TILE_SIZE_DEG,
)
from .cost import unified_heuristic  # noqa: F401 — re-exported for planner


def astar(start, goal, neighbors_fn, heuristic_fn):
    """Generic A*. Works with any hashable node type.

    Returns ``(path, None)`` on success or ``(None, visited_set)`` when no
    path exists.  The visited set lets callers diagnose *why* the search
    failed (e.g. which blocked tiles walled off the goal).
    """
    open_set = [(0.0, start)]
    came_from = {}
    g = {start: 0.0}
    visited = set()
    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal:
            path = [cur]
            while cur in came_from:
                cur = came_from[cur]
                path.append(cur)
            path.reverse()
            return path, None
        if cur in visited:
            continue
        visited.add(cur)
        for nb, cost in neighbors_fn(cur):
            if nb in visited or cost == float("inf"):
                continue
            tg = g[cur] + cost
            if tg < g.get(nb, float("inf")):
                came_from[nb] = cur
                g[nb] = tg
                heapq.heappush(open_set, (tg + heuristic_fn(nb), nb))
    return None, visited


def unified_neighbors(road_adj, tile_adj, bridge_adj, mode):
    """Returns a neighbors function that dispatches by mode and node type."""
    def neighbors(node):
        result = []
        if node.kind == "road" and mode in ("on_road", "mixed"):
            result.extend(road_adj.get(node, []))
        if node.kind == "tile" and mode in ("off_road", "mixed"):
            result.extend(tile_adj.get(node, []))
        if mode == "mixed":
            result.extend(bridge_adj.get(node, []))
        return result
    return neighbors


def find_nearest_road_node(lat, lon, node_pos):
    """Find nearest road intersection node to a lat/lon."""
    best = None
    best_d = float("inf")
    for node, (nlon, nlat) in node_pos.items():
        d = haversine(lat, lon, nlat, nlon)
        if d < best_d:
            best_d = d
            best = node
    return best


def find_nearest_tile_node(lat, lon, tile_grid, bbox):
    """Find the tile node containing a lat/lon."""
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    r = int((lat - bbox[0]) / TILE_SIZE_DEG)
    c = int((lon - bbox[1]) / TILE_SIZE_DEG)
    r = max(0, min(rows - 1, r))
    c = max(0, min(cols - 1, c))
    return TileNode("tile", r, c)

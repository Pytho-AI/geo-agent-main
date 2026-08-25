"""Unified cost functions for road and tile edges."""

from typing import List, Optional, Tuple

from app.services.knowledge.geo_utils import haversine
from .models import (
    ThreatZone, NoGoZone, NoGoLine, MacroTile, RoutePreferences,
    TILE_SIZE_MI, METERS_PER_MILE,
)

# Minimum cost-per-mile for each edge type (zero threat, best terrain).
# Used by the A* heuristic to stay admissible.
MIN_ROAD_COST_PER_MI = 1.0   # edge_cost(dist, threat=0) = dist * 1.0
MIN_TILE_COST_PER_MI = TILE_SIZE_MI * 1.0  # best trafficability (1.0), flat (0% slope)


def point_in_polygon(px, py, polygon):
    """Ray casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def in_nogo(lon, lat, no_go: List[NoGoZone]) -> bool:
    """Check if a point falls inside any no-go polygon."""
    return any(point_in_polygon(lon, lat, z.coords) for z in no_go)


def _ccw(ax, ay, bx, by, cx, cy) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def segments_cross(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    """Return True if segment AB properly crosses segment CD."""
    d1 = _ccw(cx, cy, dx, dy, ax, ay)
    d2 = _ccw(cx, cy, dx, dy, bx, by)
    d3 = _ccw(ax, ay, bx, by, cx, cy)
    d4 = _ccw(ax, ay, bx, by, dx, dy)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def crosses_nogo_line(ax, ay, bx, by, no_go_lines: List[NoGoLine]) -> bool:
    """Return True if segment (ax,ay)-(bx,by) crosses any no-go line."""
    for line in no_go_lines:
        for i in range(len(line.coords) - 1):
            cx, cy = line.coords[i]
            dx, dy = line.coords[i + 1]
            if segments_cross(ax, ay, bx, by, cx, cy, dx, dy):
                return True
    return False


def threat_cost_at(lat, lon, threats: List[ThreatZone]) -> float:
    """Threat cost at a point. Linear falloff from hostile entity positions."""
    cost = 0.0
    for t in threats:
        d = haversine(lat, lon, t.lat, t.lon)
        if d < t.radius_m:
            cost += t.weight * (1.0 - d / t.radius_m)
    return cost


def edge_cost(base_dist: float, threat: float, blocked: bool) -> float:
    """
    Unified cost formula for both road and tile edges.
      1. If blocked (no-go or impassable) -> inf
      2. cost = base_dist * (1 + threat)
    """
    if blocked:
        return float("inf")
    return base_dist * (1.0 + threat)


def tile_cost(tile: MacroTile, preferences: Optional[RoutePreferences] = None) -> float:
    """Off-road tile cost. Reads pre-computed fields from populate_tiles."""
    slope_w = preferences.slope_weight if preferences else 1.0
    threat_w = preferences.threat_weight if preferences else 1.0
    conceal_w = preferences.concealment_weight if preferences else 0.0
    weather_w = preferences.weather_weight if preferences else 1.0

    base = TILE_SIZE_MI * tile.worst_trafficability * tile.terrain_cost_modifier
    base += slope_w * (tile.max_slope_pct / 10) ** 2

    # Weather cost: apply modifier scaled by weather_weight
    # modifier is >= 1.0 (1.0 = clear, 3.0+ = severe storm)
    if weather_w > 0 and tile.weather_cost_modifier > 1.0:
        # Blend: at weather_weight=1.0 use full modifier, at 0.5 use half the penalty
        weather_penalty = (tile.weather_cost_modifier - 1.0) * weather_w
        base *= 1.0 + weather_penalty

    # Concealment reward: reduce cost for concealed tiles
    if conceal_w > 0:
        discount = conceal_w * (tile.concealment_pct / 100.0) * TILE_SIZE_MI
        base = max(base - discount, TILE_SIZE_MI * 0.1)

    return edge_cost(base, threat_w * tile.worst_threat, tile.blocked)


def _min_tile_cost(preferences: Optional[RoutePreferences] = None) -> float:
    """Admissible minimum tile cost given preferences (best-case scenario)."""
    terrain_mod = 0.5 if (preferences and preferences.preferred_terrain) else 1.0
    base = TILE_SIZE_MI * 1.0 * terrain_mod  # best trafficability, best terrain modifier, flat
    conceal_w = preferences.concealment_weight if preferences else 0.0
    if conceal_w > 0:
        base = max(base - conceal_w * TILE_SIZE_MI, TILE_SIZE_MI * 0.1)
    return base


def unified_heuristic(goal_lat, goal_lon, node_pos, tile_grid,
                      preferences: Optional[RoutePreferences] = None):
    """
    A* heuristic for both road and tile nodes.
    Admissible: uses minimum cost-per-mile (zero threat, best terrain).
    """
    min_tile = _min_tile_cost(preferences)

    def h(node):
        if node.kind == "road":
            pos = node_pos.get(node)
            if pos:
                return haversine(pos[1], pos[0], goal_lat, goal_lon) / METERS_PER_MILE * MIN_ROAD_COST_PER_MI
        elif node.kind == "tile":
            r, c = node.row, node.col
            if r < len(tile_grid) and c < len(tile_grid[0]):
                t = tile_grid[r][c]
                return haversine(t.center_lat, t.center_lon, goal_lat, goal_lon) / METERS_PER_MILE * min_tile
        return 0.0
    return h


def road_edge_cost(
    dist_mi: float,
    segment_coords: List[Tuple[float, float]],
    threats: List[ThreatZone],
    no_go: List[NoGoZone],
    threat_weight: float = 1.0,
    no_go_lines: List[NoGoLine] = None,
) -> float:
    """On-road edge cost. Checks every point along the road for no-go/threats."""
    worst_threat = 0.0
    blocked = False

    for lon, lat in segment_coords:
        if not blocked and no_go and in_nogo(lon, lat, no_go):
            blocked = True
        if threats:
            worst_threat = max(worst_threat, threat_cost_at(lat, lon, threats))

    if not blocked and no_go_lines:
        for i in range(len(segment_coords) - 1):
            if crosses_nogo_line(
                segment_coords[i][0], segment_coords[i][1],
                segment_coords[i + 1][0], segment_coords[i + 1][1],
                no_go_lines,
            ):
                blocked = True
                break

    return edge_cost(dist_mi, threat_weight * worst_threat, blocked)

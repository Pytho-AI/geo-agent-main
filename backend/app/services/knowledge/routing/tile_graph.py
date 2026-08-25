"""Tile grid creation, population, tile edges, and bridge edges."""

import math
import logging
from typing import Dict, List, Tuple

from app.services.knowledge.geo_utils import haversine
from app.services.knowledge.terrain import calculate_slope
from .models import (
    Node, RoadNode, TileNode, MacroTile, BlockReason,
    ThreatZone, NoGoZone, NoGoLine, ViewportData,
    RoutePreferences,
    TILE_SIZE_MI, TILE_SIZE_DEG, SAMPLES_PER_TILE_SIDE,
    CONCEALMENT_SCORE, TRAFFICABILITY_COST, DEFAULT_MAX_SLOPE_PCT,
)
from .cost import threat_cost_at, in_nogo, crosses_nogo_line, tile_cost

logger = logging.getLogger(__name__)

_DIRECTIONS_8 = [
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
]
_DIAG = math.sqrt(2)


def create_tile_grid(bbox):
    """Divide a bbox into 1mi x 1mi tiles."""
    south, west, north, east = bbox
    rows = max(1, math.ceil((north - south) / TILE_SIZE_DEG))
    cols = max(1, math.ceil((east - west) / TILE_SIZE_DEG))
    grid = []
    for r in range(rows):
        row = []
        for c in range(cols):
            t_s = south + r * TILE_SIZE_DEG
            t_w = west + c * TILE_SIZE_DEG
            row.append(MacroTile(row=r, col=c, south=t_s, west=t_w,
                                 north=min(t_s + TILE_SIZE_DEG, north),
                                 east=min(t_w + TILE_SIZE_DEG, east)))
        grid.append(row)
    return grid


def populate_tiles(tile_grid, data: ViewportData, threats, no_go,
                    preferences: RoutePreferences = None, no_go_lines=None):
    """
    Compute all tile properties from the same sample points:
    elevation, slope, land cover, trafficability, concealment, threat, no-go.
    """
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    n_side = SAMPLES_PER_TILE_SIDE
    max_slope_threshold = preferences.max_slope_pct if preferences else DEFAULT_MAX_SLOPE_PCT
    pref_set = set(preferences.preferred_terrain) if preferences else set()
    avoid_set = set(preferences.avoid_terrain) if preferences else set()

    tile_samples: Dict[Tuple[int, int], List[int]] = {}
    for idx, rc in enumerate(data.sample_tile_map):
        tile_samples.setdefault(rc, []).append(idx)

    for r in range(rows):
        for c in range(cols):
            tile = tile_grid[r][c]
            indices = tile_samples.get((r, c), [])
            if not indices:
                continue

            tile_elevs = [data.elevations[i] for i in indices]
            tile_lcs = [data.land_covers[i] for i in indices]
            tile_pts = [data.sample_coords[i] for i in indices]

            lc_counts: Dict[str, int] = {}
            conceal_total = 0.0
            traff_scores = []
            terrain_modifiers = []
            valid_lc = 0
            worst_threat = 0.0
            hit_nogo_zone = False

            for i, (lat, lon) in enumerate(tile_pts):
                if threats:
                    worst_threat = max(worst_threat, threat_cost_at(lat, lon, threats))
                if not hit_nogo_zone and no_go and in_nogo(lon, lat, no_go):
                    hit_nogo_zone = True

                lc = tile_lcs[i]
                if lc is not None and lc.land_cover_code is not None:
                    valid_lc += 1
                    lc_counts[lc.land_cover_display] = lc_counts.get(lc.land_cover_display, 0) + 1
                    conceal_total += CONCEALMENT_SCORE.get(lc.land_cover_code, 0.0)
                    traff_scores.append(TRAFFICABILITY_COST.get(lc.land_cover_code, 1.0))

                    # Terrain preference modifier
                    if lc.land_cover_name in pref_set:
                        terrain_modifiers.append(0.5)
                    elif lc.land_cover_name in avoid_set:
                        terrain_modifiers.append(2.0)
                    else:
                        terrain_modifiers.append(1.0)

            valid_elevs = [e for e in tile_elevs if e is not None]
            if valid_elevs:
                tile.avg_elevation_ft = round(sum(valid_elevs) / len(valid_elevs) * 3.28084, 0)

            max_slope = 0.0
            for i in range(len(tile_pts)):
                row_i, col_i = divmod(i, n_side)
                for j in ([i + 1] if col_i < n_side - 1 else []) + ([i + n_side] if row_i < n_side - 1 else []):
                    if tile_elevs[i] is not None and tile_elevs[j] is not None:
                        d = haversine(tile_pts[i][0], tile_pts[i][1], tile_pts[j][0], tile_pts[j][1])
                        if d > 0:
                            max_slope = max(max_slope, abs(calculate_slope(tile_elevs[i], tile_elevs[j], d)))
            tile.max_slope_pct = round(max_slope, 1)

            total_lc = max(valid_lc, 1)
            tile.concealment_pct = round(conceal_total / total_lc * 100, 1)
            if lc_counts:
                tile.dominant_land_cover = max(lc_counts, key=lc_counts.get)
            tile.worst_trafficability = max(traff_scores) if traff_scores else 1.0

            if terrain_modifiers:
                tile.terrain_cost_modifier = sum(terrain_modifiers) / len(terrain_modifiers)

            tile.worst_threat = worst_threat
            # Check if any no-go line crosses through the tile bounding box
            hit_nogo_line = False
            if no_go_lines:
                edges = [
                    (tile.west, tile.south, tile.east, tile.south),  # bottom
                    (tile.east, tile.south, tile.east, tile.north),  # right
                    (tile.east, tile.north, tile.west, tile.north),  # top
                    (tile.west, tile.north, tile.west, tile.south),  # left
                ]
                for ax, ay, bx, by in edges:
                    if crosses_nogo_line(ax, ay, bx, by, no_go_lines):
                        hit_nogo_line = True
                        break
            tile.block_reason = BlockReason(
                nogo_zone=hit_nogo_zone,
                nogo_line=hit_nogo_line,
                slope=tile.max_slope_pct > max_slope_threshold,
                impassable=tile.worst_trafficability >= float("inf"),
            )

    return tile_grid


def build_tile_edges(grid, preferences: RoutePreferences = None) -> Dict[Node, List[Tuple[Node, float]]]:
    """Build tile-to-tile off-road edges (8 directions)."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    adj: Dict[Node, List[Tuple[Node, float]]] = {}

    # Pre-compute tile costs so each tile is evaluated once instead of ~9x
    costs = [[tile_cost(grid[r][c], preferences) for c in range(cols)] for r in range(rows)]

    for r in range(rows):
        for c in range(cols):
            cost_a = costs[r][c]
            if cost_a == float("inf"):
                adj[TileNode("tile", r, c)] = []
                continue
            edges = []
            for dr, dc in _DIRECTIONS_8:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                cost_b = costs[nr][nc]
                if cost_b < float("inf"):
                    dist_mult = _DIAG if (dr != 0 and dc != 0) else 1.0
                    edges.append((TileNode("tile", nr, nc), (cost_a + cost_b) / 2 * dist_mult))
            adj[TileNode("tile", r, c)] = edges

    return adj


def build_bridge_edges(node_pos, tile_grid) -> Dict[Node, List[Tuple[Node, float]]]:
    """Connect road nodes to the tile they fall in (and vice versa)."""
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    adj: Dict[Node, List[Tuple[Node, float]]] = {}
    south0 = tile_grid[0][0].south
    west0 = tile_grid[0][0].west

    for road_node, (lon, lat) in node_pos.items():
        r = int((lat - south0) / TILE_SIZE_DEG)
        c = int((lon - west0) / TILE_SIZE_DEG)
        r = max(0, min(rows - 1, r))
        c = max(0, min(cols - 1, c))

        tile_node = TileNode("tile", r, c)
        adj.setdefault(road_node, []).append((tile_node, 0.1))
        adj.setdefault(tile_node, []).append((road_node, 0.1))

    return adj

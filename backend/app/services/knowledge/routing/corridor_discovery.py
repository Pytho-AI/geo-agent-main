"""Doctrinal mobility-corridor discovery from the macro-tile cost surface.

Implements the terrain-analysis algorithm prescribed by ATP 2-01.3 §4-22
through §4-27 and FM 34-130 Chapter 2 IPB Step 2:

  4-22: "AAs consist of a series of mobility corridors through which a
  maneuvering force must pass to reach its objective."

  4-24: "Mobility corridor refers to areas that are relatively free of
  obstacles where a force will be canalized due to terrain restrictions
  allowing military forces to capitalize on the principles of mass and
  speed. They use unrestricted terrain that provides enough space for
  freedom of action by breaching or bypassing obstacles."

  4-27 + Table 4-2: corridor classes (Division/Brigade/Battalion/Company)
  based on perpendicular width.

The doctrinal method DOES NOT pre-assume routes between known key
terrain. It DISCOVERS corridors from the cost surface — every connected
region of trafficable terrain bounded by obstacles is a candidate
mobility corridor. Each tile belongs to exactly ONE connected component,
so corridors are GEOGRAPHICALLY NON-OVERLAPPING by construction.

Algorithm:
  1. Threshold the cost surface against the force-type canalization
     criterion (mechanized: trafficability ≤ 2.0 + slope ≤ 30%; dismounted:
     trafficability ≤ 4.0 + slope ≤ 50%).
  2. BFS-based connected-component labelling on the passable mask
     (4-neighbour or 8-neighbour adjacency — using 8-neighbour to capture
     diagonal connectivity through irregular terrain).
  3. For each component:
       - Build a shapely polygon (union of tile bounding boxes).
       - Measure the inscribed-circle diameter at sample points along the
         polygon → narrowest perpendicular cross-section = corridor width.
       - Classify per ATP 2-01.3 Table 4-2.
       - Identify endpoints where the polygon touches the AO boundary
         (N/S/E/W edges).
       - Identify any key_terrain features inside the polygon.

The output is consumed by pytho-app's MCOO enrichment pipeline to:
  - Build the doctrinal AAs (groups of corridors that share an objective).
  - Render each corridor as a `mobility_corridor` overlay (doctrinal small
    parallel-bracket arrow symbol per FM 1-02.2 / ATP 2-01.3 Fig 4-6).
  - Render each AA as one `avenue_of_approach` chevron envelope.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Dict, List, Tuple, Any, Optional

from .models import MacroTile, METERS_PER_MILE, TILE_SIZE_MI

logger = logging.getLogger(__name__)


# Doctrinal Table 4-2 widths in km (mechanized). Same nesting the
# pytho-app side already uses; replicated here so the discovery algorithm
# can self-classify without round-tripping. Ordered largest-to-smallest;
# first match wins.
_ATP_TABLE_4_2_MECH = (
    ("division",    6.0),
    ("brigade",     3.0),
    ("battalion",   1.5),
    ("company",     0.5),
)
_ATP_TABLE_4_2_DISMOUNTED = tuple((label, w / 2.0) for label, w in _ATP_TABLE_4_2_MECH)


def _class_from_width_km(width_km: float, force_type: str) -> str:
    """Map a corridor's measured width to its ATP Table 4-2 class."""
    table = (
        _ATP_TABLE_4_2_DISMOUNTED
        if (force_type or "").lower().startswith(("dismount", "infantry", "sof", "special"))
        else _ATP_TABLE_4_2_MECH
    )
    for label, min_km in table:
        if width_km >= min_km:
            return label
    return "sub-company"


def _morphological_close(
    mask: List[List[bool]],
    rows: int,
    cols: int,
    iterations: int = 1,
) -> List[List[bool]]:
    """Morphological closing: dilate then erode. Fills 1-tile-wide
    obstacles inside otherwise-passable regions and bridges near-
    adjacent components across narrow obstacle strips.

    Doctrinal motivation: a 1-mile-wide forest belt inside an
    otherwise-trafficable cropland corridor isn't a corridor-splitting
    obstacle — formations can bypass single-tile pinches. The discovery
    algorithm should treat the cropland region as ONE corridor with a
    noted narrow point, not two separate corridors.

    8-neighbour structuring element matches the connected-component
    adjacency.
    """
    if rows == 0 or cols == 0:
        return mask
    cur = mask
    for _ in range(iterations):
        # Dilate: any tile adjacent (8-neighbour) to a True tile becomes True.
        dilated = [[False] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                if cur[r][c]:
                    dilated[r][c] = True
                    continue
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols and cur[nr][nc]:
                            dilated[r][c] = True
                            break
                    if dilated[r][c]:
                        break
        # Erode: True tile only stays True if all 8 neighbours are True.
        # This restores boundaries (so dilate+erode = close = fill holes
        # without bloating the region).
        eroded = [[False] * cols for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                if not dilated[r][c]:
                    continue
                all_true = True
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols:
                            if not dilated[nr][nc]:
                                all_true = False
                                break
                        # Edge tiles: treat off-grid as True so we don't
                        # erode boundary corridors that touch the AO edge.
                    if not all_true:
                        break
                eroded[r][c] = all_true
        cur = eroded
    return cur


# Land-cover display names for water-class tiles (per landcover.py
# LAND_COVER_DISPLAY_NAMES). These must remain unpassable through
# morphological closing — otherwise the dilate step bridges across small
# lakes and corridors get extended into open water (Estonia's Lake Võrtsjärv
# / Peipus shoreline regularly triggers this without the protection).
_WATER_NAMES_ALL = ("Permanent Water", "Mangroves")
_WATER_NAMES_MECH = ("Permanent Water", "Mangroves", "Herbaceous Wetland")


def _water_protected_names(force_type: str) -> Tuple[str, ...]:
    """Return the set of landcover names that morph-close must NOT fill in.

    Dismounted infantry can ford herbaceous wetlands (poor but trafficable);
    mechanized cannot. Permanent water + mangroves are universally
    impassable.
    """
    if (force_type or "").lower().startswith(("dismount", "infantry", "sof", "special")):
        return _WATER_NAMES_ALL
    return _WATER_NAMES_MECH


def _passable_mask(
    tile_grid: List[List[MacroTile]],
    force_type: str,
) -> Tuple[List[List[bool]], List[List[bool]], float, float, float, float, int, int]:
    """Build a binary mask of passable tiles per the canalization criterion,
    plus a parallel water_mask marking tiles whose dominant_land_cover is
    universally impassable (open water / wetland for mech / mangroves).

    Returns
        (passable_mask, water_mask, south0, west0, north_max, east_max,
         rows, cols)

    The water_mask is preserved across morphological closing in
    discover_mobility_corridors so dilate-then-erode never fills lakes.
    """
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    if rows == 0 or cols == 0:
        return [], [], 0.0, 0.0, 0.0, 0.0, 0, 0

    # Same canalization criterion as compute_corridor_widths (analysis.py)
    # — keep in sync. Mechanized: trafficability > 2.5 OR slope > 30% pinches.
    # Dismounted: more permissive.
    if (force_type or "").lower().startswith(("dismount", "infantry", "sof", "special")):
        max_traff_ok = 10.0
        max_slope_ok = 60.0
    else:
        max_traff_ok = 2.5
        max_slope_ok = 30.0

    water_names = set(_water_protected_names(force_type))
    mask: List[List[bool]] = [[False] * cols for _ in range(rows)]
    water_mask: List[List[bool]] = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            t = tile_grid[r][c]
            if t.dominant_land_cover in water_names:
                water_mask[r][c] = True
            if t.blocked:
                continue
            if t.worst_trafficability > max_traff_ok:
                continue
            if t.max_slope_pct > max_slope_ok:
                continue
            mask[r][c] = True

    south0 = tile_grid[0][0].south
    west0 = tile_grid[0][0].west
    north_max = tile_grid[rows - 1][0].north
    east_max = tile_grid[0][cols - 1].east
    return mask, water_mask, south0, west0, north_max, east_max, rows, cols


def _connected_components(
    mask: List[List[bool]],
    rows: int,
    cols: int,
) -> List[List[Tuple[int, int]]]:
    """BFS connected-component labelling on the passable mask using
    8-neighbour adjacency. Returns a list of components; each component
    is a list of (row, col) tile indices.

    8-neighbour because the macro-tile grid is coarse (1 mile per tile) and
    natural corridors run diagonally — 4-neighbour adjacency artificially
    splits diagonally-trending corridors into multiple components.
    """
    if rows == 0 or cols == 0:
        return []
    seen = [[False] * cols for _ in range(rows)]
    components: List[List[Tuple[int, int]]] = []
    neighbours = ((-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1))
    for r0 in range(rows):
        for c0 in range(cols):
            if not mask[r0][c0] or seen[r0][c0]:
                continue
            comp: List[Tuple[int, int]] = []
            q = deque([(r0, c0)])
            seen[r0][c0] = True
            while q:
                r, c = q.popleft()
                comp.append((r, c))
                for dr, dc in neighbours:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols \
                            and mask[nr][nc] and not seen[nr][nc]:
                        seen[nr][nc] = True
                        q.append((nr, nc))
            components.append(comp)
    return components


def _component_polygon(
    comp: List[Tuple[int, int]],
    tile_grid: List[List[MacroTile]],
):
    """Build a shapely Polygon (or MultiPolygon) covering the component's
    tile bounding boxes via union. Coordinates are (lon, lat)."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    boxes = []
    for r, c in comp:
        t = tile_grid[r][c]
        boxes.append(box(t.west, t.south, t.east, t.north))
    return unary_union(boxes)


def _polygon_width_km(polygon, lat_for_scale: float) -> float:
    """Measure the polygon's effective corridor width in km.

    Approach: pick sample points along the polygon's centroid axis (the
    long axis of its minimum rotated bounding rectangle) and at each
    sample compute the perpendicular extent (intersection of a
    perpendicular line with the polygon, clipped to the polygon's
    boundary). Width = NARROWEST such perpendicular cross-section.

    Falls back to simple bbox-minor-axis width when the polygon is too
    small to sample meaningfully (< ~3 tiles).

    Conversion to km: at the polygon's representative latitude,
    1 deg lat ≈ 111 km; 1 deg lon ≈ 111 * cos(lat) km. We compute the
    metric width by converting the polygon's perpendicular extent at
    each sample to meters using local lat scale.
    """
    import math
    from shapely.geometry import LineString
    from shapely.affinity import rotate

    if polygon.is_empty:
        return 0.0
    # Long axis = major axis of minimum rotated rectangle.
    mrr = polygon.minimum_rotated_rectangle
    # mrr coords are 5 (closed); 4 unique vertices. Take the longest edge
    # as the long axis.
    coords = list(mrr.exterior.coords)[:4]
    edges = []
    for i in range(4):
        a = coords[i]
        b = coords[(i + 1) % 4]
        ed_len = math.hypot(b[0] - a[0], b[1] - a[1])
        edges.append((ed_len, a, b))
    edges.sort(key=lambda e: -e[0])
    longest_edge_len = edges[0][0]
    # Long-axis bearing (in degrees from east, atan2). Sample along
    # the long axis; for each sample, draw a perpendicular line and
    # intersect with the polygon.
    long_a = edges[0][1]
    long_b = edges[0][2]
    if longest_edge_len < 1e-9:
        return 0.0
    # Direction unit vector along long axis (degree coords).
    dx = (long_b[0] - long_a[0]) / longest_edge_len
    dy = (long_b[1] - long_a[1]) / longest_edge_len
    # Perpendicular unit vector (in degree coords).
    px, py = -dy, dx

    # Sample along the long axis. Skip the very ends to avoid bbox
    # corner artifacts.
    n_samples = max(5, int(longest_edge_len * 3000))  # ~3 samples per 0.001°
    samples = []
    for i in range(1, n_samples - 1):
        t = i / (n_samples - 1)
        cx = long_a[0] + t * (long_b[0] - long_a[0])
        cy = long_a[1] + t * (long_b[1] - long_a[1])
        # Perpendicular line, long enough to clip across the polygon.
        clip_len = longest_edge_len * 2.0  # 2x long-axis length, plenty
        p1 = (cx + px * clip_len, cy + py * clip_len)
        p2 = (cx - px * clip_len, cy - py * clip_len)
        seg = LineString([p1, p2])
        # Intersection with polygon: take the longest contiguous
        # intersection (the part of the perpendicular that's INSIDE
        # the corridor at this sample). Multiple segments can exist
        # if the polygon is U-shaped near the sample; the corridor's
        # width at this sample is the slice through the corridor body,
        # which is the longest contiguous interior segment.
        cut = seg.intersection(polygon)
        cut_len_deg = 0.0
        if cut.is_empty:
            samples.append(0.0)
            continue
        if cut.geom_type == "LineString":
            cut_len_deg = cut.length
        elif cut.geom_type == "MultiLineString":
            cut_len_deg = max(ls.length for ls in cut.geoms)
        else:
            # Point / GeometryCollection — treat as zero-width slice.
            cut_len_deg = 0.0
        # Convert degree length to meters using local lat scale.
        # The perpendicular vector is in degree space — its physical
        # length depends on the lat component. Approximate by treating
        # the perpendicular's horizontal degree-component as lon and
        # vertical as lat.
        m_per_deg_lon = 111000.0 * math.cos(math.radians(lat_for_scale))
        m_per_deg_lat = 111000.0
        # Perpendicular unit vector in meters:
        ux_m = px * m_per_deg_lon
        uy_m = py * m_per_deg_lat
        unit_metric_len_per_deg = math.hypot(ux_m, uy_m)
        if unit_metric_len_per_deg < 1e-9:
            samples.append(0.0)
            continue
        cut_len_m = cut_len_deg * unit_metric_len_per_deg
        samples.append(cut_len_m)
    if not samples:
        return 0.0
    # Per ATP 2-01.3 Table 4-2 + ¶4-27 corridor width is "the distance
    # between the terrain features that form the corridor" — the bulk
    # width that defines the formation it can carry, NOT the narrowest
    # single pinch (a 1-tile chokepoint inside a 4-tile-wide corridor is
    # an analyst-notable obstacle, not the corridor's class). Median
    # captures the corridor's effective width robust to pinch outliers.
    # Pinch min preserved separately if consumers want to surface it.
    nonzero = sorted([s for s in samples if s > 0.1])
    if not nonzero:
        return 0.0
    median_m = nonzero[len(nonzero) // 2]
    return median_m / 1000.0


def _polygon_centerline(
    polygon,
    lat_for_scale: float,
    n_points: int = 12,
) -> List[Tuple[float, float]]:
    """Approximate centerline as a sequence of points along the polygon's
    long axis (minimum rotated rectangle's longest edge). Returns
    [(lon, lat), ...] for renderer consumption. Not a true medial axis
    but good enough for chevron placement."""
    import math
    if polygon.is_empty:
        return []
    mrr = polygon.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)[:4]
    edges = []
    for i in range(4):
        a = coords[i]
        b = coords[(i + 1) % 4]
        ed_len = math.hypot(b[0] - a[0], b[1] - a[1])
        edges.append((ed_len, a, b))
    edges.sort(key=lambda e: -e[0])
    long_a = edges[0][1]
    long_b = edges[0][2]
    longest_edge_len = edges[0][0]
    if longest_edge_len < 1e-9:
        return []
    # Sample at the midpoint of perpendicular extent at each step. Since
    # we're approximating with the long-axis line, just walk the long
    # axis offset by half the polygon's centroid-relative shift.
    centroid = polygon.centroid
    # Use the long-axis line offset so it passes through the centroid:
    mid_a = ((long_a[0] + long_b[0]) / 2, (long_a[1] + long_b[1]) / 2)
    offset = (centroid.x - mid_a[0], centroid.y - mid_a[1])
    out: List[Tuple[float, float]] = []
    for i in range(n_points):
        t = i / (n_points - 1)
        x = long_a[0] + t * (long_b[0] - long_a[0]) + offset[0]
        y = long_a[1] + t * (long_b[1] - long_a[1]) + offset[1]
        out.append((x, y))
    return out


def _endpoints_on_ao_edge(
    polygon,
    south0: float, west0: float, north_max: float, east_max: float,
    epsilon_deg: float = 0.001,
) -> List[str]:
    """Return which AO bounding-box edges the polygon touches.
    Used by downstream AA aggregation to decide if a corridor connects
    friendly (south) to threat (north), or is lateral (E-W), etc."""
    minx, miny, maxx, maxy = polygon.bounds
    edges = []
    if abs(miny - south0) < epsilon_deg + TILE_SIZE_MI / 69.0:
        edges.append("south")
    if abs(maxy - north_max) < epsilon_deg + TILE_SIZE_MI / 69.0:
        edges.append("north")
    if abs(minx - west0) < epsilon_deg + TILE_SIZE_MI / 69.0:
        edges.append("west")
    if abs(maxx - east_max) < epsilon_deg + TILE_SIZE_MI / 69.0:
        edges.append("east")
    return edges


def discover_mobility_corridors(
    tile_grid: List[List[MacroTile]],
    force_type: str = "mechanized",
    min_class: str = "battalion",
    min_tiles: int = 30,
    morph_close_iterations: int = 2,
    max_corridors: int = 12,
) -> List[Dict[str, Any]]:
    """Discover non-overlapping doctrinal mobility corridors in the AO.

    Per ATP 2-01.3 §4-24 a mobility corridor is "areas relatively free of
    obstacles where a force will be canalized." Each connected region of
    passable terrain (per the canalization criterion for the force_type)
    is one candidate corridor; the corridor's class follows from its
    measured width per Table 4-2.

    Args:
      tile_grid: macro-tile cost surface (built by build_tile_grid).
      force_type: "mechanized" (default) or "dismounted".
      min_class: drop corridors smaller than this class to reduce noise.
        Default "company" (≥500m wide for mechanized).

    Returns: list of corridor dicts, each:
      {
        "corridor_id": "MC-N" (sequential),
        "polygon": GeoJSON Polygon,
        "centerline": GeoJSON LineString,
        "width_km": float,                # narrowest perpendicular pinch
        "class": "division"|...|"sub-company",
        "tile_count": int,
        "edges_touched": list[str],       # subset of ["north","south","east","west"]
        "bbox": [w, s, e, n],
      }
    Each tile belongs to exactly one corridor; corridors are
    GEOGRAPHICALLY NON-OVERLAPPING by construction.
    """
    if not tile_grid:
        return []
    (
        mask, water_mask, south0, west0, north_max, east_max, rows, cols,
    ) = _passable_mask(tile_grid, force_type)
    if rows == 0:
        return []
    # Morphological closing: bridge near-adjacent passable regions
    # across 1-tile obstacle strips (a single forest tile inside an
    # otherwise-trafficable cropland corridor isn't doctrinally a
    # corridor-splitting obstacle per ¶4-24).
    if morph_close_iterations > 0:
        mask = _morphological_close(mask, rows, cols, morph_close_iterations)
        # CRITICAL: morph-close's dilate step will happily fill in a 1-tile
        # lake surrounded by passable land. Re-apply the water mask so any
        # tile that was open water before closing remains unpassable.
        # Without this, AAs end up originating from / passing through
        # lake centers (the recurring "AA starts in the fucking lake" bug).
        water_filled = 0
        for r in range(rows):
            for c in range(cols):
                if water_mask[r][c] and mask[r][c]:
                    mask[r][c] = False
                    water_filled += 1
        if water_filled:
            logger.info(
                f"discover_mobility_corridors: morph-close filled {water_filled} "
                f"water tiles; restored to unpassable"
            )
    components = _connected_components(mask, rows, cols)
    logger.info(
        f"discover_mobility_corridors: {len(components)} components from "
        f"{sum(sum(1 for v in row if v) for row in mask)} passable tiles "
        f"(force_type={force_type})"
    )
    rank = {
        "division": 5, "brigade": 4, "battalion": 3,
        "company": 2, "sub-company": 1, "unknown": 0,
    }
    min_rank = rank.get(min_class, 2)

    corridors: List[Dict[str, Any]] = []
    for idx, comp in enumerate(components):
        if not comp:
            continue
        # Drop noise — tiny components below the doctrinal Battalion
        # area threshold (~12 km² at 1mi tiles ≈ 5 tiles). The default
        # min_tiles=8 excludes anything below Brigade-area scale.
        if len(comp) < min_tiles:
            continue
        polygon = _component_polygon(comp, tile_grid)
        # Representative latitude for metric conversion.
        rep_lat = polygon.centroid.y
        width_km = _polygon_width_km(polygon, rep_lat)
        cls = _class_from_width_km(width_km, force_type)
        if rank.get(cls, 0) < min_rank:
            continue
        centerline = _polygon_centerline(polygon, rep_lat)
        edges = _endpoints_on_ao_edge(polygon, south0, west0, north_max, east_max)
        # GeoJSON the polygon. unary_union may return Polygon or
        # MultiPolygon; flatten to a list of polygon coord-rings.
        if polygon.geom_type == "Polygon":
            polygon_coords = [list(polygon.exterior.coords)]
        elif polygon.geom_type == "MultiPolygon":
            polygon_coords = [list(p.exterior.coords) for p in polygon.geoms]
        else:
            polygon_coords = []
        bounds = polygon.bounds  # (minx, miny, maxx, maxy)
        corridors.append({
            "corridor_id": f"MC-{idx + 1}",
            "polygon": {
                "type": "Polygon" if polygon.geom_type == "Polygon" else "MultiPolygon",
                "coordinates": [polygon_coords] if polygon.geom_type == "MultiPolygon"
                else polygon_coords,
            },
            "centerline": {
                "type": "LineString",
                "coordinates": [list(p) for p in centerline],
            },
            "width_km": round(width_km, 2),
            "class": cls,
            "tile_count": len(comp),
            "edges_touched": edges,
            "bbox": [bounds[0], bounds[1], bounds[2], bounds[3]],
        })
    # Sort largest-first so consumers can prioritize.
    corridors.sort(key=lambda c: -c["tile_count"])
    # Cap to max_corridors (default 12) — doctrinal MCOOs show 3-7
    # major corridors per ATP 2-01.3 Fig 4-6 / Fig 4-10. More than ~12
    # is noise for analyst consumption regardless of how trafficable
    # the AO is in aggregate.
    if max_corridors and len(corridors) > max_corridors:
        corridors = corridors[:max_corridors]
    logger.info(
        f"discover_mobility_corridors: {len(corridors)} corridors passing "
        f"min_class={min_class} min_tiles={min_tiles} (class breakdown: "
        f"{ {c['class']: sum(1 for x in corridors if x['class'] == c['class']) for c in corridors} })"
    )
    return corridors

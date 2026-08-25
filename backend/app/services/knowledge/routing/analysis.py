"""Post-route analysis from tile summaries and path coordinates."""

import logging
import math
from typing import Dict, List, Tuple, Any, Optional

from app.services.knowledge.geo_utils import haversine
from app.services.knowledge.roads import Road
from .models import MacroTile, ThreatZone, TILE_SIZE_MI, TILE_SIZE_DEG, METERS_PER_MILE, RoadNode
from .cost import threat_cost_at
from .weather import fetch_weather_for_route

logger = logging.getLogger(__name__)


# OSM highway-type → ATP 2-01.3 Table 4-2 mobility-corridor class mapping
# for mechanized formations. Each highway class supports a column of
# vehicles at the rate-of-march doctrine assumes; the class here is the
# largest formation the road can sustain as a road-bound column per the
# corridor's accommodating echelon. Tracked vehicles need wide hard
# surfaces for division-scale movement; secondary/tertiary roads narrow
# the supportable echelon doctrinally (single-vehicle column = company).
#
# Sources: ATP 2-01.3 ¶4-26 (mechanized force road-network dependence),
# FM 1-04 lane/throughput defaults, OSM Wiki highway tag classification.
_HIGHWAY_TO_MECH_CLASS = {
    "motorway":     "division",   # 2+ lanes/dir divided
    "motorway_link": "division",
    "trunk":        "division",   # 2 lanes/dir (often divided)
    "trunk_link":   "division",
    "primary":      "brigade",    # 1-2 lanes/dir
    "primary_link": "brigade",
    "secondary":    "battalion",  # 1 lane/dir
    "secondary_link": "battalion",
    "tertiary":     "company",
    "tertiary_link": "company",
    "unclassified": "company",
    "residential":  "company",
    "living_street": "sub-company",
    "service":      "sub-company",
    "track":        "sub-company",
    "path":         "sub-company",
}
# Dismounted forces can use lighter roads/trails at higher echelon
# (no axle-load limit, no width minimum). Per ¶4-26 dismounted "might
# be able to use more restrictive corridors."
_HIGHWAY_TO_DISMOUNTED_CLASS = {
    "motorway":     "division",
    "motorway_link": "division",
    "trunk":        "division",
    "trunk_link":   "division",
    "primary":      "division",
    "primary_link": "division",
    "secondary":    "brigade",
    "secondary_link": "brigade",
    "tertiary":     "brigade",
    "tertiary_link": "brigade",
    "unclassified": "battalion",
    "residential":  "battalion",
    "living_street": "battalion",
    "service":      "company",
    "track":        "company",
    "path":         "company",
}

# Rank ordering for "narrowest" class (matches AA-echelon-rollup ranking
# used in pytho-app's _aa_echelon_from_corridor_classes).
_CLASS_RANK = {
    "division": 5, "brigade": 4, "battalion": 3,
    "company": 2, "sub-company": 1, "unknown": 0,
}


def compute_road_supported_class(
    path: list,
    roads: List[Road],
    force_type: str = "mechanized",
) -> Dict[str, Any]:
    """For the on-road segments of a mixed-mode path, find the dominant
    OSM highway class along the route's road portion and map it to an
    ATP 2-01.3 mobility-corridor class for the maneuvering force.

    Per ¶4-26 a mobility corridor supported by a road network sustains
    the formation the road's throughput can carry as a column. The
    corridor's road-supported class is the NARROWEST road class along
    its on-road segments — the road bottleneck is the column capacity
    bottleneck. Off-road segments are ignored here (off-road extent is
    handled by compute_corridor_widths separately).

    Returns:
        {
          "road_supported_class": str,   # division/brigade/battalion/...
          "road_class_breakdown": dict,  # highway_type -> distance fraction
          "road_distance_mi": float,     # total on-road distance along path
          "road_class_basis": str,       # provenance string
        }
        Empty dict if the path has no on-road segments.
    """
    if not path or not roads:
        return {}
    table = (
        _HIGHWAY_TO_DISMOUNTED_CLASS
        if (force_type or "").lower().startswith(("dismount", "infantry", "sof", "special"))
        else _HIGHWAY_TO_MECH_CLASS
    )
    # Index roads by way_id for O(1) lookup.
    roads_by_id: Dict[int, Road] = {r.way_id: r for r in roads}

    # Walk the path edges, find road-to-road transitions on the same way
    # (those are on-road segments); accumulate distance per highway_type.
    dist_by_highway: Dict[str, float] = {}
    classes_seen: List[str] = []
    total_road_m = 0.0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        if not (isinstance(a, RoadNode) and isinstance(b, RoadNode)):
            continue
        if a.way_id != b.way_id:
            # Intersection cross-link between two roads — zero-distance edge.
            continue
        road = roads_by_id.get(a.way_id)
        if road is None:
            continue
        # Distance along this segment: sum haversine between consecutive
        # road coords from a.coord_idx to b.coord_idx (inclusive).
        ci_a, ci_b = a.coord_index, b.coord_index
        if ci_a > ci_b:
            ci_a, ci_b = ci_b, ci_a
        seg_m = 0.0
        for j in range(ci_a, ci_b):
            seg_m += haversine(
                road.coords[j][1], road.coords[j][0],
                road.coords[j + 1][1], road.coords[j + 1][0],
            )
        dist_by_highway[road.highway_type] = (
            dist_by_highway.get(road.highway_type, 0.0) + seg_m
        )
        classes_seen.append(table.get(road.highway_type, "unknown"))
        total_road_m += seg_m

    if total_road_m <= 0:
        return {}
    # Distance-weighted dominant class. Doctrinally the pinch (narrowest)
    # is the bottleneck per Table 4-2, but OSM highway tagging granularity
    # is too coarse for direct pinch use: a "track" segment can be a
    # well-graded gravel road or a muddy trail, and a few hundred meters
    # of track in a Battalion-grade route shouldn't downgrade the whole
    # AA. Distance-weighted dominant captures the route's actual
    # character — the formation the road network as a whole sustains.
    # The class-distribution breakdown is preserved so an analyst can
    # see chokepoint segments and apply judgment.
    dist_by_class: Dict[str, float] = {}
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        if not (isinstance(a, RoadNode) and isinstance(b, RoadNode)):
            continue
        if a.way_id != b.way_id:
            continue
        road = roads_by_id.get(a.way_id)
        if road is None:
            continue
        ci_a, ci_b = a.coord_index, b.coord_index
        if ci_a > ci_b:
            ci_a, ci_b = ci_b, ci_a
        seg_m = 0.0
        for j in range(ci_a, ci_b):
            seg_m += haversine(
                road.coords[j][1], road.coords[j][0],
                road.coords[j + 1][1], road.coords[j + 1][0],
            )
        cls = table.get(road.highway_type, "unknown")
        dist_by_class[cls] = dist_by_class.get(cls, 0.0) + seg_m
    dominant_class = max(dist_by_class.items(), key=lambda x: x[1])[0] if dist_by_class else "unknown"
    narrowest_class = min(classes_seen, key=lambda c: _CLASS_RANK.get(c, 0))
    breakdown = {
        ht: round(dist_m / total_road_m, 3)
        for ht, dist_m in sorted(dist_by_highway.items(), key=lambda x: -x[1])
    }
    class_breakdown = {
        cls: round(dist_m / total_road_m, 3)
        for cls, dist_m in sorted(dist_by_class.items(), key=lambda x: -x[1])
    }
    return {
        # Dominant (distance-weighted) class — the formation the road
        # network as a whole sustains. Used as the AA's road-supported
        # corridor class for echelon roll-up.
        "road_supported_class": dominant_class,
        # Narrowest class — the bottleneck the formation would have to
        # pass through. Preserved for analyst inspection (engineer
        # support / bypass planning around chokepoints).
        "road_pinch_class": narrowest_class,
        "road_class_breakdown": breakdown,
        "road_supported_breakdown": class_breakdown,
        "road_distance_mi": round(total_road_m / METERS_PER_MILE, 2),
        "road_class_basis": (
            f"dominant distance-weighted OSM highway class along route's "
            f"on-road portion ({total_road_m / METERS_PER_MILE:.1f} mi total) "
            f"mapped to ATP 2-01.3 echelon via {force_type} table; "
            f"pinch class={narrowest_class}"
        ),
    }


def compute_corridor_widths(
    tile_grid: List[List[MacroTile]],
    coords: List[Tuple[float, float]],
    *,
    force_type: str = "mechanized",
    sample_interval_mi: float = 0.5,
    max_search_km: float = 10.0,
    step_mi: float = 0.5,
) -> Dict[str, Any]:
    """For each sample point along the path, walk perpendicular outward in
    both directions until hitting a "pinch" tile (a tile that meaningfully
    canalizes the maneuvering force at this force_type's doctrinal scale).
    The contiguous un-pinched perpendicular span at that sample is the
    local mobility-corridor width.

    Per ATP 2-01.3 §4-24 a mobility corridor is "areas that are relatively
    free of obstacles where a force will be CANALIZED due to terrain
    restrictions." So the pinch criterion is broader than just impassable —
    fair/poor land cover (forest, urban, soft soil) and steep slopes
    canalize a mechanized force even when not strictly blocked. The
    planner's MacroTile.blocked only catches water/impassable land cover
    and slopes above max_slope_pct — too permissive for AA width sampling.

    Force-type modulation per §4-25 / §4-26:
      - mechanized: trafficability > 1.5 (fair/poor/impassable) OR
                     slope > 30% (moderate+) — wider canalization band
      - dismounted: trafficability > 2.5 (poor/impassable only) OR
                     slope > 50% (very_steep+) — narrower canalization band
                     (dismounted units can use forest, swamp, etc. that
                     mechanized cannot)

    Maps to ATP 2-01.3 Table 4-2 doctrinal mobility-corridor classes
    (mechanized force): Division ≥ 6 km, Brigade ≥ 3 km, Battalion ≥ 1.5 km,
    Company ≥ 0.5 km. A path's accommodating echelon is bounded by its
    narrowest (pinch) corridor width along its length.

    Returns:
        {
          "corridor_width_m": float,           # minimum perpendicular span (pinch)
          "corridor_widths_sampled_m": list,   # per-sample widths along the route
          "corridor_sample_count": int,
          "corridor_width_basis": str,         # one-line provenance string
        }
        Empty dict if the path is too short to sample or grid is empty.
    """
    # Force-type-specific pinch thresholds (per ATP 2-01.3 §4-25/§4-26).
    # Per ¶4-24 a mobility corridor is "areas RELATIVELY FREE OF OBSTACLES"
    # — open / fair terrain isn't an obstacle, it's just slower terrain.
    # Only poor/impassable land cover (tree_cover, wetland) and steep
    # slopes canalize a force off-road. So the threshold sits at
    # trafficability > "fair" (which is 2.0 in TRAFFICABILITY_COST) to
    # let cropland / grassland / shrubland pass without pinching.
    if (force_type or "").lower().startswith(
        ("dismount", "infantry", "sof", "special")
    ):
        # Dismounted units traverse forest, swamp, etc. per ¶4-26 — only
        # truly impassable (water, mangroves) pinches.
        max_trafficability_ok = 10.0
        max_slope_pct_ok = 60.0
        force_type_label = "dismounted"
    else:
        max_trafficability_ok = 2.5  # fair (2.0) passes; poor (4.0) pinches
        max_slope_pct_ok = 30.0
        force_type_label = "mechanized"

    def tile_pinches(t: MacroTile) -> bool:
        """True if `t` canalizes the maneuvering force at this scale."""
        if t.blocked:
            return True
        if t.worst_trafficability > max_trafficability_ok:
            return True
        if t.max_slope_pct > max_slope_pct_ok:
            return True
        return False

    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    if rows == 0 or cols == 0 or len(coords) < 2:
        return {}
    south0 = tile_grid[0][0].south
    west0 = tile_grid[0][0].west

    def tile_at(lat: float, lon: float) -> Optional[MacroTile]:
        r = int((lat - south0) / TILE_SIZE_DEG)
        c = int((lon - west0) / TILE_SIZE_DEG)
        if 0 <= r < rows and 0 <= c < cols:
            return tile_grid[r][c]
        return None

    # Cumulative path distance (meters) per vertex.
    cum_m = [0.0]
    for i in range(1, len(coords)):
        cum_m.append(cum_m[-1] + haversine(
            coords[i - 1][1], coords[i - 1][0],
            coords[i][1], coords[i][0],
        ))
    total_m = cum_m[-1]
    if total_m <= 0:
        return {}

    # Sample offsets along the path, centered between endpoints.
    sample_step_m = sample_interval_mi * METERS_PER_MILE
    sample_offsets_m: List[float] = []
    off = sample_step_m / 2.0
    while off < total_m:
        sample_offsets_m.append(off)
        off += sample_step_m
    if not sample_offsets_m:
        return {}

    step_m = step_mi * METERS_PER_MILE
    max_steps = max(1, int(max_search_km * 1000.0 / step_m))

    widths_m: List[float] = []
    for s_off in sample_offsets_m:
        # Locate the path segment containing this sample offset.
        idx = 0
        while idx < len(cum_m) - 2 and cum_m[idx + 1] < s_off:
            idx += 1
        seg_a = coords[idx]
        seg_b = coords[idx + 1]
        seg_len = cum_m[idx + 1] - cum_m[idx]
        if seg_len <= 0:
            continue
        t_along = (s_off - cum_m[idx]) / seg_len
        lon = seg_a[0] + t_along * (seg_b[0] - seg_a[0])
        lat = seg_a[1] + t_along * (seg_b[1] - seg_a[1])

        # Local segment direction in meters (convert degree deltas via the
        # local lat scale so the perpendicular vector is geometrically
        # orthogonal in metric space, not in raw lon/lat units).
        lat_rad = math.radians(lat)
        scale_lon_m_per_deg = 111000.0 * math.cos(lat_rad)
        scale_lat_m_per_deg = 111000.0
        dx_m = (seg_b[0] - seg_a[0]) * scale_lon_m_per_deg
        dy_m = (seg_b[1] - seg_a[1]) * scale_lat_m_per_deg
        seg_metric = math.hypot(dx_m, dy_m)
        if seg_metric <= 0:
            continue
        # Unit perpendicular vectors (left & right of travel direction).
        ux_left = -dy_m / seg_metric
        uy_left = dx_m / seg_metric

        def walk(ux: float, uy: float) -> float:
            travelled_m = 0.0
            for k in range(1, max_steps + 1):
                ox_m = ux * step_m * k
                oy_m = uy * step_m * k
                p_lat = lat + oy_m / scale_lat_m_per_deg
                p_lon = lon + ox_m / scale_lon_m_per_deg
                t = tile_at(p_lat, p_lon)
                if t is None or tile_pinches(t):
                    break
                travelled_m = step_m * k
            return travelled_m

        left_m = walk(ux_left, uy_left)
        right_m = walk(-ux_left, -uy_left)
        widths_m.append(left_m + right_m)

    if not widths_m:
        return {}
    return {
        "corridor_width_m": round(min(widths_m), 1),
        "corridor_widths_sampled_m": [round(w, 1) for w in widths_m],
        "corridor_sample_count": len(widths_m),
        "corridor_width_basis": (
            f"perpendicular sampling at {sample_interval_mi}-mi intervals "
            f"against tile canalization criterion "
            f"(force_type={force_type_label}: trafficability ≤ "
            f"{max_trafficability_ok}, slope ≤ {max_slope_pct_ok}%); "
            f"(step={step_mi}mi, max_search={max_search_km}km); "
            f"reported width is the narrowest pinch along the path"
        ),
    }


def analyze_route(
    tile_grid: List[List[MacroTile]],
    coords: List[Tuple[float, float]],
    threats: List[ThreatZone] = None,
    mode: str = "mixed",
    force_type: str = "mechanized",
    path: Optional[list] = None,
    roads: Optional[List[Road]] = None,
) -> Dict[str, Any]:
    """Compute route analysis by finding which tiles the path passes through."""
    if not coords or len(coords) < 2:
        return {}

    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    if rows == 0:
        return {}

    south0 = tile_grid[0][0].south
    west0 = tile_grid[0][0].west

    # Find unique tiles the path passes through
    visited_tiles = []
    seen = set()
    for lon, lat in coords:
        r = int((lat - south0) / TILE_SIZE_DEG)
        c = int((lon - west0) / TILE_SIZE_DEG)
        r = max(0, min(rows - 1, r))
        c = max(0, min(cols - 1, c))
        if (r, c) not in seen:
            seen.add((r, c))
            visited_tiles.append(tile_grid[r][c])

    if not visited_tiles:
        return {}

    n = len(visited_tiles)

    # Distance from actual coords
    total_m = sum(
        haversine(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
        for i in range(len(coords) - 1)
    )
    dist_mi = total_m / METERS_PER_MILE

    max_slope = max((t.max_slope_pct for t in visited_tiles), default=0)
    avg_conceal = 0.0 if mode == "on_road" else sum(t.concealment_pct for t in visited_tiles) / n
    max_elev = max((t.avg_elevation_ft for t in visited_tiles), default=0)

    # Elevation profile
    cum = 0.0
    profile = []
    for i, t in enumerate(visited_tiles):
        if i > 0:
            cum += TILE_SIZE_MI
        profile.append({"mi": round(cum, 1), "elevation_ft": t.avg_elevation_ft})

    # Terrain breakdown
    lc_counts = {}
    for t in visited_tiles:
        lc_counts[t.dominant_land_cover] = lc_counts.get(t.dominant_land_cover, 0) + 1

    # Elevation gain/loss
    gain = loss = 0.0
    for i in range(1, n):
        diff = visited_tiles[i].avg_elevation_ft - visited_tiles[i - 1].avg_elevation_ft
        if diff > 0:
            gain += diff
        else:
            loss += abs(diff)

    # Threat exposure — walk actual path coordinates
    threat_mi = 0.0
    if threats:
        for i in range(len(coords) - 1):
            mid_lat = (coords[i][1] + coords[i + 1][1]) / 2
            mid_lon = (coords[i][0] + coords[i + 1][0]) / 2
            if threat_cost_at(mid_lat, mid_lon, threats) > 0:
                seg_m = haversine(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
                threat_mi += seg_m / METERS_PER_MILE

    result = {
        "distance_mi": round(dist_mi, 2),
        "max_slope_pct": round(max_slope, 1),
        "elevation_gain_ft": round(gain),
        "elevation_loss_ft": round(loss),
        "max_elevation_ft": round(max_elev),
        "concealment_pct": round(avg_conceal, 1),
        "threat_exposure_mi": round(threat_mi, 2),
        "elevation_profile": profile,
        "terrain_breakdown": {k: round(v / n, 2) for k, v in sorted(lc_counts.items(), key=lambda x: -x[1])},
    }
    # ATP 2-01.3 Table 4-2 mobility-corridor width derivation: sample
    # perpendicular cross-sections against the canalization criterion
    # (trafficability + slope, force-type modulated). The pinch point
    # sets the off-road corridor extent.
    corridor = compute_corridor_widths(tile_grid, coords, force_type=force_type)
    if corridor:
        result.update(corridor)
    # Road-supported corridor class per ¶4-26 — when the route uses a
    # road network the corridor's accommodating echelon is also bounded
    # by the road's column capacity. The corridor's effective class is
    # the BETTER of off-road extent (Table 4-2 widths) and road-supported
    # class (highway-class lookup). A motorway through forest carries a
    # Brigade even when off-road extent is 0; a 10km cropland valley
    # with no road carries a Division on cross-country movement.
    if path and roads:
        road_supported = compute_road_supported_class(path, roads, force_type=force_type)
        if road_supported:
            result.update(road_supported)
    return result


async def analyze_route_with_weather(
    tile_grid: List[List[MacroTile]],
    coords: List[Tuple[float, float]],
    threats: List[ThreatZone] = None,
    mode: str = "mixed",
    departure_time: Optional[float] = None,
    rate_of_advance_mph: float = 0.0,
    force_type: str = "mechanized",
    path: Optional[list] = None,
    roads: Optional[List[Road]] = None,
) -> Dict[str, Any]:
    """Run terrain analysis + weather fetch, merge results.

    Calls the sync analyze_route() for terrain, then fetches OWM forecasts
    for sample points along the route. Weather failures are non-fatal —
    the weather key is simply omitted.
    """
    analysis = analyze_route(
        tile_grid, coords, threats, mode,
        force_type=force_type, path=path, roads=roads,
    )
    if not analysis:
        return analysis

    try:
        weather = await fetch_weather_for_route(coords, departure_time, rate_of_advance_mph)
        if weather:
            analysis["weather"] = weather
    except Exception as e:
        logger.warning(f"Weather fetch failed (non-fatal): {e}")

    return analysis

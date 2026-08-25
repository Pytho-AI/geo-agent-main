"""
Common geospatial data layer.

Provides a unified interface for fetching terrain data (elevation, land cover,
slope) used by route planning, NL chat agent, and COP generation.

Two entry points:
    get_terrain(bbox, resolution=...)    — grid-based, for chat/COP consumers
    sample_terrain_at(coords, bbox=...)  — custom coordinates, for route planner
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.services.knowledge.terrain import (
    get_elevation_profile,
    calculate_slope,
)
from app.services.knowledge.geo_utils import haversine
from app.services.knowledge.landcover import (
    get_land_cover_grid,
    get_concealment_level,
    get_cover_level,
    LAND_COVER_PROPERTIES,
)
from app.services.knowledge.cache import spatial_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TerrainPoint:
    """Single point of geospatial data — the common currency across all consumers."""
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    slope_pct: Optional[float] = None
    land_cover_code: Optional[int] = None
    land_cover_name: Optional[str] = None         # e.g. "tree_cover"
    land_cover_display: Optional[str] = None      # e.g. "Tree Cover"
    concealment: Optional[str] = None
    cover: Optional[str] = None
    trafficability_wheeled: Optional[str] = None
    trafficability_tracked: Optional[str] = None
    trafficability_infantry: Optional[str] = None


@dataclass
class TerrainGrid:
    """Result of terrain sampling — a grid of points within a bbox."""
    points: List[TerrainPoint]
    bbox: Tuple[float, float, float, float]
    grid_size: int
    resolution: str


# ---------------------------------------------------------------------------
# Resolution presets
# ---------------------------------------------------------------------------

RESOLUTION_GRID_SIZES: Dict[str, int] = {
    "fine": 10,
}

# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------

_GLOBAL = "global"


def _make_composite_bbox(bbox: Tuple, resolution: str, elevation_zoom: int) -> list:
    """Encode resolution + zoom into a synthetic bbox for cache key differentiation."""
    # Append resolution hash as extra coordinates so spatial_cache hashes them
    tag = hashlib.md5(f"{resolution}:{elevation_zoom}".encode()).hexdigest()[:8]
    tag_float = int(tag, 16) / 1e12  # deterministic float from params
    return [bbox[0], bbox[1], bbox[2], bbox[3], tag_float]


# ---------------------------------------------------------------------------
# Grid coordinate generation
# ---------------------------------------------------------------------------

def _grid_coords_from_bbox(
    bbox: Tuple[float, float, float, float],
    grid_size: int,
) -> List[Tuple[float, float]]:
    """Generate evenly-spaced (lat, lon) sample coordinates within a bbox.

    bbox format: (min_lon, min_lat, max_lon, max_lat).
    Returns: List of (lat, lon) tuples.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_step = (max_lat - min_lat) / (grid_size - 1) if grid_size > 1 else 0
    lon_step = (max_lon - min_lon) / (grid_size - 1) if grid_size > 1 else 0

    coords = []
    for i in range(grid_size):
        for j in range(grid_size):
            lat = min_lat + i * lat_step
            lon = min_lon + j * lon_step
            coords.append((lat, lon))
    return coords


# ---------------------------------------------------------------------------
# Shared fetch + enrich pipeline
# ---------------------------------------------------------------------------

async def _fetch_and_enrich(
    coords: List[Tuple[float, float]],
    *,
    compute_slope: bool = True,
    elevation_zoom: int = 12,
) -> List[TerrainPoint]:
    """Fetch elevation + land cover in parallel, compute slope, enrich with properties."""
    if not coords:
        return []

    # Build elevation sample points (3 per coord when computing slope)
    delta = 0.001
    if compute_slope:
        elev_coords = []
        for lat, lon in coords:
            elev_coords.extend([(lat, lon), (lat + delta, lon), (lat, lon + delta)])
    else:
        elev_coords = list(coords)

    # Parallel fetch
    t0 = time.time()
    elevations, land_covers = await asyncio.gather(
        get_elevation_profile(elev_coords, zoom=elevation_zoom),
        get_land_cover_grid(coords),
    )
    elapsed = time.time() - t0
    logger.info(f"  geodata fetch: {len(coords)} points in {elapsed:.2f}s (zoom={elevation_zoom}, slope={compute_slope})")

    # Assemble TerrainPoints
    points = []
    for i, (lat, lon) in enumerate(coords):
        tp = TerrainPoint(lat=lat, lon=lon)

        # Elevation
        if compute_slope:
            base_idx = i * 3
            elev_center = elevations[base_idx]
            elev_north = elevations[base_idx + 1]
            elev_east = elevations[base_idx + 2]
        else:
            elev_center = elevations[i]
            elev_north = None
            elev_east = None

        if elev_center is not None:
            tp.elevation_m = round(elev_center, 1)
            if compute_slope and elev_north is not None and elev_east is not None:
                dist = haversine(lat, lon, lat + delta, lon)
                if dist > 0:
                    slope_ns = calculate_slope(elev_center, elev_north, dist)
                    slope_ew = calculate_slope(elev_center, elev_east, dist)
                    tp.slope_pct = round(max(abs(slope_ns), abs(slope_ew)), 1)

        # Land cover
        lc = land_covers[i]
        if lc is not None:
            tp.land_cover_code = lc.code
            tp.land_cover_name = lc.name
            tp.land_cover_display = lc.display_name
            tp.concealment = get_concealment_level(lc.code)
            tp.cover = get_cover_level(lc.code)
            props = LAND_COVER_PROPERTIES.get(lc.code, {})
            tp.trafficability_wheeled = props.get("trafficability_wheeled")
            tp.trafficability_tracked = props.get("trafficability_tracked")
            tp.trafficability_infantry = props.get("trafficability_infantry")

        points.append(tp)

    return points


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _normalize_bbox(bbox: Tuple, padding: float) -> Tuple[float, float, float, float]:
    """Apply padding and round to cache-friendly precision."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if padding > 0:
        lon_span = max_lon - min_lon
        lat_span = max_lat - min_lat
        min_lon -= lon_span * padding
        min_lat -= lat_span * padding
        max_lon += lon_span * padding
        max_lat += lat_span * padding
    return (
        round(min_lon, 3),
        round(min_lat, 3),
        round(max_lon, 3),
        round(max_lat, 3),
    )


async def get_terrain(
    bbox: Tuple[float, float, float, float],
    *,
    resolution: str = "medium",
    bbox_padding: float = 0.0,
    compute_slope: bool = True,
    elevation_zoom: int = 12,
) -> TerrainGrid:
    """
    Fetch terrain data on a standard grid within a bbox.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat)
        resolution: "coarse" (5x5), "medium" (7x7), or "fine" (10x10)
        bbox_padding: fractional buffer (0.4 = 40% expansion)
        compute_slope: whether to compute per-point slope
        elevation_zoom: terrain tile zoom level

    Returns:
        TerrainGrid with assembled TerrainPoint objects.
    """
    grid_size = RESOLUTION_GRID_SIZES.get(resolution, 7)
    norm_bbox = _normalize_bbox(bbox, bbox_padding)
    cache_bbox = _make_composite_bbox(norm_bbox, resolution, elevation_zoom)

    # Check cache
    cached = spatial_cache.get("terrain_grid", _GLOBAL, cache_bbox)
    if cached is not None:
        return cached

    # Generate grid and fetch
    coords = _grid_coords_from_bbox(norm_bbox, grid_size)
    points = await _fetch_and_enrich(
        coords,
        compute_slope=compute_slope,
        elevation_zoom=elevation_zoom,
    )

    grid = TerrainGrid(
        points=points,
        bbox=norm_bbox,
        grid_size=grid_size,
        resolution=resolution,
    )
    spatial_cache.put("terrain_grid", _GLOBAL, cache_bbox, grid, ttl_seconds=1800)
    return grid


async def sample_terrain_at(
    coords: List[Tuple[float, float]],
    *,
    bbox: Optional[Tuple] = None,
    compute_slope: bool = False,
    elevation_zoom: int = 12,
) -> List[TerrainPoint]:
    """
    Fetch terrain data at explicit coordinates.

    Used by the route planner which needs tile-aligned sample points.

    Args:
        coords: List of (lat, lon) tuples
        bbox: optional bbox for cache key (enables caching)
        compute_slope: whether to compute per-point slope
        elevation_zoom: terrain tile zoom level

    Returns:
        List of TerrainPoint in same order as coords.
    """
    if bbox is not None:
        cached = spatial_cache.get("terrain_points", _GLOBAL, list(bbox))
        if cached is not None:
            return cached

    points = await _fetch_and_enrich(
        coords,
        compute_slope=compute_slope,
        elevation_zoom=elevation_zoom,
    )

    if bbox is not None:
        spatial_cache.put("terrain_points", _GLOBAL, list(bbox), points, ttl_seconds=1800)

    return points

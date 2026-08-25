"""
Terrain sampling utilities for the NL agent.

Delegates to the common geodata layer for fetching and caching.
"""

import logging
from typing import Dict, Any, List, Tuple

from app.services.knowledge.geodata import get_terrain, TerrainPoint

logger = logging.getLogger(__name__)


def _terrain_point_to_dict(p: TerrainPoint) -> Dict[str, Any]:
    """Convert TerrainPoint to the dict format expected by the NL agent."""
    d: Dict[str, Any] = {
        "lat": p.lat,
        "lon": p.lon,
        "elevation_m": p.elevation_m,
        "slope_pct": p.slope_pct,
        "land_cover": None,
    }
    if p.land_cover_code is not None:
        d["land_cover"] = {
            "code": p.land_cover_code,
            "type": p.land_cover_name,
            "display_name": p.land_cover_display,
            "concealment": p.concealment,
            "cover": p.cover,
        }
    return d


# Map old grid_size args to resolution presets
_SIZE_TO_RESOLUTION = {10: "fine"}


async def _sample_terrain_grid(
    bbox: Tuple[float, float, float, float],
    grid_size: int = 5,
) -> List[Dict[str, Any]]:
    """
    Sample terrain at a grid of points within bbox.

    Args:
        bbox: [min_lon, min_lat, max_lon, max_lat]
        grid_size: Number of points per axis (default 5x5 = 25 points)

    Returns:
        List of terrain data points with lat, lon, elevation_m, land_cover, slope_pct
    """
    resolution = _SIZE_TO_RESOLUTION.get(grid_size, "coarse")
    grid = await get_terrain(
        bbox,
        resolution=resolution,
        compute_slope=True,
        elevation_zoom=8,
    )
        # Get the 3 elevation values for this coord (center, north, east)
    result = [_terrain_point_to_dict(p) for p in grid.points]
    logger.info(f"Sampled terrain grid: {len(result)} points")
    return result

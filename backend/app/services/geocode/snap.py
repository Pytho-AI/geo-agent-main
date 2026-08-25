"""Snap a point onto the nearest linear OSM feature — railway or road.

Infrastructure named for a linear feature (a railway segment, a bridge,
an MSR waypoint) belongs ON that feature, not at the town center. This
queries Overpass for the nearest matching way within a search radius
and projects the point onto the closest segment.

Fails open: no network / no way in range → the original point is
returned with snapped=False, so a snap attempt never blocks a write.
"""

import asyncio
import logging
import math
from typing import Optional, Tuple

import httpx

from app.services.knowledge.roads import (
    OVERPASS_HEADERS, OVERPASS_SERVERS,
)

logger = logging.getLogger(__name__)

# OSM selectors per feature family.
_FEATURE_FILTERS = {
    "railway": '["railway"~"^(rail|light_rail|subway|tram|narrow_gauge)$"]',
    "road": '["highway"~"^(motorway|trunk|primary|secondary|tertiary|'
            'unclassified|residential)$"]',
}


def _project_point_on_segment(px, py, ax, ay, bx, by):
    """Nearest point on segment AB to P, in lon/lat (planar approx —
    fine at snap scale). Returns (x, y, t)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ax, ay, 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ax + t * dx, ay + t * dy, t


def _approx_km(lon1, lat1, lon2, lat2):
    dlat = (lat2 - lat1) * 111.32
    dlon = (lon2 - lon1) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


async def snap_to_osm_feature(
    lat: float, lon: float, feature: str = "railway",
    radius_m: int = 3000,
) -> Tuple[float, float, Optional[float], Optional[str]]:
    """Snap (lat, lon) onto the nearest OSM way of `feature` kind within
    radius_m. Returns (lat, lon, moved_km_or_None, way_name_or_None):
    moved_km None = no snap (nothing in range or fetch failed)."""
    flt = _FEATURE_FILTERS.get(feature)
    if flt is None:
        return lat, lon, None, None
    query = (f"[out:json][timeout:15];way(around:{radius_m},{lat},{lon})"
             f"{flt};out geom;")
    data = None
    for server in OVERPASS_SERVERS:
        try:
            async with httpx.AsyncClient(timeout=20, headers=OVERPASS_HEADERS) as c:
                r = await c.post(server, data={"data": query})
                if r.status_code == 200:
                    data = r.json()
                    break
        except Exception as e:
            logger.debug("overpass snap %s failed: %s", server, e)
    if not data:
        return lat, lon, None, None

    best = None                                  # (dist_km, lon, lat, name)
    for el in data.get("elements", []):
        geom = el.get("geometry") or []
        name = (el.get("tags") or {}).get("name")
        for a, b in zip(geom, geom[1:]):
            sx, sy, _ = _project_point_on_segment(
                lon, lat, a["lon"], a["lat"], b["lon"], b["lat"])
            d = _approx_km(lon, lat, sx, sy)
            if best is None or d < best[0]:
                best = (d, sx, sy, name)
    if best is None:
        return lat, lon, None, None
    _, sx, sy, name = best
    moved = _approx_km(lon, lat, sx, sy)
    # Already on the feature (within 50 m) — treat as no move.
    if moved < 0.05:
        return sy, sx, 0.0, name
    return sy, sx, moved, name

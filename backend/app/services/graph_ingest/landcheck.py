"""Land checking and snapping for position writes and derivations.

A land unit never sits in permanent water — INCLUDING when a stated
grid says so (user ruling 2026-07-17: stated coordinates snap to the
nearest landmass; the raw grid stays in the observation's provenance
note). Maritime entities are exempt — a carrier strike group belongs
in the water.

ESA WorldCover class 80 (permanent water) is the block; wetland and
mangrove stay placeable (restrictive terrain is a mobility problem,
not a floating-division bug).
"""

import math
from typing import List, Optional, Tuple

from app.services.knowledge.landcover import get_land_cover_grid

_WATER = {80}

# Ring-search schedule for wet candidates: radii out to 15 km, eight
# bearings each, nearest-first.
_NUDGE_RADII_KM = (1.0, 2.0, 4.0, 8.0, 15.0)
_NUDGE_BEARINGS = tuple(range(0, 360, 45))

# Maritime detection — these entities legitimately sit in water. Word
# match against name + unit_type (lowercased). Deliberately narrow:
# 'squadron' alone is a ground cavalry echelon, never a naval cue.
_MARITIME_CUES = (
    "uss ", "navy", "naval", "fleet", "maritime", "coast guard",
    "amphibious", "carrier", "strike group", "ready group", "vessel",
    "dhow", "skiff", "boarding", "littoral",
)

# Exact-point memo (about 100 m resolution) — position writes arrive
# one at a time during ingest and repeatedly for co-located units.
_SNAP_MEMO: dict = {}


def is_maritime(name: str, unit_type: Optional[str] = None) -> bool:
    t = f" {(name or '').lower()} {(unit_type or '').lower()} "
    return any(cue in t for cue in _MARITIME_CUES)


def _offset(lon: float, lat: float, bearing_rad: float, dist_m: float):
    lat_m = 111320.0
    lon_m = 111320.0 * max(0.2, math.cos(math.radians(lat)))
    return (lon + dist_m * math.sin(bearing_rad) / lon_m,
            lat + dist_m * math.cos(bearing_rad) / lat_m)


async def ensure_on_land(
    points: List[Tuple[float, float]],
) -> List[Tuple[float, float, Optional[float]]]:
    """Land-check (lon, lat) points in ONE batched classification pass
    per search tier. Returns (lon, lat, moved_km): moved_km None = the
    point was already dry (or landcover had no data — fail open, a data
    outage must not block placement); moved_km set = snapped to the
    nearest dry ground; moved_km = -1.0 = NO land within the budget —
    caller decides (skip for synthesized points; keep-and-flag for
    stated ones)."""
    codes = await get_land_cover_grid([(lat, lon) for lon, lat in points])
    out: List[Tuple[float, float, Optional[float]]] = []
    wet: List[int] = []
    for i, (pt, lc) in enumerate(zip(points, codes)):
        if lc is not None and lc.code in _WATER:
            out.append((pt[0], pt[1], -1.0))     # provisional: unresolved
            wet.append(i)
        else:
            out.append((pt[0], pt[1], None))
    if not wet:
        return out
    for radius_km in _NUDGE_RADII_KM:
        pending = [i for i in wet if out[i][2] == -1.0]
        if not pending:
            break
        ring: List[Tuple[float, float]] = []
        owners: List[int] = []
        for i in pending:
            lon0, lat0 = points[i]
            for brg in _NUDGE_BEARINGS:
                ring.append(_offset(lon0, lat0, math.radians(brg),
                                    radius_km * 1000.0))
                owners.append(i)
        ring_codes = await get_land_cover_grid(
            [(lat, lon) for lon, lat in ring])
        for (cand, owner, lc) in zip(ring, owners, ring_codes):
            if out[owner][2] != -1.0:
                continue                          # already resolved
            if lc is None or lc.code not in _WATER:
                out[owner] = (cand[0], cand[1], radius_km)
    return out


async def snap_point_to_land(lon: float, lat: float):
    """Single-point convenience with memo. Returns (lon, lat,
    moved_km_or_None_or_-1)."""
    key = (round(lon, 3), round(lat, 3))
    hit = _SNAP_MEMO.get(key)
    if hit is not None:
        return hit
    result = (await ensure_on_land([(lon, lat)]))[0]
    if len(_SNAP_MEMO) > 8192:
        _SNAP_MEMO.clear()
    _SNAP_MEMO[key] = result
    return result

"""Doctrinal AREA SYNTHESIS — the analyst judgment an OPORD delegates.

An order states an area feature as a center and a radius ("TAA BRAVO,
34UEE 58000 50000, 2 km radius") and expects the analyst to DRAW the
doctrinal graphic: an irregular area shaped by the ground — on land,
excluding water, preferring the cover the feature's function wants
(an assembly area hugs concealment; a position area for artillery
wants open firing ground with cover at its edges). This module does
that derivation from ESA WorldCover, the same terrain source the
doctrinal disposition engine land-checks against.

The output is deliberately conservative: the stated center and radius
govern the extent; terrain only SHAPES the boundary inside that
envelope. When the terrain read fails (no coverage, all-water
neighborhood) the caller falls back to the stated circle — the
source's own placeholder notation.
"""
import logging
import math
from typing import List, Optional

log = logging.getLogger("app.area_synthesis")

_WATER = {80}

# Kinds whose center+radius notation is a placeholder for a
# terrain-shaped area. NOT fire_support_coord_measure: an NFA radius
# around a point target is itself the doctrinal form.
TERRAIN_SHAPED_KINDS = {
    "assembly_area", "battle_position", "objective", "engagement_area",
    "named_area_of_interest", "targeted_area_of_interest",
}

# WorldCover codes: 10 tree, 20 shrub, 30 grass, 40 crop, 50 built,
# 60 bare, 80 water, 90 wetland, 95 mangrove, 100 moss.
# Per-kind suitability WEIGHTS (0 = excluded). The weight scales the
# cell's reach from the center: high-weight terrain extends the
# boundary toward the full stated radius, low-weight terrain pulls it
# in. Water is excluded everywhere; wetland is near-excluded for
# anything that parks vehicles.
_KIND_WEIGHTS = {
    # Assembly areas: concealment first — forest and mixed cover.
    "assembly_area": {10: 1.0, 20: 0.9, 30: 0.75, 40: 0.7, 50: 0.4,
                      60: 0.6, 90: 0.15, 100: 0.5},
    # Battle positions: cover with fields of fire.
    "battle_position": {10: 0.95, 20: 0.9, 30: 0.85, 40: 0.8, 50: 0.5,
                        60: 0.7, 90: 0.15, 100: 0.5},
    # Objectives: the ground itself (any trafficable terrain, towns
    # included — objectives are often built-up).
    "objective": {10: 0.9, 20: 0.9, 30: 0.95, 40: 0.95, 50: 1.0,
                  60: 0.8, 90: 0.2, 100: 0.6},
}
_DEFAULT_WEIGHTS = {10: 0.9, 20: 0.85, 30: 0.9, 40: 0.85, 50: 0.6,
                    60: 0.7, 90: 0.15, 100: 0.5}


async def synthesize_area(lat: float, lon: float, radius_m: float,
                          kind: str, n_rays: int = 24,
                          samples_per_ray: int = 6,
                          ) -> Optional[List[List[float]]]:
    """Shape a center+radius area feature by the ground.

    Casts n_rays bearings from the stated center; along each ray,
    samples WorldCover out to the stated radius and sets the boundary
    at the last suitable sample, weighted by the kind's terrain
    preference — water truncates the ray outright. Returns an OPEN
    ring [[lon, lat], ...] (caller closes it), or None when terrain
    coverage is unavailable (caller keeps the stated circle)."""
    from app.services.knowledge.landcover import get_land_cover_grid

    weights = _KIND_WEIGHTS.get(kind, _DEFAULT_WEIGHTS)
    coslat = math.cos(math.radians(lat)) or 1e-9

    coords = []
    for i in range(n_rays):
        th = 2.0 * math.pi * i / n_rays
        for k in range(1, samples_per_ray + 1):
            r = radius_m * k / samples_per_ray
            coords.append((lat + (r * math.cos(th)) / 111320.0,
                           lon + (r * math.sin(th)) / (111320.0 * coslat)))
    try:
        cells = await get_land_cover_grid(coords)
    except Exception as e:
        log.warning("area synthesis: landcover unavailable (%s)", e)
        return None
    if not cells or all(c is None for c in cells):
        return None

    ring: List[List[float]] = []
    for i in range(n_rays):
        th = 2.0 * math.pi * i / n_rays
        # Walk outward; the boundary sits at the last sample whose
        # terrain supports the feature. Water ends the ray.
        reach = 0.35  # minimum footprint even in poor terrain
        acc = 0.0
        for k in range(samples_per_ray):
            cell = cells[i * samples_per_ray + k]
            if cell is None:
                continue
            if cell.code in _WATER:
                break
            w = weights.get(cell.code, 0.5)
            if w <= 0.0:
                break
            acc = (k + 1) / samples_per_ray * w
            if acc > reach:
                reach = acc
        r = radius_m * min(1.0, reach)
        ring.append([lon + (r * math.sin(th)) / (111320.0 * coslat),
                     lat + (r * math.cos(th)) / 111320.0])
    # Light smoothing: average each vertex with its neighbors so the
    # boundary reads as a drawn graphic, not a radar plot.
    n = len(ring)
    smoothed = []
    for i in range(n):
        p0, p1, p2 = ring[(i - 1) % n], ring[i], ring[(i + 1) % n]
        smoothed.append([(p0[0] + 2.0 * p1[0] + p2[0]) / 4.0,
                         (p0[1] + 2.0 * p1[1] + p2[1]) / 4.0])
    return smoothed

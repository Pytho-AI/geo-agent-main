"""Road-following geometry for route-kind line entities.

A stated route ("TRM: Rose Barracks - Frankfurt - Warsaw - Elk - BPTA,
Route 58") names WAYPOINTS; the road between them is the road network's
business, not a straight schematic segment. Each consecutive waypoint
pair routes on-road: corridor legs (>40 km) over the planet-tile road
hierarchy, tactical legs through the dense engine when a db session is
available. A leg with no road path stays the straight statement — the
caller's data is never dropped, only refined.
"""
import logging
import math
from typing import List, Optional

log = logging.getLogger("app.route_geometry")

ROAD_FOLLOWED_KINDS = {"route", "main_supply_route",
                       "alternate_supply_route"}

_CORRIDOR_KM = 40.0
_MIN_LEG_KM = 1.5


def _haversine_km(la1, lo1, la2, lo2):
    r = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    a = (math.sin(dp / 2.0) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2)
    return 2.0 * r * math.asin(math.sqrt(a))


# Bridge-splice thresholds. The FIRST and LAST segments of a corridor
# result are endpoint bridges by construction (true endpoint -> nearest
# corridor node) and get spliced from 3 km up. INTERIOR segments only
# count as gaps past 8 km — ordinary corridor-zoom geometry carries
# multi-km straight runs on real roads (simplification, not a bridge),
# and treating those as gaps fired a splice on every other segment of a
# thousand-km corridor.
_GAP_SPLICE_BRIDGE_KM = 3.0
_GAP_SPLICE_INTERIOR_KM = 8.0


async def _splice_straight_gaps(routed, progress=None):
    """Re-route the straight bridge segments of a corridor result over
    the LOCAL TILE network (tile_router.route_local_gap: connect-zoom
    tiles clipped to the gap, all road classes, the same persisted
    contraction-hierarchy machinery as the corridors). The Szczuczyn to
    Pisz connect: the through-network's nearest node sat 31 km from the
    waypoint and the bridge drew straight across country while the
    regional roads sat right there on the map. Never the dense Overpass
    engine — that is the 2026-07-17 outage. A gap the local network
    cannot serve keeps its straight statement."""
    if len(routed) < 2:
        return routed
    from app.services.knowledge.routing.tile_router import route_local_gap
    out = [list(routed[0])]
    last = len(routed) - 2
    for gi, (a, b) in enumerate(zip(routed, routed[1:])):
        gap_km = _haversine_km(a[1], a[0], b[1], b[0])
        threshold = (_GAP_SPLICE_BRIDGE_KM if gi in (0, last)
                     else _GAP_SPLICE_INTERIOR_KM)
        if threshold <= gap_km < _CORRIDOR_KM:
            if progress is not None:
                await progress(gi, len(routed),
                               f"re-routing a {gap_km:.0f} km straight "
                               "gap over the local road network")
            try:
                local = await route_local_gap(a[1], a[0], b[1], b[0])
                if local and len(local) >= 2:
                    out.extend([list(p) for p in local[1:]])
                    out[-1] = list(b)
                    log.info("spliced a %.0f km straight gap with a "
                             "%d-vertex local road path", gap_km,
                             len(local))
                    continue
            except Exception as e:
                log.warning("gap splice failed open (%.0f km kept "
                            "straight): %s", gap_km, e)
        out.append(list(b))
    return out


# Retrace-loop erasure bounds: an excursion counts when the line comes
# back to within _RETRACE_PROXIMITY_KM of an earlier vertex after
# wandering between the min and max loop lengths. The floor ignores
# vertex jitter; the ceiling protects genuinely long self-approaching
# geometry (a valley road passing a parallel valley road).
_RETRACE_PROXIMITY_KM = 0.3
_RETRACE_MIN_LOOP_KM = 1.0
_RETRACE_MAX_LOOP_KM = 25.0


def _erase_retrace_loops(coords: List[List[float]]) -> List[List[float]]:
    """Splice out out-and-back excursions from an assembled polyline.

    A convoy route never dives into a town center and doubles back over
    the same bridges to touch a named waypoint — the drawn corridor
    stays on the through road and the town name stays in the notes.
    Heading-angle checks miss this failure (a smooth loop turns 180
    degrees without any sharp vertex), so the test is positional: when
    the line returns to within _RETRACE_PROXIMITY_KM of an earlier
    vertex after 1-25 km of wander, everything between is removed. The
    route's true start and end always survive (an excursion that ends
    the line never returns, so it never matches)."""
    if len(coords) < 4:
        return coords
    kept: List[List[float]] = [list(coords[0])]
    kcum = [0.0]
    erased_km = 0.0
    for pt in coords[1:]:
        cur = kcum[-1] + _haversine_km(kept[-1][1], kept[-1][0],
                                       pt[1], pt[0])
        best = None
        k = len(kept) - 1
        while k >= 0 and cur - kcum[k] <= _RETRACE_MAX_LOOP_KM:
            if (cur - kcum[k] >= _RETRACE_MIN_LOOP_KM
                    and _haversine_km(pt[1], pt[0], kept[k][1],
                                      kept[k][0])
                    <= _RETRACE_PROXIMITY_KM):
                best = k                 # earliest hit = largest loop
            k -= 1
        if best is not None:
            erased_km += cur - kcum[best]
            del kept[best + 1:]
            del kcum[best + 1:]
            cur = kcum[-1] + _haversine_km(kept[-1][1], kept[-1][0],
                                           pt[1], pt[0])
        kept.append(list(pt))
        kcum.append(cur)
    if erased_km:
        log.info("retrace erasure removed %.1f km of out-and-back "
                 "excursions (%d -> %d vertices)",
                 erased_km, len(coords), len(kept))
    return kept


async def road_follow(coords: List[List[float]], kind: str,
                      db=None, map_id=None,
                      progress=None) -> List[List[float]]:
    """[[lon, lat], ...] waypoints -> road-following vertex list.

    Legs keep their endpoints; failures keep the straight leg."""
    if kind not in ROAD_FOLLOWED_KINDS or len(coords) < 2:
        return coords
    out: List[List[float]] = [list(coords[0])]
    for i in range(len(coords) - 1):
        (lo1, la1), (lo2, la2) = coords[i], coords[i + 1]
        leg_km = _haversine_km(la1, lo1, la2, lo2)
        if progress is not None:
            await progress(i, len(coords) - 1,
                           f"road-following leg {i + 1}/"
                           f"{len(coords) - 1} ({leg_km:.0f} km)")
        routed: Optional[List] = None
        try:
            if leg_km > _CORRIDOR_KM:
                from app.services.knowledge.routing.tile_router import (
                    route_on_road_hierarchical)
                routed = await route_on_road_hierarchical(
                    la1, lo1, la2, lo2)
                if routed and len(routed) >= 2:
                    routed = await _splice_straight_gaps(
                        routed, progress=progress)
            elif leg_km >= _MIN_LEG_KM:
                # Short legs ride the tile plane too (connect-zoom
                # tiles, all road classes, persisted contraction
                # hierarchy). The dense engine's Overpass fetch is an
                # EXTERNAL dependency that stalls the whole redraw for
                # minutes when the mirrors 504 — routing never leaves
                # the internal tile plane.
                from app.services.knowledge.routing.tile_router import (
                    route_local_gap)
                routed = await route_local_gap(la1, lo1, la2, lo2)
        except Exception as e:
            log.warning("road follow leg %d failed (%s) — keeping "
                        "straight statement", i, e)
        if routed and len(routed) >= 2:
            out.extend([list(p) for p in routed[1:]])
            out[-1] = [lo2, la2]
        else:
            out.append([lo2, la2])
    # Retrace erasure RETIRED (2026-07-21): it was built for routes
    # terminating inside town centers, a pathology fixed at the cause
    # (waypoint discipline — terminals at road-reachable destinations).
    # Against correct geometry it destroys legitimate out-and-back
    # spurs: a convoy that visits a depot off the through road drives
    # in and back out, and the eraser collapsed 11 km of routed road
    # into straight chords. _erase_retrace_loops stays available but
    # is no longer applied.
    return out

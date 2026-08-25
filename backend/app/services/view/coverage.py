"""Terrain-aware engagement/detection coverage — the §6.7 derivation.

A radar or SAM ring is really a VIEWSHED: line of sight from the
bearer against topology, out to the envelope's range. The DEM is
already in-stack (the terrain endpoint's tile cache); this module
walks it: N bearings from the bearer, sampling terrain along each ray,
and truncates the ray where terrain masks the line of sight. The
result is the coverage polygon the renderer paints — the familiar 2D
circle is what falls out on flat ground, and doctrine's dead ground
appears exactly where the earth actually blocks the beam.

Trajectory class decides masking: direct-fire and sensor/emitter
envelopes (line-of-sight physics) get the viewshed; ballistic and
loiter envelopes fly over the crest and keep their range-limited ring
(crest-clearance refinement is a later consumer per the design doc).

Coverage is a pure function of (position, range, sensor height) over
immutable terrain — derived once per key and cached in-process.
"""
import logging
import math
from typing import List, Optional, Tuple

log = logging.getLogger("app.view.coverage")

# LOS-masked trajectory/employment classes; everything else ranges
# over the crest.
_LOS_CATEGORIES = {
    "cema", "cyberspace_electromagnetic_activities",
    "air_defense", "ada", "reconnaissance_and_surveillance",
}
# equipment_class signals for LOS physics inside broader categories
# (SAM systems file under category=fires but engage by radar LOS).
_LOS_CLASSES = {"ada", "sam", "air_defense", "radar", "ew", "uav"}

_COVERAGE_CACHE: dict = {}
_COVERAGE_CACHE_MAX = 4096

# Terrain does not move: derived coverage persists to the data volume
# (peaks-store pattern) — one derivation per (position, range), ever.
_COVERAGE_STORE = None


def _coverage_store():
    global _COVERAGE_STORE
    if _COVERAGE_STORE is None:
        import os
        import sqlite3
        try:
            base = os.environ.get("GEO_DATA_DIR", "/app/data")
            os.makedirs(base, exist_ok=True)
            conn = sqlite3.connect(
                os.path.join(base, "coverage_store.sqlite"),
                check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coverage ("
                "lat REAL, lon REAL, radius_m INTEGER, ring TEXT, "
                "PRIMARY KEY (lat, lon, radius_m))")
            # v3 rows key on the band's reference target height as
            # well (air vs ground evaluation); older tables stay for
            # nothing and are never read.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coverage3 ("
                "lat REAL, lon REAL, radius_m INTEGER, target_h INTEGER, "
                "payload TEXT, "
                "PRIMARY KEY (lat, lon, radius_m, target_h))")
            conn.commit()
            _COVERAGE_STORE = conn
        except Exception as exc:
            log.warning("coverage store unavailable (%s)", exc)
            _COVERAGE_STORE = False
    return _COVERAGE_STORE or None

_N_RAYS = 72
_SAMPLES_PER_RAY = 24
# Antenna/launcher height above ground at the bearer. Target height is
# PER BAND (caller-supplied): an air-defense or surveillance envelope
# is evaluated against a reference low-altitude AIR target, a
# direct-fire ground band against a vehicle-height target. A single
# ground-hugging default made every long-range boundary collapse into
# ray-to-ray whipsaw (nothing sees a 10 m target through rolling
# terrain at 12 km) — the starburst was the wrong question, not the
# terrain.
_SENSOR_HEIGHT_M = 10.0
_DEFAULT_TARGET_HEIGHT_M = 10.0


def needs_los(category: Optional[str], trajectory: Optional[str],
              equipment_class: Optional[str] = None) -> bool:
    if trajectory in ("ballistic", "cruise", "loiter"):
        return False
    if trajectory == "direct":
        return True
    if (equipment_class or "").lower() in _LOS_CLASSES:
        return True
    return (category or "").lower() in _LOS_CATEGORIES


async def _elevations(points: List[Tuple[float, float]]) -> List[Optional[float]]:
    """DEM elevations for (lat, lon) points via the terrain module's
    cached tile images."""
    from PIL import Image  # noqa: F401 — import check

    import io

    from app.api.v1.tiles import _get_client
    from app.api.v1.terrain import (_DEM_IMG_CACHE, _DEM_IMG_CACHE_MAX,
                                    _DEM_ZOOM, _dem_tile_and_pixel)
    from PIL import Image

    client = _get_client()
    out: List[Optional[float]] = [None] * len(points)
    by_tile: dict = {}
    for i, (lat, lon) in enumerate(points):
        x, y, px, py = _dem_tile_and_pixel(lon, lat)
        by_tile.setdefault((x, y), []).append((i, px, py))
    for (x, y), refs in by_tile.items():
        img = _DEM_IMG_CACHE.get((x, y))
        if img is None:
            try:
                resp = await client.get(f"/dem/{_DEM_ZOOM}/{x}/{y}.webp")
                if resp.status_code != 200:
                    continue
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                if len(_DEM_IMG_CACHE) >= _DEM_IMG_CACHE_MAX:
                    _DEM_IMG_CACHE.clear()
                _DEM_IMG_CACHE[(x, y)] = img
            except Exception:
                continue
        for i, px, py in refs:
            r, g, b = img.getpixel((px, py))
            out[i] = (r * 256 + g + b / 256) - 32768
    return out


async def coverage_ring(lat: float, lon: float, radius_m: float,
                        target_h_m: float = _DEFAULT_TARGET_HEIGHT_M
                        ) -> Optional[dict]:
    """LOS coverage for one band: {"ring": [[lon, lat] * _N_RAYS],
    "crest_tan": [tan(alpha) * _N_RAYS]}. ring is the ground-level
    reach boundary; crest_tan is the masking crest's elevation-angle
    tangent per ray (0 on open ground) — the 3D envelope carves its
    dead space under h = x * crest_tan. None when the DEM is
    unreadable (caller keeps the circle)."""
    import json as _json
    key = (round(lat, 4), round(lon, 4), int(radius_m), int(target_h_m))
    hit = _COVERAGE_CACHE.get(key)
    if hit is not None:
        return hit
    conn = _coverage_store()
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT payload FROM coverage3 WHERE lat=? AND lon=? AND "
                "radius_m=? AND target_h=?", key).fetchone()
            if row:
                out = _json.loads(row[0])
                if len(_COVERAGE_CACHE) >= _COVERAGE_CACHE_MAX:
                    _COVERAGE_CACHE.clear()
                _COVERAGE_CACHE[key] = out
                return out
        except Exception:
            pass

    coslat = math.cos(math.radians(lat)) or 1e-9
    # Sample grid: per ray, points from center out to radius.
    pts: List[Tuple[float, float]] = [(lat, lon)]
    for i in range(_N_RAYS):
        th = 2.0 * math.pi * i / _N_RAYS
        for k in range(1, _SAMPLES_PER_RAY + 1):
            r = radius_m * k / _SAMPLES_PER_RAY
            pts.append((lat + (r * math.cos(th)) / 111320.0,
                        lon + (r * math.sin(th)) / (111320.0 * coslat)))
    elev = await _elevations(pts)
    if elev[0] is None:
        return None
    eye = elev[0] + _SENSOR_HEIGHT_M

    ring: List[List[float]] = []
    crests: List[float] = []
    for i in range(_N_RAYS):
        th = 2.0 * math.pi * i / _N_RAYS
        # Walk out along the ray keeping the max angular obstruction;
        # a sample is visible while its sightline clears every crest
        # before it. Reach = last visible sample.
        max_tan = -math.inf
        blocked_at = None
        for k in range(1, _SAMPLES_PER_RAY + 1):
            e = elev[1 + i * _SAMPLES_PER_RAY + (k - 1)]
            if e is None:
                continue
            d = radius_m * k / _SAMPLES_PER_RAY
            crest_tan = (e - eye) / d
            target_tan = (e + target_h_m - eye) / d
            if target_tan < max_tan:
                blocked_at = k
                break
            if crest_tan > max_tan:
                max_tan = crest_tan
        reach_k = (blocked_at - 1) if blocked_at else _SAMPLES_PER_RAY
        reach_k = max(1, reach_k)
        r = radius_m * reach_k / _SAMPLES_PER_RAY
        ring.append([lon + (r * math.sin(th)) / (111320.0 * coslat),
                     lat + (r * math.cos(th)) / 111320.0])
        # The dead-space boundary the 3D envelope carves under:
        # targets along this azimuth are masked below h = x * tan(a).
        # Open ground (nothing above the sightline) carves nothing.
        crests.append(round(max(max_tan, 0.0), 5))
    out = {"ring": ring, "crest_tan": crests}
    if conn is not None:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO coverage3 (lat, lon, radius_m, "
                "target_h, payload) VALUES (?, ?, ?, ?, ?)",
                (*key, _json.dumps(out)))
            conn.commit()
        except Exception:
            pass
    if len(_COVERAGE_CACHE) >= _COVERAGE_CACHE_MAX:
        _COVERAGE_CACHE.clear()
    _COVERAGE_CACHE[key] = out
    return out

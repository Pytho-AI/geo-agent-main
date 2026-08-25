"""Web-mercator tile math — shared by any server-side tile decoder.

Kept dependency-free (pure math) so the geocoder, the locator renderer,
and future tile consumers share ONE correct implementation of the
lon/lat <-> tile transforms instead of each carrying their own copy.
The `pois`-layer peak sweep (api/v1/terrain.py) predates this module and
still inlines its own equivalents; new decoders use these.
"""
from __future__ import annotations

import math
from typing import Tuple

WEB_MERCATOR_LAT_LIMIT = 85.05112878


def lonlat_to_tile_xy(lon: float, lat: float, z: int) -> Tuple[float, float]:
    """Fractional tile coordinates for a lon/lat at zoom z."""
    lat = max(-WEB_MERCATOR_LAT_LIMIT, min(WEB_MERCATOR_LAT_LIMIT, lat))
    n = 2 ** z
    xf = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    yf = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n
    return xf, yf


def tile_range(w: float, s: float, e: float, n: float, z: int):
    """Integer tile x/y range (inclusive) covering a lon/lat bbox at zoom z.

    Returns (x0, x1, y0, y1). North latitude maps to the smaller y.
    """
    x0f, y0f = lonlat_to_tile_xy(w, n, z)
    x1f, y1f = lonlat_to_tile_xy(e, s, z)
    return int(math.floor(x0f)), int(math.floor(x1f)), \
        int(math.floor(y0f)), int(math.floor(y1f))


def tile_count(w: float, s: float, e: float, n: float, z: int) -> int:
    x0, x1, y0, y1 = tile_range(w, s, e, n, z)
    return max(0, x1 - x0 + 1) * max(0, y1 - y0 + 1)


def pick_zoom_for_bbox(w: float, s: float, e: float, n: float,
                       budget: int, zmin: int = 2, zmax: int = 12) -> int:
    """Highest zoom whose tile count over the bbox stays within `budget`.

    Higher zoom pulls in smaller places (villages appear only in deep
    tiles), so we want the deepest sweep the budget allows. A tiny bbox
    saturates at zmax; a continental bbox falls back toward zmin (only
    the low-`min_zoom` countries/cities exist in those tiles anyway).
    """
    chosen = zmin
    for z in range(zmin, zmax + 1):
        if tile_count(w, s, e, n, z) <= budget:
            chosen = z
        else:
            break
    return chosen


def mvt_point_to_lonlat(px: float, py: float, x: int, y: int, z: int,
                        extent: int) -> Tuple[float, float]:
    """Decode an MVT point (mapbox_vector_tile Cartesian, origin
    bottom-left) inside tile (z/x/y) to lon/lat."""
    n = 2 ** z
    lon = (x + px / extent) / n * 360.0 - 180.0
    yf = (y + (1.0 - py / extent)) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yf))))
    return lon, lat


def tile_to_lonlat(x: float, y: float, z: int) -> Tuple[float, float]:
    """Lon/lat of a fractional tile coordinate's top-left (or any
    fractional point) at zoom z — inverse of lonlat_to_tile_xy."""
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat

"""Spot-height peaks + elevations — INTERNAL API.

Feeds the map UI's spot-height layer. Peaks live in the planet vector
tiles' `pois` layer, but ONLY in tiles at zoom 11 and deeper — so a
client rendering an operational-scale view (product renders sit near
1:250,000 and coarser) has no peak data in the tiles it loads. This
endpoint decodes the z11 tiles COVERING a bbox server-side, regardless
of the caller's view zoom, joins elevations from the same Mapterhorn
Terrarium DEM that drives the hillshade and contours (through the
tilecache's /dem block — shared 365-day disk cache, air-gap-friendly),
and returns render-ready points. This replaced a five-peak fixture
hard-coded to one area of operations, which is why spot heights used
to exist nowhere else.

    GET /api/v1/terrain/peaks?bbox=w,s,e,n
    -> { "peaks": [ { "name", "lon", "lat", "elevation_m" }, ... ],
         "truncated": bool }

Results sort by elevation descending (the most prominent summits
survive the cap — the doctrinally interesting ones).
"""

import asyncio
import asyncio
import gzip
import io
import json
import os
import sqlite3
import logging
import math
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
log = logging.getLogger("app.terrain")

# Peaks appear in the planet pois layer from this zoom — and ONLY from
# this zoom (verified z7-z10 tiles over the Everest massif carry zero
# peak pois), so there is no lower-zoom shortcut for wide views: the
# sweep is always at z11.
_PEAK_TILE_ZOOM = 11
# Full-decode budget. A fullscreen z10 view needs ~300 z11 tiles; the
# per-tile decode cache below makes warm repeats free.
_MAX_TILES = 320
# Wider views (z <= ~9.5 fullscreen) exceed the budget: decode an EVEN
# spatial stride across the grid instead of a west-edge slice (the
# original `tiles[:cap]` truncation covered a sliver of the viewport
# and returned zero peaks for everything east of it), flag truncated.
_MAX_PEAKS = 120
# Mapterhorn maxzoom is 12 — native resolution for the elevation join.
_DEM_ZOOM = 12
_DEM_TILE_PX = 512


def _tile_range(w: float, s: float, e: float, n: float, z: int):
    def tx(lon):
        return (lon + 180.0) / 360.0 * (2 ** z)

    def ty(lat):
        r = math.radians(max(-85.06, min(85.06, lat)))
        return (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * (2 ** z)

    x0, x1 = int(tx(w)), int(tx(e))
    y0, y1 = int(ty(n)), int(ty(s))
    return x0, x1, y0, y1


def _mvt_point_to_lonlat(px: float, py: float, x: int, y: int, z: int,
                         extent: int) -> tuple[float, float]:
    # mapbox_vector_tile decodes with a Cartesian y axis (origin
    # bottom-left of the tile), so flip back into tile-row space first.
    n = 2 ** z
    lon = (x + px / extent) / n * 360.0 - 180.0
    yf = (y + (1.0 - py / extent)) / n
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yf))))
    return lon, lat


def _dem_tile_and_pixel(lon: float, lat: float) -> tuple[int, int, int, int]:
    n = 2 ** _DEM_ZOOM
    xf = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    yf = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n
    x, y = int(xf), int(yf)
    px = max(0, min(_DEM_TILE_PX - 1, int((xf - x) * _DEM_TILE_PX)))
    py = max(0, min(_DEM_TILE_PX - 1, int((yf - y) * _DEM_TILE_PX)))
    return x, y, px, py


# Decoded DEM tile images — immutable per planet build; adjacent peaks
# tiles share DEM tiles at their borders and every repaint used to
# re-fetch + re-decode them per request.
_DEM_IMG_CACHE: dict[tuple[int, int], object] = {}
_DEM_IMG_CACHE_MAX = 2048


async def _join_elevations(peaks: list[dict]) -> None:
    """Fill elevation_m in place from the DEM (grouped per tile)."""
    try:
        from PIL import Image
    except ImportError:
        return
    from app.api.v1.tiles import _get_client

    by_tile: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for i, p in enumerate(peaks):
        # Entries that already carry a surveyed elevation (volcano ele
        # tags) keep it — the DEM fills only the gaps.
        if p.get("elevation_m") is not None:
            continue
        x, y, px, py = _dem_tile_and_pixel(p["lon"], p["lat"])
        by_tile[(x, y)].append((i, px, py))

    client = _get_client()
    for (x, y), refs in by_tile.items():
        try:
            img = _DEM_IMG_CACHE.get((x, y))
            if img is None:
                resp = await client.get(f"/dem/{_DEM_ZOOM}/{x}/{y}.webp")
                if resp.status_code != 200:
                    continue
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                if len(_DEM_IMG_CACHE) >= _DEM_IMG_CACHE_MAX:
                    _DEM_IMG_CACHE.clear()
                _DEM_IMG_CACHE[(x, y)] = img
            for i, px, py in refs:
                # A peak is a LOCAL MAX — the single pixel at ~76 m
                # resolution smooths sharp summits under their true
                # elevation; take the max over a 5x5 neighborhood.
                best = None
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        qx = min(_DEM_TILE_PX - 1, max(0, px + dx))
                        qy = min(_DEM_TILE_PX - 1, max(0, py + dy))
                        r, g, b = img.getpixel((qx, qy))
                        # Terrarium encoding.
                        val = (r * 256 + g + b / 256) - 32768
                        if best is None or val > best:
                            best = val
                if best is not None:
                    peaks[i]["elevation_m"] = round(best, 1)
        except Exception as exc:
            log.debug("elevation tile %s/%s lookup failed: %s", x, y, exc)


# Decoded peaks per tile — static per planet build, so cache decoded
# results in-process (the tilecache already caches the raw pbf bytes;
# this skips the protobuf decode on warm views). Simple dict cache with
# FIFO eviction; a full z10 fullscreen view is ~320 entries.
_TILE_PEAK_CACHE: dict[tuple[int, int], list[dict]] = {}
_TILE_PEAK_CACHE_MAX = 8192

# Mountains do not move. A tile's peaks (WITH joined elevations) are
# processed exactly ONCE per deployment and persisted to the data
# volume — restarts and deploys read them back from disk; the decode +
# DEM join never runs twice for the same ground. The in-memory dict
# above is just the hot layer over this store.
_PEAK_STORE: Optional[sqlite3.Connection] = None


def _peak_store() -> Optional[sqlite3.Connection]:
    global _PEAK_STORE
    if _PEAK_STORE is None:
        try:
            base = os.environ.get("GEO_DATA_DIR", "/app/data")
            os.makedirs(base, exist_ok=True)
            conn = sqlite3.connect(
                os.path.join(base, "peaks_store.sqlite"),
                check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS peak_tiles ("
                "z INTEGER, x INTEGER, y INTEGER, peaks TEXT, "
                "PRIMARY KEY (z, x, y))")
            conn.commit()
            _PEAK_STORE = conn
        except Exception as exc:
            log.warning("peaks store unavailable (%s) — falling back to "
                        "in-process cache only", exc)
            _PEAK_STORE = None
    return _PEAK_STORE


def _store_get(x: int, y: int) -> Optional[list[dict]]:
    conn = _peak_store()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT peaks FROM peak_tiles WHERE z=? AND x=? AND y=?",
            (_PEAK_TILE_ZOOM, x, y)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _store_put(x: int, y: int, peaks: list[dict]) -> None:
    conn = _peak_store()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO peak_tiles (z, x, y, peaks) "
            "VALUES (?, ?, ?, ?)",
            (_PEAK_TILE_ZOOM, x, y, json.dumps(peaks)))
        conn.commit()
    except Exception as exc:
        log.debug("peaks store write failed %s/%s: %s", x, y, exc)

# Volcano summits — SUPPLEMENT to the tile sweep. The Protomaps pois
# schema ingests `natural` only for peak and beach (verified in the
# basemaps source, layers/Pois.java: zero `volcano` handling anywhere),
# so volcano-tagged summits — Mount Fuji, Rainier, Etna — can NEVER
# come from the planet tiles. They come from a CHECKED-IN global
# catalog (backend/app/data/volcanoes.json, ~4900 named summits,
# regenerated by scripts/generate_volcano_catalog.py) filtered locally
# per bbox. A per-request Overpass supplement was tried first and cut:
# both public mirrors 504/time out from cloud egress IPs, and a
# per-request third-party dependency has no place in an
# air-gap-deployable service. Entries prefer the node's surveyed `ele`
# (volcano nodes sit on the crater rim, often hundreds of meters from
# the true summit, so the windowed DEM read under-measures badly —
# Fuji: 3543 from the DEM window vs its surveyed 3776 — and a surveyed
# spot elevation is what a real sheet prints anyway); the DEM join
# fills any without one.
_VOLCANO_CATALOG: Optional[list[dict]] = None


def _volcano_catalog() -> list[dict]:
    global _VOLCANO_CATALOG
    if _VOLCANO_CATALOG is None:
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "data" / "volcanoes.json"
        try:
            _VOLCANO_CATALOG = json.loads(path.read_text())
        except Exception as exc:
            log.warning("volcano catalog unavailable (%s): %s", path, exc)
            _VOLCANO_CATALOG = []
    return _VOLCANO_CATALOG


def _volcanoes_in_bbox(w: float, s: float, e: float, n: float) -> list[dict]:
    return [
        {"name": v["name"], "lon": v["lon"], "lat": v["lat"],
         "elevation_m": v.get("ele")}
        for v in _volcano_catalog()
        if w <= v["lon"] <= e and s <= v["lat"] <= n
    ]


async def _peaks_in_tile(client, x: int, y: int) -> list[dict]:
    key = (x, y)
    cached = _TILE_PEAK_CACHE.get(key)
    if cached is not None:
        return cached
    stored = _store_get(x, y)
    if stored is not None:
        if len(_TILE_PEAK_CACHE) >= _TILE_PEAK_CACHE_MAX:
            _TILE_PEAK_CACHE.clear()
        _TILE_PEAK_CACHE[key] = stored
        return stored
    import mapbox_vector_tile
    out: list[dict] = []
    try:
        resp = await client.get(f"/data/basemap/{_PEAK_TILE_ZOOM}/{x}/{y}.pbf")
        if resp.status_code == 200 and resp.content:
            data = resp.content
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            decoded = mapbox_vector_tile.decode(data)
            pois = decoded.get("pois")
            if pois:
                extent = pois.get("extent", 4096)
                for f in pois.get("features", []):
                    props = f.get("properties") or {}
                    if props.get("kind") != "peak":
                        continue
                    name = props.get("name:en") or props.get("name")
                    if not name:
                        continue
                    geom = f.get("geometry") or {}
                    if geom.get("type") != "Point":
                        continue
                    px, py = geom.get("coordinates", (None, None))
                    if px is None:
                        continue
                    lon, lat = _mvt_point_to_lonlat(
                        px, py, x, y, _PEAK_TILE_ZOOM, extent)
                    out.append({"name": str(name), "lon": round(lon, 6),
                                "lat": round(lat, 6), "elevation_m": None})
    except Exception as exc:
        log.debug("peak tile %s/%s decode failed: %s", x, y, exc)
        return out  # NOT cached — transient fetch failures get retried
    # Join elevations ONCE, at decode time, so the cached tile carries
    # them — the endpoint used to copy cached dicts before joining,
    # which re-ran the whole DEM join on EVERY request forever.
    await _join_elevations(out)
    _store_put(x, y, out)
    if len(_TILE_PEAK_CACHE) >= _TILE_PEAK_CACHE_MAX:
        _TILE_PEAK_CACHE.clear()
    _TILE_PEAK_CACHE[key] = out
    return out


@router.get("/coverage")
async def terrain_coverage(
    lat: float = Query(...), lon: float = Query(...),
    radius_m: float = Query(..., gt=0),
    target_h: float = Query(10.0, ge=0, le=1000),
) -> dict:
    """Terrain-derived LOS coverage boundary for one envelope band —
    the ring is the flat-earth slice; this is the viewshed (design doc
    §6.7). Derived once per (position, range), persisted; the client
    fetches it for the SELECTED unit's bands only."""
    from app.services.view.coverage import coverage_ring
    out = await coverage_ring(lat, lon, radius_m, target_h_m=target_h)
    if out is None:
        return {"coverage": None, "crest_tan": None}
    return {"coverage": out["ring"], "crest_tan": out["crest_tan"]}


@router.get("/peaks")
async def peaks_in_bbox(
    bbox: str = Query(..., description="w,s,e,n (lon/lat)"),
) -> dict:
    try:
        import mapbox_vector_tile
    except ImportError as exc:
        raise HTTPException(status_code=503,
                            detail=f"vector tile decoder unavailable: {exc}")
    from app.api.v1.tiles import _get_client

    try:
        w, s, e, n = (float(v) for v in bbox.split(","))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"bad bbox: {exc}") from exc

    x0, x1, y0, y1 = _tile_range(w, s, e, n, _PEAK_TILE_ZOOM)
    nx, ny = (x1 - x0 + 1), (y1 - y0 + 1)
    total = nx * ny
    truncated = total > _MAX_TILES
    if truncated:
        # Even spatial stride across BOTH axes so the sample covers the
        # whole viewport uniformly.
        stride = math.ceil(math.sqrt(total / _MAX_TILES))
        tiles = [(x, y)
                 for x in range(x0, x1 + 1, stride)
                 for y in range(y0, y1 + 1, stride)][:_MAX_TILES]
    else:
        tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    client = _get_client()
    peaks: list[dict] = []
    seen: set[tuple[float, float]] = set()
    # Volcano supplement FIRST so a volcano summit wins the dedup over
    # any coincident tile poi.
    for peak in _volcanoes_in_bbox(w, s, e, n):
        lon, lat = peak["lon"], peak["lat"]
        if not (w <= lon <= e and s <= lat <= n):
            continue
        key = (round(lon, 4), round(lat, 4))
        if key in seen:
            continue
        seen.add(key)
        peaks.append(dict(peak))
    sem = asyncio.Semaphore(16)

    async def _one(x: int, y: int) -> list[dict]:
        async with sem:
            return await _peaks_in_tile(client, x, y)

    tile_results = await asyncio.gather(
        *[_one(x, y) for x, y in tiles])
    for tile_peaks in tile_results:
        for peak in tile_peaks:
            lon, lat = peak["lon"], peak["lat"]
            if not (w <= lon <= e and s <= lat <= n):
                continue
            key = (round(lon, 4), round(lat, 4))
            if key in seen:
                continue
            seen.add(key)
            peaks.append(dict(peak))

    await _join_elevations(peaks)
    peaks.sort(key=lambda p: (p["elevation_m"] is None,
                              -(p["elevation_m"] or 0)))
    if len(peaks) > _MAX_PEAKS:
        peaks = peaks[:_MAX_PEAKS]
        truncated = True
    return {"peaks": peaks, "truncated": truncated}

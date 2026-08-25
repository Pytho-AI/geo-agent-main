"""Tile endpoints — the single public surface for all map tiles.

geo-agent is THE map endpoint: consumers (pytho-app nginx, cloud, any
future service) forward /geo-api/* here and never touch the tileserver
or any tile cache themselves. Internally these routes proxy the stack's
tilecache container (infra/tilecache/nginx.conf), which fronts
tileserver-gl with an on-disk cache — tileserver-gl itself has no
persistent cache (its docs direct you to put a caching proxy in front).

Routes (match the paths the frontend's mapStyles.js and the /basemaps
catalog advertise):

    GET /api/v1/tiles/basemap/{default|terrain|topo}/{z}/{x}/{y}.jpg
    GET /api/v1/tiles/basemap/satellite/{z}/{x}/{y}.jpg
    GET /api/v1/tiles/vector/basemap/{z}/{x}/{y}.pbf
    GET /api/v1/tiles/dem/{z}/{x}/{y}.webp
    GET /api/v1/tiles/labels/{z}/{x}/{y}.png
    GET /api/v1/fonts/{fontstack}/{range}.pbf
"""

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Response

logger = logging.getLogger("app.tiles")

router = APIRouter()

# The internal tile cache (nginx fronting tileserver-gl). Compose sets
# this to http://tilecache:8080; for bare uvicorn dev runs, export
# TILECACHE_URL at whatever port you exposed the tilecache on (no
# compose service publishes one by default).
_TILECACHE_URL = os.environ.get("TILECACHE_URL", "http://tilecache:8080").rstrip("/")

# Shared async client — connection pooling across tile requests. MapLibre
# fires ~20 tile requests per pan; per-request clients would burn a TCP
# handshake each.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_TILECACHE_URL,
            timeout=httpx.Timeout(30.0, connect=5.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )
    return _client


_PASSTHROUGH_HEADERS = ("content-type", "cache-control", "etag", "last-modified", "x-cache-status")


async def _proxy(upstream_path: str) -> Response:
    try:
        resp = await _get_client().get(upstream_path)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"tile upstream unreachable: {exc}") from exc
    headers = {k: v for k, v in resp.headers.items() if k.lower() in _PASSTHROUGH_HEADERS}
    return Response(content=resp.content, status_code=resp.status_code, headers=headers)


@router.get("/tiles/basemap/satellite/{z}/{x}/{y}.jpg")
async def satellite_tile(z: int, x: int, y: int) -> Response:
    # ESRI World Imagery via the tilecache's /satellite block (which owns
    # the TMS y-flip and the upstream TLS config).
    return await _proxy(f"/satellite/{z}/{x}/{y}.jpg")


@router.get("/tiles/basemap/{style}/{z}/{x}/{y}.jpg")
async def basemap_tile(style: str, z: int, x: int, y: int) -> Response:
    if style not in ("default", "terrain", "topo"):
        raise HTTPException(status_code=404, detail=f"unknown basemap style: {style}")
    return await _proxy(f"/styles/{style}/{z}/{x}/{y}.jpg")


# ── Romanized label tiles ────────────────────────────────────────────
# The place-label symbol layers read name:en with a name fallback. The
# planet tiles carry native toponyms and only major places have
# name:en, so villages rendered native script/diacritics. The military
# map convention is romanized toponyms: inject an ASCII name:en into
# every named feature that lacks one, so the client's existing
# coalesce shows ASCII everywhere. Rewritten tiles are immutable —
# cached in-process.
_VECTOR_TILE_CACHE: dict = {}
_VECTOR_TILE_CACHE_MAX = 8192


def _romanize_label_tile(data: bytes) -> bytes:
    import gzip as _gzip

    import mapbox_vector_tile as mvt

    from app.services.geocode.service import romanize

    raw = data
    if raw[:2] == b"\x1f\x8b":
        raw = _gzip.decompress(raw)
    try:
        decoded = mvt.decode(raw, default_options={"y_coord_down": True})
    except TypeError:  # older mapbox_vector_tile API
        decoded = mvt.decode(raw, y_coord_down=True)
    changed = False
    layers = []
    for lname, layer in decoded.items():
        feats = layer.get("features", [])
        for f in feats:
            props = f.get("properties") or {}
            name = props.get("name")
            if not name:
                continue
            en = props.get("name:en") or props.get("name_en")
            best = en if (en and all(ord(c) < 128 for c in en)) \
                else romanize(en or name)
            if props.get("name:en") != best:
                props["name:en"] = best
                changed = True
        layers.append({"name": lname, "features": feats,
                       "extent": layer.get("extent", 4096)})
    if not changed:
        return data
    ext = layers[0]["extent"] if layers else 4096
    try:
        out = mvt.encode(layers, default_options={
            "y_coord_down": True, "quantize_bounds": None,
            "extents": ext})
    except TypeError:  # older mapbox_vector_tile API
        out = mvt.encode(layers, y_coord_down=True,
                         quantize_bounds=None, extents=ext)
    return out


@router.get("/tiles/vector/basemap/{z}/{x}/{y}.pbf")
async def vector_tile(z: int, x: int, y: int) -> Response:
    key = (z, x, y)
    cached = _VECTOR_TILE_CACHE.get(key)
    if cached is not None:
        return Response(content=cached,
                        media_type="application/x-protobuf",
                        headers={"cache-control": "public, max-age=86400"})
    upstream = await _proxy(f"/data/basemap/{z}/{x}/{y}.pbf")
    if upstream.status_code != 200 or not upstream.body:
        return upstream
    try:
        body = _romanize_label_tile(upstream.body)
    except Exception:
        logger.warning("label-tile romanization failed for %s/%s/%s — "
                       "serving the native tile", z, x, y, exc_info=True)
        body = upstream.body
    if len(_VECTOR_TILE_CACHE) >= _VECTOR_TILE_CACHE_MAX:
        _VECTOR_TILE_CACHE.clear()
    _VECTOR_TILE_CACHE[key] = body
    return Response(content=body, media_type="application/x-protobuf",
                    headers={"cache-control": "public, max-age=86400"})


@router.get("/tiles/dem/{z}/{x}/{y}.webp")
async def dem_tile(z: int, x: int, y: int) -> Response:
    # Mapterhorn Terrarium DEM via the tilecache's /dem block (which
    # owns the upstream TLS hop + the on-disk cache). Feeds the
    # CLIENT-SIDE contour source (frontend utils/contours.js) — the
    # same elevation data the tileserver styles reference for their
    # baked hillshade, proxied so the browser stays same-origin and
    # the tiles are air-gap-cacheable like every other tile shape.
    return await _proxy(f"/dem/{z}/{x}/{y}.webp")


@router.get("/tiles/labels/{z}/{x}/{y}.png")
async def labels_tile(z: int, x: int, y: int) -> Response:
    return await _proxy(f"/styles/labels/{z}/{x}/{y}.png")


@router.get("/fonts/{fontstack}/{range}.pbf")
async def glyphs(fontstack: str, range: str) -> Response:  # noqa: A002 - route param name
    # Glyph PBFs for MapLibre symbol layers (place labels). Served by
    # tileserver-gl's font endpoint; passthrough (uncached location).
    return await _proxy(f"/fonts/{fontstack}/{range}.pbf")


# --- Weather forecast raster tiles (the analyst weather overlay) ---
# Upstream is OpenWeatherMap Weather Maps 2.0; the layer codes (TA2,
# PR0, …) are that service's own identifiers. The wire path is plain
# /tiles/weather/{layer}/{z}/{x}/{y}?date=<unix>. The API key stays
# server-side (settings.owm_api_key — the existing OWM_API_KEY env
# knob); the browser never sees it.

_WEATHER_LAYERS = {
    "TA2", "TD2", "TS0", "TS10",           # temperature
    "PR0", "PAC0", "PA0", "PAR0", "PAS0",  # precipitation
    "SD0",                                  # snow depth
    "WS10", "WND",                          # wind
    "APM",                                  # pressure
    "HRD0",                                 # humidity
    "CL",                                   # clouds
}

# Custom palettes for full-coverage layers to make them more distinct.
_WEATHER_PALETTES = {
    "TA2": "-40:880088;-38:770099;-36:6600AA;-34:5500BB;-32:4400CC;-30:3300DD;-28:2211EE;-26:1122FF;-24:0033FF;-22:0044FF;-20:0055FF;-18:0066FF;-16:0077FF;-14:0088FF;-12:0099FF;-10:00AAFF;-8:00BBFF;-6:00CCFF;-4:00DDFF;-2:00EEFF;0:00FFFF;2:00FFDD;4:00FFBB;6:00FF99;8:00FF77;10:00FF55;12:22FF33;14:44FF11;16:66FF00;18:88FF00;20:AAFF00;22:CCFF00;24:EEFF00;26:FFFF00;28:FFEE00;30:FFCC00;32:FFAA00;34:FF8800;36:FF6600;38:FF4400;40:FF2200;42:FF0000;44:EE0000;46:DD0000;48:CC0000;50:880000",
}

@router.get("/tiles/weather/{layer}/{z}/{x}/{y}")
async def weather_tile(layer: str, z: int, x: int, y: int, date: int | None = None) -> Response:
    """Proxy weather raster tiles (OpenWeatherMap Weather Maps 2.0
    upstream), optional forecast timestamp (unix seconds) for the
    0-72h scrub.

    Rides the SAME tile plane as every other tile shape: this route
    validates + appends the server-side API key, then proxies the
    tilecache's /weather/ location (infra/tilecache/nginx.conf), which
    owns the upstream TLS hop and the on-disk cache — identical
    structure to the ESRI satellite proxy."""
    from app.config import get_settings
    api_key = get_settings().owm_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="OWM_API_KEY not configured")
    if layer not in _WEATHER_LAYERS:
        raise HTTPException(status_code=404, detail=f"Unknown weather layer: {layer}")

    # Weather-aligned caching, one rule: the upstream refreshes on a
    # ~10-minute cadence, so timestamps round DOWN to 600s and the
    # tilecache TTL is 10m (infra/tilecache/nginx.conf /weather/ block).
    # Rounding makes analysts in the same 10-minute window share cache
    # entries; because the rounded value advances every 10 minutes, the
    # cache KEY itself rolls forward with the weather — current and
    # forecast frames alike can never be served staler than one
    # upstream refresh.
    upstream = f"/weather/{layer}/{z}/{x}/{y}?appid={api_key}&fill_bound=false"
    if layer in _WEATHER_PALETTES:
        upstream += f"&palette={_WEATHER_PALETTES[layer]}"
    if date is not None:
        upstream += f"&date={date - (date % 600)}"
    return await _proxy(upstream)

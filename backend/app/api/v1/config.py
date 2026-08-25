"""
Configuration API endpoint.
Returns all type definitions, SIDC codes, symbols, and supported entity/overlay types.
This serves as the single source of truth for frontend configuration.
"""

import json
import os

from fastapi import APIRouter, Query
from typing import Dict, Any, List, Optional

from app.config import get_settings
from app.constants import (
    SIDC_AFFILIATION,
    SIDC_ECHELON,
    SIDC_STATUS,
    SIDC_UNIT_TYPE,
    AFFILIATION_KEYWORDS,
    ECHELON_KEYWORDS,
    OVERLAY_TYPES,
    OVERLAY_STYLES,
    ENTITY_TYPES,
    SYMBOL_SETS,
    get_all_symbols_cached,
    get_symbols_by_set,
    get_symbol_set_list,
    search_symbols,
)

router = APIRouter()


def _load_region_metadata() -> Optional[Dict[str, Any]]:
    """Load region.json from offline data directory if available."""
    settings = get_settings()
    if not settings.offline_mode:
        return None
    region_path = os.path.join(settings.offline_data_dir, "region.json")
    try:
        with open(region_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _detect_offline_basemaps() -> List[str]:
    """Detect which raster basemap MBTiles are available in the offline data dir."""
    settings = get_settings()
    if not settings.offline_mode:
        return []
    tiles_dir = os.path.join(settings.offline_data_dir, "tiles")
    available = []
    for layer in ("street", "satellite", "topo"):
        path = os.path.join(tiles_dir, f"basemap_{layer}.mbtiles")
        if os.path.isfile(path):
            available.append(layer)
    return available


@router.get("/basemaps")
async def get_basemaps() -> Dict[str, Any]:
    """
    Basemap catalog for the analyst-facing map surface.

    Returns the four server-rendered basemap raster tiles (default,
    terrain, topo, satellite) + the English label PNG overlay. Frontend
    populates its LayerSwitcher from this response and points MapLibre
    raster sources at the returned tile_urls. Zero tile bytes flow
    through this endpoint — metadata only.

    Basemap sources (server-side):
      - default + terrain + topo: tileserver-gl renders JPGs from
        Protomaps' public planet PMTiles (basemaps schema) with
        hillshade baked in from Mapterhorn's Terrarium DEM tile
        endpoint. topo additionally gets CLIENT-side contour lines
        (frontend utils/contours.js) — they are not in the raster.
      - satellite: nginx caches ESRI World Imagery tiles at
        server.arcgisonline.com; no local render.
    """
    return {
        "basemaps": [
            {
                "id": "default",
                "name": "Default",
                "minzoom": 0,
                "maxzoom": 14,
                "tile_url": "/geo-api/v1/tiles/basemap/default/{z}/{x}/{y}.jpg",
                "attribution": (
                    "Protomaps / OpenStreetMap contributors / "
                    "Mapterhorn / Copernicus"
                ),
            },
            {
                "id": "terrain",
                "name": "Terrain",
                "minzoom": 0,
                "maxzoom": 14,
                "tile_url": "/geo-api/v1/tiles/basemap/terrain/{z}/{x}/{y}.jpg",
                "attribution": (
                    "Protomaps / OpenStreetMap contributors / "
                    "Mapterhorn / Copernicus"
                ),
            },
            {
                "id": "topo",
                "name": "Topo",
                "minzoom": 0,
                "maxzoom": 14,
                "tile_url": "/geo-api/v1/tiles/basemap/topo/{z}/{x}/{y}.jpg",
                "attribution": (
                    "Protomaps / OpenStreetMap contributors / "
                    "Mapterhorn / Copernicus"
                ),
            },
            {
                "id": "satellite",
                "name": "Satellite",
                "minzoom": 0,
                "maxzoom": 19,
                "tile_url": "/geo-api/v1/tiles/basemap/satellite/{z}/{x}/{y}.jpg",
                "attribution": (
                    "Esri / DigitalGlobe / Earthstar Geographics / "
                    "CNES / Airbus / Maxar"
                ),
            },
        ],
        "labels": {
            "tile_url": "/geo-api/v1/tiles/labels/{z}/{x}/{y}.png",
            "attribution": (
                "Protomaps / OpenStreetMap contributors"
            ),
        },
    }


@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """
    Get application configuration including all type definitions.

    Returns all SIDC codes, overlay types, entity types, and keyword mappings
    that the frontend needs to render military symbols and validate input.

    In offline mode, also includes `region` with tile bounds and max zoom.

    Note: For symbols, use /config/symbols endpoints to avoid large payload.
    """
    settings = get_settings()
    result = {
        "sidc": {
            "affiliation": SIDC_AFFILIATION,
            "echelon": SIDC_ECHELON,
            "status": SIDC_STATUS,
            "unitType": SIDC_UNIT_TYPE,
        },
        "keywords": {
            "affiliation": AFFILIATION_KEYWORDS,
            "echelon": ECHELON_KEYWORDS,
        },
        "overlayTypes": OVERLAY_TYPES,
        "overlayStyles": OVERLAY_STYLES,
        "entityTypes": ENTITY_TYPES,
        "symbolSets": get_symbol_set_list(),
        "offlineMode": settings.offline_mode,
    }
    # Per-deployment first-open camera (settings.default_view =
    # "lng,lat,zoom"). Malformed values are dropped rather than shipping
    # a broken camera to every client.
    if settings.default_view:
        try:
            lng, lat, zoom = (float(x) for x in settings.default_view.split(","))
            result["defaultView"] = {"center": [lng, lat], "zoom": zoom}
        except (ValueError, TypeError):
            pass
    region = _load_region_metadata()
    if region:
        result["region"] = region
    basemaps = _detect_offline_basemaps()
    if basemaps:
        result["offlineBasemaps"] = basemaps
    return result


@router.get("/config/sidc")
async def get_sidc_config() -> Dict[str, Any]:
    """Get SIDC-related configuration only."""
    return {
        "affiliation": SIDC_AFFILIATION,
        "echelon": SIDC_ECHELON,
        "status": SIDC_STATUS,
        "unitType": SIDC_UNIT_TYPE,
    }


@router.get("/config/overlays")
async def get_overlay_config() -> Dict[str, Any]:
    """Get overlay types configuration only."""
    return {
        "types": OVERLAY_TYPES,
        "styles": OVERLAY_STYLES,
    }


@router.get("/config/entities")
async def get_entity_config() -> Dict[str, Any]:
    """Get entity types configuration only."""
    return {
        "types": ENTITY_TYPES,
    }


@router.get("/config/symbols")
async def get_symbols_config(
    symbol_set: Optional[str] = Query(None, description="Filter by symbol set code (e.g., '10' for Land Unit)")
) -> Dict[str, Any]:
    """
    Get all MIL-STD-2525D symbols.
    
    Optionally filter by symbol set code:
    - 01: Air
    - 02: Air Missile
    - 05: Space
    - 06: Space Missile
    - 10: Land Unit
    - 11: Land Civilian
    - 15: Land Equipment
    - 20: Land Installation
    - 25: Control Measure
    - 30: Sea Surface
    - 35: Sea Subsurface
    - 36: Mine Warfare
    - 40: Activities
    - 50: Signals Intelligence
    - 60: Cyberspace
    """
    if symbol_set:
        symbols = get_symbols_by_set(symbol_set)
        set_info = SYMBOL_SETS.get(symbol_set, {})
        return {
            "symbolSet": symbol_set,
            "symbolSetName": set_info.get("name", "Unknown"),
            "symbols": symbols,
            "count": len(symbols),
        }
    else:
        symbols = get_all_symbols_cached()
        return {
            "symbolSets": get_symbol_set_list(),
            "symbols": symbols,
            "count": len(symbols),
        }


@router.get("/config/symbols/search")
async def search_symbols_endpoint(
    q: str = Query(..., description="Search query"),
    symbol_set: Optional[str] = Query(None, description="Filter by symbol set code"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return")
) -> Dict[str, Any]:
    """
    Search symbols by name or keywords.
    
    Returns symbols matching the query, sorted by relevance.
    The first result is the best match across all symbol sets.
    
    Use limit=1 to get just the best match (for auto-detection).
    """
    results = search_symbols(q, symbol_set=symbol_set, limit=limit)
    return {
        "query": q,
        "symbolSet": symbol_set,
        "results": results,
        "count": len(results),
        "bestMatch": results[0] if results else None,
    }


@router.get("/config/symbols/sets")
async def get_symbol_sets() -> List[Dict[str, str]]:
    """Get list of all available symbol sets."""
    return get_symbol_set_list()


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

@router.get("/config/cache")
async def get_cache_stats() -> Dict[str, Any]:
    """Get spatial data cache statistics."""
    from app.services.knowledge.cache import spatial_cache
    return spatial_cache.stats()


@router.delete("/config/cache")
async def clear_cache(
    map_id: Optional[str] = Query(None, description="Clear cache for a specific map, or all if omitted"),
    namespace: Optional[str] = Query(None, description="Clear a specific namespace (viewport_roads, viewport_elevation, viewport_landcover, location_context)"),
) -> Dict[str, Any]:
    """Clear the spatial data cache."""
    from app.services.knowledge.cache import spatial_cache

    if namespace and map_id:
        count = spatial_cache.clear(namespace, map_id)
    elif namespace:
        count = spatial_cache.clear(namespace)
    elif map_id:
        count = spatial_cache.clear_map(map_id)
    else:
        count = spatial_cache.clear_all()

    return {"cleared": count}

"""
Terrain analysis using AWS Terrain Tiles.

Tiles are in Terrarium format:
  elevation = (red * 256 + green + blue / 256) - 32768

Tile server: https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
"""

import asyncio
import logging
import math
import os
import sqlite3
import httpx
from typing import Tuple, Optional
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)

TERRAIN_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

_terrain_db: Optional[sqlite3.Connection] = None


def _get_terrain_db() -> sqlite3.Connection:
    """Open (and cache) the offline terrain MBTiles database."""
    global _terrain_db
    if _terrain_db is None:
        settings = get_settings()
        db_path = os.path.join(settings.offline_data_dir, "tiles", "terrain.mbtiles")
        _terrain_db = sqlite3.connect(db_path, check_same_thread=False)
    return _terrain_db


def _fetch_terrain_tile_offline(zoom: int, x: int, y: int) -> Optional[bytes]:
    """Read a terrain tile from the local MBTiles file."""
    db = _get_terrain_db()
    tms_y = (2 ** zoom - 1) - y  # MBTiles uses TMS y-flip
    row = db.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (zoom, x, tms_y),
    ).fetchone()
    return row[0] if row else None


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Convert lat/lon to tile x,y at given zoom level"""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_lat_lon(x: int, y: int, zoom: int) -> Tuple[float, float]:
    """Convert tile x,y to lat/lon (top-left corner)"""
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


async def get_elevation(lat: float, lon: float, zoom: int = 12) -> Optional[float]:
    """
    Get elevation at a point using AWS Terrain Tiles.

    Returns elevation in meters, or None if unavailable.
    In offline mode, reads from local MBTiles.
    """
    try:
        from PIL import Image
        import io

        x, y = lat_lon_to_tile(lat, lon, zoom)

        settings = get_settings()
        if settings.offline_mode:
            tile_data = _fetch_terrain_tile_offline(zoom, x, y)
            if tile_data is None:
                return None
        else:
            url = TERRAIN_TILE_URL.format(z=zoom, x=x, y=y)
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
            tile_data = response.content

        img = Image.open(io.BytesIO(tile_data))

        # Calculate pixel position within tile
        tile_lat, tile_lon = tile_to_lat_lon(x, y, zoom)
        next_lat, next_lon = tile_to_lat_lon(x + 1, y + 1, zoom)

        px = int((lon - tile_lon) / (next_lon - tile_lon) * 256)
        py = int((tile_lat - lat) / (tile_lat - next_lat) * 256)

        px = max(0, min(255, px))
        py = max(0, min(255, py))

        r, g, b = img.getpixel((px, py))[:3]

        # Terrarium encoding
        elevation = (r * 256 + g + b / 256) - 32768
        return elevation

    except ImportError:
        return None
    except Exception:
        return None


async def get_elevation_profile(
    points: list[Tuple[float, float]],
    zoom: int = 12
) -> list[Optional[float]]:
    """
    Get elevation for multiple points efficiently.
    Groups points by tile and fetches all tiles in parallel.
    """
    if not points:
        return []
    
    from PIL import Image
    import io
    
    # Group points by tile
    tile_points: dict[Tuple[int, int], list[Tuple[int, float, float]]] = {}
    for i, (lat, lon) in enumerate(points):
        tile_x, tile_y = lat_lon_to_tile(lat, lon, zoom)
        key = (tile_x, tile_y)
        if key not in tile_points:
            tile_points[key] = []
        tile_points[key].append((i, lat, lon))
    
    results: list[Optional[float]] = [None] * len(points)
    logger.info(f"    Elevation: {len(points)} points -> {len(tile_points)} tiles (zoom {zoom})")
    
    async def fetch_tile(tile_key: Tuple[int, int], indexed_points: list):
        """Fetch a single tile and extract elevations for its points."""
        tile_x, tile_y = tile_key
        try:
            settings = get_settings()
            if settings.offline_mode:
                tile_data = _fetch_terrain_tile_offline(zoom, tile_x, tile_y)
                if tile_data is None:
                    return []
            else:
                async with httpx.AsyncClient() as client:
                    url = TERRAIN_TILE_URL.format(z=zoom, x=tile_x, y=tile_y)
                    response = await client.get(url)
                    response.raise_for_status()
                tile_data = response.content

            img = Image.open(io.BytesIO(tile_data))
            
            tile_lat, tile_lon = tile_to_lat_lon(tile_x, tile_y, zoom)
            next_lat, next_lon = tile_to_lat_lon(tile_x + 1, tile_y + 1, zoom)
            
            tile_results = []
            for idx, lat, lon in indexed_points:
                px = int((lon - tile_lon) / (next_lon - tile_lon) * 256)
                py = int((tile_lat - lat) / (tile_lat - next_lat) * 256)
                px = max(0, min(255, px))
                py = max(0, min(255, py))
                
                r, g, b = img.getpixel((px, py))[:3]
                elevation = (r * 256 + g + b / 256) - 32768
                tile_results.append((idx, elevation))
            
            return tile_results
        except Exception:
            return []
    
    # Fetch all tiles in parallel
    tile_tasks = [fetch_tile(key, pts) for key, pts in tile_points.items()]
    tile_results = await asyncio.gather(*tile_tasks)
    
    # Combine results
    for tile_result in tile_results:
        for idx, elevation in tile_result:
            results[idx] = elevation
    
    return results


# Simple terrain analysis functions

def calculate_slope(elev1: float, elev2: float, distance_m: float) -> float:
    """Calculate slope between two points as percent grade (rise/run * 100)."""
    if distance_m == 0:
        return 0
    rise = elev2 - elev1
    return (rise / distance_m) * 100


from app.services.knowledge.geo_utils import haversine as haversine_distance

"""
Land cover classification using ESA WorldCover data from AWS S3.

ESA WorldCover provides global 10m resolution land cover maps.
Data is stored as Cloud Optimized GeoTIFFs (COG) in 3°x3° tiles.

Bucket: s3://esa-worldcover/v200/2021/map/
File pattern: ESA_WorldCover_10m_2021_v200_N{lat}_E{lon}_Map.tif

Land cover classes:
    10 = Tree cover
    20 = Shrubland  
    30 = Grassland
    40 = Cropland
    50 = Built-up
    60 = Bare / sparse vegetation
    70 = Snow and ice
    80 = Permanent water bodies
    90 = Herbaceous wetland
    95 = Mangroves
    100 = Moss and lichen
"""

import asyncio
import math
import logging
import os
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from app.config import get_settings

logger = logging.getLogger(__name__)

# ESA WorldCover classes
LAND_COVER_CLASSES: Dict[int, str] = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    70: "snow_ice",
    80: "water",
    90: "wetland",
    95: "mangroves",
    100: "moss_lichen",
    0: "no_data",
}

LAND_COVER_DISPLAY_NAMES: Dict[int, str] = {
    10: "Tree Cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up Area",
    60: "Bare/Sparse Vegetation",
    70: "Snow and Ice",
    80: "Permanent Water",
    90: "Herbaceous Wetland",
    95: "Mangroves",
    100: "Moss and Lichen",
    0: "No Data",
}

# Tactical properties of each land cover type
LAND_COVER_PROPERTIES: Dict[int, Dict[str, Any]] = {
    10: {  # Tree cover
        "concealment": "full",
        "cover": "partial",
        "trafficability_wheeled": "poor",
        "trafficability_tracked": "poor",
        "trafficability_infantry": "good",
        "observation": "blocked",
    },
    20: {  # Shrubland
        "concealment": "partial",
        "cover": "none",
        "trafficability_wheeled": "fair",
        "trafficability_tracked": "good",
        "trafficability_infantry": "good",
        "observation": "limited",
    },
    30: {  # Grassland
        "concealment": "none",
        "cover": "none",
        "trafficability_wheeled": "good",
        "trafficability_tracked": "excellent",
        "trafficability_infantry": "excellent",
        "observation": "clear",
    },
    40: {  # Cropland
        "concealment": "seasonal",
        "cover": "none",
        "trafficability_wheeled": "fair",
        "trafficability_tracked": "good",
        "trafficability_infantry": "good",
        "observation": "seasonal",
    },
    50: {  # Built-up
        "concealment": "full",
        "cover": "full",
        "trafficability_wheeled": "good",  # Roads
        "trafficability_tracked": "fair",  # Urban restricted
        "trafficability_infantry": "good",
        "observation": "blocked",
    },
    60: {  # Bare/sparse
        "concealment": "none",
        "cover": "none",
        "trafficability_wheeled": "good",
        "trafficability_tracked": "excellent",
        "trafficability_infantry": "excellent",
        "observation": "clear",
    },
    70: {  # Snow/ice
        "concealment": "none",
        "cover": "none",
        "trafficability_wheeled": "poor",
        "trafficability_tracked": "fair",
        "trafficability_infantry": "poor",
        "observation": "clear",
    },
    80: {  # Water
        "concealment": "none",
        "cover": "none",
        "trafficability_wheeled": "impassable",
        "trafficability_tracked": "impassable",
        "trafficability_infantry": "impassable",
        "observation": "clear",
    },
    90: {  # Wetland
        "concealment": "partial",
        "cover": "none",
        "trafficability_wheeled": "impassable",
        "trafficability_tracked": "poor",
        "trafficability_infantry": "poor",
        "observation": "limited",
    },
    95: {  # Mangroves
        "concealment": "full",
        "cover": "partial",
        "trafficability_wheeled": "impassable",
        "trafficability_tracked": "impassable",
        "trafficability_infantry": "poor",
        "observation": "blocked",
    },
    100: {  # Moss/lichen (Arctic/Alpine)
        "concealment": "none",
        "cover": "none",
        "trafficability_wheeled": "poor",
        "trafficability_tracked": "fair",
        "trafficability_infantry": "fair",
        "observation": "clear",
    },
}


@dataclass
class LandCoverResult:
    """Result of a land cover query."""
    code: int
    name: str
    display_name: str
    properties: Dict[str, Any]
    lat: float
    lon: float


def _get_tile_bounds(lat: float, lon: float) -> Tuple[int, int]:
    """
    Get the ESA WorldCover tile that contains a given lat/lon.
    
    Tiles are 3°x3° and named by their SW corner.
    Example: N12_E099 covers 12°N to 15°N, 99°E to 102°E
    
    Returns:
        Tuple of (tile_lat, tile_lon) for the SW corner
    """
    # Round down to nearest 3 degrees for tile SW corner
    tile_lat = int(math.floor(lat / 3) * 3)
    tile_lon = int(math.floor(lon / 3) * 3)
    return tile_lat, tile_lon


def _format_tile_name(tile_lat: int, tile_lon: int) -> str:
    """
    Format the tile filename for ESA WorldCover.
    
    Format: ESA_WorldCover_10m_2021_v200_N39W120_Map.tif
    Note: Uses N/S for latitude, E/W for longitude, NO underscore between them
    
    The tile designation is the 2-digit lat + 3-digit lon of the lower-left corner.
    Example: N39W120 = 39°N, 120°W
    """
    lat_prefix = "N" if tile_lat >= 0 else "S"
    lon_prefix = "E" if tile_lon >= 0 else "W"
    
    lat_str = f"{abs(tile_lat):02d}"
    lon_str = f"{abs(tile_lon):03d}"
    
    # No underscore between lat and lon: N39W120, not N39_W120
    return f"ESA_WorldCover_10m_2021_v200_{lat_prefix}{lat_str}{lon_prefix}{lon_str}_Map.tif"


def _get_pixel_position(lat: float, lon: float, tile_lat: int, tile_lon: int) -> Tuple[int, int]:
    """
    Calculate pixel position within a 3°x3° tile at 10m resolution.
    
    Each tile is approximately 33,333 x 33,333 pixels (3° / 0.00009° per pixel).
    Actually ESA uses 0.0000833333° (~10m at equator).
    
    Returns:
        Tuple of (row, col) pixel indices
    """
    # Pixel size in degrees (10m at equator ≈ 0.0000833333°)
    pixel_size = 1 / 12000  # 3° / 36000 pixels = 0.0000833...
    
    # Calculate offset from tile SW corner
    lat_offset = lat - tile_lat
    lon_offset = lon - tile_lon
    
    # Convert to pixel coordinates
    # Note: Row 0 is at the top (north), so we invert lat
    col = int(lon_offset / pixel_size)
    row = int((3 - lat_offset) / pixel_size)  # 3° tile height
    
    # Clamp to valid range (0 to 35999)
    col = max(0, min(35999, col))
    row = max(0, min(35999, row))
    
    return row, col


def _fetch_single_tile(
    tile_lat: int,
    tile_lon: int,
    points: list[Tuple[int, float, float]],
) -> list[Tuple[int, Optional[int]]]:
    """Fetch a single tile and extract land cover for its points."""
    try:
        import rasterio
        from rasterio.windows import Window
    except ImportError:
        return [(idx, None) for idx, _, _ in points]
    
    results = []

    try:
        tile_name = _format_tile_name(tile_lat, tile_lon)

        settings = get_settings()
        if settings.offline_mode:
            # ESA WorldCover 10m GeoTIFFs live under offline/landcover/
            # — the IDX26 preload pipeline downloads them to
            # `_work/worldcover/` as intermediate staging input for the
            # `worldcover-2021.mbtiles` tileserver layer, then we copy
            # the raw classification GeoTIFFs out to the loader path
            # (the mbtiles are colorized PNGs unusable for code lookup).
            # The historical `routing/landcover/` path was never populated
            # by any pipeline.
            tile_path = os.path.join(settings.offline_data_dir, "landcover", tile_name)
        else:
            base_url = "https://esa-worldcover.s3.amazonaws.com"
            tile_path = f"/vsicurl/{base_url}/v200/2021/map/{tile_name}"

        with rasterio.open(tile_path) as src:
            for idx, lat, lon in points:
                try:
                    row, col = _get_pixel_position(lat, lon, tile_lat, tile_lon)
                    window = Window(col, row, 1, 1)
                    data = src.read(1, window=window)
                    results.append((idx, int(data[0, 0])))
                except Exception:
                    results.append((idx, None))
    except Exception as e:
        logger.debug(f"Could not fetch tile ({tile_lat}, {tile_lon}): {e}")
        results = [(idx, None) for idx, _, _ in points]
    
    return results


def _fetch_land_cover_grid_sync(
    coords: list[Tuple[float, float]],
) -> list[Optional[int]]:
    """
    Fetch land cover for multiple points efficiently.
    Groups points by tile and fetches all tiles in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor
    
    # Group coords by tile
    tile_coords: Dict[Tuple[int, int], list[Tuple[int, float, float]]] = {}
    for i, (lat, lon) in enumerate(coords):
        tile_lat, tile_lon = _get_tile_bounds(lat, lon)
        key = (tile_lat, tile_lon)
        if key not in tile_coords:
            tile_coords[key] = []
        tile_coords[key].append((i, lat, lon))
    
    logger.info(f"    LandCover: {len(coords)} points -> {len(tile_coords)} tiles (3° each)")
    
    results = [None] * len(coords)
    
    # Fetch all tiles in parallel
    with ThreadPoolExecutor(max_workers=min(8, len(tile_coords))) as executor:
        futures = [
            executor.submit(_fetch_single_tile, tile_lat, tile_lon, points)
            for (tile_lat, tile_lon), points in tile_coords.items()
        ]
        
        for future in futures:
            for idx, code in future.result():
                results[idx] = code
    
    return results


async def get_land_cover_grid(
    coords: list[Tuple[float, float]],
) -> list[Optional[LandCoverResult]]:
    """
    Get land cover for multiple coordinates efficiently.
    Fetches each tile only once, then samples all points from it.
    
    Args:
        coords: List of (lat, lon) tuples
        
    Returns:
        List of LandCoverResult (or None) in same order as coords
    """
    # Run blocking rasterio in thread pool
    codes = await asyncio.to_thread(_fetch_land_cover_grid_sync, coords)
    
    results = []
    for i, code in enumerate(codes):
        if code is None:
            results.append(None)
        else:
            lat, lon = coords[i]
            name = LAND_COVER_CLASSES.get(code, "unknown")
            display_name = LAND_COVER_DISPLAY_NAMES.get(code, "Unknown")
            properties = LAND_COVER_PROPERTIES.get(code, {})
            results.append(LandCoverResult(
                code=code,
                name=name,
                display_name=display_name,
                properties=properties,
                lat=lat,
                lon=lon,
            ))
    
    return results


def get_concealment_level(land_cover_code: int) -> str:
    """Get concealment level for a land cover type."""
    props = LAND_COVER_PROPERTIES.get(land_cover_code, {})
    return props.get("concealment", "none")


def get_cover_level(land_cover_code: int) -> str:
    """Get cover (protection from fire) level for a land cover type."""
    props = LAND_COVER_PROPERTIES.get(land_cover_code, {})
    return props.get("cover", "none")

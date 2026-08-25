"""MGRS coordinate conversion utilities.

Provides helpers to convert between MGRS grid references and lat/lon,
and to post-process LLM-generated GeoJSON that uses MGRS strings
in place of [lon, lat] coordinate arrays.
"""

import logging
import re
from typing import Any, List, Tuple, Union

import mgrs

logger = logging.getLogger(__name__)

_converter = mgrs.MGRS()

# Pattern to detect an MGRS string (e.g. "36S YA 1234 5678" or "36SYA12345678")
# The easting/northing may be separated by a space (e.g. "7000 5000")
_MGRS_PATTERN = re.compile(
    r"^\d{1,2}[C-X]\s*[A-Z]{2}\s*\d{1,5}\s*\d{1,5}$", re.IGNORECASE
)


def latlng_to_mgrs(lat: float, lng: float, precision: int = 4) -> str:
    """Convert latitude/longitude to an MGRS string.

    Args:
        lat: Latitude in degrees.
        lng: Longitude in degrees.
        precision: MGRS precision 1-5 (4 = 10 m).

    Returns:
        MGRS string, e.g. "36S YA 1234 5678".
    """
    raw = _converter.toMGRS(lat, lng, MGRSPrecision=precision)
    # Format with spaces for readability: "36SYA12345678" -> "36S YA 1234 5678"
    return _format_mgrs(raw, precision)


def mgrs_to_latlng(mgrs_string: str) -> Tuple[float, float]:
    """Convert an MGRS string to (lat, lng).

    Args:
        mgrs_string: MGRS coordinate, e.g. "36S YA 1234 5678" or "36SYA12345678".

    Returns:
        Tuple of (latitude, longitude).
    """
    # Strip spaces — the mgrs library expects compact form
    compact = mgrs_string.replace(" ", "")
    lat, lng = _converter.toLatLon(compact)
    return (lat, lng)


def is_mgrs_string(value: Any) -> bool:
    """Check whether a value looks like an MGRS coordinate string."""
    if not isinstance(value, str):
        return False
    return bool(_MGRS_PATTERN.match(value.strip()))


def convert_mgrs_coordinates(coordinates: Any) -> Any:
    """Recursively convert MGRS strings in a GeoJSON coordinates structure to [lon, lat].

    Handles:
    - LineString: ["36S YA 1234 5678", "36S YA 2345 6789"] -> [[lon, lat], ...]
    - Polygon:   [["36S YA ...", ...]] -> [[[lon, lat], ...]]
    - Already-numeric coordinates are passed through unchanged.

    Returns:
        Converted coordinates in standard GeoJSON [lon, lat] format.
    """
    if isinstance(coordinates, str):
        # Single MGRS string -> [lon, lat]
        if is_mgrs_string(coordinates):
            lat, lng = mgrs_to_latlng(coordinates)
            return [round(lng, 6), round(lat, 6)]
        return coordinates

    if isinstance(coordinates, (list, tuple)):
        if len(coordinates) == 0:
            return coordinates

        first = coordinates[0]

        # Already a numeric coordinate pair [lon, lat] or [lon, lat, alt]
        if isinstance(first, (int, float)):
            return coordinates

        # Array of MGRS strings (LineString) or array of arrays (Polygon ring)
        return [convert_mgrs_coordinates(c) for c in coordinates]

    return coordinates


def convert_geojson_mgrs_to_latlng(geom: dict) -> dict:
    """Convert a GeoJSON geometry dict that may use MGRS strings for coordinates.

    Args:
        geom: GeoJSON geometry dict, e.g. {"type": "LineString", "coordinates": [...]}.

    Returns:
        Same dict with coordinates converted to [lon, lat] arrays.
    """
    if "coordinates" not in geom:
        return geom

    try:
        geom["coordinates"] = convert_mgrs_coordinates(geom["coordinates"])
    except Exception as e:
        logger.warning(f"Failed to convert MGRS coordinates: {e}")

    return geom


def _format_mgrs(raw: str, precision: int) -> str:
    """Format a compact MGRS string with spaces for readability.

    "36SYA12345678" -> "36S YA 1234 5678"
    """
    # Find the grid zone designator (digits + letter)
    match = re.match(r"(\d{1,2}[A-Z])([A-Z]{2})(\d+)", raw, re.IGNORECASE)
    if not match:
        return raw

    gzd, sq, numeric = match.groups()
    half = len(numeric) // 2
    easting = numeric[:half]
    northing = numeric[half:]
    return f"{gzd} {sq} {easting} {northing}"

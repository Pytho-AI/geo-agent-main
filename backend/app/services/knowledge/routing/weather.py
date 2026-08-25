"""Fetch OWM 5-day/3-hour forecasts along a route and summarize."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

import httpx

from app.config import get_settings
from app.services.knowledge.geo_utils import haversine
from app.services.knowledge.cache import spatial_cache
from .models import METERS_PER_MILE, MacroTile

logger = logging.getLogger(__name__)

# Limit concurrent OWM requests across all route planning calls
_owm_semaphore = asyncio.Semaphore(10)

# Shared HTTP client — reuses TCP connections across all OWM calls
_owm_client: Optional[httpx.AsyncClient] = None

def _get_owm_client() -> httpx.AsyncClient:
    global _owm_client
    if _owm_client is None or _owm_client.is_closed:
        _owm_client = httpx.AsyncClient(timeout=10.0)
    return _owm_client

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_CACHE_NAMESPACE = "owm_forecast"
OWM_CACHE_TTL = 1800  # 30 minutes
OWM_COORD_PRECISION = 2  # round lat/lon to 2 decimals (~1.1km)


def _sample_route_points(
    coords: List[Tuple[float, float]],
    n: int = 10,
) -> List[Dict[str, Any]]:
    """Pick N evenly-spaced points along the route by cumulative haversine distance.

    Args:
        coords: [(lon, lat), ...] path coordinates
        n: number of sample points

    Returns:
        List of {lat, lon, distance_along_mi} dicts
    """
    if len(coords) < 2:
        lon, lat = coords[0]
        return [{"lat": lat, "lon": lon, "distance_along_mi": 0.0}]

    # Build cumulative distance array
    cum_dist = [0.0]
    for i in range(1, len(coords)):
        seg = haversine(coords[i - 1][1], coords[i - 1][0],
                        coords[i][1], coords[i][0])
        cum_dist.append(cum_dist[-1] + seg)
    total_m = cum_dist[-1]
    total_mi = total_m / METERS_PER_MILE

    # Scale N based on route length
    if total_mi < 0.1:
        n = 1
    elif total_mi < 5:
        n = min(n, 3)
    elif total_mi < 20:
        n = min(n, 6)
    elif total_mi < 50:
        n = min(n, 10)
    elif total_mi < 100:
        n = min(n, 15)
    else:
        n = min(n, 20)

    n = max(1, n)

    points = []
    cursor = 0
    for i in range(n):
        target_m = (i / max(n - 1, 1)) * total_m if n > 1 else total_m / 2
        while cursor < len(cum_dist) - 1 and cum_dist[cursor] < target_m:
            cursor += 1
        lon, lat = coords[cursor]
        points.append({
            "lat": lat,
            "lon": lon,
            "distance_along_mi": round(cum_dist[cursor] / METERS_PER_MILE, 2),
        })

    return points


async def _fetch_owm_forecast(lat: float, lon: float) -> Optional[List[Dict]]:
    """Fetch OWM 5-day/3-hour forecast for a single point. Cached.

    Returns the `list` array from the OWM response (up to 40 forecast entries),
    or None on error.
    """
    settings = get_settings()
    api_key = settings.owm_api_key
    if not api_key:
        return None

    # Round coordinates for cache deduplication
    r_lat = round(lat, OWM_COORD_PRECISION)
    r_lon = round(lon, OWM_COORD_PRECISION)

    # Check cache
    cache_bbox = [r_lon, r_lat, r_lon, r_lat]
    cached = spatial_cache.get(OWM_CACHE_NAMESPACE, "global", cache_bbox)
    if cached is not None:
        return cached

    # Fetch from OWM (shared client — reuses TCP connections)
    url = f"{OWM_FORECAST_URL}?lat={r_lat}&lon={r_lon}&appid={api_key}&units=metric"
    async with _owm_semaphore:
        try:
            client = _get_owm_client()
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"OWM forecast {resp.status_code} for ({r_lat}, {r_lon})")
                return None
            data = resp.json()
            forecasts = data.get("list", [])
            spatial_cache.put(OWM_CACHE_NAMESPACE, "global", cache_bbox,
                              forecasts, ttl_seconds=OWM_CACHE_TTL)
            return forecasts
        except Exception as e:
            logger.warning(f"OWM forecast error for ({r_lat}, {r_lon}): {e}")
            return None


def _pick_closest_forecast(
    forecasts: List[Dict],
    target_dt: float,
) -> Optional[Dict]:
    """From OWM forecast list, pick the entry closest to target_dt (unix timestamp)."""
    if not forecasts:
        return None
    best = None
    best_diff = float("inf")
    for f in forecasts:
        diff = abs(f.get("dt", 0) - target_dt)
        if diff < best_diff:
            best_diff = diff
            best = f
    return best


def _extract_point_weather(forecast: Dict) -> Dict[str, Any]:
    """Extract weather fields from a single OWM forecast entry."""
    main = forecast.get("main", {})
    wind = forecast.get("wind", {})
    weather_list = forecast.get("weather", [{}])
    weather = weather_list[0] if weather_list else {}
    rain = forecast.get("rain", {})
    snow = forecast.get("snow", {})

    return {
        "condition": weather.get("main", "Unknown"),
        "description": weather.get("description", ""),
        "temp_c": main.get("temp"),
        "humidity_pct": main.get("humidity"),
        "wind_speed_ms": wind.get("speed"),
        "wind_gust_ms": wind.get("gust"),
        "wind_deg": wind.get("deg"),
        "visibility_m": forecast.get("visibility"),
        "precip_probability": forecast.get("pop"),
        "rain_3h_mm": rain.get("3h", 0.0),
        "snow_3h_mm": snow.get("3h", 0.0),
        "cloud_cover_pct": forecast.get("clouds", {}).get("all"),
        "forecast_time": forecast.get("dt_txt"),
    }


# Weather severity for picking the "worst" condition
_SEVERITY = {
    "Thunderstorm": 6, "Tornado": 6, "Squall": 5,
    "Snow": 4, "Rain": 3, "Drizzle": 2,
    "Mist": 1, "Fog": 1, "Haze": 1, "Smoke": 1, "Dust": 1, "Sand": 1,
    "Clouds": 0, "Clear": 0,
}

# Condition → color for the frontend weather bar
_CONDITION_COLORS = {
    "Clear": "#22c55e",        # green
    "Clouds": "#94a3b8",       # slate
    "Mist": "#cbd5e1", "Fog": "#cbd5e1", "Haze": "#cbd5e1",
    "Drizzle": "#60a5fa",      # light blue
    "Rain": "#3b82f6",         # blue
    "Snow": "#e2e8f0",         # white-ish
    "Thunderstorm": "#ef4444", # red
    "Squall": "#f97316",       # orange
    "Tornado": "#dc2626",      # dark red
}


def _build_segments(point_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group consecutive points with the same condition into segments.

    Each segment has: start_mi, end_mi, condition, color, temp_c, wind_speed_ms, description.
    """
    if not point_results:
        return []

    segments = []
    current = {
        "start_mi": point_results[0].get("distance_along_mi", 0),
        "condition": point_results[0].get("condition", "Unknown"),
        "description": point_results[0].get("description", ""),
        "color": _CONDITION_COLORS.get(point_results[0].get("condition", ""), "#94a3b8"),
        "temps": [],
        "winds": [],
    }
    if point_results[0].get("temp_c") is not None:
        current["temps"].append(point_results[0]["temp_c"])
    if point_results[0].get("wind_speed_ms") is not None:
        current["winds"].append(point_results[0]["wind_speed_ms"])

    for p in point_results[1:]:
        cond = p.get("condition", "Unknown")
        if cond == current["condition"]:
            # Extend current segment
            if p.get("temp_c") is not None:
                current["temps"].append(p["temp_c"])
            if p.get("wind_speed_ms") is not None:
                current["winds"].append(p["wind_speed_ms"])
        else:
            # Close current segment, start new one
            current["end_mi"] = p.get("distance_along_mi", 0)
            current["temp_c"] = round(sum(current["temps"]) / len(current["temps"]), 1) if current["temps"] else None
            current["wind_speed_ms"] = round(max(current["winds"]), 1) if current["winds"] else None
            del current["temps"], current["winds"]
            segments.append(current)

            current = {
                "start_mi": p.get("distance_along_mi", 0),
                "condition": cond,
                "description": p.get("description", ""),
                "color": _CONDITION_COLORS.get(cond, "#94a3b8"),
                "temps": [],
                "winds": [],
            }
            if p.get("temp_c") is not None:
                current["temps"].append(p["temp_c"])
            if p.get("wind_speed_ms") is not None:
                current["winds"].append(p["wind_speed_ms"])

    # Close last segment
    current["end_mi"] = point_results[-1].get("distance_along_mi", 0)
    current["temp_c"] = round(sum(current["temps"]) / len(current["temps"]), 1) if current["temps"] else None
    current["wind_speed_ms"] = round(max(current["winds"]), 1) if current["winds"] else None
    del current["temps"], current["winds"]
    segments.append(current)

    return segments


def _detect_hazards(point_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect hazardous segments along the route.

    Returns list of {type, severity, start_mi, end_mi, message} dicts.
    severity: "warning" (yellow) or "danger" (red).
    """
    hazards = []

    # Group consecutive points by hazard type
    def _flush_hazard(htype, severity, message, start_mi, end_mi):
        if start_mi == end_mi:
            hazards.append({"type": htype, "severity": severity,
                            "start_mi": start_mi, "end_mi": end_mi,
                            "message": f"At mi {start_mi}: {message}"})
        else:
            hazards.append({"type": htype, "severity": severity,
                            "start_mi": start_mi, "end_mi": end_mi,
                            "message": f"Mi {start_mi}-{end_mi}: {message}"})

    # Scan for each hazard type
    for htype, test_fn, severity, msg_fn in [
        ("ice_risk", lambda p: (p.get("temp_c") or 99) < 0 and ((p.get("rain_3h_mm") or 0) > 0 or (p.get("snow_3h_mm") or 0) > 0),
         "danger", lambda p: f"Ice risk — {p['temp_c']:.0f}°C with precipitation"),
        ("low_visibility", lambda p: (p.get("visibility_m") or 99999) < 5000,
         "warning", lambda p: f"Low visibility — {p['visibility_m'] / 1000:.1f} km"),
        ("high_wind", lambda p: (p.get("wind_speed_ms") or 0) > 10,
         "warning", lambda p: f"High winds — {p['wind_speed_ms']:.0f} m/s" + (f", gusts {p['wind_gust_ms']:.0f} m/s" if p.get("wind_gust_ms") else "")),
        ("heavy_precip", lambda p: (p.get("rain_3h_mm") or 0) > 5 or (p.get("snow_3h_mm") or 0) > 5,
         "warning", lambda p: f"Heavy {'snow' if (p.get('snow_3h_mm') or 0) > (p.get('rain_3h_mm') or 0) else 'rain'} — {max(p.get('rain_3h_mm', 0), p.get('snow_3h_mm', 0)):.1f} mm"),
        ("thunderstorm", lambda p: p.get("condition") in ("Thunderstorm", "Tornado", "Squall"),
         "danger", lambda p: f"{p['condition']} — {p.get('description', '')}"),
    ]:
        run_start = None
        run_msg = None
        for p in point_results:
            mi = p.get("distance_along_mi", 0)
            if test_fn(p):
                if run_start is None:
                    run_start = mi
                    run_msg = msg_fn(p)
            else:
                if run_start is not None:
                    _flush_hazard(htype, severity, run_msg, run_start, mi)
                    run_start = None
        if run_start is not None:
            _flush_hazard(htype, severity, run_msg, run_start,
                          point_results[-1].get("distance_along_mi", 0))

    # Sort by start mile
    hazards.sort(key=lambda h: h["start_mi"])
    return hazards


def _summarize_weather(
    point_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate per-point weather into summary + segments + hazards + points."""
    if not point_results:
        return {}

    temps = [p["temp_c"] for p in point_results if p.get("temp_c") is not None]
    winds = [p["wind_speed_ms"] for p in point_results if p.get("wind_speed_ms") is not None]
    gusts = [p["wind_gust_ms"] for p in point_results if p.get("wind_gust_ms") is not None]
    vis = [p["visibility_m"] for p in point_results if p.get("visibility_m") is not None]
    pops = [p["precip_probability"] for p in point_results if p.get("precip_probability") is not None]
    rains = [p["rain_3h_mm"] for p in point_results if p.get("rain_3h_mm") is not None]
    snows = [p["snow_3h_mm"] for p in point_results if p.get("snow_3h_mm") is not None]

    # Pick worst condition by severity
    worst_condition = "Clear"
    worst_description = "clear sky"
    worst_severity = -1
    for p in point_results:
        sev = _SEVERITY.get(p.get("condition", ""), 0)
        if sev > worst_severity:
            worst_severity = sev
            worst_condition = p.get("condition", "Clear")
            worst_description = p.get("description", "")

    summary = {
        "condition": worst_condition,
        "description": worst_description,
        "temp_c": round(sum(temps) / len(temps), 1) if temps else None,
        "temp_min_c": round(min(temps), 1) if temps else None,
        "temp_max_c": round(max(temps), 1) if temps else None,
        "wind_speed_ms": round(max(winds), 1) if winds else None,
        "wind_gust_ms": round(max(gusts), 1) if gusts else None,
        "visibility_m": round(min(vis)) if vis else None,
        "precip_probability": round(max(pops), 2) if pops else None,
        "rain_3h_mm": round(max(rains), 1) if rains else None,
        "snow_3h_mm": round(max(snows), 1) if snows else None,
    }

    segments = _build_segments(point_results)
    hazards = _detect_hazards(point_results)

    return {
        "summary": summary,
        "segments": segments,
        "hazards": hazards,
        "points": point_results,
    }


def _compute_weather_cost_modifier(
    condition: str,
    precip_mm: float,
    wind_ms: float,
    temp_c: Optional[float],
    visibility_m: float,
) -> float:
    """Compute a cost multiplier from weather conditions.

    Returns a value >= 1.0 where higher = worse weather for travel.
    Used by both tile weather population and (later) road cost.
    """
    modifier = 1.0

    # Precipitation — mud, reduced traction
    if precip_mm > 10:
        modifier *= 2.0    # heavy rain/snow
    elif precip_mm > 5:
        modifier *= 1.5    # moderate
    elif precip_mm > 1:
        modifier *= 1.2    # light

    # Ice risk — freezing temp + any precipitation
    if temp_c is not None and temp_c < 0 and precip_mm > 0:
        modifier *= 2.5    # ice is very dangerous

    # High wind
    if wind_ms > 15:
        modifier *= 1.8    # severe wind
    elif wind_ms > 10:
        modifier *= 1.3    # strong wind

    # Low visibility
    if visibility_m < 1000:
        modifier *= 1.5    # very poor
    elif visibility_m < 3000:
        modifier *= 1.2    # poor

    # Severe conditions
    if condition in ("Thunderstorm", "Tornado", "Squall"):
        modifier *= 3.0

    return modifier


async def populate_tile_weather(
    tile_grid: List[List["MacroTile"]],
    start_lat: float,
    start_lon: float,
    departure_time: Optional[float] = None,
    rate_of_advance_mph: float = 0.0,
) -> None:
    """Fetch weather forecasts and populate tiles with weather fields.

    Samples a sparse grid across the bbox (max 10x10 = 100 OWM calls),
    then assigns each tile to its nearest sample point. Weather is spatially
    smooth so this is sufficient for A* cost decisions.

    Called BEFORE build_tile_edges() so tile_cost() can factor in weather.
    """
    settings = get_settings()
    if not settings.owm_api_key or settings.offline_mode:
        return

    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    if rows == 0:
        return

    t0 = time.time()

    if departure_time is None:
        departure_time = datetime.now(timezone.utc).timestamp()
    speed_mph = rate_of_advance_mph if rate_of_advance_mph > 0 else 30.0

    # Compute bbox from tile grid corners
    south = tile_grid[0][0].south
    west = tile_grid[0][0].west
    north = tile_grid[-1][-1].north
    east = tile_grid[0][-1].east

    lat_span_mi = haversine(south, west, north, west) / METERS_PER_MILE
    lon_span_mi = haversine(south, west, south, east) / METERS_PER_MILE

    # Scale sample grid based on bbox size (max 10x10 = 100 points)
    def _grid_size(span_mi):
        if span_mi < 10:
            return 3
        if span_mi < 30:
            return 5
        if span_mi < 80:
            return 7
        return 10

    n_lat = _grid_size(lat_span_mi)
    n_lon = _grid_size(lon_span_mi)

    # Build evenly-spaced sample points across the bbox
    sample_points = []
    for i in range(n_lat):
        lat = south + (i + 0.5) * (north - south) / n_lat
        for j in range(n_lon):
            lon = west + (j + 0.5) * (east - west) / n_lon
            sample_points.append((lat, lon))

    logger.info(f"Tile weather: {rows * cols} tiles, {len(sample_points)} sample points "
                f"({n_lat}x{n_lon} grid, bbox {lat_span_mi:.0f}x{lon_span_mi:.0f} mi)")

    # Fetch forecasts for all sample points concurrently
    tasks = [_fetch_owm_forecast(lat, lon) for lat, lon in sample_points]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build sample weather data (pre-compute arrival time + weather for each sample)
    samples = []  # [(lat, lon, weather_fields_dict)]
    for (lat, lon), result in zip(sample_points, results):
        if isinstance(result, Exception) or result is None:
            continue

        dist_m = haversine(start_lat, start_lon, lat, lon)
        dist_mi = dist_m / METERS_PER_MILE
        hours = dist_mi / speed_mph if speed_mph > 0 else 0
        target_dt = departure_time + hours * 3600

        forecast = _pick_closest_forecast(result, target_dt)
        if not forecast:
            continue

        wx = _extract_point_weather(forecast)
        condition = wx.get("condition", "Clear")
        precip_mm = (wx.get("rain_3h_mm") or 0) + (wx.get("snow_3h_mm") or 0)
        wind_ms = wx.get("wind_speed_ms") or 0
        temp_c = wx.get("temp_c")
        visibility_m = wx.get("visibility_m") or 10000
        cost_mod = _compute_weather_cost_modifier(condition, precip_mm, wind_ms, temp_c, visibility_m)

        samples.append((lat, lon, {
            "condition": condition,
            "precip_mm": precip_mm,
            "wind_ms": wind_ms,
            "temp_c": temp_c,
            "visibility_m": visibility_m,
            "cost_modifier": cost_mod,
        }))

    if not samples:
        elapsed = time.time() - t0
        logger.warning(f"Tile weather: no samples succeeded ({elapsed:.2f}s)")
        return

    # Assign each tile to its nearest sample point
    populated = 0
    for r in range(rows):
        for c in range(cols):
            t = tile_grid[r][c]
            # Find nearest sample (simple scan over ≤100 points)
            best_dist = float("inf")
            best_wx = None
            for s_lat, s_lon, wx in samples:
                d = (t.center_lat - s_lat) ** 2 + (t.center_lon - s_lon) ** 2
                if d < best_dist:
                    best_dist = d
                    best_wx = wx
            if best_wx:
                t.weather_condition = best_wx["condition"]
                t.weather_precip_mm = best_wx["precip_mm"]
                t.weather_wind_ms = best_wx["wind_ms"]
                t.weather_temp_c = best_wx["temp_c"]
                t.weather_visibility_m = best_wx["visibility_m"]
                t.weather_cost_modifier = best_wx["cost_modifier"]
                populated += 1

    elapsed = time.time() - t0
    logger.info(f"Tile weather: {populated}/{rows * cols} tiles from "
                f"{len(samples)} samples, {elapsed:.2f}s")


async def fetch_weather_for_route(
    coords: List[Tuple[float, float]],
    departure_time: Optional[float] = None,
    rate_of_advance_mph: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """Fetch weather forecasts along a route and return structured summary.

    Args:
        coords: [(lon, lat), ...] route path coordinates
        departure_time: unix timestamp for start of travel (defaults to now)
        rate_of_advance_mph: user-specified speed in mph (0 = use default 30 mph)

    Returns:
        Weather dict with 'summary', 'segments', 'hazards', and 'points',
        or None if unavailable.
    """
    settings = get_settings()
    if not settings.owm_api_key or settings.offline_mode:
        return None

    if not coords or len(coords) < 2:
        return None

    t0 = time.time()

    # Sample points along route
    sample_points = _sample_route_points(coords)

    if departure_time is None:
        departure_time = datetime.now(timezone.utc).timestamp()

    # Estimate arrival time at each sample point based on distance
    total_mi = sample_points[-1]["distance_along_mi"] if sample_points else 0
    avg_speed_mph = rate_of_advance_mph if rate_of_advance_mph > 0 else 30.0

    # Fetch forecasts concurrently
    tasks = []
    for pt in sample_points:
        tasks.append(_fetch_owm_forecast(pt["lat"], pt["lon"]))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build per-point weather
    point_results = []
    for i, (pt, forecast_list) in enumerate(zip(sample_points, results)):
        if isinstance(forecast_list, Exception) or forecast_list is None:
            continue

        # Estimate arrival time at this point
        if avg_speed_mph > 0 and total_mi > 0:
            hours_to_point = pt["distance_along_mi"] / avg_speed_mph
        else:
            hours_to_point = 0
        target_dt = departure_time + hours_to_point * 3600

        forecast = _pick_closest_forecast(forecast_list, target_dt)
        if not forecast:
            continue

        weather = _extract_point_weather(forecast)
        weather["lat"] = pt["lat"]
        weather["lon"] = pt["lon"]
        weather["distance_along_mi"] = pt["distance_along_mi"]
        point_results.append(weather)

    if not point_results:
        logger.warning("No weather data retrieved for any route point")
        return None

    result = _summarize_weather(point_results)
    elapsed = time.time() - t0
    n_hazards = len(result.get("hazards", []))
    n_segments = len(result.get("segments", []))
    logger.info(f"Route weather: {len(point_results)}/{len(sample_points)} points, "
                f"{n_segments} segments, {n_hazards} hazards, "
                f"{result['summary'].get('condition', '?')}, {elapsed:.2f}s")
    return result

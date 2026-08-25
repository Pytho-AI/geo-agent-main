from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional, Tuple
from uuid import UUID
import asyncio
import json
import logging
import re
import time

from sqlalchemy import select

from app.services.knowledge.spatial_query import get_entities, get_overlays
from app.services.knowledge.geoops_executor import execute_geoops
from app.services.knowledge.cache import spatial_cache
from app.services.knowledge.route_query import get_routes
from app.schemas.geoops import GeoOpsRequest, CreateEntity, CreateOverlay
from app.schemas.common import GeoJSON
from app.services.nl.prompts import CHAT_SYSTEM_PROMPT
from app.services.llm.client import get_llm_client
from app.services.llm.base import Message
from app.utils.mgrs_utils import mgrs_to_latlng, is_mgrs_string, convert_geojson_mgrs_to_latlng
from app.models.map import Map
from app.constants.symbols import search_symbols, get_symbols_by_set
from app.constants.overlays import get_all_overlay_types, get_overlay_type_info
from app.constants.terrain import is_terrain_suitable, UNIT_TERRAIN_COMPATIBILITY
from app.config import get_settings

import httpx

logger = logging.getLogger(__name__)

OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
NL_WEATHER_CACHE_NS = "nl_weather"
NL_WEATHER_CACHE_TTL = 900  # 15 minutes


async def process_nl_query(db: AsyncSession, request) -> Dict[str, Any]:
    """
    Process natural language query.
    
    TODO: Integrate LLM for intent parsing and response generation.
    For now, returns simple spatial query results.
    """
    
    # Get entities and overlays in bbox
    entities = await get_entities(
        db,
        request.map_id,
        None,
        request.bbox,
    )
    
    overlays = await get_overlays(
        db,
        request.map_id,
        None,
        request.bbox,
    )
    
    # Simple response (TODO: LLM-generated)
    entity_count = len(entities)
    overlay_count = len(overlays)
    
    answer = f"Found {entity_count} entities and {overlay_count} overlays"
    if request.bbox:
        answer += f" in the specified area"
    answer += "."
    
    if entity_count > 0:
        kinds = list(set(e.kind for e in entities))
        answer += f" Entity types: {', '.join(kinds)}."
    
    return {
        "answer": answer,
        "entities": [
            {"id": str(e.id), "kind": e.kind, "attrs": e.attrs}
            for e in entities[:10]  # Limit to 10
        ],
        "overlays": [
            {"id": str(o.id), "kind": o.kind, "name": o.name}
            for o in overlays[:10]
        ],
        "suggested_filters": {
            "kinds": list(set(e.kind for e in entities)),
        }
    }


async def process_nl_update(db: AsyncSession, request) -> Dict[str, Any]:
    """
    Process natural language update.
    
    TODO: Integrate LLM to parse intent into GeoOps.
    For now, returns placeholder response.
    """
    
    # TODO: Use LLM to parse request.text into GeoOps
    # Example flow:
    # 1. LLM parses "Add a unit at 45.5, -122.6" into CreateEntity op
    # 2. Execute the op via geoops_executor
    # 3. Return result
    
    return {
        "success": False,
        "message": "Natural language updates require LLM integration. Use /geoops endpoint for structured operations.",
        "ops_executed": None,
    }


def _build_map_context(bbox: Optional[List[float]], entities: list, overlays: list, routes: list = None) -> str:
    """Build context string describing current map state for LLM."""
    context_parts = []

    # Add viewport info
    if bbox:
        center_lon = (bbox[0] + bbox[2]) / 2
        center_lat = (bbox[1] + bbox[3]) / 2
        context_parts.append(f"Map viewport center: [{center_lon:.4f}, {center_lat:.4f}]")
        context_parts.append(f"Bounding box: west={bbox[0]:.4f}, south={bbox[1]:.4f}, east={bbox[2]:.4f}, north={bbox[3]:.4f}")

    # Add entity summary - show all for deletion support
    if entities:
        entity_summary = []
        for e in entities:  # Show all entities so LLM can delete them
            attrs = e.attrs or {}
            name = attrs.get('name', 'Unnamed')
            entity_summary.append(f"- {e.kind}: {name} (id: {e.id})")
        context_parts.append(f"Existing entities in view ({len(entities)} total):\n" + "\n".join(entity_summary))
    else:
        context_parts.append("No existing entities in the current view.")

    # Add overlay summary
    if overlays:
        overlay_summary = []
        for o in overlays[:5]:
            overlay_summary.append(f"- {o.kind}: {o.name or 'Unnamed'} (id: {o.id})")
        context_parts.append(f"Existing overlays in view ({len(overlays)} total):\n" + "\n".join(overlay_summary))
    else:
        context_parts.append("No existing overlays in the current view.")

    # Add route summary
    if routes:
        route_summary = []
        for r in routes:
            start = r.start_geom
            end = r.end_geom
            start_str = f"[{start['coordinates'][0]:.4f}, {start['coordinates'][1]:.4f}]" if isinstance(start, dict) else "?"
            end_str = f"[{end['coordinates'][0]:.4f}, {end['coordinates'][1]:.4f}]" if isinstance(end, dict) else "?"
            route_summary.append(f"- {r.name or 'Unnamed'}: {start_str} → {end_str}, mode={r.route_mode}, status={r.status} (id: {r.id})")
        context_parts.append(f"Existing routes ({len(routes)} total):\n" + "\n".join(route_summary))
    else:
        context_parts.append("No existing routes on this map.")

    return "\n\n".join(context_parts)


def _parse_llm_response(response_text: str) -> Dict[str, Any]:
    """Parse LLM response JSON, handling common issues."""
    # Try to extract JSON from the response
    text = response_text.strip()
    
    # Handle markdown code blocks
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    
    # Try to find JSON object
    if not text.startswith("{"):
        # Look for first { and last }
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse LLM response as JSON: {e}\nResponse: {response_text[:500]}")
        # If the LLM returned plain text instead of JSON, wrap it as a
        # chat-style response so the user still sees something useful.
        if response_text.strip():
            return {
                "message": response_text.strip(),
                "proposed_ops": [],
                "requires_approval": False,
                "clarification_needed": None,
            }
        return {
            "message": "I couldn't understand that request. Could you please rephrase it?",
            "proposed_ops": [],
            "requires_approval": False,
            "clarification_needed": "Failed to parse response",
        }


def _bbox_changed(old_bbox: Optional[List[float]], new_bbox: Optional[List[float]]) -> bool:
    """
    Check if viewport bbox has changed (user panned or zoomed).
    Returns True if any coordinate differs by more than 1%.
    """
    if not old_bbox or not new_bbox:
        return True
    if len(old_bbox) != 4 or len(new_bbox) != 4:
        return True
    for i in range(4):
        if abs(old_bbox[i] - new_bbox[i]) > 0.01:
            return True
    return False


def _get_or_build_location_context(map_id: str, bbox: Optional[List[float]]) -> Tuple[Optional[str], bool]:
    """
    Get cached location context or indicate it needs to be built.
    Uses the shared spatial_cache with namespace "location_context".

    Returns:
        (cached_context, needs_rebuild) - context string if cached and valid, else None with needs_rebuild=True
    """
    cached = spatial_cache.get("location_context", str(map_id), bbox)
    if cached is not None:
        return cached.get("context"), False
    return None, True


def _cache_location_context(
    map_id: str,
    bbox: Optional[List[float]],
    context: str,
    grid: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Store location context and terrain grid in the shared spatial cache."""
    data = {
        "context": context,
        "grid": grid or [],
    }
    # TTL 10 minutes (default) — rebuilds when bbox changes anyway
    spatial_cache.put("location_context", str(map_id), bbox, data)
    logger.info(f"Cached location context for map {map_id} with {len(grid or [])} grid points")


def clear_location_context_cache(map_id: Optional[str] = None) -> None:
    """
    Clear location context cache.

    Args:
        map_id: Specific map to clear, or None to clear all
    """
    if map_id:
        spatial_cache.clear("location_context", str(map_id))
    else:
        spatial_cache.clear("location_context")


async def _get_region_boundary(
    db: AsyncSession,
    map_id: UUID,
) -> Optional[str]:
    """
    Build region boundary context from the Map's stored bbox.

    Returns a prompt section string, or None if no boundary is defined.
    """
    result = await db.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()

    if not map_obj or not all(
        v is not None
        for v in [map_obj.bbox_west, map_obj.bbox_south, map_obj.bbox_east, map_obj.bbox_north]
    ):
        return None

    return (
        "## Region Boundary\n"
        "The following boundary defines the area of operations for this map.\n"
        "- Prefer placing entities and overlays within this boundary.\n"
        "- If coordinates fall slightly outside, clamp them to the nearest boundary edge.\n"
        "- If coordinates are clearly outside the region, STILL include the operation in "
        "proposed_ops but note the boundary issue in the message field.\n"
        "- NEVER return empty proposed_ops because of boundary concerns.\n\n"
        f"Map region boundary: "
        f"west={map_obj.bbox_west:.4f}, south={map_obj.bbox_south:.4f}, "
        f"east={map_obj.bbox_east:.4f}, north={map_obj.bbox_north:.4f}"
    )


def _response_looks_empty(result: Dict[str, Any], user_text: str) -> Optional[str]:
    """
    Detect when the LLM described operations in its message but returned
    empty proposed_ops. Returns a retry prompt if a retry is warranted,
    or None if the response looks fine.
    """
    ops = result.get("proposed_ops") or []
    if len(ops) > 0:
        return None  # has operations — no problem

    message = (result.get("message") or "").lower()

    # Pattern 1: message says "I found N units/entities" but ops is empty
    count_match = re.search(r'(?:found|identified|detected|extracted|parsed)\s+(\d+)\s+(?:unit|entit|force|element|position|marker)', message)
    if count_match:
        n = count_match.group(1)
        return (
            f"YOUR PREVIOUS RESPONSE WAS REJECTED. You said you found {n} units but "
            f"returned an EMPTY proposed_ops array. This is a critical failure — the user "
            f"sees nothing on the map.\n\n"
            f"You MUST output the COMPLETE proposed_ops array with ALL {n} operations. "
            f"Do NOT describe what you will do. Do NOT check boundaries first. "
            f"Output the JSON with every operation NOW.\n\n"
            f"Original user request: {user_text}"
        )

    # Pattern 2: message says "I'll place/create/add" but ops is empty
    if re.search(r"i'?ll\s+(place|create|add|draw|plan|move|delete)", message):
        return (
            "YOUR PREVIOUS RESPONSE WAS REJECTED. You said you would perform operations "
            "but returned an EMPTY proposed_ops array. The user sees nothing.\n\n"
            "You MUST include ALL operations in proposed_ops. Do NOT narrate what you "
            "intend to do — actually do it. Output the full JSON with every operation NOW.\n\n"
            f"Original user request: {user_text}"
        )

    # Pattern 3: message mentions "checking" or "verifying" boundary — LLM is deferring
    if re.search(r"check|verif|validat|within.*boundar|fall.*within", message):
        return (
            "YOUR PREVIOUS RESPONSE WAS REJECTED. You appear to be doing a boundary check "
            "as a separate step and returned EMPTY proposed_ops. This is wrong.\n\n"
            "Boundary checks happen INLINE — include ALL operations in proposed_ops and "
            "note any boundary issues in the message field. NEVER return empty ops.\n\n"
            f"Original user request: {user_text}"
        )

    return None


async def _call_llm_with_retry(
    llm,
    messages: List[Message],
    system_prompt: str,
    user_text: str,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """
    Call the LLM and validate the response. If the response describes
    operations but proposed_ops is empty, retry once with explicit
    failure feedback injected as a follow-up message.
    """
    llm_start = time.time()
    response = await llm.chat(
        messages=messages,
        system=system_prompt,
        max_tokens=8192,
        temperature=0.3,
    )
    llm_elapsed = time.time() - llm_start
    logger.info(f"LLM call took {llm_elapsed:.2f}s")

    result = _parse_llm_response(response.content)
    _ensure_result_structure(result)

    # Check if the response looks like a failed empty-ops case
    retry_prompt = _response_looks_empty(result, user_text)
    if retry_prompt and max_retries > 0:
        logger.warning(
            f"EMPTY-OPS DETECTED — message: {result.get('message', '')[:120]}... "
            f"Retrying with failure feedback."
        )
        # Build retry messages: original conversation + failed assistant response + correction
        retry_messages = list(messages)
        retry_messages.append(Message(role="assistant", content=response.content))
        retry_messages.append(Message(role="user", content=retry_prompt))

        retry_start = time.time()
        retry_response = await llm.chat(
            messages=retry_messages,
            system=system_prompt,
            max_tokens=8192,
            temperature=0.2,  # Lower temp for more deterministic retry
        )
        retry_elapsed = time.time() - retry_start
        logger.info(f"LLM RETRY took {retry_elapsed:.2f}s")

        retry_result = _parse_llm_response(retry_response.content)
        _ensure_result_structure(retry_result)

        # Use retry result if it has operations, otherwise fall back to original
        if len(retry_result.get("proposed_ops", [])) > 0:
            logger.info(f"Retry succeeded — got {len(retry_result['proposed_ops'])} operations")
            return retry_result
        else:
            logger.error("Retry ALSO returned empty ops — returning original result")

    return result


def _ensure_result_structure(result: Dict[str, Any]) -> None:
    """Fill in missing fields on a parsed LLM result."""
    if "message" not in result:
        result["message"] = "Operation parsed successfully."
    if "proposed_ops" not in result:
        result["proposed_ops"] = []
    if "requires_approval" not in result:
        result["requires_approval"] = len(result["proposed_ops"]) > 0
    if "clarification_needed" not in result:
        result["clarification_needed"] = None


def _format_wind_dir(deg: Optional[float]) -> str:
    """Convert wind degrees to compass direction."""
    if deg is None:
        return ""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return directions[int((deg + 22.5) / 45) % 8]


def _extract_current_weather(entry: dict) -> dict:
    """Extract current weather fields from a single OWM forecast entry."""
    w = (entry.get("weather") or [{}])[0]
    main = entry.get("main", {})
    wind = entry.get("wind", {})
    return {
        "condition": w.get("main", "Unknown"),
        "description": w.get("description", ""),
        "temp": main.get("temp"),
        "humidity": main.get("humidity"),
        "wind_speed": wind.get("speed"),
        "wind_gust": wind.get("gust"),
        "wind_dir": _format_wind_dir(wind.get("deg")),
        "visibility": entry.get("visibility"),
        "clouds": entry.get("clouds", {}).get("all"),
    }


async def _build_weather_context(bbox: Optional[List[float]]) -> str:
    """Fetch weather at 5 viewport points (center + corners) for LLM context.

    Uses OWM 5-Day/3-Hour Forecast API (free tier). Center point provides
    current conditions + 15h forecast. Corner points detect spatial variation.
    Cached 15 minutes per bbox.
    """
    settings = get_settings()
    if not settings.owm_api_key or settings.offline_mode:
        return ""

    if not bbox or len(bbox) < 4:
        return ""

    west, south, east, north = bbox[0], bbox[1], bbox[2], bbox[3]
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2

    # Cache key based on rounded bbox
    cache_bbox = [round(v, 2) for v in bbox]
    cached = spatial_cache.get(NL_WEATHER_CACHE_NS, "global", cache_bbox)
    if cached is not None:
        return cached

    api_key = settings.owm_api_key

    # 5 sample points: center + 4 corners (inset 20% to avoid bbox edge)
    lat_pad = (north - south) * 0.2
    lon_pad = (east - west) * 0.2
    sample_points = [
        ("center", center_lat, center_lon),
        ("NW", north - lat_pad, west + lon_pad),
        ("NE", north - lat_pad, east - lon_pad),
        ("SW", south + lat_pad, west + lon_pad),
        ("SE", south + lat_pad, east - lon_pad),
    ]

    # Fetch all 5 concurrently — center gets 6 entries (current + forecast),
    # corners get 1 entry each (current only)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = []
            for label, lat, lon in sample_points:
                cnt = 6 if label == "center" else 1
                r_lat, r_lon = round(lat, 2), round(lon, 2)
                url = (f"{OWM_FORECAST_URL}?lat={r_lat}&lon={r_lon}"
                       f"&appid={api_key}&units=metric&cnt={cnt}")
                tasks.append(client.get(url))
            responses = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning(f"OWM weather context error: {e}")
        return ""

    # Parse results
    point_data = {}  # label -> OWM response data
    for (label, _, _), resp in zip(sample_points, responses):
        if isinstance(resp, Exception) or resp.status_code != 200:
            continue
        point_data[label] = resp.json()

    if "center" not in point_data:
        return ""

    center_entries = point_data["center"].get("list", [])
    if not center_entries:
        return ""

    # --- Current conditions from center ---
    cw = _extract_current_weather(center_entries[0])

    lines = ["## Current Weather (viewport center)"]
    lines.append(f"- Conditions: {cw['condition']} ({cw['description']})")
    if cw["temp"] is not None:
        lines.append(f"- Temperature: {cw['temp']:.1f}\u00B0C")
    if cw["wind_speed"] is not None:
        gust = f", gusts {cw['wind_gust']:.1f} m/s" if cw["wind_gust"] else ""
        lines.append(f"- Wind: {cw['wind_speed']:.1f} m/s from {cw['wind_dir']}{gust}")
    if cw["visibility"] is not None:
        lines.append(f"- Visibility: {cw['visibility'] / 1000:.1f} km")
    if cw["humidity"] is not None:
        lines.append(f"- Humidity: {cw['humidity']}%")
    if cw["clouds"] is not None:
        lines.append(f"- Cloud cover: {cw['clouds']}%")

    # --- Spatial variation from corners ---
    corner_weather = []
    for label in ["NW", "NE", "SW", "SE"]:
        if label in point_data:
            entries = point_data[label].get("list", [])
            if entries:
                corner_weather.append((label, _extract_current_weather(entries[0])))

    if corner_weather:
        # Check if conditions differ across the viewport
        all_conditions = [cw["condition"]] + [c["condition"] for _, c in corner_weather]
        all_temps = [cw["temp"]] + [c["temp"] for _, c in corner_weather]
        all_temps = [t for t in all_temps if t is not None]

        unique_conditions = set(all_conditions)
        temp_range = max(all_temps) - min(all_temps) if len(all_temps) > 1 else 0

        if len(unique_conditions) > 1 or temp_range > 3:
            lines.append("")
            lines.append("## Weather Variation Across Viewport")
            if temp_range > 3:
                lines.append(f"- Temperature range: {min(all_temps):.0f}-{max(all_temps):.0f}\u00B0C across the area")
            for label, c in corner_weather:
                if c["condition"] != cw["condition"]:
                    lines.append(f"- {label} corner: {c['condition']} ({c['description']}), {c['temp']:.0f}\u00B0C"
                                 if c["temp"] is not None else
                                 f"- {label} corner: {c['condition']} ({c['description']})")

    # --- Forecast from center (remaining entries = next 3-15h) ---
    if len(center_entries) > 1:
        lines.append("")
        lines.append("## Forecast (next 15 hours)")
        for entry in center_entries[1:]:
            fc_w = (entry.get("weather") or [{}])[0]
            fc_main = entry.get("main", {})
            fc_wind = entry.get("wind", {})
            fc_rain = entry.get("rain", {})
            fc_snow = entry.get("snow", {})

            fc_time = entry.get("dt_txt", "")
            time_label = fc_time.split(" ")[1][:5] + " UTC" if " " in fc_time else fc_time

            parts = [f"**{time_label}**: {fc_w.get('main', '')} ({fc_w.get('description', '')})"]
            fc_temp = fc_main.get("temp")
            if fc_temp is not None:
                parts.append(f"{fc_temp:.0f}\u00B0C")
            fc_wind_speed = fc_wind.get("speed")
            if fc_wind_speed is not None:
                ws = f"wind {fc_wind_speed:.0f} m/s {_format_wind_dir(fc_wind.get('deg'))}"
                if fc_wind.get("gust"):
                    ws += f" (gusts {fc_wind['gust']:.0f})"
                parts.append(ws)
            fc_rain_mm = fc_rain.get("3h", 0)
            fc_snow_mm = fc_snow.get("3h", 0)
            if fc_rain_mm > 0:
                parts.append(f"rain {fc_rain_mm:.1f}mm")
            if fc_snow_mm > 0:
                parts.append(f"snow {fc_snow_mm:.1f}mm")
            fc_pop = entry.get("pop")
            if fc_pop is not None and fc_pop > 0.1:
                parts.append(f"{int(fc_pop * 100)}% precip chance")
            fc_vis = entry.get("visibility")
            if fc_vis is not None and fc_vis < 5000:
                parts.append(f"visibility {fc_vis / 1000:.1f}km")

            lines.append("- " + ", ".join(parts))

    context = "\n".join(lines)
    spatial_cache.put(NL_WEATHER_CACHE_NS, "global", cache_bbox,
                      context, ttl_seconds=NL_WEATHER_CACHE_TTL)
    logger.info(f"NL weather context: {cw['condition']}, {cw['temp']}\u00B0C, "
                f"{len(corner_weather)} corners, {len(center_entries)} forecast entries")
    return context


async def process_nl_chat(
    db: AsyncSession,
    text: str,
    user_id: str,
    map_id: UUID,
    bbox: Optional[List[float]],
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Process natural language chat message and return proposed operations.
    
    Terrain context is cached per map_id and rebuilt when bbox changes significantly.
    """
    try:
        logger.info(f"NL chat: user={user_id} map={map_id} message={text!r}")

        # Get current map context
        entities = await get_entities(db, map_id, None, bbox)
        overlays = await get_overlays(db, map_id, None, bbox)
        routes = await get_routes(db, map_id)

        # Build context for LLM
        map_context = _build_map_context(bbox, entities, overlays, routes)
        symbol_context = _build_symbol_context()
        boundary_context = await _get_region_boundary(db, map_id)
        
        # LOCATION CONTEXT: Get from cache or build new
        cached_context, needs_rebuild = _get_or_build_location_context(map_id, bbox)
        
        if needs_rebuild:
            logger.info(f"CACHE MISS - Building terrain context for map {map_id}")
            terrain_start = time.time()
            extracted_coords = _extract_coordinates(text)
            terrain_context, terrain_grid = await _build_terrain_context(bbox, extracted_coords)
            _cache_location_context(map_id, bbox, terrain_context, terrain_grid)
            terrain_elapsed = time.time() - terrain_start
            logger.info(f"TERRAIN API took {terrain_elapsed:.2f}s")
        else:
            logger.info(f"CACHE HIT - Using cached terrain context for map {map_id}")
            terrain_context = cached_context
        
        # WEATHER CONTEXT: Fetch current conditions at viewport center
        weather_context = await _build_weather_context(bbox)

        # Build system prompt with terrain + weather context
        boundary_section = f"\n{boundary_context}\n" if boundary_context else ""
        weather_section = f"\n{weather_context}\n" if weather_context else ""
        system_prompt = f"""{CHAT_SYSTEM_PROMPT}
{boundary_section}
## Current Map Context
{map_context}

{terrain_context}
{weather_section}
{symbol_context}
"""
        # Build messages for LLM
        messages = []
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:
                messages.append(Message(role=msg["role"], content=msg["content"]))
        
        # Add current user message
        messages.append(Message(role="user", content=text))
        
        # Call LLM (with retry on empty-ops failure)
        try:
            llm = get_llm_client()
            result = await _call_llm_with_retry(
                llm, messages, system_prompt, text
            )

            # Post-process: convert any MGRS strings in geometries to [lon, lat]
            for op in result["proposed_ops"]:
                if "geom" in op:
                    op["geom"] = convert_geojson_mgrs_to_latlng(op["geom"])
                if "start_geom" in op:
                    op["start_geom"] = convert_geojson_mgrs_to_latlng(op["start_geom"])
                if "end_geom" in op:
                    op["end_geom"] = convert_geojson_mgrs_to_latlng(op["end_geom"])

            # Post-process: enrich mil_unit entities with unitType, symbolName, SIDC
            for op in result["proposed_ops"]:
                if op.get("op") == "create_entity" and op.get("kind") == "mil_unit":
                    attrs = op.get("attrs", {})
                    enriched = enrich_entity_from_name(
                        attrs.get("name", ""),
                        attrs.get("affiliation", "Friend"),
                        attrs.get("echelon", "Battalion")
                    )
                    for key, value in enriched.items():
                        if not attrs.get(key):
                            attrs[key] = value
                    op["attrs"] = attrs

            # Post-process: ensure all overlays have valid SIDCs
            result["proposed_ops"] = _ensure_overlay_sidcs(result["proposed_ops"])

            # Post-process: enrich delete operations with entity details
            result["proposed_ops"] = _enrich_delete_ops(result["proposed_ops"], entities, overlays)

            return result

        except Exception:
            # Full stack server-side; GENERIC message to the analyst.
            # Exception text used to flow into the chat response, which
            # (a) leaks stack/internal detail to the client (CodeQL
            # py/stack-trace-exposure via the /nl/chat return) and
            # (b) surfaces system internals in the analyst-facing UI.
            logger.exception("NL chat model call failed")
            return {
                "message": (
                    "The map assistant could not process that request. "
                    "Try rephrasing it."
                ),
                "proposed_ops": [],
                "requires_approval": False,
                "clarification_needed": None,
            }

    except Exception:
        logger.exception("Error processing NL chat")
        return {
            "message": (
                "The map assistant could not process that request. "
                "Try rephrasing it."
            ),
            "proposed_ops": [],
            "requires_approval": False,
            "clarification_needed": None
        }


def _extract_coordinates(text: str) -> List[Tuple[float, float]]:
    """
    Extract coordinate pairs from user text.
    
    Supports formats:
    - Decimal: 37.7749, -122.4194
    - DMS-like: 17.42N, 102.78E
    - Bracketed: [102.78, 17.42] or (37.5, -122.2)
    
    Returns:
        List of (lat, lon) tuples
    """
    coords = []
    
    # Pattern 1: Decimal coordinates like "37.7749, -122.4194" or "at 37.5 -122.2"
    # BOUNDED quantifiers on purpose (CodeQL py/polynomial-redos): with
    # unbounded `\d+`, finditer over a long digit run does linear
    # backtracking at every start position — O(n^2), measured at 120s
    # on 100k digits. Coordinates have <= 3 integer digits and the
    # fraction cap is far beyond GPS precision, so {1,3}/{0,12} keeps
    # per-position work constant (same input measured at
    # milliseconds) while the (?<![\d.]) guard stops matches INSIDE
    # longer numbers (grid refs, IDs) that were never coordinates.
    decimal_pattern = r'(?<![\d.])(-?\d{1,3}(?:\.\d{0,12})?)[,\s]+(-?\d{1,3}(?:\.\d{0,12})?)(?![\d.])'
    for match in re.finditer(decimal_pattern, text):
        try:
            num1, num2 = float(match.group(1)), float(match.group(2))
            # Heuristic: if first number is -180 to 180 and second is -90 to 90, assume lon,lat
            # Otherwise assume lat,lon
            if -90 <= num1 <= 90 and -180 <= num2 <= 180:
                lat, lon = num1, num2
                coords.append((lat, lon))
            elif -180 <= num1 <= 180 and -90 <= num2 <= 90:
                lon, lat = num1, num2
                coords.append((lat, lon))
        except ValueError:
            continue
    
    # Pattern 2: DMS-style like "17.42N, 102.78E" (same bounded form as
    # pattern 1 — see the note there).
    dms_pattern = r'(?<![\d.])(\d{1,3}(?:\.\d{0,12})?)\s*([NSns])[,\s]+(\d{1,3}(?:\.\d{0,12})?)\s*([EWew])'
    for match in re.finditer(dms_pattern, text):
        try:
            lat = float(match.group(1))
            if match.group(2).upper() == 'S':
                lat = -lat
            lon = float(match.group(3))
            if match.group(4).upper() == 'W':
                lon = -lon
            coords.append((lat, lon))
        except ValueError:
            continue

    # Pattern 3: MGRS like "18S UJ 2337 0651" or "18SUJ23370651"
    mgrs_pattern = r'(?:MGRS\s*)?(\d{1,2}[C-X]\s*[A-Z]{2}\s*\d{1,5}\s+\d{1,5}|\d{1,2}[C-X][A-Z]{2}\d{2,10})'
    for match in re.finditer(mgrs_pattern, text, re.IGNORECASE):
        try:
            mgrs_str = match.group(1)
            if is_mgrs_string(mgrs_str):
                lat, lon = mgrs_to_latlng(mgrs_str)
                coords.append((lat, lon))
        except Exception:
            continue

    return coords


async def _build_terrain_context(
    bbox: Optional[List[float]],
    extracted_coords: List[Tuple[float, float]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Build terrain context string for LLM and collect terrain grid data for validation.
    
    Returns:
        (context_string, terrain_grid) - context for LLM and grid data for validation cache
    """
    from app.services.nl.tools.terrain import _sample_terrain_grid
    
    context_parts = ["## Terrain Analysis"]
    terrain_grid = []
    
    if not bbox:
        return "\n".join(context_parts), terrain_grid
    
    # Sample terrain grid (no unit type dependency)
    try:
        terrain_grid = await _sample_terrain_grid(tuple(bbox), grid_size=10)
        logger.info(f"Sampled {len(terrain_grid)} terrain points for location context")
    except Exception as e:
        logger.warning(f"Could not sample terrain grid: {e}")
        return "\n".join(context_parts), []
    
    if not terrain_grid:
        context_parts.append("\n(Terrain data unavailable)")
        return "\n".join(context_parts), []
    
    # Summarize terrain across the grid
    elevations = [p["elevation_m"] for p in terrain_grid if p.get("elevation_m") is not None]
    land_covers = {}
    for p in terrain_grid:
        lc = p.get("land_cover", {})
        lc_name = lc.get("display_name") if isinstance(lc, dict) else None
        if lc_name:
            land_covers[lc_name] = land_covers.get(lc_name, 0) + 1
    
    total_lc = max(sum(land_covers.values()), 1) if land_covers else 1
    context_parts.append("\n### Viewport Terrain Summary")
    if elevations:
        context_parts.append(f"- Elevation range: {min(elevations):.0f}m - {max(elevations):.0f}m")
    if land_covers:
        top_covers = sorted(land_covers.items(), key=lambda x: -x[1])[:3]
        cover_str = ", ".join(f"{name} ({round(count / total_lc * 100)}%)" for name, count in top_covers)
        context_parts.append(f"- Predominant land cover: {cover_str}")
    
    # Find suitable positions from grid for common unit types
    context_parts.append("\n### Recommended Positions")
    context_parts.append("Use these coordinates when placing units without a specific location:")
    
    for unit_type in ["armor", "infantry", "artillery"]:
        suitable_positions = []
        for point in terrain_grid:
            land_cover = point.get("land_cover", {})
            lc_type = land_cover.get("type") if isinstance(land_cover, dict) else "unknown"
            slope = point.get("slope_pct", 0) or 0
            
            result = is_terrain_suitable(unit_type, lc_type or "unknown", slope)
            if result.get("suitable"):
                suitable_positions.append(point)
        
        # Sort by elevation (higher = better tactical position)
        suitable_positions.sort(key=lambda p: p.get("elevation_m") or 0, reverse=True)
        
        if suitable_positions:
            best = suitable_positions[0]
            lat = best.get('lat')
            lon = best.get('lon')
            elev = best.get('elevation_m')
            elev_str = f"{elev}m" if elev is not None else "N/A"
            slope = best.get('slope_pct')
            slope_str = f"{slope}%" if slope is not None else "N/A"
            lc = best.get('land_cover', {})
            lc_name = lc.get('display_name', 'Unknown') if isinstance(lc, dict) else 'Unknown'
            
            context_parts.append(
                f"\n**{unit_type.replace('_', ' ').title()}:** "
                f"[{lon:.4f}, {lat:.4f}] "
                f"(elevation: {elev_str}, slope: {slope_str}, land cover: {lc_name})"
            )
        else:
            context_parts.append(f"\n**{unit_type.replace('_', ' ').title()}:** No ideal terrain found")
    
    # Analyze extracted coordinates using nearest grid point
    for i, (lat, lon) in enumerate(extracted_coords[:3]):
        nearest = min(terrain_grid, key=lambda p: (p["lat"] - lat) ** 2 + (p["lon"] - lon) ** 2)
        context_parts.append(f"\n### Mentioned Location {i+1} ({lat:.4f}, {lon:.4f})")
        if nearest.get("elevation_m") is not None:
            context_parts.append(f"- Elevation: {nearest['elevation_m']}m")
        if nearest.get("slope_pct") is not None:
            context_parts.append(f"- Slope: {nearest['slope_pct']}%")
        lc = nearest.get("land_cover", {})
        if isinstance(lc, dict) and lc.get("type"):
            context_parts.append(f"- Land cover: {lc.get('display_name', lc.get('type'))}")
    
    # Add unit-terrain compatibility reference (grouped bullets — never
    # tables in prompts; sequential readers can't scan columns)
    context_parts.append("\n### Unit-Terrain Compatibility Reference")
    for unit_type in ["armor", "infantry", "artillery", "mechanized_infantry"]:
        compat = UNIT_TERRAIN_COMPATIBILITY.get(unit_type, {})
        max_slope = compat.get("max_slope_pct", "N/A")
        impassable = ", ".join(compat.get("impassable_terrain", [])[:3])
        context_parts.append(
            f"- **{unit_type}**: max slope {max_slope}%"
            + (f"; avoids {impassable}" if impassable else "")
        )
    
    logger.info(f"Built terrain context with {len(terrain_grid)} cached points")
    return "\n".join(context_parts), terrain_grid


def _build_symbol_context() -> str:
    """
    Build a context string of valid MIL-STD-2525D symbols for the LLM.
    Includes common land unit types and their entity codes.
    """
    from app.constants.overlays import LINE_OVERLAY_TYPES, POLYGON_OVERLAY_TYPES
    
    # Get land unit symbols (symbol set 10)
    land_units = get_symbols_by_set("10")
    
    # Get a curated subset of common unit types
    common_units = []
    common_keywords = [
        "infantry", "armor", "artillery", "cavalry", "engineer", 
        "signal", "medical", "supply", "aviation", "reconnaissance",
        "air defense", "headquarters", "special", "mechanized", "motorized"
    ]
    
    for symbol in land_units:
        name_lower = symbol["name"].lower()
        if any(kw in name_lower for kw in common_keywords):
            common_units.append({
                "name": symbol["name"],
                "code": symbol["code"],
                "sidc_template": symbol["sidc"]
            })
    
    # Limit to most relevant 30 symbols
    common_units = common_units[:30]
    
    context = "## Valid MIL-STD-2525D Unit Types (use these entity codes)\n"
    for unit in common_units:
        context += f"- {unit['name']}: code={unit['code']}\n"
    
    context += "\n## Valid Overlay Types (Line - use LineString geometry)\n"
    for overlay in LINE_OVERLAY_TYPES:
        context += f"- {overlay['value']}: {overlay['label']} - {overlay['desc']}\n"
    
    context += "\n## Valid Overlay Types (Area - use Polygon geometry)\n"
    for overlay in POLYGON_OVERLAY_TYPES:
        context += f"- {overlay['value']}: {overlay['label']} - {overlay['desc']}\n"
    
    return context


def _modify_sidc(base_sidc: str, affiliation: str, echelon: str, status: str) -> str:
    """
    Modify a base SIDC to set affiliation, echelon, and status.
    
    SIDC structure (20 chars):
    [0-1] version, [2] context, [3] identity, [4-5] symbolSet, [6] status, 
    [7] hqtfd, [8-9] echelon, [10-15] entity, [16-19] mods
    """
    affiliation_codes = {"Friend": "3", "Hostile": "6", "Neutral": "4", "Unknown": "1"}
    echelon_codes = {
        "Team": "11", "Squad": "12", "Section": "13", "Platoon": "14",
        "Company": "15", "Battalion": "16", "Regiment": "17", "Brigade": "18",
        "Division": "21", "Corps": "22", "Army": "23"
    }
    status_codes = {"Present": "0", "Planned": "1", "Anticipated": "2"}
    
    sidc = list(base_sidc)
    sidc[3] = affiliation_codes.get(affiliation, "3")
    sidc[6] = status_codes.get(status, "0")
    echelon_code = echelon_codes.get(echelon, "16")
    sidc[8] = echelon_code[0]
    sidc[9] = echelon_code[1]
    return "".join(sidc)


def enrich_entity_from_name(name: str, affiliation: str = "Friend", echelon: str = "Battalion") -> Dict[str, Any]:
    """
    Enrich entity attributes by parsing the name to find unit type and symbol.
    
    Args:
        name: Unit name like "1st Armor Company"
        affiliation: Provided by LLM
        echelon: Provided by LLM
    
    Returns:
        Dict with unitType, symbolName, symbolSet, sidc, status
    """
    result = {"status": "Present"}
    
    # Search for symbol using the name
    symbols = search_symbols(name, symbol_set="10", limit=1)
    if symbols:
        symbol = symbols[0]
        result["unitType"] = symbol.get("code", "110300")
        result["symbolSet"] = symbol.get("symbolSet", "10")
        result["symbolName"] = (
            symbol.get("entitySubtype") or 
            symbol.get("entityType") or 
            symbol.get("entity") or 
            symbol.get("name", "")
        )
        # Get base SIDC and modify for affiliation/echelon/status
        base_sidc = symbol.get("sidc", "10031000160000000000")
        result["sidc"] = _modify_sidc(base_sidc, affiliation, echelon, result["status"])
    else:
        result["unitType"] = "110300"
        result["symbolSet"] = "10"
        result["symbolName"] = ""
        result["sidc"] = _modify_sidc("10031000160000000000", affiliation, echelon, result["status"])
    
    logger.info(f"Enriched entity '{name}' -> unitType: {result['unitType']}, symbolName: {result['symbolName']}")
    return result



# Map LLM-generated overlay kinds to registered kinds when names don't match exactly.
_OVERLAY_KIND_ALIASES = {
    "direction_of_attack": "direction_of_attack_main",
    "axis_of_advance": "direction_of_attack_main",  # axis requires 3+ pts; use arrow instead
    "objective": "engagement_area",        # render as area graphic
    "battle_position": "assembly_area",    # render as area graphic
    "strong_point": "fortified_area",      # render as area graphic
}


# Fallback SIDCs for completely unknown overlay types (so they still render).
# Line → phase_line SIDC, area → assembly_area SIDC.
_FALLBACK_LINE_SIDC = "10032500001403000000"   # phase_line
_FALLBACK_AREA_SIDC = "10032500001101000000"   # assembly_area


def _ensure_overlay_sidcs(proposed_ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure all overlay create operations have valid SIDCs.
    If SIDC is missing, look it up from the overlay type definition.
    Falls back to _OVERLAY_KIND_ALIASES for types the LLM uses that
    don't have a direct registry entry, and finally to a generic
    line/area SIDC so the overlay always renders.
    """
    for op in proposed_ops:
        if op.get("op") == "create_overlay":
            attrs = op.get("attrs") or {}
            sidc = attrs.get("sidc")

            # If SIDC is missing, look it up from overlay type
            if not sidc:
                overlay_kind = op.get("kind")
                if overlay_kind:
                    overlay_type_info = get_overlay_type_info(overlay_kind)
                    # Fall back to alias if exact kind not found
                    if not overlay_type_info:
                        alias = _OVERLAY_KIND_ALIASES.get(overlay_kind)
                        if alias:
                            overlay_type_info = get_overlay_type_info(alias)
                            logger.info(f"Mapped overlay kind '{overlay_kind}' -> '{alias}'")
                    if overlay_type_info and overlay_type_info.get("sidc"):
                        attrs["sidc"] = overlay_type_info["sidc"]
                        op["attrs"] = attrs
                        logger.info(f"Added SIDC {attrs['sidc']} for overlay {op.get('name', overlay_kind)}")
                    else:
                        # Last resort: pick fallback based on geometry type
                        geom_type = op.get("geom", {}).get("type", "")
                        fallback = _FALLBACK_AREA_SIDC if geom_type == "Polygon" else _FALLBACK_LINE_SIDC
                        attrs["sidc"] = fallback
                        op["attrs"] = attrs
                        logger.warning(f"No SIDC found for overlay kind '{overlay_kind}', using fallback {fallback}")

    return proposed_ops


def _enrich_delete_ops(proposed_ops: List[Dict[str, Any]], entities: list, overlays: list) -> List[Dict[str, Any]]:
    """
    Enrich delete operations with entity/overlay details for preview display.
    Uses 'attrs' and 'kind' fields to match create operation structure.
    """
    # Build lookup maps
    entity_map = {str(e.id): e for e in entities}
    overlay_map = {str(o.id): o for o in overlays}
    
    for op in proposed_ops:
        if op.get("op") == "delete_entity":
            entity_id = op.get("id")
            if entity_id and entity_id in entity_map:
                entity = entity_map[entity_id]
                entity_attrs = entity.attrs or {}
                # Use same field names as create_entity for consistency
                op["kind"] = entity.kind
                op["attrs"] = {
                    "name": entity_attrs.get("name", "Unnamed"),
                    "sidc": entity_attrs.get("sidc"),
                    "affiliation": entity_attrs.get("affiliation"),
                    "echelon": entity_attrs.get("echelon"),
                    "unitType": entity_attrs.get("unitType")
                }
        
        elif op.get("op") == "delete_overlay":
            overlay_id = op.get("id")
            if overlay_id and overlay_id in overlay_map:
                overlay = overlay_map[overlay_id]
                op["kind"] = overlay.kind
                op["name"] = overlay.name or "Unnamed"
    
    return proposed_ops

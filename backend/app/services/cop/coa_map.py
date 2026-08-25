"""
COA Map generation service.

Clones the COP base map (entities) and adds COA-specific tactical overlays
(phase lines, avenues of approach, objectives, etc.) extracted from the
COA brief content via a single LLM call.
"""

import logging
import time
from typing import Dict, Any, List, Union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.map import Map
from app.schemas.cop import COAMapRequest, COAMapResponse
from app.schemas.geoops import (
    GeoOpsRequest,
    CreateEntity,
    CreateOverlay,
)
from app.schemas.common import GeoJSON
from app.services.llm.client import get_llm_client
from app.services.llm.base import Message
from app.services.knowledge.geoops_executor import execute_geoops
from app.services.knowledge.spatial_query import get_entities
from app.services.view.map_state import get_map_state
from app.services.nl.agent import _parse_llm_response
from app.services.cop.coa_map_prompts import COA_MAP_SYSTEM_PROMPT
from app.constants.overlays import get_overlay_type_info
from app.utils.mgrs_utils import latlng_to_mgrs, convert_geojson_mgrs_to_latlng

from sqlalchemy import select

logger = logging.getLogger(__name__)


def _entity_positions_context(entities) -> str:
    """Build a text summary of entity positions for the LLM prompt.

    Entities from get_entities() have .geom as GeoJSON dicts,
    e.g. {"type": "Point", "coordinates": [lon, lat]}.

    Includes both MGRS grid references and [lon, lat] so the LLM can
    output overlays using MGRS coordinates.
    """
    lines = []
    for e in entities:
        geom = e.geom  # already a GeoJSON dict
        coords = geom.get("coordinates", [])
        attrs = e.attrs or {}
        name = attrs.get("name", "Unknown")
        affiliation = attrs.get("affiliation", "Unknown")
        if geom.get("type") == "Point" and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            try:
                mgrs_str = latlng_to_mgrs(lat, lon, precision=4)
                lines.append(f"- {name} ({affiliation}): {mgrs_str}")
            except Exception:
                lines.append(f"- {name} ({affiliation}): [{lon:.4f}, {lat:.4f}]")
        else:
            lines.append(f"- {name} ({affiliation}): {coords}")
    return "\n".join(lines) if lines else "No entities on map."


async def generate_coa_map(
    db: AsyncSession,
    request: COAMapRequest,
) -> COAMapResponse:
    """
    Generate a COA-specific map by cloning the COP and adding tactical overlays.

    Pipeline:
    1. Read entities from source COP map
    2. Create new map for this COA
    3. Clone entities into new map
    4. LLM extracts tactical overlays from COA brief content
    5. Create overlays on new map
    6. Return map state
    """
    t0 = time.time()

    # --- Step 1: Read source COP map and its entities ---
    source_map = await db.execute(
        select(Map).where(Map.id == request.source_map_id)
    )
    source_map_obj = source_map.scalar_one_or_none()
    if not source_map_obj:
        raise ValueError(f"Source map {request.source_map_id} not found")

    source_entities = await get_entities(db, request.source_map_id, None, None)
    logger.info(f"COA map: cloning {len(source_entities)} entities from COP map")

    # --- Step 2: Create new map ---
    bbox = [
        source_map_obj.bbox_west,
        source_map_obj.bbox_south,
        source_map_obj.bbox_east,
        source_map_obj.bbox_north,
    ]
    title = request.coa_title or f"COA {request.coa_number}"
    map_obj = Map(
        name=f"COA {request.coa_number} — {title[:40]}",
        user_id=request.user_id,
        bbox_west=bbox[0],
        bbox_south=bbox[1],
        bbox_east=bbox[2],
        bbox_north=bbox[3],
        center_lng=source_map_obj.center_lng,
        center_lat=source_map_obj.center_lat,
        zoom=source_map_obj.zoom,
        attrs={"source": "coa_map", "coa_number": request.coa_number, "source_cop_map_id": str(request.source_map_id)},
    )
    db.add(map_obj)
    await db.flush()

    # --- Step 3: Clone entities into new map ---
    # Entity .geom is already a GeoJSON dict from get_entities()
    clone_ops = []
    for e in source_entities:
        clone_ops.append(
            CreateEntity(
                kind=e.kind,
                geom=GeoJSON(
                    type=e.geom["type"],
                    coordinates=e.geom["coordinates"],
                ),
                attrs=dict(e.attrs) if e.attrs else {},
            )
        )

    if clone_ops:
        clone_request = GeoOpsRequest(
            map_id=map_obj.id,
            user_id=request.user_id,
            ops=clone_ops,
        )
        clone_result = await execute_geoops(db, clone_request)
        cloned = sum(1 for r in clone_result.results if r.success)
        logger.info(f"COA map: cloned {cloned}/{len(clone_ops)} entities")

    # --- Step 4: LLM call to extract tactical overlays ---
    entity_context = _entity_positions_context(source_entities)

    text_content = (
        f"## Existing Unit Positions (MGRS grid references)\n{entity_context}\n\n"
        f"## COA {request.coa_number} Brief\n{request.brief_content}"
    )

    # Build multimodal message when COP screenshot is provided
    if request.cop_screenshot_b64:
        user_content: Union[str, list] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": request.cop_screenshot_b64,
                },
            },
            {
                "type": "text",
                "text": (
                    "Above is the current COP map with MGRS grid labels. "
                    "Use the visible grid references and unit positions to "
                    "place overlays accurately using MGRS coordinates."
                ),
            },
            {"type": "text", "text": text_content},
        ]
    else:
        user_content = text_content

    logger.info("=== COA MAP LLM INPUT ===")
    logger.info(f"System prompt:\n{COA_MAP_SYSTEM_PROMPT}")
    logger.info(f"User prompt (text):\n{text_content}")
    if request.cop_screenshot_b64:
        logger.info("COP screenshot included as image input")

    llm = get_llm_client()
    response = await llm.chat(
        messages=[Message(role="user", content=user_content)],
        system=COA_MAP_SYSTEM_PROMPT,
        max_tokens=8192,
        temperature=0.3,
    )
    logger.info(f"COA map LLM call took {time.time() - t0:.2f}s")

    logger.info("=== COA MAP LLM OUTPUT ===")
    logger.info(f"Raw response:\n{response.content}")

    # --- Step 5: Parse and create overlays ---
    parsed = _parse_llm_response(response.content)
    raw_ops = parsed.get("ops", [])

    overlay_ops = []
    for op_dict in raw_ops:
        if op_dict.get("op") != "create_overlay":
            continue
        try:
            geom_data = op_dict["geom"]

            # Convert MGRS strings in coordinates to [lon, lat] arrays
            logger.info(f"Converting overlay geom: {geom_data}")
            geom_data = convert_geojson_mgrs_to_latlng(geom_data)
            logger.info(f"Converted overlay geom: {geom_data}")

            kind = op_dict.get("kind")
            if not kind:
                logger.warning("Skipping overlay op with no kind")
                continue
            attrs = op_dict.get("attrs", {})

            # Enrich with SIDC code so frontend renders the overlay
            type_info = get_overlay_type_info(kind)
            if type_info and "sidc" in type_info:
                attrs["sidc"] = type_info["sidc"]
            else:
                logger.warning(f"No SIDC found for overlay kind '{kind}' — will not render on map")

            overlay_ops.append(
                CreateOverlay(
                    kind=kind,
                    name=op_dict.get("name"),
                    geom=GeoJSON(
                        type=geom_data["type"],
                        coordinates=geom_data["coordinates"],
                    ),
                    attrs=attrs,
                )
            )
        except Exception as e:
            logger.warning(f"Skipping invalid overlay op: {e}")

    if overlay_ops:
        overlay_request = GeoOpsRequest(
            map_id=map_obj.id,
            user_id=request.user_id,
            ops=overlay_ops,
        )
        overlay_result = await execute_geoops(db, overlay_request)
        created = sum(1 for r in overlay_result.results if r.success)
        failed = sum(1 for r in overlay_result.results if not r.success)
        logger.info(f"COA map overlays: {created} created, {failed} failed")

    # --- Step 6: Return map state ---
    map_state = await get_map_state(db, map_obj.id)
    await db.commit()

    logger.info(f"COA map generation total: {time.time() - t0:.2f}s")

    return COAMapResponse(
        map_id=map_obj.id,
        bbox=bbox,
        entities=map_state["entities"],
        overlays=map_state["overlays"],
        routes=map_state["routes"],
        meta=map_state["meta"],
    )

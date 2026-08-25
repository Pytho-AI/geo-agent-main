"""
COP (Common Operational Picture) generation service.

Takes a world state narrative plus optional structured inputs (forces,
IPOE products, mission analysis), feeds everything to a single LLM call
to extract military entities, then enriches with SIDC symbols and
populates a geo-agent map.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.map import Map
from app.schemas.cop import (
    COPGenerateRequest,
    COPGenerateResponse,
    COPTerrainSummary,
)
from app.schemas.geoops import (
    GeoOpsRequest,
    CreateEntity,
)
from app.schemas.common import GeoJSON
from app.services.llm.client import get_llm_client
from app.services.llm.base import Message
from app.services.knowledge.geoops_executor import execute_geoops
from app.services.view.map_state import get_map_state
from app.services.nl.agent import (
    _parse_llm_response,
    enrich_entity_from_name,
    _build_symbol_context,
)
from app.services.cop.prompts import COP_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _build_user_prompt(request: COPGenerateRequest) -> str:
    """Assemble all available context into a single user prompt for the LLM."""
    sections: List[str] = []

    # World state is always present
    sections.append(f"## World State\n{request.world_state}")

    # Structured friendly forces
    if request.forces:
        lines = []
        for f in request.forces:
            parts = [f.unitName]
            if f.unitType:
                parts.append(f"Type: {f.unitType}")
            if f.size:
                parts.append(f"Size: {f.size}")
            if f.currentLocation:
                parts.append(f"Location: {f.currentLocation}")
            if f.capability:
                parts.append(f"Capability: {f.capability}")
            if f.availability:
                parts.append(f"Availability: {f.availability}")
            if f.notes:
                parts.append(f"Notes: {f.notes}")
            lines.append("- " + " | ".join(parts))
        sections.append(
            "## Friendly Forces (structured Order of Battle)\n"
            "These are FRIENDLY units. Set affiliation to 'Friend' for all of them.\n"
            + "\n".join(lines)
        )

    # IPOE products (enemy intelligence)
    if request.ipoe_products:
        sections.append(
            "## IPOE Products (Intelligence - Enemy Forces)\n"
            "Extract all enemy/hostile units from this intelligence product. "
            "Set affiliation to 'Hostile' for all enemy entities.\n"
            + request.ipoe_products
        )

    # Mission analysis
    if request.mission_analysis:
        sections.append(
            "## Mission Analysis\n"
            "Use this for additional context on locations, tasks, and operational areas.\n"
            + request.mission_analysis
        )

    return "\n\n".join(sections)


async def generate_cop(
    db: AsyncSession,
    request: COPGenerateRequest,
) -> COPGenerateResponse:
    """
    Generate a COP from all available context in a single LLM call.

    Pipeline:
    1. Assemble world_state + forces + IPOE + mission analysis into one prompt
    2. LLM extracts all entities (friendly + enemy) with coordinates
    3. Enrich entities with SIDC symbols
    4. Create map and execute GeoOps
    """
    t0 = time.time()

    # --- Step 1: Single LLM call with all context ---
    llm = get_llm_client()
    # symbol_context = _build_symbol_context()
    system_prompt = f"{COP_SYSTEM_PROMPT}"

    user_content = _build_user_prompt(request)
    messages = [Message(role="user", content=user_content)]

    logger.info("=== COP LLM INPUT ===")
    logger.info(f"System prompt:\n{system_prompt}")
    logger.info(f"User prompt:\n{user_content}")

    response = await llm.chat(
        messages=messages,
        system=system_prompt,
        max_tokens=8192,
        temperature=0.3,
    )
    logger.info(f"COP LLM call took {time.time() - t0:.2f}s")

    logger.info("=== COP LLM OUTPUT ===")
    logger.info(f"Raw response:\n{response.content}")

    # --- Step 2: Parse response ---
    parsed = _parse_llm_response(response.content)
    summary = parsed.get("summary", "COP generated")
    bbox = parsed.get("bbox")
    raw_ops = parsed.get("ops", [])

    if not bbox or len(bbox) != 4:
        bbox = _derive_bbox_from_ops(raw_ops)

    # --- Step 3: Build typed GeoOps ---
    geoops = _build_geoops(raw_ops)

    # --- Step 4: Enrich entities with SIDC symbols ---
    for op in geoops:
        if isinstance(op, CreateEntity) and op.kind == "mil_unit":
            attrs = op.attrs or {}
            enriched = enrich_entity_from_name(
                attrs.get("name", ""),
                attrs.get("affiliation", "Friend"),
                attrs.get("echelon", "Battalion"),
            )
            for key, value in enriched.items():
                if not attrs.get(key):
                    attrs[key] = value
            op.attrs = attrs

    # --- Step 5: Create Map ---
    map_obj = Map(
        name=f"COP - {summary[:50]}",
        user_id=request.user_id,
        bbox_west=bbox[0],
        bbox_south=bbox[1],
        bbox_east=bbox[2],
        bbox_north=bbox[3],
        center_lng=(bbox[0] + bbox[2]) / 2,
        center_lat=(bbox[1] + bbox[3]) / 2,
        zoom=8,
        attrs={"source": "cop_generation"},
    )
    db.add(map_obj)
    await db.flush()

    # --- Step 6: Execute GeoOps ---
    geoops_request = GeoOpsRequest(
        map_id=map_obj.id,
        user_id=request.user_id,
        ops=geoops,
    )
    geoops_response = await execute_geoops(db, geoops_request)

    success_count = sum(1 for r in geoops_response.results if r.success)
    fail_count = sum(1 for r in geoops_response.results if not r.success)
    route_count = sum(1 for r in geoops_response.results if r.op == "create_route" and r.success)
    logger.info(f"COP GeoOps: {success_count} succeeded, {fail_count} failed ({route_count} routes)")

    # --- Step 7: Terrain sampling (optional, non-fatal) ---
    terrain_summary = None
    try:
        terrain_summary = await _sample_cop_terrain(tuple(bbox))
    except Exception as e:
        logger.warning(f"Terrain sampling failed (non-fatal): {e}")

    # --- Step 8: Get map state ---
    map_state = await get_map_state(db, map_obj.id)

    await db.commit()

    logger.info(f"COP generation total: {time.time() - t0:.2f}s")

    return COPGenerateResponse(
        map_id=map_obj.id,
        bbox=bbox,
        entities=map_state["entities"],
        overlays=map_state["overlays"],
        routes=map_state["routes"],
        terrain=terrain_summary,
        meta={
            **map_state["meta"],
            "route_count": route_count,
            "ops_succeeded": success_count,
            "ops_failed": fail_count,
        },
        generation_summary=summary,
    )


def _derive_bbox_from_ops(ops: List[Dict]) -> List[float]:
    """Derive bounding box from entity/overlay/route coordinates with padding."""
    lons, lats = [], []
    for op in ops:
        # Handle route start/end points
        if op.get("op") == "create_route":
            for geom_key in ("start_geom", "end_geom"):
                geom = op.get(geom_key, {})
                coords = geom.get("coordinates", [])
                if len(coords) == 2:
                    lons.append(coords[0])
                    lats.append(coords[1])
            continue

        geom = op.get("geom", {})
        coords = geom.get("coordinates", [])
        if geom.get("type") == "Point" and len(coords) == 2:
            lons.append(coords[0])
            lats.append(coords[1])
        elif geom.get("type") == "LineString":
            for c in coords:
                if isinstance(c, (list, tuple)) and len(c) == 2:
                    lons.append(c[0])
                    lats.append(c[1])
        elif geom.get("type") == "Polygon" and coords:
            for ring in coords:
                for c in ring:
                    if isinstance(c, (list, tuple)) and len(c) == 2:
                        lons.append(c[0])
                        lats.append(c[1])

    if not lons or not lats:
        return [-1, -1, 1, 1]

    padding = 0.1  # ~11km at equator
    return [
        min(lons) - padding,
        min(lats) - padding,
        max(lons) + padding,
        max(lats) + padding,
    ]


def _build_geoops(raw_ops: List[Dict]) -> list:
    """Convert raw LLM ops dicts into typed CreateEntity objects (entities only)."""
    typed_ops = []
    for op_dict in raw_ops:
        if op_dict.get("op") != "create_entity":
            continue
        try:
            geom_data = op_dict["geom"]
            typed_ops.append(
                CreateEntity(
                    kind=op_dict.get("kind", "mil_unit"),
                    geom=GeoJSON(
                        type=geom_data["type"],
                        coordinates=geom_data["coordinates"],
                    ),
                    attrs=op_dict.get("attrs", {}),
                )
            )
        except Exception as e:
            logger.warning(f"Skipping invalid op: {e}")
    return typed_ops


async def _sample_cop_terrain(
    bbox: tuple,
) -> Optional[COPTerrainSummary]:
    """Sample terrain for the COP area of operations."""
    from app.services.knowledge.geodata import get_terrain
    from app.services.nl.tools.terrain import _terrain_point_to_dict

    grid = await get_terrain(bbox, resolution="fine", compute_slope=False)
    if not grid.points:
        return None

    elevations = [
        p.elevation_m for p in grid.points if p.elevation_m is not None
    ]
    land_covers: Dict[str, int] = {}
    for p in grid.points:
        if p.land_cover_display:
            land_covers[p.land_cover_display] = land_covers.get(p.land_cover_display, 0) + 1

    dominant = sorted(land_covers.items(), key=lambda x: -x[1])[:3]

    # Convert to dict format for terrain_grid field (preserves schema contract)
    grid_dicts = [_terrain_point_to_dict(p) for p in grid.points]

    return COPTerrainSummary(
        elevation_range_m=[min(elevations), max(elevations)] if elevations else None,
        dominant_land_cover=[name for name, _ in dominant],
        terrain_grid=grid_dicts,
    )

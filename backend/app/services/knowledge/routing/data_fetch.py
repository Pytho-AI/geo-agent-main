"""Viewport data fetching and threat/no-go extraction."""

import asyncio
import logging
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.roads import fetch_roads, Road
from app.services.knowledge.geodata import sample_terrain_at
from app.services.knowledge.spatial_query import get_entities, get_overlays
from app.services.knowledge.cache import spatial_cache
from .models import (
    ThreatZone, NoGoZone, NoGoLine, MacroTile, ViewportData,
    SAMPLES_PER_TILE_SIDE,
)

logger = logging.getLogger(__name__)


async def extract_threats(db: AsyncSession, map_id, bbox):
    """Fetch threats, no-go zones, and no-go lines from map entities/overlays."""
    threats, no_go, no_go_lines = [], [], []
    bbox_query = [bbox[1], bbox[0], bbox[3], bbox[2]]
    entity_result, overlay_result = await asyncio.gather(
        get_entities(db, map_id, bbox=bbox_query),
        get_overlays(db, map_id, bbox=bbox_query),
        return_exceptions=True,
    )
    if not isinstance(entity_result, Exception):
        for ent in entity_result:
            attrs = ent.attrs or {}
            if attrs.get("affiliation", "").lower() in ("hostile", "enemy", "opposing"):
                geom = ent.geom
                if isinstance(geom, dict) and geom.get("type") == "Point":
                    c = geom["coordinates"]
                    threats.append(ThreatZone(c[1], c[0], attrs.get("threat_radius_m", 2000), 5.0))
    else:
        logger.warning(f"Could not fetch entities: {entity_result}")
    if not isinstance(overlay_result, Exception):
        for ov in overlay_result:
            attrs = ov.attrs or {}
            affiliation = attrs.get("affiliation", "").lower()
            if affiliation not in ("hostile", "enemy", "opposing"):
                continue
            geom = ov.geom
            if isinstance(geom, dict):
                if geom.get("type") == "Polygon":
                    no_go.append(NoGoZone([(c[0], c[1]) for c in geom["coordinates"][0]]))
                elif geom.get("type") == "LineString":
                    no_go_lines.append(NoGoLine([(c[0], c[1]) for c in geom["coordinates"]]))
    else:
        logger.warning(f"Could not fetch overlays: {overlay_result}")
    logger.info(f"Route planner: {len(threats)} threats, {len(no_go)} no-go zones, {len(no_go_lines)} no-go lines")
    return threats, no_go, no_go_lines


async def fetch_viewport_data(bbox, tile_grid, map_id, mode) -> ViewportData:
    """Fetch roads, elevation, and land cover with per-source caching."""
    rows = len(tile_grid)
    cols = len(tile_grid[0]) if rows else 0
    cache_bbox = list(bbox)
    needs_roads = mode in ("on_road", "mixed")

    sample_coords, sample_tile_map = [], []
    for r in range(rows):
        for c in range(cols):
            tile = tile_grid[r][c]
            h_step = (tile.north - tile.south) / SAMPLES_PER_TILE_SIDE
            w_step = (tile.east - tile.west) / SAMPLES_PER_TILE_SIDE
            for sr in range(SAMPLES_PER_TILE_SIDE):
                for sc in range(SAMPLES_PER_TILE_SIDE):
                    sample_coords.append((tile.south + (sr + 0.5) * h_step,
                                          tile.west + (sc + 0.5) * w_step))
                    sample_tile_map.append((r, c))

    # Fetch roads (separate concern — polyline network, not point-sampled)
    roads: List[Road] = []
    roads_task = None
    if needs_roads:
        cached = spatial_cache.get("viewport_roads", map_id, cache_bbox)
        if cached is not None:
            roads = cached
        else:
            roads_task = fetch_roads(bbox, map_id=map_id)

    # Fetch terrain data via common geodata layer
    terrain_task = sample_terrain_at(
        sample_coords,
        bbox=tuple(cache_bbox),
        compute_slope=False,  # tile_graph computes tile-level slope
        elevation_zoom=12,
    )

    if roads_task is not None:
        logger.info("Fetching: roads, terrain")
        roads_result, terrain_points = await asyncio.gather(roads_task, terrain_task)
        roads = roads_result
        spatial_cache.put("viewport_roads", map_id, cache_bbox, roads, ttl_seconds=1800)
    else:
        logger.info("Fetching: terrain")
        terrain_points = await terrain_task

    elevations = [p.elevation_m for p in terrain_points]
    land_covers = terrain_points  # tile_graph reads TerrainPoint attributes

    return ViewportData(roads=roads, sample_coords=sample_coords,
                        elevations=elevations, land_covers=land_covers,
                        sample_tile_map=sample_tile_map)

"""
Road data from OpenStreetMap via Overpass API.

Roads are represented as named corridors (polylines), not a routing graph.
Each OSM way becomes one Road with its full coordinate list.

Used by the route planner to build the road graph for on-road
and mixed mode routing.
"""

import asyncio
import json
import logging
import math
import os
import shutil
import tempfile
import httpx
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from app.services.knowledge.geo_utils import haversine
from app.config import get_settings

logger = logging.getLogger(__name__)

# Multiple public Overpass API servers — rotate to avoid rate limiting
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_server_index = 0

# Overpass operators reject anonymous/generic client UAs (the bare
# python-httpx default draws 406 Not Acceptable from overpass-api.de).
# OSM ecosystem policy wants an identifying product string + contact.
OVERPASS_HEADERS = {
    "User-Agent": "pytho-geo-agent/1.0 (+https://pytho.ai; allen@pytho.ai)",
}

# OSM highway types and their properties
ROAD_PROPERTIES: Dict[str, Dict[str, Any]] = {
    "motorway":       {"speed_mph": 65, "label": "Motorway"},
    "trunk":          {"speed_mph": 55, "label": "Trunk Road"},
    "primary":        {"speed_mph": 45, "label": "Primary Road"}, 
}


@dataclass
class Road:
    """A road corridor — one OSM way as a polyline."""
    way_id: int
    name: Optional[str]
    highway_type: str
    speed_mph: float
    oneway: bool
    coords: List[Tuple[float, float]]  # [(lon, lat), ...] — full polyline
    length_m: float = 0.0  # total road length


def _build_overpass_query(bbox: Tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox

    highway_types = "|".join(ROAD_PROPERTIES.keys())
    return f"""
[out:json][timeout:180];
(
  way["highway"~"^({highway_types})$"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
"""


def _parse_overpass_response(data: dict) -> List[Road]:
    """Parse Overpass JSON into a list of Road corridors."""
    # First pass: collect all nodes
    nodes: Dict[int, Tuple[float, float]] = {}  # id -> (lat, lon)
    for el in data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])

    # Second pass: build roads from ways
    roads: List[Road] = []
    for el in data.get("elements", []):
        if el["type"] != "way":
            continue

        tags = el.get("tags", {})
        highway = tags.get("highway", "unclassified")
        props = ROAD_PROPERTIES.get(highway)
        if not props:
            continue  # skip road types we don't care about
        node_ids = el.get("nodes", [])
        if len(node_ids) < 2:
            continue

        # Build coordinate list, skip missing nodes
        coords = []
        for nid in node_ids:
            if nid in nodes:
                lat, lon = nodes[nid]
                coords.append((lon, lat))
        if len(coords) < 2:
            continue

        # Compute total length
        length_m = 0.0
        for i in range(len(coords) - 1):
            length_m += haversine(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])

        roads.append(Road(
            way_id=el["id"],
            name=tags.get("name"),
            highway_type=highway,
            speed_mph=props["speed_mph"],
            oneway=tags.get("oneway", "no") in ("yes", "true", "1"),
            coords=coords,
            length_m=length_m,
        ))

    return roads


MAX_CHUNK_DEG = 2.0  # ~220km — safe for major roads only (motorway/trunk/primary)


def _split_bbox(bbox: Tuple[float, float, float, float]) -> List[Tuple[float, float, float, float]]:
    """Split a large bbox into smaller chunks that won't timeout on Overpass."""
    s, w, n, e = bbox
    lat_span = n - s
    lon_span = e - w

    if lat_span <= MAX_CHUNK_DEG and lon_span <= MAX_CHUNK_DEG:
        return [bbox]

    lat_steps = max(1, math.ceil(lat_span / MAX_CHUNK_DEG))
    lon_steps = max(1, math.ceil(lon_span / MAX_CHUNK_DEG))
    lat_size = lat_span / lat_steps
    lon_size = lon_span / lon_steps

    chunks = []
    for ri in range(lat_steps):
        for ci in range(lon_steps):
            chunks.append((
                s + ri * lat_size,
                w + ci * lon_size,
                s + (ri + 1) * lat_size,
                w + (ci + 1) * lon_size,
            ))
    return chunks


async def _fetch_chunk(bbox: Tuple[float, float, float, float], retries: int = 3) -> List[Road]:
    """Fetch roads for a single bbox chunk. Retries with backoff on failure."""
    global _server_index
    query = _build_overpass_query(bbox)

    for attempt in range(retries + 1):
        url = OVERPASS_SERVERS[_server_index % len(OVERPASS_SERVERS)]
        _server_index += 1
        try:
            async with httpx.AsyncClient(timeout=180, headers=OVERPASS_HEADERS) as client:
                response = await client.post(url, data={"data": query})
                if response.status_code == 429:
                    raise httpx.HTTPStatusError("429 Too Many Requests", request=response.request, response=response)
                response.raise_for_status()
                text = response.text
                if not text or not text.strip().startswith("{"):
                    raise ValueError(f"Non-JSON response from {url}: {text[:100]}")
                data = response.json()
            return _parse_overpass_response(data)
        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as e:
            if attempt < retries:
                delay = (attempt + 1) * 5  # 5s, 10s, 15s backoff
                logger.warning(f"Roads: {url} failed ({e}), retrying in {delay}s (attempt {attempt + 1}/{retries})")
                await asyncio.sleep(delay)
            else:
                raise


_offline_roads_cache: Optional[List[Road]] = None


def _load_offline_roads() -> List[Road]:
    """Load pre-downloaded road data from JSON file."""
    global _offline_roads_cache
    if _offline_roads_cache is not None:
        return _offline_roads_cache

    settings = get_settings()
    # Roads live under offline/osm/ alongside the other OSM-derived JSON
    # dumps (builtup, forest, water, waterways, wetland) produced by
    # scripts/offline/download_roads.py. The historical "routing/" path
    # was never populated and never matched the download script's output.
    roads_file = os.path.join(settings.offline_data_dir, "osm", "roads.json")
    logger.info(f"Roads: loading offline data from {roads_file}")

    # Copy to local filesystem first — bind mounts from Windows are extremely
    # slow for random-read I/O (json.load).  A sequential copy is faster.
    local_copy = os.path.join(tempfile.gettempdir(), "roads_local.json")
    shutil.copy2(roads_file, local_copy)
    logger.info(f"Roads: copied to {local_copy}")

    with open(local_copy, "r") as f:
        data = json.load(f)

    os.remove(local_copy)
    logger.info(f"Roads: JSON parsed, {len(data)} entries")

    roads = [Road(
        way_id=r["way_id"],
        name=r.get("name"),
        highway_type=r["highway_type"],
        speed_mph=r["speed_mph"],
        oneway=r["oneway"],
        coords=[tuple(c) for c in r["coords"]],
        length_m=r.get("length_m", 0.0),
    ) for r in data]

    logger.info(f"Roads: loaded {len(roads)} roads from offline cache")
    _offline_roads_cache = roads
    return roads


async def fetch_roads(
    bbox: Tuple[float, float, float, float],
    map_id: str,
) -> List[Road]:
    """
    Fetch roads from OSM Overpass API for a bounding box.
    Splits large bboxes into smaller parallel chunks to avoid timeouts.
    Deduplicates roads by way_id across chunks.

    In offline mode, loads from pre-downloaded JSON and filters by bbox.
    """
    settings = get_settings()
    if settings.offline_mode:
        all_roads = _load_offline_roads()
        s, w, n, e = bbox
        filtered = roads_in_bbox(all_roads, s, w, n, e)
        logger.info(f"Roads: {len(filtered)} corridors in bbox (offline)")
        return filtered

    chunks = _split_bbox(bbox)
    logger.info(f"Roads: fetching {len(chunks)} chunk(s) for bbox {bbox}")

    if len(chunks) == 1:
        roads = await _fetch_chunk(chunks[0])
    else:
        # Fetch chunks in batches of 4 to avoid Overpass rate limiting
        BATCH_SIZE = 4
        all_results = []
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i + BATCH_SIZE]
            results = await asyncio.gather(*[_fetch_chunk(c) for c in batch], return_exceptions=True)
            all_results.extend(results)           
        results = all_results

        # Merge and deduplicate by way_id
        seen_ids: set = set()
        roads: List[Road] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Roads: chunk failed ({result})")
                continue
            for road in result:
                if road.way_id not in seen_ids:
                    seen_ids.add(road.way_id)
                    roads.append(road)

    logger.info(f"Roads: {len(roads)} corridors total")
    return roads


def roads_in_bbox(roads: List[Road], south: float, west: float, north: float, east: float) -> List[Road]:
    """Filter roads that have at least one coordinate within a bbox."""
    result = []
    for road in roads:
        for lon, lat in road.coords:
            if south <= lat <= north and west <= lon <= east:
                result.append(road)
                break
    return result


def find_boundary_crossings(
    roads: List[Road],
    south: float, west: float, north: float, east: float,
    margin: float = 0.001,
) -> Dict[str, List[Tuple[int, float, float, str, float]]]:
    """
    Find where roads cross tile boundaries.

    Returns: {direction: [(way_id, lat, lon, road_name, speed_mph), ...]}
    """
    crossings: Dict[str, List[Tuple[int, float, float, str, float]]] = {
        "north": [], "south": [], "east": [], "west": [],
    }

    for road in roads:
        for i in range(len(road.coords) - 1):
            lon_a, lat_a = road.coords[i]
            lon_b, lat_b = road.coords[i + 1]

            # Check if segment crosses north boundary
            if (lat_a < north <= lat_b) or (lat_b < north <= lat_a):
                if west <= lon_a <= east or west <= lon_b <= east:
                    frac = (north - lat_a) / (lat_b - lat_a) if lat_b != lat_a else 0.5
                    cross_lon = lon_a + frac * (lon_b - lon_a)
                    crossings["north"].append((road.way_id, north, cross_lon, road.name, road.speed_mph))

            # South boundary
            if (lat_a < south <= lat_b) or (lat_b < south <= lat_a):
                if west <= lon_a <= east or west <= lon_b <= east:
                    frac = (south - lat_a) / (lat_b - lat_a) if lat_b != lat_a else 0.5
                    cross_lon = lon_a + frac * (lon_b - lon_a)
                    crossings["south"].append((road.way_id, south, cross_lon, road.name, road.speed_mph))

            # East boundary
            if (lon_a < east <= lon_b) or (lon_b < east <= lon_a):
                if south <= lat_a <= north or south <= lat_b <= north:
                    frac = (east - lon_a) / (lon_b - lon_a) if lon_b != lon_a else 0.5
                    cross_lat = lat_a + frac * (lat_b - lat_a)
                    crossings["east"].append((road.way_id, cross_lat, east, road.name, road.speed_mph))

            # West boundary
            if (lon_a < west <= lon_b) or (lon_b < west <= lon_a):
                if south <= lat_a <= north or south <= lat_b <= north:
                    frac = (west - lon_a) / (lon_b - lon_a) if lon_b != lon_a else 0.5
                    cross_lat = lat_a + frac * (lat_b - lat_a)
                    crossings["west"].append((road.way_id, cross_lat, west, road.name, road.speed_mph))

    return crossings


def get_road_coords_in_bbox(
    road: Road,
    south: float, west: float, north: float, east: float,
) -> List[Tuple[float, float]]:
    """Get the portion of a road's coordinates that fall within a bbox."""
    return [(lon, lat) for lon, lat in road.coords
            if south <= lat <= north and west <= lon <= east]


def get_road_by_id(roads: List[Road], way_id: int) -> Optional[Road]:
    """Find a road by its way_id."""
    for r in roads:
        if r.way_id == way_id:
            return r
    return None

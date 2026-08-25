"""Build road intersection graph from Road corridors."""

import logging
import time
from typing import Dict, List, Tuple

from app.services.knowledge.geo_utils import haversine
from app.services.knowledge.roads import Road
from .models import (
    Node, RoadNode, ThreatZone, NoGoZone, NoGoLine, RoutePreferences,
    METERS_PER_MILE,
)
from .cost import road_edge_cost

logger = logging.getLogger(__name__)


def build_road_graph(
    roads: List[Road],
    threats: List[ThreatZone] = None,
    no_go: List[NoGoZone] = None,
    preferences: RoutePreferences = None,
    no_go_lines: List[NoGoLine] = None,
) -> Tuple[
    Dict[Node, List[Tuple[Node, float]]],                  # search adj
    Dict[Tuple[Node, Node], List[Tuple[float, float]]],    # drawing data
    Dict[Node, Tuple[float, float]],                        # node positions
]:
    """
    Build a road graph where nodes are only at intersections and endpoints.
    Edges carry distance cost for search. Drawing coords stored separately.
    """
    t0 = time.monotonic()
    search_adj: Dict[Node, List[Tuple[Node, float]]] = {}
    draw_data: Dict[Tuple[Node, Node], List[Tuple[float, float]]] = {}
    node_pos: Dict[Node, Tuple[float, float]] = {}

    total_coords = sum(len(r.coords) for r in roads)
    logger.info(f"Road graph: building from {len(roads)} roads, {total_coords} coords")

    # Step 1: Index all road coord positions for intersection detection
    coord_index: Dict[Tuple[int, int], List[Tuple[int, int, float, float]]] = {}
    for road in roads:
        for ci, (lon, lat) in enumerate(road.coords):
            key = (round(lat * 3000), round(lon * 3000))  # ~30m grid
            coord_index.setdefault(key, []).append((road.way_id, ci, lon, lat))

    # Step 2: Find intersection indices — coords shared by 2+ roads, plus endpoints
    intersection_set: set = set()
    for entries in coord_index.values():
        if len(entries) > 1:
            for way_id, ci, _, _ in entries:
                intersection_set.add((way_id, ci))

    for road in roads:
        intersection_set.add((road.way_id, 0))
        intersection_set.add((road.way_id, len(road.coords) - 1))

    # Pre-index intersections by way_id to avoid scanning the full set per road
    way_intersections: Dict[int, List[int]] = {}
    for wid, ci in intersection_set:
        way_intersections.setdefault(wid, []).append(ci)
    for wid in way_intersections:
        way_intersections[wid].sort()

    # Step 3: Build edges between consecutive intersection nodes on each road
    for road in roads:
        road_intersections = way_intersections.get(road.way_id, [])

        for k in range(len(road_intersections) - 1):
            ci_a = road_intersections[k]
            ci_b = road_intersections[k + 1]

            node_a = RoadNode("road", road.way_id, ci_a)
            node_b = RoadNode("road", road.way_id, ci_b)

            node_pos[node_a] = road.coords[ci_a]
            node_pos[node_b] = road.coords[ci_b]

            # Compute edge distance along the road
            dist = 0.0
            segment_coords = []
            for i in range(ci_a, ci_b + 1):
                segment_coords.append(road.coords[i])
                if i > ci_a:
                    dist += haversine(
                        road.coords[i - 1][1], road.coords[i - 1][0],
                        road.coords[i][1], road.coords[i][0],
                    ) / METERS_PER_MILE

            # Edge cost: checks every point along the road for no-go/threats
            threat_w = preferences.threat_weight if preferences else 1.0
            cost = road_edge_cost(dist, segment_coords, threats, no_go, threat_w, no_go_lines)
            if cost == float("inf"):
                continue

            search_adj.setdefault(node_a, []).append((node_b, cost))
            draw_data[(node_a, node_b)] = segment_coords

            if not road.oneway:
                search_adj.setdefault(node_b, []).append((node_a, cost))
                draw_data[(node_b, node_a)] = list(reversed(segment_coords))

    # Step 4: Connect intersections across roads (where coords are close)
    for entries in coord_index.values():
        if len(entries) <= 1:
            continue
        nodes_here = [RoadNode("road", wid, ci) for wid, ci, _, _ in entries if (wid, ci) in intersection_set]
        for i in range(len(nodes_here)):
            for j in range(i + 1, len(nodes_here)):
                na, nb = nodes_here[i], nodes_here[j]
                if na == nb:
                    continue
                pos_a = node_pos.get(na)
                pos_b = node_pos.get(nb)
                if pos_a and pos_b:
                    search_adj.setdefault(na, []).append((nb, 0.0))
                    search_adj.setdefault(nb, []).append((na, 0.0))
                    draw_data[(na, nb)] = [pos_a, pos_b]
                    draw_data[(nb, na)] = [pos_b, pos_a]

    elapsed = time.monotonic() - t0
    logger.info(f"Road graph: {len(node_pos)} nodes, {sum(len(v) for v in search_adj.values())} edges ({elapsed:.2f}s)")
    return search_adj, draw_data, node_pos

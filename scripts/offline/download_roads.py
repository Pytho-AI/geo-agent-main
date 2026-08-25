#!/usr/bin/env python3
"""
Pre-fetch OSM road data via Overpass API and save as JSON.

Reuses the same query logic and road types as the backend roads.py module.

Usage:
  python download_roads.py --bbox "south,west,north,east" --output roads.json
"""

import argparse
import json
import math
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError

OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

ROAD_PROPERTIES = {
    "motorway":       {"speed_mph": 65, "label": "Motorway"},
    "trunk":          {"speed_mph": 55, "label": "Trunk Road"},
    "primary":        {"speed_mph": 45, "label": "Primary Road"},
    "secondary":      {"speed_mph": 35, "label": "Secondary Road"},
    "tertiary":       {"speed_mph": 30, "label": "Tertiary Road"},
    "unclassified":   {"speed_mph": 25, "label": "Unclassified Road"},
    "residential":    {"speed_mph": 25, "label": "Residential"},
    "service":        {"speed_mph": 15, "label": "Service Road"},
    "track":          {"speed_mph": 10, "label": "Track"},
}

ROAD_TYPES = "|".join(ROAD_PROPERTIES.keys())

MAX_CHUNK_DEG = 0.5  # ~55km — minor + track classes are 100x denser than majors; smaller chunks keep each Overpass response under cap
_server_index = 0


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def split_bbox(bbox):
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
                s + ri * lat_size, w + ci * lon_size,
                s + (ri + 1) * lat_size, w + (ci + 1) * lon_size,
            ))
    return chunks


def fetch_chunk(bbox, retries=2):
    global _server_index
    s, w, n, e = bbox
    query = f"""
[out:json][timeout:180];
(
  way["highway"~"^({ROAD_TYPES})$"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
"""
    for attempt in range(retries + 1):
        url = OVERPASS_SERVERS[_server_index % len(OVERPASS_SERVERS)]
        _server_index += 1
        try:
            data = f"data={query}".encode("utf-8")
            req = Request(url, data=data, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "geo-agent-offline-prep/1.0",
            })
            with urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return parse_overpass(result)
        except Exception as e:
            if attempt < retries:
                print(f"  Warning: {url} failed ({e}), retrying...")
                time.sleep(1)
            else:
                raise


def parse_overpass(data):
    nodes = {}
    for el in data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])

    roads = []
    for el in data.get("elements", []):
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        highway = tags.get("highway", "unclassified")
        props = ROAD_PROPERTIES.get(highway)
        if not props:
            continue
        node_ids = el.get("nodes", [])
        if len(node_ids) < 2:
            continue
        coords = []
        for nid in node_ids:
            if nid in nodes:
                lat, lon = nodes[nid]
                coords.append([lon, lat])
        if len(coords) < 2:
            continue

        length_m = 0.0
        for i in range(len(coords) - 1):
            length_m += haversine(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])

        roads.append({
            "way_id": el["id"],
            "name": tags.get("name"),
            "highway_type": highway,
            "speed_mph": props["speed_mph"],
            "oneway": tags.get("oneway", "no") in ("yes", "true", "1"),
            "coords": coords,
            "length_m": length_m,
        })
    return roads


def download_roads(bbox, output):
    chunks = split_bbox(bbox)
    print(f"Fetching roads: {len(chunks)} chunk(s) for bbox {bbox}")

    seen_ids = set()
    all_roads = []

    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i + 1}/{len(chunks)}: {chunk}")
        try:
            roads = fetch_chunk(chunk)
            for road in roads:
                if road["way_id"] not in seen_ids:
                    seen_ids.add(road["way_id"])
                    all_roads.append(road)
        except Exception as e:
            print(f"  Warning: chunk {i + 1} failed ({e}), skipping")

        # Rate limit between chunks
        if i < len(chunks) - 1:
            time.sleep(0.5)

    print(f"Total: {len(all_roads)} roads")

    with open(output, "w") as f:
        json.dump(all_roads, f)

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"Saved to {output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    import os
    parser = argparse.ArgumentParser(description="Download OSM road data")
    parser.add_argument("--bbox", required=True, help="south,west,north,east")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    parts = [float(x.strip()) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("Error: bbox must be 'south,west,north,east'")
        sys.exit(1)

    download_roads(tuple(parts), args.output)

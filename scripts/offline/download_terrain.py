#!/usr/bin/env python3
"""
Download AWS Terrain Tiles and pack them into an MBTiles file.

Tiles are Terrarium-encoded PNGs:
  elevation = (red * 256 + green + blue / 256) - 32768

Usage:
  python download_terrain.py --bbox "south,west,north,east" --output terrain.mbtiles [--max-zoom 14]
"""

import argparse
import math
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request

TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
USER_AGENT = "geo-agent-offline-prep/1.0"


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def count_tiles(bbox: tuple[float, float, float, float], min_zoom: int, max_zoom: int) -> int:
    south, west, north, east = bbox
    total = 0
    for z in range(min_zoom, max_zoom + 1):
        x_min, _ = lat_lon_to_tile(north, west, z)
        x_max, _ = lat_lon_to_tile(south, east, z)
        _, y_min = lat_lon_to_tile(north, west, z)
        _, y_max = lat_lon_to_tile(south, east, z)
        total += (x_max - x_min + 1) * (y_max - y_min + 1)
    return total


def init_mbtiles(path: str) -> sqlite3.Connection:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    conn.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('name', 'terrain-terrarium')")
    conn.execute("INSERT INTO metadata VALUES ('format', 'png')")
    conn.execute("INSERT INTO metadata VALUES ('type', 'baselayer')")
    conn.commit()
    return conn


def fetch_tile(z: int, x: int, y: int) -> tuple[int, int, int, bytes | None]:
    url = TERRAIN_URL.format(z=z, x=x, y=y)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                return z, x, y, resp.read()
    except Exception:
        pass
    return z, x, y, None


def download_terrain(bbox: tuple, output: str, min_zoom: int = 0, max_zoom: int = 14):
    south, west, north, east = bbox
    total = count_tiles(bbox, min_zoom, max_zoom)
    print(f"Downloading {total} terrain tiles (zoom {min_zoom}-{max_zoom})...")

    conn = init_mbtiles(output)
    downloaded = 0
    failed = 0

    for z in range(min_zoom, max_zoom + 1):
        x_min, _ = lat_lon_to_tile(north, west, z)
        x_max, _ = lat_lon_to_tile(south, east, z)
        _, y_min = lat_lon_to_tile(north, west, z)
        _, y_max = lat_lon_to_tile(south, east, z)

        tasks = []
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tasks.append((z, x, y))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_tile, *t) for t in tasks]
            for future in as_completed(futures):
                tz, tx, ty, data = future.result()
                if data:
                    # MBTiles uses TMS y-flip
                    tms_y = (2 ** tz - 1) - ty
                    conn.execute(
                        "INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)",
                        (tz, tx, tms_y, data),
                    )
                    downloaded += 1
                else:
                    failed += 1

                if (downloaded + failed) % 100 == 0:
                    conn.commit()
                    pct = (downloaded + failed) / total * 100
                    print(f"  zoom {z}: {pct:.1f}% ({downloaded} ok, {failed} failed)")

        conn.commit()
        print(f"  zoom {z} complete: {len(tasks)} tiles")

    # Store bbox in metadata
    conn.execute("INSERT INTO metadata VALUES ('bounds', ?)", (f"{west},{south},{east},{north}",))
    conn.execute("INSERT INTO metadata VALUES ('minzoom', ?)", (str(min_zoom),))
    conn.execute("INSERT INTO metadata VALUES ('maxzoom', ?)", (str(max_zoom),))
    conn.commit()
    conn.close()

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"Done: {downloaded} tiles, {failed} failed, {size_mb:.1f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download terrain tiles to MBTiles")
    parser.add_argument("--bbox", required=True, help="south,west,north,east")
    parser.add_argument("--output", required=True, help="Output MBTiles path")
    parser.add_argument("--min-zoom", type=int, default=0)
    parser.add_argument("--max-zoom", type=int, default=14)
    args = parser.parse_args()

    parts = [float(x.strip()) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("Error: bbox must be 'south,west,north,east'")
        sys.exit(1)

    download_terrain(tuple(parts), args.output, args.min_zoom, args.max_zoom)

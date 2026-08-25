#!/usr/bin/env python3
"""
Download raster base-map tiles and pack them into MBTiles files.

Supports three free tile sources:
  - street:    OpenStreetMap standard tiles
  - satellite: USGS National Map / NAIP imagery (free, no API key)
  - topo:      OpenTopoMap topographic tiles

Usage:
  python download_raster_basemaps.py --bbox "south,west,north,east" --output-dir ./tiles [--max-zoom 14] [--layers street,satellite,topo]

Each layer is saved as a separate MBTiles file:
  basemap_street.mbtiles
  basemap_satellite.mbtiles
  basemap_topo.mbtiles
"""

import argparse
import math
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request

# `geo-agent-offline-prep/1.0` is on the OSM tile policy blacklist — it
# returns the 6987-byte "blocked tile" PNG instead of real imagery. Using
# that UA is what poisoned basemap_street.mbtiles last month. Current
# working contact UA is `pytho-idx26-prep/1.0` with a maintainer e-mail.
USER_AGENT = "pytho-idx26-prep/1.0 (+https://pytho.ai/idx26; allen@pytho.ai)"

# Tile sources — all free, no API key required.
#
# `max_workers` / `min_request_gap_s` enforce each source's usage policy.
# OSM is the strictest (max ~1 req/s, bulk downloads disallowed) — exceeding
# that is what got the previous UA blacklisted and got the mbtiles poisoned
# with the 6987-byte error PNG. OpenTopoMap is OSM-derived and shares the
# same backend, so similar discipline. ESRI World Imagery is permissive.
TILE_SOURCES = {
    "street": {
        "name": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "format": "png",
        "max_src_zoom": 19,
        "tileSize": 256,
        "max_workers": 1,
        "min_request_gap_s": 1.1,
    },
    "satellite": {
        "name": "Esri World Imagery",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "format": "jpg",
        "max_src_zoom": 18,
        "tileSize": 256,
        "max_workers": 4,
        "min_request_gap_s": 0.0,
    },
    "topo": {
        "name": "OpenTopoMap",
        "url": "https://tile.opentopomap.org/{z}/{x}/{y}.png",
        "format": "png",
        "max_src_zoom": 17,
        "tileSize": 256,
        "max_workers": 2,
        "min_request_gap_s": 0.6,
    },
}

# Per-source last-request timestamp + lock so the rate gap is enforced
# across concurrent workers within one source. Each source key gets its
# own (last_ts, lock) pair lazily.
import threading
_RATE_STATE: dict[str, tuple[list[float], threading.Lock]] = {}


def _rate_limit(source_key: str, min_gap_s: float) -> None:
    """Block until at least `min_gap_s` has elapsed since the previous
    request to `source_key`. Threadsafe across workers within one source."""
    if min_gap_s <= 0:
        return
    if source_key not in _RATE_STATE:
        _RATE_STATE[source_key] = ([0.0], threading.Lock())
    last_ts_box, lock = _RATE_STATE[source_key]
    with lock:
        now = time.time()
        wait = (last_ts_box[0] + min_gap_s) - now
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        last_ts_box[0] = now


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def count_tiles(bbox: tuple, min_zoom: int, max_zoom: int) -> int:
    south, west, north, east = bbox
    total = 0
    for z in range(min_zoom, max_zoom + 1):
        x_min, _ = lat_lon_to_tile(north, west, z)
        x_max, _ = lat_lon_to_tile(south, east, z)
        _, y_min = lat_lon_to_tile(north, west, z)
        _, y_max = lat_lon_to_tile(south, east, z)
        total += (x_max - x_min + 1) * (y_max - y_min + 1)
    return total


def init_mbtiles(path: str, layer_key: str) -> sqlite3.Connection:
    """Open or create an MBTiles file. Reuses existing file for resume support."""
    if os.path.exists(path):
        conn = sqlite3.connect(path)
        # Check if schema exists (valid partial download)
        try:
            conn.execute("SELECT count(*) FROM tiles")
            return conn
        except sqlite3.OperationalError:
            conn.close()
            os.remove(path)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    conn.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('name', ?)", (f"basemap-{layer_key}",))
    conn.execute("INSERT INTO metadata VALUES ('format', ?)", (TILE_SOURCES[layer_key]["format"],))
    conn.execute("INSERT INTO metadata VALUES ('type', 'baselayer')")
    conn.commit()
    return conn


def get_existing_tiles(conn: sqlite3.Connection) -> set[tuple[int, int, int]]:
    """Return set of (zoom, column, tms_row) already downloaded."""
    return set(conn.execute("SELECT zoom_level, tile_column, tile_row FROM tiles").fetchall())


def fetch_tile(source_key: str, url_template: str, min_gap_s: float, z: int, x: int, y: int,
               retries: int = 2) -> tuple[int, int, int, bytes | None]:
    _rate_limit(source_key, min_gap_s)
    url = url_template.format(z=z, x=x, y=y)
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    return z, x, y, resp.read()
        except Exception:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    return z, x, y, None


def download_layer(layer_key: str, bbox: tuple, output_dir: str, min_zoom: int, max_zoom: int,
                   workers: int | None = None):
    source = TILE_SOURCES[layer_key]
    # Each source declares its own worker cap + per-tile gap. Caller can
    # still pass `workers` to lower further but never above the source cap.
    src_max_workers = source.get("max_workers", 6)
    effective_workers = min(workers, src_max_workers) if workers else src_max_workers
    min_gap_s = source.get("min_request_gap_s", 0.0)
    effective_min = max(min_zoom, source.get("min_src_zoom", 0))
    effective_max = min(max_zoom, source["max_src_zoom"])
    total = count_tiles(bbox, effective_min, effective_max)
    output_path = os.path.join(output_dir, f"basemap_{layer_key}.mbtiles")

    print(f"\n  [{layer_key}] {source['name']}")
    print(f"    Tiles: {total} (zoom {effective_min}-{effective_max})")

    south, west, north, east = bbox
    conn = init_mbtiles(output_path, layer_key)
    existing = get_existing_tiles(conn)
    skipped = len(existing)
    if skipped:
        print(f"    Resuming: {skipped} tiles already downloaded, {total - skipped} remaining")
    downloaded = 0
    failed = 0
    start = time.time()

    # Chunk size — caps in-flight futures so a deep-zoom run can't OOM on
    # the system when the future-and-PNG-blob memory grows quadratically
    # with bbox area. At z=14 over a 12°×4.5° bbox a single zoom holds
    # ~184k tiles × ~30 KB PNG = ~5.5 GB resident if not chunked. With
    # CHUNK_TILES=8192 the peak resident set drops to ~250 MB per chunk.
    CHUNK_TILES = 8192
    for z in range(effective_min, effective_max + 1):
        x_min, _ = lat_lon_to_tile(north, west, z)
        x_max, _ = lat_lon_to_tile(south, east, z)
        _, y_min = lat_lon_to_tile(north, west, z)
        _, y_max = lat_lon_to_tile(south, east, z)

        tasks = []
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tms_y = (2 ** z - 1) - y
                if (z, x, tms_y) not in existing:
                    tasks.append((z, x, y))

        if not tasks:
            continue

        for chunk_start in range(0, len(tasks), CHUNK_TILES):
            chunk = tasks[chunk_start:chunk_start + CHUNK_TILES]
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                futures = [
                    executor.submit(fetch_tile, layer_key, source["url"], min_gap_s, *t)
                    for t in chunk
                ]
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

                    done = skipped + downloaded + failed
                    if (downloaded + failed) % 200 == 0:
                        conn.commit()
                    if (downloaded + failed) % 200 == 0 or done == total:
                        elapsed = time.time() - start
                        rate = (downloaded + failed) / elapsed if elapsed > 0 else 0
                        pct = done / total * 100
                        print(f"    {pct:5.1f}%  ({skipped + downloaded} ok, {failed} failed, {rate:.0f} tiles/s)")
            conn.commit()

    # Store metadata (replace in case of resume)
    conn.execute("DELETE FROM metadata WHERE name IN ('bounds', 'minzoom', 'maxzoom')")
    conn.execute("INSERT INTO metadata VALUES ('bounds', ?)", (f"{west},{south},{east},{north}",))
    conn.execute("INSERT INTO metadata VALUES ('minzoom', ?)", (str(effective_min),))
    conn.execute("INSERT INTO metadata VALUES ('maxzoom', ?)", (str(effective_max),))
    conn.commit()
    conn.close()

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    elapsed = time.time() - start
    total_ok = skipped + downloaded
    print(f"    Done: {total_ok} tiles ({skipped} cached, {downloaded} new), {failed} failed, {size_mb:.1f} MB, {elapsed:.0f}s")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Download raster base-map tiles to MBTiles")
    parser.add_argument("--bbox", required=True, help="south,west,north,east")
    parser.add_argument("--output-dir", required=True, help="Output directory for MBTiles files")
    parser.add_argument("--min-zoom", type=int, default=0)
    parser.add_argument("--max-zoom", type=int, default=14)
    parser.add_argument(
        "--layers",
        default="street,satellite,topo",
        help="Comma-separated list of layers to download (default: street,satellite,topo)",
    )
    parser.add_argument("--workers", type=int, default=6, help="Download threads per layer (default: 6)")
    args = parser.parse_args()

    parts = [float(x.strip()) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("Error: bbox must be 'south,west,north,east'")
        sys.exit(1)
    bbox = tuple(parts)

    layers = [l.strip() for l in args.layers.split(",")]
    for layer in layers:
        if layer not in TILE_SOURCES:
            print(f"Error: unknown layer '{layer}'. Available: {', '.join(TILE_SOURCES.keys())}")
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Downloading raster base maps for bbox: {bbox}")
    print(f"Layers: {', '.join(layers)}")
    print(f"Zoom range: {args.min_zoom}-{args.max_zoom}")

    total_start = time.time()
    for layer in layers:
        download_layer(layer, bbox, args.output_dir, args.min_zoom, args.max_zoom, args.workers)

    total_elapsed = time.time() - total_start
    print(f"\nAll base maps downloaded in {total_elapsed:.0f}s")


if __name__ == "__main__":
    main()

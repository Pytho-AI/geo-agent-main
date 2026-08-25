#!/usr/bin/env python3
"""
Download ESA WorldCover GeoTIFF tiles for a bounding box.

Tiles are 3x3 degree Cloud Optimized GeoTIFFs stored on AWS S3.

Usage:
  python download_landcover.py --bbox "south,west,north,east" --output ./landcover/
"""

import argparse
import math
import os
import sys
from urllib.request import urlopen, Request
from urllib.error import HTTPError

BASE_URL = "https://esa-worldcover.s3.amazonaws.com/v200/2021/map"


def format_tile_name(tile_lat: int, tile_lon: int) -> str:
    lat_prefix = "N" if tile_lat >= 0 else "S"
    lon_prefix = "E" if tile_lon >= 0 else "W"
    return f"ESA_WorldCover_10m_2021_v200_{lat_prefix}{abs(tile_lat):02d}{lon_prefix}{abs(tile_lon):03d}_Map.tif"


def download_landcover(bbox: tuple, output_dir: str):
    south, west, north, east = bbox
    os.makedirs(output_dir, exist_ok=True)

    # Calculate which 3x3 degree tiles we need
    tiles = []
    lat_start = int(math.floor(south / 3) * 3)
    lat_end = int(math.ceil(north / 3) * 3)
    lon_start = int(math.floor(west / 3) * 3)
    lon_end = int(math.ceil(east / 3) * 3)

    for tile_lat in range(lat_start, lat_end, 3):
        for tile_lon in range(lon_start, lon_end, 3):
            tiles.append((tile_lat, tile_lon))

    print(f"Need {len(tiles)} land cover tile(s)")

    for tile_lat, tile_lon in tiles:
        tile_name = format_tile_name(tile_lat, tile_lon)
        dest = os.path.join(output_dir, tile_name)

        if os.path.exists(dest):
            print(f"  {tile_name} already exists, skipping")
            continue

        url = f"{BASE_URL}/{tile_name}"
        print(f"  Downloading {tile_name}...")

        try:
            req = Request(url, headers={"User-Agent": "geo-agent-offline-prep/1.0"})
            with urlopen(req, timeout=300) as resp:
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)

            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"    Done ({size_mb:.1f} MB)")

        except HTTPError as e:
            if e.code == 404:
                print(f"    Not found (may be ocean-only tile), skipping")
            else:
                print(f"    Error: {e}")
        except Exception as e:
            print(f"    Error: {e}")
            if os.path.exists(dest):
                os.remove(dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download ESA WorldCover tiles")
    parser.add_argument("--bbox", required=True, help="south,west,north,east")
    parser.add_argument("--output", required=True, help="Output directory")
    args = parser.parse_args()

    parts = [float(x.strip()) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("Error: bbox must be 'south,west,north,east'")
        sys.exit(1)

    download_landcover(tuple(parts), args.output)

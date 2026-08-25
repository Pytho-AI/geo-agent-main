#!/bin/bash
# Generate OpenMapTiles-schema vector tiles using Planetiler.
#
# Downloads a regional OSM PBF extract from Geofabrik (or uses a provided one),
# then generates MBTiles using Planetiler in Docker.
#
# Usage: ./download_vector_tiles.sh --bbox "west,south,east,north" --output <path.mbtiles> [--osm-pbf <path>] [--max-zoom 14]

set -e

BBOX=""
OUTPUT=""
OSM_PBF=""
MAX_ZOOM=14

while [[ $# -gt 0 ]]; do
    case $1 in
        --bbox) BBOX="$2"; shift 2;;
        --output) OUTPUT="$2"; shift 2;;
        --osm-pbf) OSM_PBF="$2"; shift 2;;
        --max-zoom) MAX_ZOOM="$2"; shift 2;;
        *) echo "Unknown option: $1"; exit 1;;
    esac
done

if [ -z "$OUTPUT" ]; then
    echo "Usage: $0 --bbox 'west,south,east,north' --output <path.mbtiles> [--osm-pbf <path>] [--max-zoom 14]"
    exit 1
fi

OUTPUT_DIR="$(dirname "$OUTPUT")"
STAGING_DIR="$(dirname "$OUTPUT_DIR")/staging"
mkdir -p "$OUTPUT_DIR" "$STAGING_DIR"

# If no PBF provided, user needs to download one manually
if [ -z "$OSM_PBF" ]; then
    OSM_PBF="$STAGING_DIR/region.osm.pbf"
    if [ ! -f "$OSM_PBF" ]; then
        echo "No OSM PBF file found at $OSM_PBF"
        echo ""
        echo "Please download a regional extract from Geofabrik:"
        echo "  https://download.geofabrik.de/"
        echo ""
        echo "Example for California:"
        echo "  wget -O $OSM_PBF https://download.geofabrik.de/north-america/us/california-latest.osm.pbf"
        echo ""
        echo "Or provide one with --osm-pbf <path>"
        exit 1
    fi
fi

echo "Generating vector tiles from $OSM_PBF..."
echo "  Bbox: $BBOX"
echo "  Max zoom: $MAX_ZOOM"
echo "  Output: $OUTPUT"

# Use Planetiler to generate OpenMapTiles-schema MBTiles
# Planetiler resolves "data/sources/" relative to CWD, so we:
#   - mount staging dir to /data (for persisting downloaded sources like lake_centerline)
#   - set workdir to / so relative "data/sources/" resolves to "/data/sources/"
docker run --rm \
    -v "$(cd "$(dirname "$OSM_PBF")" && pwd):/input" \
    -v "$(cd "$OUTPUT_DIR" && pwd):/output" \
    -v "$(cd "$STAGING_DIR" && pwd):/data" \
    -w / \
    ghcr.io/onthegomap/planetiler:latest \
    --osm-path="/input/$(basename "$OSM_PBF")" \
    --output="/output/$(basename "$OUTPUT")" \
    --bounds="$BBOX" \
    --maxzoom="$MAX_ZOOM" \
    --download \
    --force

size_mb=$(du -m "$OUTPUT" | cut -f1)
echo "Done: $OUTPUT ($size_mb MB)"

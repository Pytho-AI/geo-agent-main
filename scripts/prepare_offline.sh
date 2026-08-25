#!/bin/bash
# Prepare offline data for geo-agent deployment.
#
# Downloads and packages all data needed for offline map rendering and routing
# for a given geographic bounding box.
#
# Usage:
#   ./scripts/prepare_offline.sh --bbox "west,south,east,north" [--max-zoom 14] [--skip-vectors] [--data-dir <path>]
#
# Example:
#   ./scripts/prepare_offline.sh --bbox "-123.5,36.5,-121.0,38.5" --max-zoom 14
#   ./scripts/prepare_offline.sh --bbox "-123.5,36.5,-121.0,38.5" --data-dir /persistent/geo-data/offline
#
# After preparation, deploy with:
#   OFFLINE_MODE=true docker compose --profile offline up

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BBOX=""
MAX_ZOOM=14
CUSTOM_DATA_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --bbox) BBOX="$2"; shift 2;;
        --max-zoom) MAX_ZOOM="$2"; shift 2;;
        --data-dir) CUSTOM_DATA_DIR="$2"; shift 2;;
        *) echo "Unknown option: $1"; exit 1;;
    esac
done

if [ -z "$BBOX" ]; then
    echo "Usage: $0 --bbox 'west,south,east,north' [--max-zoom 14] [--skip-vectors]"
    echo ""
    echo "Options:"
    echo "  --bbox          Bounding box as 'west,south,east,north' (required)"
    echo "  --max-zoom      Maximum zoom level for tiles (default: 14)"
    echo "  --data-dir      Custom output directory (default: <project>/data/offline)"
    echo ""
    echo "Example:"
    echo "  $0 --bbox '-122.6,37.6,-122.2,37.9' --max-zoom 14"
    exit 1
fi

# Parse bbox into components
WEST=$(echo "$BBOX" | cut -d, -f1 | tr -d ' ')
SOUTH=$(echo "$BBOX" | cut -d, -f2 | tr -d ' ')
EAST=$(echo "$BBOX" | cut -d, -f3 | tr -d ' ')
NORTH=$(echo "$BBOX" | cut -d, -f4 | tr -d ' ')

# For backend scripts, bbox is south,west,north,east
BACKEND_BBOX="$SOUTH,$WEST,$NORTH,$EAST"

DATA_DIR="${CUSTOM_DATA_DIR:-${GEO_DATA_DIR:-$PROJECT_DIR/data}/offline}"
TILES_DIR="$DATA_DIR/tiles"
FONTS_DIR="$DATA_DIR/fonts"
ROUTING_DIR="$DATA_DIR/routing"
LANDCOVER_DIR="$ROUTING_DIR/landcover"
STAGING_DIR="$DATA_DIR/staging"

mkdir -p "$TILES_DIR" "$FONTS_DIR" "$ROUTING_DIR" "$LANDCOVER_DIR" "$STAGING_DIR"

TOTAL_START=$(date +%s)

echo "============================================"
echo "  geo-agent Offline Data Preparation"
echo "============================================"
echo "  Bbox: $WEST,$SOUTH,$EAST,$NORTH"
echo "  Max zoom: $MAX_ZOOM"
echo "  Output: $DATA_DIR"
echo "  Estimated size: ~250-320 MB"
echo "  Estimated time: ~4-6 minutes"
echo "============================================"
echo ""

# --- Step 1/8: Vector Tiles ---
if [ -f "$TILES_DIR/openmaptiles.mbtiles" ]; then
    echo "[1/8] Vector tiles .................. EXISTS ($(du -h "$TILES_DIR/openmaptiles.mbtiles" | cut -f1))"
else
    echo "[1/8] Vector tiles .................. downloading"
    STEP_START=$(date +%s)
    bash "$SCRIPT_DIR/offline/download_vector_tiles.sh" \
        --bbox "$WEST,$SOUTH,$EAST,$NORTH" \
        --output "$TILES_DIR/openmaptiles.mbtiles" \
        --max-zoom "$MAX_ZOOM"
    STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
    echo "      Done (${STEP_ELAPSED}s, $(du -h "$TILES_DIR/openmaptiles.mbtiles" | cut -f1))"
fi
echo ""

# --- Step 2/8: Terrain Tiles ---
if [ -f "$TILES_DIR/terrain.mbtiles" ]; then
    echo "[2/8] Terrain tiles ................. EXISTS ($(du -h "$TILES_DIR/terrain.mbtiles" | cut -f1))"
else
    echo "[2/8] Terrain tiles ................. downloading (~5-8 MB)"
    STEP_START=$(date +%s)
    python3 "$SCRIPT_DIR/offline/download_terrain.py" \
        --bbox "$BACKEND_BBOX" \
        --output "$TILES_DIR/terrain.mbtiles" \
        --max-zoom "$MAX_ZOOM"
    STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
    echo "      Done (${STEP_ELAPSED}s, $(du -h "$TILES_DIR/terrain.mbtiles" | cut -f1))"
fi
echo ""

# --- Step 3/8: Fonts ---
FONT_COUNT=$(find "$FONTS_DIR" -name "*.pbf" 2>/dev/null | wc -l)
if [ "$FONT_COUNT" -gt 200 ]; then
    echo "[3/8] Font glyphs ................... EXISTS ($FONT_COUNT files)"
else
    echo "[3/8] Font glyphs ................... downloading 768 glyph files (~3-6 MB)"
    STEP_START=$(date +%s)
    bash "$SCRIPT_DIR/offline/download_fonts.sh" "$FONTS_DIR"
    STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
    FONT_COUNT=$(find "$FONTS_DIR" -name "*.pbf" 2>/dev/null | wc -l)
    echo "      Done (${STEP_ELAPSED}s, $FONT_COUNT files)"
fi
echo ""

# --- Step 4/8: Roads ---
if [ -f "$ROUTING_DIR/roads.json" ]; then
    echo "[4/8] Road network .................. EXISTS ($(du -h "$ROUTING_DIR/roads.json" | cut -f1))"
else
    echo "[4/8] Road network .................. downloading from Overpass API (~2-8 MB)"
    STEP_START=$(date +%s)
    python3 "$SCRIPT_DIR/offline/download_roads.py" \
        --bbox "$BACKEND_BBOX" \
        --output "$ROUTING_DIR/roads.json"
    STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
    echo "      Done (${STEP_ELAPSED}s, $(du -h "$ROUTING_DIR/roads.json" | cut -f1))"
fi
echo ""

# --- Step 5/8: Land Cover ---
LC_COUNT=$(find "$LANDCOVER_DIR" -name "*.tif" 2>/dev/null | wc -l)
if [ "$LC_COUNT" -gt 0 ]; then
    LC_SIZE=$(du -sh "$LANDCOVER_DIR" 2>/dev/null | cut -f1)
    echo "[5/8] Land cover .................... EXISTS ($LC_COUNT tiles, $LC_SIZE)"
else
    echo "[5/8] Land cover .................... downloading ESA WorldCover (~110-300 MB)"
    STEP_START=$(date +%s)
    python3 "$SCRIPT_DIR/offline/download_landcover.py" \
        --bbox "$BACKEND_BBOX" \
        --output "$LANDCOVER_DIR"
    STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
    LC_COUNT=$(find "$LANDCOVER_DIR" -name "*.tif" 2>/dev/null | wc -l)
    LC_SIZE=$(du -sh "$LANDCOVER_DIR" 2>/dev/null | cut -f1)
    echo "      Done (${STEP_ELAPSED}s, $LC_COUNT tiles, $LC_SIZE)"
fi
echo ""

# --- Step 6/8: Raster Base Maps (supports resume) ---
echo "[6/8] Raster base maps .............. downloading/resuming (street, satellite, topo)"
STEP_START=$(date +%s)
python3 "$SCRIPT_DIR/offline/download_raster_basemaps.py" \
    --bbox "$BACKEND_BBOX" \
    --output-dir "$TILES_DIR" \
    --max-zoom "$MAX_ZOOM" \
    --layers "street,satellite,topo"
STEP_ELAPSED=$(( $(date +%s) - STEP_START ))
BASEMAP_SIZE=$(du -shc "$TILES_DIR"/basemap_*.mbtiles 2>/dev/null | tail -1 | cut -f1)
echo "      Done (${STEP_ELAPSED}s, $BASEMAP_SIZE total)"
echo ""

# --- Step 7/8: Tileserver Config ---
echo "[7/8] Tileserver configuration ....... generating"

# Build data sources list based on which mbtiles files actually exist
DATA_ENTRIES=""
if [ -f "$TILES_DIR/openmaptiles.mbtiles" ]; then
    DATA_ENTRIES="$DATA_ENTRIES\"openmaptiles\": { \"mbtiles\": \"openmaptiles.mbtiles\" },"
fi
if [ -f "$TILES_DIR/terrain.mbtiles" ]; then
    DATA_ENTRIES="$DATA_ENTRIES\"terrain\": { \"mbtiles\": \"terrain.mbtiles\" },"
fi
if [ -f "$TILES_DIR/basemap_street.mbtiles" ]; then
    DATA_ENTRIES="$DATA_ENTRIES\"basemap_street\": { \"mbtiles\": \"basemap_street.mbtiles\" },"
fi
if [ -f "$TILES_DIR/basemap_satellite.mbtiles" ]; then
    DATA_ENTRIES="$DATA_ENTRIES\"basemap_satellite\": { \"mbtiles\": \"basemap_satellite.mbtiles\" },"
fi
if [ -f "$TILES_DIR/basemap_topo.mbtiles" ]; then
    DATA_ENTRIES="$DATA_ENTRIES\"basemap_topo\": { \"mbtiles\": \"basemap_topo.mbtiles\" },"
fi
# Remove trailing comma
DATA_ENTRIES=$(echo "$DATA_ENTRIES" | sed 's/,$//')

cat > "$DATA_DIR/tileserver-config.json" << EOF
{
  "options": {
    "paths": {
      "fonts": "/data/fonts",
      "mbtiles": "/data/tiles"
    },
    "serveAllFonts": true
  },
  "data": {
    $DATA_ENTRIES
  }
}
EOF
echo "      Created tileserver-config.json"
echo ""

# --- Step 8/8: Region Metadata ---
echo "[8/8] Region metadata ............... generating"
cat > "$DATA_DIR/region.json" << EOF
{
  "bbox": {
    "west": $WEST,
    "south": $SOUTH,
    "east": $EAST,
    "north": $NORTH
  },
  "max_zoom": $MAX_ZOOM,
  "prepared_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
echo "      Created region.json"
echo ""

# --- Summary ---
TOTAL_ELAPSED=$(( $(date +%s) - TOTAL_START ))
TOTAL_MIN=$(( TOTAL_ELAPSED / 60 ))
TOTAL_SEC=$(( TOTAL_ELAPSED % 60 ))
TOTAL_SIZE=$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)

echo "============================================"
echo "  Offline data preparation complete!"
echo "============================================"
echo ""
echo "  Total time:     ${TOTAL_MIN}m ${TOTAL_SEC}s"
echo "  Total size:     $TOTAL_SIZE"
echo "  Data directory: $DATA_DIR"
echo ""
if [ -f "$TILES_DIR/openmaptiles.mbtiles" ]; then
    echo "  Vector tiles:   $(du -h "$TILES_DIR/openmaptiles.mbtiles" | cut -f1)"
fi
if [ -f "$TILES_DIR/terrain.mbtiles" ]; then
    echo "  Terrain tiles:  $(du -h "$TILES_DIR/terrain.mbtiles" | cut -f1)"
fi
if [ -f "$ROUTING_DIR/roads.json" ]; then
    echo "  Roads:          $(du -h "$ROUTING_DIR/roads.json" | cut -f1)"
fi
for bm in street satellite topo; do
    if [ -f "$TILES_DIR/basemap_${bm}.mbtiles" ]; then
        echo "  Basemap ($bm): $(du -h "$TILES_DIR/basemap_${bm}.mbtiles" | cut -f1)"
    fi
done
LC_FINAL_SIZE=$(du -sh "$LANDCOVER_DIR" 2>/dev/null | cut -f1)
if [ -n "$LC_FINAL_SIZE" ]; then
    echo "  Land cover:     $LC_FINAL_SIZE"
fi
FONT_FINAL=$(find "$FONTS_DIR" -name "*.pbf" 2>/dev/null | wc -l)
if [ "$FONT_FINAL" -gt 0 ]; then
    echo "  Fonts:          $FONT_FINAL glyph files"
fi
echo ""
echo "  To deploy offline:"
echo "    OFFLINE_MODE=true docker compose --profile offline up"
echo ""

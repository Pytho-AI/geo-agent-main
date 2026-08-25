#!/bin/bash
# Download OpenMapTiles font glyphs (PBF format) for offline use.
#
# Downloads pre-built font PBFs from the openmaptiles/fonts repository.
#
# Usage: ./download_fonts.sh <output_dir>

set -e

OUTPUT_DIR="${1:?Usage: $0 <output_dir>}"

mkdir -p "$OUTPUT_DIR"

FONTS_URL="https://github.com/openmaptiles/fonts/releases/download/v3.0"

# The fonts used in mapStyles.js
FONTS=("Open Sans Bold" "Open Sans Italic" "Open Sans Regular")

# PBF glyph ranges: each font needs 0-255, 256-511, ..., 65280-65535
# Total: 256 ranges per font
RANGES=()
for start in $(seq 0 256 65280); do
    end=$((start + 255))
    RANGES+=("${start}-${end}")
done

for font in "${FONTS[@]}"; do
    font_dir="$OUTPUT_DIR/$font"

    if [ -d "$font_dir" ] && [ "$(ls -1 "$font_dir"/*.pbf 2>/dev/null | wc -l)" -gt 200 ]; then
        echo "  $font already downloaded, skipping"
        continue
    fi

    mkdir -p "$font_dir"
    echo "  Downloading $font glyphs..."

    downloaded=0
    failed=0

    for range in "${RANGES[@]}"; do
        url="https://fonts.openmaptiles.org/${font// /%20}/${range}.pbf"
        dest="$font_dir/${range}.pbf"

        if [ -f "$dest" ]; then
            downloaded=$((downloaded + 1))
            continue
        fi

        if curl -sf -o "$dest" "$url" 2>/dev/null; then
            downloaded=$((downloaded + 1))
        else
            # Some ranges may not exist (empty glyphs), create empty file
            touch "$dest"
            failed=$((failed + 1))
        fi
    done

    echo "    $downloaded downloaded, $failed empty"
done

echo "Fonts complete."

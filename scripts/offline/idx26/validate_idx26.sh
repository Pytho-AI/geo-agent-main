#!/usr/bin/env bash
# Validate the IDX 26 raster overlay tileserver entries.
# Hits each /data/<id>.json endpoint and prints the response shape.
set -uo pipefail

LAYERS=(
  basemap-satellite
  basemap-street
  basemap-topo
  terrain
  maaamet-ortho-rgb
  maaamet-ortho-nrg
  s2-truecolor-winter
  s2-truecolor-spring
  s2-truecolor-summer
  s2-truecolor-fall
  s2-nir-winter
  s2-nir-spring
  s2-nir-summer
  s2-nir-fall
  s2-swir-winter
  s2-swir-spring
  s2-swir-summer
  s2-swir-fall
  s2-ndvi-winter
  s2-ndvi-spring
  s2-ndvi-summer
  s2-ndvi-fall
  s2-ndwi-winter
  s2-ndwi-spring
  s2-ndwi-summer
  s2-ndwi-fall
  s2-ndmi-winter
  s2-ndmi-spring
  s2-ndmi-summer
  s2-ndmi-fall
  dem-hillshade
  dem-slope
  dem-aspect
  dem-terrain-rgb
  dem-contours-20m
  worldcover-2021
)

ok=0
fail=0
for layer in "${LAYERS[@]}"; do
  json=$(curl -sf "http://localhost:9847/data/${layer}.json")
  if [ $? -eq 0 ] && [ -n "$json" ]; then
    fmt=$(echo "$json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"{d.get('format','?'):>3}  z=[{d.get('minzoom','?')},{d.get('maxzoom','?')}]  bounds={d.get('bounds','-')}\")")
    printf '  OK  %-26s %s\n' "$layer" "$fmt"
    ok=$((ok+1))
  else
    printf '  FAIL %-26s\n' "$layer"
    fail=$((fail+1))
  fi
done
echo
echo "summary: ok=$ok fail=$fail"

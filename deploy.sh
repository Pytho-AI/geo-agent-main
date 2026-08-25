#!/usr/bin/env bash
# Production deploy for the geo-agent stack: full rebuild + deep
# verification of every surface a consumer depends on.
#
# Does NOT touch git — pull is the operator's step, then:
#
#   git pull --ff-only origin ibl     # (operator, on the serving host)
#   ./deploy.sh
#
# rebuild.sh covers the targeted day-to-day flows; deploy.sh is the
# whole-stack path with the full verification battery.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> deploying HEAD: $(git log --oneline -1 2>/dev/null || echo '(not a git checkout)')"
./rebuild.sh all

echo "==> deep verification:"
fail=0
check() { # label url [expected]
    local label="$1" url="$2" expect="${3:-200}"
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' "$url" || echo 000)
    if [ "$code" = "$expect" ]; then
        echo "    OK   $label -> $code"
    else
        echo "    FAIL $label -> $code (expected $expect)"
        fail=1
    fi
}

check "health"                 http://localhost:9845/health
check "basemap catalog"        http://localhost:9845/api/v1/basemaps
check "raster tile (default)"  http://localhost:9845/api/v1/tiles/basemap/default/6/33/24.jpg
check "raster tile (terrain)"  http://localhost:9845/api/v1/tiles/basemap/terrain/6/33/24.jpg
check "raster tile (topo)"     http://localhost:9845/api/v1/tiles/basemap/topo/6/33/24.jpg
check "satellite tile"         http://localhost:9845/api/v1/tiles/basemap/satellite/6/33/24.jpg
check "vector tile"            http://localhost:9845/api/v1/tiles/vector/basemap/6/33/24.pbf
check "dem tile (contours)"    http://localhost:9845/api/v1/tiles/dem/6/33/24.webp
check "frontend /geo-app"      http://localhost:9845/geo-app/operations-map
check "headless render target" http://localhost:9845/geo-app/headless
# Nonexistent map -> 404 proves the render/latest route is wired
# (a 404 from a dead route and from this endpoint look identical on a
# GET, so probe an impossible uuid and expect the endpoint's own 404).
check "render/latest route"    http://localhost:9845/api/v1/render/latest/00000000-0000-4000-8000-000000000000.jpg 404
# Same probe pattern for the stored-render-spec route (live/edit
# surfaces read product presets from it).
check "render/spec route"      http://localhost:9845/api/v1/render/spec/00000000-0000-4000-8000-000000000000 404

if [ "$fail" -ne 0 ]; then
    echo "==> DEPLOY VERIFICATION FAILED — see FAIL lines above." >&2
    exit 1
fi
echo "==> deploy verified."

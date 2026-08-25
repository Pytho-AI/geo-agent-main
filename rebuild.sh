#!/usr/bin/env bash
# Sanctioned rebuild for the geo-agent stack — never hand-roll compose
# chains. Does NOT touch git: pull first (operator step), then run this.
#
#   ./rebuild.sh            full stack (build + recreate as needed)
#   ./rebuild.sh api        backend code / requirements / Dockerfile
#   ./rebuild.sh frontend   frontend change (baked into the backend
#                           image by the multistage Dockerfile — same
#                           path as api)
#   ./rebuild.sh tiles      tilecache/tileserver conf, style, sprite, or
#                           resolver changes (force-recreate: a running
#                           container keeps serving the OLD bind-mount
#                           inode after git pull rewrites the file)
#   ./rebuild.sh db         database service only
#
# Every invocation ends with verification — service status, health, and
# a cold tile through the single public surface (:9845).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

target="${1:-all}"

case "$target" in
    api|backend|frontend)
        # One path covers all three: `up -d --build backend` rebuilds the
        # image when backend/Dockerfile / requirements / frontend sources
        # changed (cached and fast otherwise), recreates the container
        # (which rebinds the ./backend/app bind-mount to post-pull
        # inodes), and restarts uvicorn so bind-mounted code loads.
        docker compose up -d --build backend
        ;;
    tiles|tilecache|tileserver)
        docker compose up -d --force-recreate tilecache tileserver
        ;;
    db)
        docker compose up -d db
        ;;
    all)
        docker compose up -d --build --remove-orphans
        ;;
    *)
        echo "usage: ./rebuild.sh [api|frontend|tiles|db|all]" >&2
        exit 2
        ;;
esac

echo "==> services:"
docker compose ps --format '{{.Name}}  {{.Status}}'

# A just-recreated backend takes a few seconds before uvicorn listens —
# wait (bounded) for /health before the hard verification below, so the
# script doesn't flake on its own recreate.
echo "==> waiting for the backend to listen on :9845"
ready=0
for _ in $(seq 1 30); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' \
        http://localhost:9845/health 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        ready=1
        break
    fi
    sleep 2
done
if [ "$ready" -ne 1 ]; then
    echo "==> FAIL: backend did not come up within 60s" >&2
    docker compose logs --tail 20 backend >&2 || true
    exit 1
fi

echo "==> verify public surface (:9845):"
curl -sS -o /dev/null -w '    GET /health -> %{http_code}\n' \
    http://localhost:9845/health
curl -sS -o /dev/null \
    -w '    GET /api/v1/tiles/basemap/default/6/33/24.jpg -> %{http_code} cache=%header{x-cache-status}\n' \
    http://localhost:9845/api/v1/tiles/basemap/default/6/33/24.jpg

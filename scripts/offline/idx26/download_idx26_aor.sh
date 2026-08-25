#!/usr/bin/env bash
# IDX 26 AOR raster pipeline driver — native, no docker.
#
# Why no docker:
#   The previous version ran `docker run --rm` in the foreground from an
#   interactive shell. When the shell got SIGHUP (disconnect / window
#   close), the docker CLI propagated it to the container, the container
#   died mid-write, and `--rm` deleted the container along with `docker
#   logs` history. The log file (a shell-level `>> log 2>&1` redirect)
#   stopped getting writes the instant the docker CLI died, so the failure
#   left zero forensic trail. This rewrite drops docker entirely: the
#   orchestrator runs in a host venv (~/.venvs/idx26 — rasterio bundles
#   GDAL 3.12.1, so no host gdal-bin needed), and the launcher uses
#   `setsid nohup ... &` so the python survives any shell disconnect.
#
# Usage:
#   ./download_idx26_aor.sh                              # background, default sources
#   ./download_idx26_aor.sh --foreground                 # foreground, attached to terminal
#   ./download_idx26_aor.sh --sources=maaamet,sentinel2  # subset only
#   ./download_idx26_aor.sh --zoom-max=18                # raise z18 RGB cap
#   ./download_idx26_aor.sh --status                     # show pid + tail latest log
#   ./download_idx26_aor.sh --promote                    # copy staging mbtiles → tiles dir
#   ./download_idx26_aor.sh --stop                       # SIGTERM the running pipeline
#
#   Resume is automatic: the python orchestrator scans the staging dir for
#   already-built mbtiles, loads any prior manifest, and only re-runs
#   sources whose mbtiles don't already cover the AOR bbox at zoom_max.
#
# Files:
#   $LOG_DIR/idx26-pipeline-<UTC>.log       per-run log
#   $LOG_DIR/idx26-pipeline-latest.log      symlink to latest run
#   $PID_DIR/idx26-pipeline.pid             running pid (cleared on clean exit)
#   $STAGING/manifest.json                  source-of-truth for promote step
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Conda env (not a plain venv) because the pipeline shells out to GDAL CLI
# tools (gdalwarp, gdal_translate, gdal_calc.py, gdaldem, gdal2tiles.py,
# gdalbuildvrt). The pip `gdal` package needs system gdal-config which the
# host doesn't have; conda-forge ships GDAL with full CLI inside the env
# directory, no sudo / system packages touched. The env's bin/ is prepended
# to PATH below so subprocess.run("gdalwarp", ...) resolves to the conda
# binary. Created via:
#   curl -sSL https://micro.mamba.pm/api/micromamba/linux-aarch64/latest \
#     | tar -xjf - bin/micromamba && mv bin/micromamba ~/.local/bin/
#   ~/.local/bin/micromamba create -p ~/.venvs/idx26-gdal -c conda-forge -y \
#     python=3.12 gdal rasterio pystac-client requests
VENV="${VENV:-$HOME/.venvs/idx26-gdal}"
STAGING="${STAGING:-$HOME/geo-agent-data-staging}"
TILES_DIR="${TILES_DIR:-$HOME/pytho-data/geo-agent/offline/tiles}"
# Sibling of TILES_DIR by convention — where build_worldcover publishes
# the raw ESA WorldCover GeoTIFFs (classification codes) for the
# geo-agent backend's rasterio land-cover sampler. The mbtiles in
# TILES_DIR are colorized PNGs and CANNOT be used for code lookup;
# the backend needs the raw tiles. Exported so the pipeline picks it up.
LANDCOVER_DIR="${LANDCOVER_DIR:-$(dirname "$TILES_DIR")/landcover}"
export LANDCOVER_DIR
LOG_DIR="${LOG_DIR:-$HOME/idx26-logs}"
PID_DIR="${PID_DIR:-$HOME/idx26-pids}"
LOG_STEM="${LOG_STEM:-idx26-pipeline}"
PYTHON="$VENV/bin/python3"

ZOOM_MAX=18
SOURCES="dem,worldcover,maaamet,sentinel2,placenames"
MODE="background"

for arg in "$@"; do
  case "$arg" in
    --zoom-max=*)   ZOOM_MAX="${arg#*=}" ;;
    --sources=*)    SOURCES="${arg#*=}" ;;
    --foreground|--fg) MODE="foreground" ;;
    --status)       MODE="status" ;;
    --promote)      MODE="promote" ;;
    --stop)         MODE="stop" ;;
    -h|--help)
      sed -n '2,/^set -euo/p' "$0" | head -n -1
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$STAGING" "$TILES_DIR" "$LOG_DIR" "$PID_DIR"
PID_FILE="$PID_DIR/${LOG_STEM}.pid"
LATEST_LINK="$LOG_DIR/${LOG_STEM}-latest.log"

if [ ! -x "$PYTHON" ]; then
  echo "venv missing at $VENV. Create with:" >&2
  echo "  uv venv $VENV --python 3.12" >&2
  echo "  uv pip install --python $PYTHON requests pystac-client rasterio" >&2
  exit 4
fi

# ---- status ----------------------------------------------------------------
if [ "$MODE" = "status" ]; then
  echo "venv:    $VENV  ($("$PYTHON" --version 2>&1))"
  echo "staging: $STAGING"
  echo "tiles:   $TILES_DIR"
  if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "status:  RUNNING  pid=$PID"
    else
      echo "status:  STALE pid file (pid=$PID not alive); pipeline not running"
    fi
  else
    echo "status:  NOT RUNNING (no pid file)"
  fi
  if [ -L "$LATEST_LINK" ]; then
    echo "log:     $LATEST_LINK -> $(readlink "$LATEST_LINK")"
    echo ""
    echo "--- last 20 log lines ---"
    tail -n 20 "$LATEST_LINK" 2>/dev/null || echo "(empty)"
  fi
  if [ -f "$STAGING/manifest.json" ]; then
    echo ""
    echo "--- manifest entries ---"
    "$PYTHON" -c "import json; [print(f'  {e[\"id\"]:<28} {e[\"file\"]}') for e in json.load(open('$STAGING/manifest.json'))]"
  fi
  exit 0
fi

# ---- stop ------------------------------------------------------------------
if [ "$MODE" = "stop" ]; then
  if [ ! -f "$PID_FILE" ]; then
    echo "no pid file at $PID_FILE; nothing to stop" >&2
    exit 0
  fi
  PID=$(cat "$PID_FILE")
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "pid $PID not alive; clearing stale pid file" >&2
    rm -f "$PID_FILE"
    exit 0
  fi
  echo "sending SIGTERM to pid $PID (signal handler will flush manifest)" >&2
  kill -TERM "$PID"
  # Give it 10s to flush + exit, then SIGKILL if still alive.
  for i in $(seq 1 10); do
    sleep 1
    kill -0 "$PID" 2>/dev/null || { echo "stopped cleanly after ${i}s"; exit 0; }
  done
  echo "still alive after 10s, sending SIGKILL" >&2
  kill -KILL "$PID"
  rm -f "$PID_FILE"
  exit 0
fi

# ---- promote ---------------------------------------------------------------
if [ "$MODE" = "promote" ]; then
  MANIFEST="$STAGING/manifest.json"
  [ -f "$MANIFEST" ] || { echo "no manifest at $MANIFEST" >&2; exit 1; }
  echo "promoting manifest entries from $STAGING to $TILES_DIR"
  "$PYTHON" - <<PY
import json, os, shutil, sys, time
m = json.load(open("$MANIFEST"))
tiles_dir = "$TILES_DIR"
os.makedirs(tiles_dir, exist_ok=True)
for e in m:
    src = e["file"]
    if not os.path.exists(src):
        print(f"  MISSING: {src}", file=sys.stderr)
        continue
    dst = os.path.join(tiles_dir, os.path.basename(src))
    tmp = dst + ".incoming"
    t0 = time.time()
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src) and \
       int(os.path.getmtime(dst)) >= int(os.path.getmtime(src)):
        print(f"  SKIP   {e['id']:<28} (same size + same/newer mtime as staging)")
        continue
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    sz = os.path.getsize(dst) / 1024 / 1024
    print(f"  PROMOTE {e['id']:<28} {os.path.basename(src):<40} {sz:>9.1f} MB  ({time.time()-t0:.1f}s)")
PY
  echo ""
  echo "next: restart tileserver to pick up new mbtiles:"
  echo "  docker restart geo-agent-tileserver-1"
  exit 0
fi

# Prepend the env's bin/ to PATH so subprocess.run("gdalwarp", ...) calls
# in idx26_pipeline.py resolve to the conda-forge binaries. Without this
# the pipeline would crash with FileNotFoundError on the first gdal call
# even though the python venv has rasterio.
export PATH="$VENV/bin:$PATH"

# PROJ_LIB is where libproj looks for proj.db (the EPSG SRS database).
# Conda installs it under share/proj/. Without this, every gdalwarp call
# that references an EPSG code dies with:
#   ERROR 1: PROJ: proj_create_from_database: Open of <somewhere>/share/proj failed
#   ERROR 1: Invalid SRS for -t_srs
# and prints the gdalwarp usage banner instead of running. GDAL_DATA is
# its CSV/PROJ4 fallback dir (rare these days but cheap to set).
export PROJ_LIB="$VENV/share/proj"
export GDAL_DATA="$VENV/share/gdal"

# Parallelize every gdal op that can be multi-threaded. NUM_THREADS
# affects raster I/O, compression (ZSTD especially), and warp re-
# projection. ALL_CPUS picks all available cores at runtime.
# GDAL_CACHEMAX in MB --- bigger cache means fewer block-reload cycles
# during the giant stack-to-8bit translates (default ~5% of RAM). Set
# to 8 GB which is comfortable on a 32+ GB host and pays back in
# avoided block re-reads on the S2 stacks.
export GDAL_NUM_THREADS="ALL_CPUS"
export GDAL_CACHEMAX="8192"

# ---- background / foreground -----------------------------------------------
if [ -f "$PID_FILE" ]; then
  EXISTING=$(cat "$PID_FILE")
  if kill -0 "$EXISTING" 2>/dev/null; then
    echo "ALREADY RUNNING: pid=$EXISTING" >&2
    echo "Log: $LATEST_LINK" >&2
    echo "Use --stop to stop it, or --status to inspect." >&2
    exit 3
  fi
  echo "stale pid file (pid $EXISTING not alive); clearing" >&2
  rm -f "$PID_FILE"
fi

LOG="$LOG_DIR/${LOG_STEM}-$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sfn "$(basename "$LOG")" "$LATEST_LINK"

CMD=(
  "$PYTHON"
  "$SCRIPT_DIR/idx26_pipeline.py"
  --zoom-max="$ZOOM_MAX"
  --sources="$SOURCES"
  --staging="$STAGING"
  --pid-file="$PID_FILE"
)

if [ "$MODE" = "foreground" ]; then
  echo "Running foreground. Log streaming to terminal AND to $LOG." >&2
  echo "Ctrl-C to stop (signal handler will flush manifest)." >&2
  exec "${CMD[@]}" 2>&1 | tee -a "$LOG"
fi

# Background. setsid puts the python in its own session so SIGHUP from the
# launching shell can't propagate. nohup also ignores SIGHUP at the kernel
# level as a belt-and-braces. The log fd is opened by THIS shell via the
# redirect, then inherited by python — python keeps it open across the shell
# exit, so the file keeps growing.
setsid nohup "${CMD[@]}" >> "$LOG" 2>&1 < /dev/null &
NEW_PID=$!
disown $NEW_PID 2>/dev/null || true

# Backup PID write so callers can see the PID immediately without racing
# the python startup. Python will overwrite this with its own PID
# (should be identical) once install_durability runs.
echo "$NEW_PID" > "$PID_FILE"

cat <<EOF
Started:    pid=$NEW_PID
Log:        $LOG
Latest:     $LATEST_LINK
Status:     $0 --status
Stop:       $0 --stop
Promote:    $0 --promote          (run after pipeline completes)

Tail live:  tail -F $LATEST_LINK
EOF

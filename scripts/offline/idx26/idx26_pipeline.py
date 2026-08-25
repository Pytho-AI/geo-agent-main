#!/usr/bin/env python3
"""
IDX 26 AOR raster pipeline.

Pulls four public open-source imagery sources for the Voru-Tartu Estonia AOR,
runs derivation + reprojection + tiling via GDAL, packs each layer into a
single MBTiles file, then prints a JSON manifest of layer-id -> file mapping.

Sources (all via plain HTTPS, no AWS CLI):
  - Sentinel-2 L2A COG (Element 84 STAC) -> 6 compositions x 4 seasons = 24 layers
  - Copernicus DEM GLO-30                -> 5 derived terrain overlays
  - ESA WorldCover v200 (2021)           -> 1 landcover overlay
  - Maa-amet 2024 orthophoto             -> 2 layers (RGB true-color, NRG via WMS)

Run inside geo-tools:idx26 container.
"""
from __future__ import annotations

import argparse
import atexit
import json
import math
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Unified IDX 26 Annex C bbox (was all-Estonia (21.5, 57.5, 28.5, 59.8), prior
# to that Voru-Tartu AOR (25.5, 57.4, 27.7, 58.6) — both regressions).
#
# Source: IDX 26 Annex C polygon in
# scratch/docs/ibl/event_data/IDX 26 Annex A & Annex C.pptx
# polygon corners (lon, lat): (20.83, 60.22) (32.92, 60.22)
#                              (32.92, 55.77) (20.83, 55.77)
#
# Covers Estonia + Latvia + Lithuania + slices of Sweden/Finland/Russia/Belarus
# + the eastern Baltic. ~12° × 4.5° = ~840 × 500 km. Every preload (orthophoto
# / S2 / DEM / WC / OSM) uses THIS bbox — single source of truth.
BBOX_WSEN = (20.83, 55.77, 32.92, 60.22)        # west south east north (lon lat)
BBOX_SWNE = (55.77, 20.83, 60.22, 32.92)        # south west north east (XYZ tiler)

# Sentinel-2 season windows. Each season is a (start, end) ISO date range
# the STAC query restricts items to. The winter / spring picks shift one
# year vs summer / fall because we want low-cloud imagery and the previous
# winter is more recent than the current scenario year's winter.
S2_SEASON_WINDOWS = {
    "winter": ("2025-01-01", "2025-02-28"),
    "spring": ("2025-03-15", "2025-05-15"),
    "summer": ("2024-06-01", "2024-08-15"),
    "fall":   ("2024-09-01", "2024-10-15"),
}
# Discovered at pipeline runtime by `s2_discover_picks` — one entry per
# MGRS tile per season, lowest-cloud item.
S2_PICKS: dict[str, list[dict]] = {}
# Element 84 STAC endpoint for the public sentinel-2-l2a collection.
S2_STAC_URL = "https://earth-search.aws.element84.com/v1"
S2_COLLECTION = "sentinel-2-l2a"
# Max acceptable cloud cover per item — items above this are rejected.
S2_MAX_CLOUD_PCT = 35.0

# Sentinel-2 composition recipes. Each is rendered to one mbtiles (PNG).
# kind=rgb: 3-band stack with contrast stretch.
# kind=index: single-band ratio with colormap.
S2_RECIPES = {
    "truecolor": {"kind": "rgb",   "bands": ["B04", "B03", "B02"], "stretch": (200, 3500)},
    "nir":       {"kind": "rgb",   "bands": ["B08", "B04", "B03"], "stretch": (200, 4500)},
    "swir":      {"kind": "rgb",   "bands": ["B12", "B08", "B04"], "stretch": (200, 4000)},
    "ndvi":      {"kind": "index", "num": "B08", "den_pos": "B08", "den_neg": "B04", "ramp": "ndvi"},
    "ndwi":      {"kind": "index", "num": "B03", "den_pos": "B03", "den_neg": "B08", "ramp": "ndwi"},
    "ndmi":      {"kind": "index", "num": "B08", "den_pos": "B08", "den_neg": "B11", "ramp": "ndmi"},
}

# Web Mercator tile-grid zooms per source. Every layer goes from z=0 so the
# analyst can pan/zoom-out smoothly to global scale without MapLibre having
# to upscale a parent tile. Sources that don't publish below some zoom (e.g.
# Maaamet starts ~z=6) just 404 and the fetcher skips — see _maa_fetch_one
# which returns None on miss.
S2_ZOOM_MIN, S2_ZOOM_MAX = 0, 11           # z=11 (~40 m/px) is plenty for AOR-scale S2 thematic layers; z=13 was a 16x cost for upsampled 10m source
DEM_ZOOM_MIN, DEM_ZOOM_MAX = 0, 13         # DEM is 30m
WC_ZOOM_MIN,  WC_ZOOM_MAX = 0, 13          # WorldCover is 10m
MAAAMET_ZOOM_MIN, MAAAMET_ZOOM_MAX = 0, 18 # Capped at z18 (~60cm/px). z19 (~30cm/px, native source resolution) was tried and quadruples the tile count for marginal analyst benefit at IDX 26 viewing distances. Maaamet publishes Estonia only — lower zooms 404 outside Estonia and inside Estonia only at the served zooms (~6+). The fetcher handles None returns, so leaving min=0 costs only a handful of cheap 404s at startup.

# DEM tile lat/lon origins — auto-derived from the unified BBOX_WSEN so a
# bbox change here flows through. Each Copernicus GLO-30 tile covers 1 deg ×
# 1 deg, named by the SW corner (Cop30_e021_n057.tif etc.).
def _dem_tile_keys_for_bbox(bbox):
    w, s, e, n = bbox
    out = []
    for la in range(int(s), int(n) + 1):
        for lo in range(int(w), int(e) + 1):
            out.append((la, lo))
    return out
DEM_TILE_KEYS = _dem_tile_keys_for_bbox(BBOX_WSEN)

# WorldCover 3-deg tiles — origin = SW corner of a 3-deg-aligned cell. The
# all-Estonia bbox spans (21.5, 57.5, 28.5, 59.8), which intersects
# (57N, 21E), (57N, 24E), (57N, 27E), (60N, 21E), (60N, 24E), (60N, 27E).
def _wc_tile_keys_for_bbox(bbox):
    w, s, e, n = bbox
    out = set()
    la = (int(s) // 3) * 3
    while la <= n:
        lo = (int(w) // 3) * 3
        while lo <= e:
            out.add((la, lo))
            lo += 3
        la += 3
    return sorted(out)
WC_TILE_KEYS = _wc_tile_keys_for_bbox(BBOX_WSEN)

WORK_DIR = Path(os.environ.get("IDX26_WORK_DIR") or
                str(Path.home() / "geo-agent-data-staging" / "_work"))  # ephemeral scratch under staging
STAGING = Path("/staging")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


# ---------------------------------------------------------------------------
# Durability scaffolding: incremental manifest + signal handlers + pid file.
#
# Pre-2026-05-26 wrapper failure mode: the orchestrator built the manifest
# in memory and wrote it once at the END of main(). Any death between
# source completion and end-of-main left successful work stranded in
# staging with no record. The bash promotion step then read the stale
# manifest and silently promoted nothing new.
#
# Fix: every source helper now calls `flush_manifest(...)` immediately
# after appending its entry. SIGHUP/SIGTERM/SIGINT also flush + exit
# with a logged reason. atexit flushes on normal exit. The manifest on
# disk is always a true reflection of what staging actually contains.
# ---------------------------------------------------------------------------

# Process-wide run state pointed at the current staging+manifest so signal
# handlers (which can't take arbitrary args) can persist progress.
_RUN_STATE: dict = {"staging": None, "manifest": None, "pid_file": None}


def flush_manifest(staging: Path | None = None, manifest: list[dict] | None = None) -> None:
    """Atomic manifest write: temp file + rename. Safe to call any time;
    swallows errors (best-effort persistence during signal handling)."""
    s = staging if staging is not None else _RUN_STATE.get("staging")
    m = manifest if manifest is not None else _RUN_STATE.get("manifest")
    if s is None or m is None:
        return
    try:
        target = Path(s) / "manifest.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, indent=2))
        os.replace(tmp, target)
    except Exception as exc:
        try:
            log(f"flush_manifest FAILED: {exc!r}")
        except Exception:
            pass


def _clear_pid_file() -> None:
    pf = _RUN_STATE.get("pid_file")
    if pf:
        try:
            Path(pf).unlink(missing_ok=True)
        except Exception:
            pass


def _on_signal(sig: int, _frame) -> None:
    name = {signal.SIGHUP: "SIGHUP", signal.SIGTERM: "SIGTERM",
            signal.SIGINT: "SIGINT"}.get(sig, str(sig))
    log(f"received {name}, flushing manifest and exiting")
    flush_manifest()
    _clear_pid_file()
    # Re-raise default disposition so the exit code reflects the signal.
    sys.exit(128 + sig)


def _completed_marker(path: Path) -> Path:
    """Sibling `.done` marker file alongside `path`. Written ONLY after the
    step that produces `path` succeeds in full. Absence of the marker is
    proof that any existing `path` is a partial from an interrupted run."""
    return path.with_name(path.name + ".done")


def is_complete(path: Path) -> bool:
    """Step output is complete iff both the output AND its .done marker exist."""
    return path.exists() and _completed_marker(path).exists()


def mark_complete(path: Path) -> None:
    """Atomic-ish: touch the .done marker after the step succeeds."""
    _completed_marker(path).touch()


def ensure_step(out: Path, build_fn, label: str | None = None) -> bool:
    """Mid-step resume helper used by sources that have non-resumable
    sub-operations (gdalwarp WMS fetch, gdal_translate COG crop, etc.).

    Contract:
      * If `out` exists AND `out.done` exists -> step considered complete,
        build_fn is NOT called, returns True.
      * If `out` exists WITHOUT `out.done` -> assume partial from a
        crashed previous run, delete `out`, then run build_fn().
      * If `out` does not exist -> run build_fn().
      * After build_fn() returns without raising, write the `.done` marker.
        If build_fn raises, `out` is left in place (will be cleaned on
        next run) and `.done` is NOT written.

    Returns True if cached, False if just built.
    """
    name = label or out.name
    if is_complete(out):
        log(f"  cache HIT  {name}  (size={out.stat().st_size:,} B)")
        return True
    if out.exists():
        log(f"  cache STALE {name} (no .done marker, deleting partial)")
        out.unlink()
    if _completed_marker(out).exists():
        _completed_marker(out).unlink()
    build_fn()
    mark_complete(out)
    log(f"  cache BUILT {name}  (size={out.stat().st_size:,} B)")
    return False


def install_durability(staging: Path, manifest: list[dict],
                       pid_file: Path | None) -> None:
    """Wire up signal handlers + atexit + pid file. Call once at startup."""
    _RUN_STATE["staging"] = staging
    _RUN_STATE["manifest"] = manifest
    _RUN_STATE["pid_file"] = str(pid_file) if pid_file else None
    if pid_file:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{os.getpid()}\n")
        log(f"wrote pid_file {pid_file} (pid={os.getpid()})")
    atexit.register(flush_manifest)
    atexit.register(_clear_pid_file)
    for s in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _on_signal)
    log("durability scaffolding installed (signal handlers + atexit + pid file)")


def deg2num(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def count_tiles(bbox_swne, zmin: int, zmax: int) -> int:
    s, w, n_, e = bbox_swne
    total = 0
    for z in range(zmin, zmax + 1):
        x0, y0 = deg2num(n_, w, z)
        x1, y1 = deg2num(s, e, z)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


def init_mbtiles(path: Path, layer_id: str, fmt: str, tile_type: str = "overlay",
                 attribution: str = "", bbox: tuple[float, float, float, float] | None = None,
                 minzoom: int = 0, maxzoom: int = 16) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    conn.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    meta = [
        ("name", layer_id),
        ("format", fmt),
        ("type", tile_type),
        ("minzoom", str(minzoom)),
        ("maxzoom", str(maxzoom)),
    ]
    if bbox:
        meta.append(("bounds", ",".join(f"{v:.6f}" for v in bbox)))
        meta.append(("center", f"{(bbox[0]+bbox[2])/2:.6f},{(bbox[1]+bbox[3])/2:.6f},{minzoom}"))
    if attribution:
        meta.append(("attribution", attribution))
    conn.executemany("INSERT INTO metadata VALUES (?,?)", meta)
    conn.commit()
    return conn


def _mbtile_already_covers(mbtiles_path: Path,
                           bbox: tuple[float, float, float, float] | None,
                           minzoom: int, maxzoom: int) -> bool:
    """True iff the mbtile's stored bounds fully cover `bbox` and its zoom
    range spans at least [minzoom, maxzoom]. Used by callers to short-circuit
    the expensive render step entirely when a previous run already produced a
    superset of what we'd build now.
    """
    if not mbtiles_path.exists() or bbox is None:
        return False
    try:
        conn = sqlite3.connect(str(mbtiles_path))
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        conn.close()
    except sqlite3.DatabaseError:
        return False
    bounds_str = meta.get("bounds")
    maxz_str = meta.get("maxzoom")
    minz_str = meta.get("minzoom")
    if not bounds_str or not maxz_str or not minz_str:
        return False
    try:
        w, s, e, n = (float(v) for v in bounds_str.split(","))
        bw, bs, be, bn = bbox
        return (w <= bw and s <= bs and e >= be and n >= bn
                and int(maxz_str) >= maxzoom and int(minz_str) <= minzoom)
    except (ValueError, TypeError):
        return False


def tile_vrt_into_mbtiles(vrt_path: Path, mbtiles_path: Path, layer_id: str, fmt: str,
                          zmin: int, zmax: int, attribution: str,
                          extra_gdal2tiles: list[str] | None = None,
                          bbox: tuple[float, float, float, float] | None = None) -> None:
    """Render a VRT/TIFF into an mbtile with per-tile resume.

    Pipeline: gdal2tiles → walk the produced dir → INSERT each (z, x, y) tile
    into the mbtile, skipping any (z, x, y) already present. This is the
    resume-safe replacement for the old mb-util pack which wiped + reissued the
    full mbtile every run.

    Three modes:
      * `FORCE=1` env var: wipe the mbtile, render fresh, insert everything.
      * Existing mbtile already covers the requested bbox+zoom span (per
        `_mbtile_already_covers`): skip rendering entirely.
      * Otherwise (mbtile missing, narrower bbox, lower zoom, or partial):
        render the full requested span, open or create the mbtile, insert only
        (z, x, y) keys NOT already present. Preserves prior coverage so a
        bbox-grown re-run extends instead of replacing.

    The mb-util dependency is gone — we walk the tile dir and write directly
    into the SQLite to keep the existing rows intact.
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    force = os.environ.get("FORCE") == "1"
    if not force and _mbtile_already_covers(mbtiles_path, bbox, zmin, zmax):
        log(f"  {layer_id}: existing mbtile already covers bbox+zoom, skip render")
        return
    # Use gdal_translate's MBTILES driver to write tiles directly into the
    # output sqlite in one threaded pass. Replaces the older gdal2tiles
    # + walk-and-insert approach which produced individual PNG files first
    # (slow filesystem churn + serial per-file insert). MBTILES driver
    # writes blocks straight into the SQLite, uses NUM_THREADS=ALL_CPUS
    # for the underlying I/O + PNG encode. Observed gdal2tiles on this
    # AOR was ~3 tiles/sec; gdal_translate -of MBTILES on the same
    # VRT cascade should be 10-100x faster.
    tiles_dir = Path(tempfile.mkdtemp(prefix=f"tiles_{layer_id}_", dir=str(WORK_DIR)))
    try:
        # Wipe-then-rebuild only when FORCE=1 explicitly asks for it. For
        # everything else (partial mbtile, smaller bbox, lower zoom) we
        # build fresh then INSERT OR REPLACE during the merge below.
        if force and mbtiles_path.exists():
            mbtiles_path.unlink()
        fresh_mbtiles = tiles_dir / "fresh.mbtiles"
        cmd = [
            "gdal_translate", "-q",
            "-of", "MBTILES",
            "-co", f"MINZOOM={zmin}",
            "-co", f"MAXZOOM={zmax}",
            "-co", "TILE_FORMAT=PNG",
            "-co", "RESAMPLING=BILINEAR",
            "-co", "BLOCKSIZE=256",
            "-co", f"NAME={layer_id}",
            "-co", f"DESCRIPTION={layer_id}",
            "-co", f"ATTRIBUTION={attribution}",
            str(vrt_path), str(fresh_mbtiles),
        ]
        run(cmd)
        # MBTILES driver writes only the BASE zoom; need to addo for overviews.
        run([
            "gdaladdo", "-q",
            "-r", "average",
            str(fresh_mbtiles),
            *[str(2 ** k) for k in range(1, zmax - zmin + 1)],
        ])
        # Walk a synthetic tiles_dir would have produced. With gdal_translate
        # -of MBTILES + gdaladdo we already have a complete mbtiles file.
        # If we're MERGING into an existing mbtiles (resume / extend), copy
        # the fresh entries in. Otherwise replace.
        if mbtiles_path.exists():
            conn_src = sqlite3.connect(str(fresh_mbtiles))
            conn_dst = sqlite3.connect(str(mbtiles_path))
            conn_dst.executemany(
                "INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                conn_src.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"),
            )
            conn_dst.commit()
            conn_src.close()
            conn_dst.close()
            log(f"  {layer_id}: merged fresh mbtiles into existing target")
        else:
            mbtiles_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(fresh_mbtiles), str(mbtiles_path))
            log(f"  {layer_id}: wrote new mbtiles ({mbtiles_path.stat().st_size:,} B)")
        # Skip the old gdal2tiles + dir-walk path. Early-return.
        return
        cmd = []  # dead, kept so the leftover code below doesn't run

        # Wipe-then-rebuild only when FORCE=1 explicitly asks for it.
        if force and mbtiles_path.exists():
            mbtiles_path.unlink()

        if mbtiles_path.exists():
            conn = sqlite3.connect(str(mbtiles_path))
            cur = conn.cursor()
            # The new render may carry a wider bbox / deeper zoom than what
            # the prior run stored — keep the metadata in sync so consumers
            # (and our own _mbtile_already_covers check) see the union. UPSERT
            # via DELETE-then-INSERT because the metadata schema has no UNIQUE
            # constraint on `name`, so neither a plain INSERT nor INSERT OR
            # REPLACE will reliably overwrite. The bare UPDATE used before
            # silently no-op'd on mbtiles whose metadata table was empty
            # (notably the mb-util-built ones from prior pipeline versions),
            # which made every subsequent cover-check miss + re-render the
            # full layer.
            def _upsert_meta(name, value):
                cur.execute("DELETE FROM metadata WHERE name=?", (name,))
                cur.execute("INSERT INTO metadata VALUES (?, ?)", (name, value))
            _upsert_meta("maxzoom", str(zmax))
            _upsert_meta("minzoom", str(zmin))
            if bbox is not None:
                _upsert_meta("bounds", ",".join(f"{v:.6f}" for v in bbox))
                _upsert_meta("center",
                             f"{(bbox[0]+bbox[2])/2:.6f},{(bbox[1]+bbox[3])/2:.6f},{zmin}")
            conn.commit()
            existing = set(cur.execute(
                "SELECT zoom_level, tile_column, tile_row FROM tiles"
            ).fetchall())
        else:
            conn = init_mbtiles(mbtiles_path, layer_id, fmt, tile_type="overlay",
                                attribution=attribution, bbox=bbox,
                                minzoom=zmin, maxzoom=zmax)
            cur = conn.cursor()
            existing = set()

        inserted = 0
        skipped_existing = 0
        for z_dir in sorted(tiles_dir.iterdir()):
            if not z_dir.is_dir():
                continue
            try:
                z = int(z_dir.name)
            except ValueError:
                continue
            for x_dir in sorted(z_dir.iterdir()):
                if not x_dir.is_dir():
                    continue
                try:
                    x = int(x_dir.name)
                except ValueError:
                    continue
                for tile_file in x_dir.iterdir():
                    if tile_file.suffix.lstrip(".") != fmt:
                        continue
                    try:
                        y_xyz = int(tile_file.stem)
                    except ValueError:
                        continue
                    # gdal2tiles --xyz writes y in XYZ; mbtiles stores TMS row.
                    tms_y = (2 ** z) - 1 - y_xyz
                    if (z, x, tms_y) in existing:
                        skipped_existing += 1
                        continue
                    cur.execute(
                        "INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                        (z, x, tms_y, tile_file.read_bytes()),
                    )
                    inserted += 1
            conn.commit()  # flush per-zoom so a kill loses at most one zoom
        conn.close()
        log(f"  {layer_id}: inserted={inserted} skipped-existing={skipped_existing}")
    finally:
        if tiles_dir.exists():
            shutil.rmtree(tiles_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Sentinel-2 pipeline
# ---------------------------------------------------------------------------
def s2_discover_picks(season_window: tuple[str, str], bbox: tuple[float, float, float, float]) -> list[dict]:
    """Query the Earth Search STAC for sentinel-2-l2a items intersecting `bbox`
    within `season_window`, group by MGRS tile, pick the lowest-cloud item
    per tile. Returns a list of picks each carrying {id, base, mgrs_tile,
    cloud_cover, datetime}.

    Items above S2_MAX_CLOUD_PCT cloud cover are rejected outright. If a
    tile has no item below the threshold, it's skipped — the mosaic will
    have a gap at that MGRS square (acceptable; less worse than a 60%
    cloud composite)."""
    from pystac_client import Client  # imported here so the function only
                                       # loads pystac when actually used
    log(f"S2 STAC discovery {season_window[0]}..{season_window[1]} over bbox={bbox}")
    # Element 84's STAC server 500s on large pages (limit=500 reliably
    # fails for any season with >~200 matched items). Direct curl with
    # limit=10 succeeds where limit=500 fails on the SAME query, so the
    # issue is per-page payload size. Use limit=20 + manual pagination
    # via item.collection_id 'next' links. Retry each PAGE up to 3 times
    # with backoff to absorb the occasional transient 500.
    client = Client.open(S2_STAC_URL)
    items: list = []
    last_exc = None
    search = client.search(
        collections=[S2_COLLECTION],
        bbox=list(bbox),
        datetime=f"{season_window[0]}/{season_window[1]}",
        query={"eo:cloud_cover": {"lt": S2_MAX_CLOUD_PCT}},
        limit=20,
    )
    # pystac-client's pages() generator yields ItemCollection objects;
    # each yield is one network call. Wrap in retry. If a page exhausts
    # retries, log + return what we have so far (partial is better than
    # empty for downstream mosaicing).
    page_iter = search.pages()
    page_idx = 0
    while True:
        page = None
        for attempt in range(3):
            try:
                page = next(page_iter)
                break
            except StopIteration:
                page = "STOP"
                break
            except Exception as exc:
                last_exc = exc
                log(f"  S2 STAC page {page_idx} attempt {attempt+1}/3 failed: {exc!r}; "
                    f"retrying in {2**attempt}s")
                time.sleep(2 ** attempt)
        if page == "STOP":
            break
        if page is None:
            log(f"  S2 STAC page {page_idx} exhausted retries: {last_exc!r}; "
                f"returning {len(items)} items collected so far")
            break
        items.extend(page.items)
        page_idx += 1
    log(f"  S2 STAC: {page_idx} pages, {len(items)} items total")

    by_tile: dict[str, dict] = {}
    for item in items:
        # Element 84's current sentinel-2-l2a schema dropped the composite
        # s2:mgrs_tile field and split it across mgrs:utm_zone (int),
        # mgrs:latitude_band (str), and mgrs:grid_square (str). Reconstruct
        # the MGRS tile id as "<utm><band><grid>" (e.g. 36 + V + VH = 36VVH).
        # Fall back to the legacy fields and to parsing the item.id
        # ("S2C_36VVH_20250226_0_L2A" -> "36VVH") if all else fails.
        p = item.properties
        mgrs = (
            p.get("s2:mgrs_tile") or p.get("mgrs:tile")
            or (
                f"{p['mgrs:utm_zone']}{p['mgrs:latitude_band']}{p['mgrs:grid_square']}"
                if all(k in p for k in ("mgrs:utm_zone", "mgrs:latitude_band", "mgrs:grid_square"))
                else None
            )
        )
        if not mgrs:
            # Last-resort: id like "S2C_36VVH_20250226_0_L2A"
            parts = (item.id or "").split("_")
            if len(parts) >= 2 and len(parts[1]) == 5:
                mgrs = parts[1]
        cloud = p.get("eo:cloud_cover")
        if not mgrs or cloud is None:
            continue
        existing = by_tile.get(mgrs)
        if existing is None or cloud < existing["cloud_cover"]:
            # `base` is the asset URL stripped of /B0X.tif suffix — but
            # Element 84's assets each carry their own href. We grab the
            # B04 asset (always present) and lop the filename to get a
            # base. If absent, skip the tile.
            assets = item.assets or {}
            b04 = (
                assets.get("red") or assets.get("B04") or assets.get("blue")
                or next(iter(assets.values()), None)
            )
            if b04 is None or not getattr(b04, "href", None):
                continue
            base = b04.href.rsplit("/", 1)[0]
            by_tile[mgrs] = {
                "id": item.id,
                "base": base,
                "mgrs_tile": mgrs,
                "cloud_cover": cloud,
                "datetime": item.datetime.isoformat() if item.datetime else None,
            }
    picks = sorted(by_tile.values(), key=lambda p: p["mgrs_tile"])
    log(f"  picks: {len(picks)} tiles, "
        f"cloud range {min((p['cloud_cover'] for p in picks), default=0):.1f}-"
        f"{max((p['cloud_cover'] for p in picks), default=0):.1f}%")
    return picks


def s2_download_band_for_pick(pick: dict, band: str, dest: Path,
                                bbox: tuple[float, float, float, float]) -> Path | None:
    """Download a single COG band for one MGRS tile pick, cropping via
    /vsicurl + gdal_translate to the intersection of the tile footprint
    and the pipeline's BBOX_WSEN. Returns dest or None on failure.

    Resume: uses ensure_step's .done-marker pattern. A partial gdal_translate
    leaves a .tif on disk that opens cleanly but has wrong dimensions ---
    the .done marker is the only safe "this is complete" indicator. A crash
    during translate leaves no marker, next run treats it as partial and
    re-downloads.
    """
    if is_complete(dest):
        return dest
    src = f"/vsicurl/{pick['base']}/{band}.tif"
    w, s, e, n = bbox
    def _do_translate():
        run([
            "gdal_translate", "-q",
            "-projwin", str(w), str(n), str(e), str(s),
            "-projwin_srs", "EPSG:4326",
            "-of", "GTiff",
            "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS",
            src, str(dest),
        ])
    try:
        ensure_step(dest, _do_translate, label=f"{pick['mgrs_tile']}-{band}")
    except subprocess.CalledProcessError as exc:
        # Tile may not intersect bbox in source CRS; treat as a clean skip.
        log(f"    skip {pick['mgrs_tile']} band {band}: {exc}")
        if dest.exists():
            dest.unlink()
        if _completed_marker(dest).exists():
            _completed_marker(dest).unlink()
        return None
    return dest if dest.exists() and dest.stat().st_size > 1024 else None


def s2_mosaic_band_across_picks(season: str, band: str, picks: list[dict],
                                  work: Path) -> Path:
    """Download `band` from every pick in `picks` IN PARALLEL, build a
    single VRT mosaic in EPSG:4326, return the VRT path. Subsequent
    stretch/warp steps act on the VRT as if it were one big GeoTIFF.

    Was serial in the original implementation (one gdal_translate at a
    time, ~8 sec each, 54 picks per band, 24 layers, ~3 unique bands per
    layer = ~2.6 hours just for the S3 fetches). Now 64-thread pool
    matching the RGB / NRG fetcher patterns; sentinel-cogs S3 handles
    high concurrency fine.
    """
    paths: list[Path] = []
    t0 = time.time()
    log(f"  s2 mosaic {season}/{band}: downloading {len(picks)} picks (64 parallel)")
    with ThreadPoolExecutor(max_workers=64) as pool:
        future_to_pick = {}
        for pick in picks:
            tile_dest = work / f"{season}_{pick['mgrs_tile']}_{band}.tif"
            future_to_pick[pool.submit(
                s2_download_band_for_pick, pick, band, tile_dest, BBOX_WSEN
            )] = (pick, tile_dest)
        for fut in as_completed(future_to_pick):
            pick, tile_dest = future_to_pick[fut]
            try:
                got = fut.result()
            except Exception as exc:
                log(f"    {pick['mgrs_tile']}/{band}: {exc!r}")
                got = None
            if got is not None:
                paths.append(got)
    log(f"  s2 mosaic {season}/{band}: got {len(paths)}/{len(picks)} picks "
        f"in {time.time()-t0:.1f}s")
    if not paths:
        raise RuntimeError(f"s2 mosaic {season}/{band}: no tile downloads succeeded")
    # Single multi-source gdalwarp consolidates 54 per-pick TIFs (native
    # UTM zones) into ONE materialized EPSG:3857 mosaic TIF. Replaces
    # the prior per-pick-warp-to-VRT + gdalbuildvrt + aligned-warp chain.
    # Cascade depth drops from 6 layers (per-pick warp VRT -> mosaic VRT
    # -> aligned VRT -> stack VRT -> 8bit VRT -> tile) to 3 (mosaic TIF
    # -> stack VRT -> 8bit VRT -> tile). Reading one TIF is sequential
    # and benefits from kernel page cache; reading through a 6-VRT
    # cascade hits per-block reproject math + 54-input dispatch per tile.
    #
    # gdalwarp -multi + NUM_THREADS=ALL_CPUS parallelizes reproject+
    # composite over all 20 host cores. ZSTD_LEVEL=1 compresses ~5x
    # (vs raw) at minimal CPU cost (vs level 3+ which would CPU-bound).
    # ensure_step caches the result so subsequent recipes within the
    # same (band, season) hit cache (e.g. truecolor + ndvi + ndwi all
    # need B04 - first call builds the mosaic, rest skip).
    # -tr is the TARGET tile resolution, not source resolution. We tile
    # at S2_ZOOM_MAX (z=11 default), and z=11 web mercator pixel at the
    # Estonia 58 deg N is ~40 m. So producing the mosaic at 40 m matches
    # the output tile grid 1:1 --- gdal_translate -of MBTILES samples
    # 1 source pixel per output pixel at z=11 (base tiles), and
    # gdaladdo's lower-zoom pyramid downsamples cheaply.
    #
    # Building at the original 10 m source resolution produced a 21 GB
    # raw / 4 GB ZSTD per-band mosaic that took ~70 min per band to
    # materialize, and then per-tile generation was still 16:1 down-
    # sampling per output pixel. -tap aligns the output grid to clean
    # 40 m increments in EPSG:3857 (matches z=11 tile boundaries).
    #
    # Resolution formula for other zoom_max values:
    #   web_mercator_pixel_at_lat = (cos(lat) * 40_075_016) / (256 * 2**z)
    #   z=11 / 58 deg N ~= 40 m
    #   z=12 / 58 deg N ~= 20 m
    #   z=13 / 58 deg N ~= 10 m  (source native, no benefit to lower target)
    # For z<=11 we use 40 m; for z=12 use 20 m; for z>=13 use 10 m.
    #
    # NOTE: this is a HEURISTIC pinning to z<=11 fast path. If S2_ZOOM_MAX
    # ever goes above 11 we should compute target_res dynamically.
    target_res_m = 40 if S2_ZOOM_MAX <= 11 else (20 if S2_ZOOM_MAX == 12 else 10)
    # Explicit -te so every per-band mosaic produces the SAME output
    # dimensions. Without -te, gdalwarp computes the output extent from
    # whichever picks actually succeeded for THIS band --- pick subsets
    # differ slightly per band so extents drift by a row/column and
    # gdal_calc later refuses to combine bands with mismatched dims.
    # The hardcoded extent below is the Annex C AOR (W=20.83, S=55.77,
    # E=32.92, N=60.22 in EPSG:4326) reprojected to EPSG:3857, rounded
    # OUTWARD to a 40m grid so any S2_ZOOM_MAX <= 11 stays grid-aligned.
    AOR_TE_3857 = ("2318840", "7524440", "3664880", "8499960")
    mosaic_tif = work / f"{season}_{band}_mosaic.tif"
    def _do_mosaic():
        run([
            "gdalwarp", "-q",
            "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
            "-t_srs", "EPSG:3857",
            "-te", *AOR_TE_3857,
            "-tr", str(target_res_m), str(target_res_m), "-tap",
            "-r", "average",  # downsampling needs proper resampling not 'near'
            "-srcnodata", "0", "-dstnodata", "0",
            "-of", "GTiff",
            "-co", "TILED=YES",
            "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=1",
            "-co", "NUM_THREADS=ALL_CPUS",
            "-co", "BIGTIFF=IF_SAFER",
            *[str(p) for p in paths],
            str(mosaic_tif),
        ])
    ensure_step(mosaic_tif, _do_mosaic, label=f"s2-{season}-{band}-mosaic")
    return mosaic_tif


def s2_build_rgb_vrt(season: str, recipe: dict, work: Path) -> Path:
    bands = recipe["bands"]
    lo, hi = recipe["stretch"]
    picks = S2_PICKS.get(season) or []
    if not picks:
        raise RuntimeError(f"s2 rgb {season}: no picks discovered")

    # Per-band mosaic across all MGRS tile picks for this season.
    band_paths = []
    for b in bands:
        vrt = s2_mosaic_band_across_picks(season, b, picks, work)
        band_paths.append(vrt)

    name = recipe.get("name", "rgb")
    # band_paths are now materialized per-band mosaic TIFs in EPSG:3857
    # (produced by single multi-source gdalwarp in s2_mosaic_band_across
    # _picks). All bands already share the same CRS + grid (set by -tap
    # at 10 m), so stacking is a trivial gdalbuildvrt -separate over the
    # 3 TIFs --- no per-band realignment, no union-extent computation
    # needed since gdalwarp set each band to the same -te extent
    # implicitly via its own AOR computation.
    stacked = work / f"{season}_{name}_stack.vrt"
    def _do_stack():
        run([
            "gdalbuildvrt", "-q", "-separate",
            "-srcnodata", "0", "-vrtnodata", "0",
            str(stacked),
            *[str(p) for p in band_paths],
        ])
    ensure_step(stacked, _do_stack, label=f"s2-{season}-{name}-stack")
    # Stretch to 8-bit using min/max scaling. gdal_translate STREAMS
    # the VRT block-by-block, so memory is bounded by --config
    # GDAL_CACHEMAX (default ~5% of RAM, plenty headroom).
    # Stretch to 8-bit as a VRT (NOT a TIF). gdal_translate -of VRT writes
    # an XML descriptor with the scale baked in; rasterization happens
    # lazily when gdal2tiles reads it. This avoids materializing the
    # ~5 GB intermediate GTiff that ZSTD was taking 9+ hours per layer
    # to write --- the cumulative work doesn't go away but happens ONCE
    # inside gdal2tiles instead of twice (stretch + warp + tile).
    stretched = work / f"{season}_{name}_8bit.vrt"
    def _do_stretch():
        run([
            "gdal_translate", "-q",
            "-ot", "Byte",
            "-scale_1", str(lo), str(hi), "1", "255",
            "-scale_2", str(lo), str(hi), "1", "255",
            "-scale_3", str(lo), str(hi), "1", "255",
            "-a_nodata", "0",
            "-of", "VRT",
            str(stacked), str(stretched),
        ])
    ensure_step(stretched, _do_stretch, label=f"s2-{season}-{name}-8bit")
    # Input is already in EPSG:3857 (per-pick warps did the projection).
    # Skip the redundant 3857->3857 warp step. gdal2tiles reads the
    # stretched VRT directly.
    return stretched


def s2_build_index_vrt(season: str, recipe: dict, work: Path) -> Path:
    """Build a colorized single-band index (NDVI/NDWI/NDMI).

    formula = (pos - neg) / (pos + neg)  where pos = num (when den_pos==num)
    """
    name = recipe.get("name", "index")
    num_b = recipe["num"]
    pos_b = recipe["den_pos"]
    neg_b = recipe["den_neg"]
    picks = S2_PICKS.get(season) or []
    if not picks:
        raise RuntimeError(f"s2 index {season}: no picks discovered")
    # Mosaic each band across all MGRS-tile picks.
    p_pos = s2_mosaic_band_across_picks(season, num_b, picks, work)
    p_neg = s2_mosaic_band_across_picks(season, neg_b, picks, work)

    # Source-band-resolution alignment is no longer needed: both p_pos
    # and p_neg are now per-(band,season) mosaic TIFs produced by
    # s2_mosaic_band_across_picks at the SAME target_res_m (40m at
    # S2_ZOOM_MAX=11). They share the same grid in EPSG:3857 by
    # construction, so the legacy B11->B08 upsample step is a no-op
    # that would produce a wrong-resolution intermediate.
    #
    # (Previously: B11 was 20m source vs B08 10m, and the warp_neg step
    # forced B11 to B08's 10m grid at the FULL 10m AOR raster --- which
    # mismatched the new 40m mosaic grid and crashed gdal_calc with
    # "Dimensions ... are different from other files".)

    raw = work / f"{season}_{name}_raw.tif"
    def _do_calc():
        # gdal_calc.py NDVI-style: (A - B) / (A + B) — outputs float32.
        run([
            "gdal_calc.py", "--quiet",
            "-A", str(p_pos),
            "-B", str(p_neg),
            f"--outfile={raw}",
            "--calc=(A.astype(float)-B.astype(float))/(A.astype(float)+B.astype(float)+1e-6)",
            "--type=Float32",
            "--NoDataValue=-9999",
            "--co=BIGTIFF=IF_SAFER",
        ])
    ensure_step(raw, _do_calc, label=f"s2-{season}-{name}-raw")

    # Colorize: write a colormap file then gdaldem color-relief.
    ramps = {
        "ndvi": [
            "-1.0 191 110 65",     # bare earth — brown
            "0.0  219 192 137",
            "0.2  205 222 130",
            "0.4  149 197  98",
            "0.6   83 173  88",
            "0.8   42 130  79",
            "1.0    8  79  56",
            "nv 0 0 0 0",
        ],
        "ndwi": [
            "-1.0 240 200 100",
            "-0.2 220 220 200",
            "0.0  180 200 220",
            "0.3  110 160 220",
            "0.6   50 100 200",
            "1.0   10  40 130",
            "nv 0 0 0 0",
        ],
        "ndmi": [
            "-1.0 180 100  60",
            "-0.2 220 200 160",
            "0.0  200 220 200",
            "0.3  150 200 220",
            "0.6   80 160 200",
            "1.0   20  80 180",
            "nv 0 0 0 0",
        ],
    }
    ramp_path = work / f"{name}.txt"
    ramp_path.write_text("\n".join(ramps[recipe["ramp"]]) + "\n")

    colorized = work / f"{season}_{name}_color.tif"
    def _do_colorize():
        run([
            "gdaldem", "color-relief",
            "-q",
            "-alpha",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(raw), str(ramp_path), str(colorized),
        ])
    ensure_step(colorized, _do_colorize, label=f"s2-{season}-{name}-color")
    # Reproject to EPSG:3857.
    warped = work / f"{season}_{name}_3857.tif"
    def _do_warp():
        run([
            "gdalwarp","-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-q", "-t_srs", "EPSG:3857",
            "-r", "bilinear",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(colorized), str(warped),
        ])
    ensure_step(warped, _do_warp, label=f"s2-{season}-{name}-3857")
    return warped


def build_sentinel2(staging: Path, manifest: list[dict]) -> None:
    s2_root = staging / "s2"
    s2_root.mkdir(exist_ok=True, parents=True)
    # One STAC discovery pass per season — populates S2_PICKS at runtime
    # instead of the hardcoded single-tile picks the old pipeline used.
    # Each season ends up with N picks (one per MGRS tile intersecting
    # BBOX_WSEN, lowest-cloud-per-tile).
    for season, window in S2_SEASON_WINDOWS.items():
        if season in S2_PICKS:
            continue  # already discovered (cached across re-runs)
        try:
            S2_PICKS[season] = s2_discover_picks(window, BBOX_WSEN)
        except Exception as e:
            log(f"  S2 STAC discovery failed for {season}: {e}")
            S2_PICKS[season] = []

    # Phase 1a: collect every UNIQUE (band, season) pair needed across all
    # recipes. The per-band mosaic gdalwarp is the dominant cost (~15 min
    # each at 40 m / 54 picks / 3 UTM zones); we want each band materialized
    # exactly once even though multiple recipes within a season reference
    # the same band (e.g. truecolor + ndvi + ndwi all use B04).
    force = os.environ.get("FORCE") == "1"
    band_jobs: list[tuple[str, str, Path]] = []  # (season, band, work_dir)
    seen_band_pairs: set[tuple[str, str]] = set()
    for season, picks in S2_PICKS.items():
        if not picks:
            continue
        work = WORK_DIR / f"s2_{season}"
        for recipe_name, recipe in S2_RECIPES.items():
            if recipe["kind"] == "rgb":
                bands = recipe["bands"]
            else:
                bands = [recipe["num"], recipe["den_neg"]]
            for b in bands:
                if (season, b) in seen_band_pairs:
                    continue
                seen_band_pairs.add((season, b))
                band_jobs.append((season, b, work))
    log(f"=== Sentinel-2 phase 1a: {len(band_jobs)} unique (band,season) mosaics needed ===")

    # Phase 1b: build all per-band mosaics in PARALLEL. Memory budget on
    # this host: NVIDIA GB10 has UNIFIED CPU+GPU memory (121 GB total).
    # vllm reserves ~60% (~73 GB) on the CUDA side that does NOT show in
    # `free` but eats the same physical pool. Other host services (docker,
    # elastic, tileserver, headless render chromium, etc.) take ~30 GB.
    # That leaves ~18 GB for the preload pipeline. Each gdalwarp peaks
    # at ~9 GB RSS so **2 concurrent mosaic workers** is the safe cap;
    # going higher squeezes the browser's WebGL allocation (observed: at
    # 4 concurrent, user reported WebGL rendering issues).
    t_mosaic = time.time()
    def _build_one_mosaic(job):
        season_, band_, work_ = job
        work_.mkdir(exist_ok=True, parents=True)
        picks_ = S2_PICKS.get(season_) or []
        try:
            s2_mosaic_band_across_picks(season_, band_, picks_, work_)
            return ("ok", season_, band_, None)
        except Exception as exc:
            return ("fail", season_, band_, repr(exc))
    done_mn = fail_mn = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_build_one_mosaic, j) for j in band_jobs]
        for fut in as_completed(futures):
            status, season_, band_, err = fut.result()
            if status == "ok":
                done_mn += 1
                log(f"  mosaic DONE {season_}/{band_}  "
                    f"({done_mn}/{len(band_jobs)}, {time.time()-t_mosaic:.0f}s elapsed)")
            else:
                fail_mn += 1
                log(f"  mosaic FAIL {season_}/{band_}: {err}")
    log(f"=== Sentinel-2 phase 1b: {done_mn}/{len(band_jobs)} mosaics in {time.time()-t_mosaic:.0f}s ===")

    # Phase 1c: build per-layer VRTs (cheap, all bands now cached so
    # s2_build_rgb_vrt and s2_build_index_vrt just stack and stretch).
    jobs: list[tuple[str, str, Path, Path, str, dict]] = []
    for season, picks in S2_PICKS.items():
        if not picks:
            log(f"=== Sentinel-2 [{season}] SKIPPED (no picks) ===")
            continue
        work = WORK_DIR / f"s2_{season}"
        tile_ids = ",".join(p["mgrs_tile"] for p in picks)
        for recipe_name, recipe in S2_RECIPES.items():
            layer_id = f"s2-{recipe_name}-{season}"
            out = s2_root / f"{layer_id}.mbtiles"
            manifest.append({"id": layer_id, "file": str(out), "group": "multispectral",
                             "season": season, "kind": recipe_name})
            if not force and _mbtile_already_covers(out, BBOX_WSEN, S2_ZOOM_MIN, S2_ZOOM_MAX):
                log(f"skip {layer_id} (mbtile already covers bbox+zoom)")
                continue
            r = {**recipe, "name": recipe_name}
            if recipe["kind"] == "rgb":
                vrt = s2_build_rgb_vrt(season, r, work)
            else:
                vrt = s2_build_index_vrt(season, r, work)
            attribution = (
                f"Sentinel-2 L2A | {len(picks)} MGRS-tile mosaic ({tile_ids}) "
                f"| Copernicus / ESA"
            )
            jobs.append((layer_id, season, vrt, out, attribution, recipe))

    if not jobs:
        log("=== Sentinel-2 all layers already cached or skipped ===")
        return

    # Phase 2: run the expensive tile_vrt_into_mbtiles in PARALLEL across
    # layers. Each layer's gdal_translate -of MBTILES uses ~2-3 cores
    # (GDAL_NUM_THREADS=ALL_CPUS but bounded by VRT-cascade I/O); host
    # has 20 cores total; 6 parallel layers = ~12-18 cores saturated.
    # Per-layer memory is ~5 GB RSS -> 30 GB for 6 parallel, fits well
    # under the host's 121 GB total (already 100 GB used by other
    # services so we have headroom for ~6 concurrent without swapping).
    log(f"=== Sentinel-2: tiling {len(jobs)} layers IN PARALLEL (6 concurrent) ===")
    t0 = time.time()
    done_n = fail_n = 0
    def _tile_one(job):
        layer_id, season, vrt, out, attribution, recipe = job
        try:
            tile_vrt_into_mbtiles(
                vrt, out, layer_id, "png", S2_ZOOM_MIN, S2_ZOOM_MAX, attribution,
                bbox=BBOX_WSEN,
            )
            return ("ok", layer_id, None)
        except Exception as exc:
            return ("fail", layer_id, repr(exc))
    # 4 parallel tile workers (was 8) --- same GB10 unified memory cap
    # as phase 1b. Each gdal_translate -of MBTILES peaks at ~5 GB RSS
    # so 4 = ~20 GB, fits inside ~18-20 GB headroom alongside vllm.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_tile_one, j) for j in jobs]
        for fut in as_completed(futures):
            status, lid, err = fut.result()
            if status == "ok":
                done_n += 1
                log(f"  tile DONE  {lid}  ({done_n}/{len(jobs)}, {time.time()-t0:.0f}s elapsed)")
            else:
                fail_n += 1
                log(f"  tile FAIL  {lid}: {err}")
            flush_manifest()
    log(f"=== Sentinel-2 tile phase: {done_n}/{len(jobs)} layers in {time.time()-t0:.0f}s, {fail_n} failed ===")


# ---------------------------------------------------------------------------
# DEM pipeline
# ---------------------------------------------------------------------------
def dem_download_tile(lat: int, lon: int, dest: Path) -> Path | None:
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    lat_str = f"N{lat:02d}_00"
    lon_str = f"E{lon:03d}_00"
    name = f"Copernicus_DSM_COG_10_{lat_str}_{lon_str}_DEM"
    url = f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
    log(f"  GET {url}")
    r = requests.get(url, stream=True, timeout=120)
    if r.status_code == 404:
        log(f"  404 (ocean tile?) skip {name}")
        return None
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8 * 1024 * 1024):
            f.write(chunk)
    return dest


def build_dem(staging: Path, manifest: list[dict]) -> None:
    dem_root = staging / "dem"
    dem_root.mkdir(exist_ok=True, parents=True)

    # Outer cover-check: if every dem derivative's mbtile already covers
    # BBOX_WSEN at the full DEM zoom span, skip the whole stage --- no
    # source download, no merge gdalwarp, no reproject gdalwarp, no
    # derivative builds. Avoids ~75 sec of unconditional gdalwarp work
    # on every restart when the outputs are already current. The
    # per-derivative cover-check inside the loop below is still kept as
    # a finer-grained safety net for the case where only some derivatives
    # need rebuilding (e.g. a new derivative was added to the dict).
    derivative_ids = [
        "dem-hillshade", "dem-slope", "dem-aspect",
        "dem-terrain-rgb", "dem-contours-20m",
    ]
    if (os.environ.get("FORCE") != "1" and all(
            _mbtile_already_covers(dem_root / f"{lid}.mbtiles",
                                   BBOX_WSEN, DEM_ZOOM_MIN, DEM_ZOOM_MAX)
            for lid in derivative_ids)):
        log("=== Copernicus DEM GLO-30 [SKIP: all derivatives already cover bbox+zoom] ===")
        for lid in derivative_ids:
            manifest.append({"id": lid, "file": str(dem_root / f"{lid}.mbtiles"),
                             "group": "terrain"})
        return

    work = WORK_DIR / "dem"
    work.mkdir(exist_ok=True, parents=True)

    log("=== Copernicus DEM GLO-30 ===")
    tile_paths: list[Path] = []
    for lat, lon in DEM_TILE_KEYS:
        out = work / f"dem_N{lat:02d}E{lon:03d}.tif"
        got = dem_download_tile(lat, lon, out)
        if got is not None:
            tile_paths.append(got)

    # Merge + crop to AOR (EPSG:4326 native), then reproject for derivatives.
    merged_4326 = work / "dem_merged_4326.tif"
    if merged_4326.exists():
        merged_4326.unlink()
    run([
        "gdalwarp","-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-q", "-te", *[str(v) for v in BBOX_WSEN],  # master preload bbox (wider than the Annex C AO so we stay covered if the AO shifts mid-exercise)
        "-te_srs", "EPSG:4326",
        "-t_srs", "EPSG:4326",
        "-tr", "0.00027778", "0.00027778",  # ~30m
        "-r", "bilinear",
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
        *[str(p) for p in tile_paths], str(merged_4326),
    ])
    # Reproject to Web Mercator once for the visual derivatives.
    merged_3857 = work / "dem_merged_3857.tif"
    if merged_3857.exists():
        merged_3857.unlink()
    run([
        "gdalwarp","-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-q", "-t_srs", "EPSG:3857",
        "-r", "bilinear",
        "-tr", "30", "30",
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
        str(merged_4326), str(merged_3857),
    ])

    derivatives = {
        "dem-hillshade": {
            "build": lambda src, dst: run([
                "gdaldem", "hillshade", "-q",
                "-z", "1.5", "-az", "315", "-alt", "45",
                "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
                str(src), str(dst),
            ]),
            "fmt": "png",
        },
        "dem-slope": {
            "build": lambda src, dst: _build_colorized(src, dst, work, "slope"),
            "fmt": "png",
        },
        "dem-aspect": {
            "build": lambda src, dst: _build_colorized(src, dst, work, "aspect"),
            "fmt": "png",
        },
        "dem-terrain-rgb": {
            "build": lambda src, dst: _build_terrain_rgb(src, dst, work),
            "fmt": "png",
        },
        "dem-contours-20m": {
            "build": lambda src, dst: _build_contours(src, dst, work),
            "fmt": "png",
        },
    }

    attribution = "Copernicus DEM GLO-30 | ESA / DLR"
    force = os.environ.get("FORCE") == "1"
    for layer_id, spec in derivatives.items():
        out = dem_root / f"{layer_id}.mbtiles"
        manifest.append({"id": layer_id, "file": str(out), "group": "terrain"})
        if not force and _mbtile_already_covers(out, BBOX_WSEN, DEM_ZOOM_MIN, DEM_ZOOM_MAX):
            log(f"skip {layer_id} (mbtile already covers bbox+zoom)")
            continue
        derivative_tif = work / f"{layer_id}.tif"
        if derivative_tif.exists():
            derivative_tif.unlink()
        spec["build"](merged_3857, derivative_tif)
        tile_vrt_into_mbtiles(derivative_tif, out, layer_id, spec["fmt"],
                              DEM_ZOOM_MIN, DEM_ZOOM_MAX, attribution,
                              bbox=BBOX_WSEN)


def _build_colorized(src: Path, dst: Path, work: Path, kind: str) -> None:
    # Compute raw slope/aspect (float32), then color-relief.
    raw = work / f"{kind}_raw.tif"
    if raw.exists():
        raw.unlink()
    if kind == "slope":
        run([
            "gdaldem", "slope", "-q",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(src), str(raw),
        ])
        ramp = [
            "0    150 200 150",
            "5    200 220 100",
            "15   220 180  60",
            "30   220 100  30",
            "45   180  30  10",
            "90   100   0   0",
            "nv 0 0 0 0",
        ]
    else:  # aspect
        run([
            "gdaldem", "aspect", "-q",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(src), str(raw),
        ])
        # Wrap aspect colormap: N red, E green, S blue, W orange, cyclic.
        ramp = [
            "0    230  60  60",
            "45   230 180  60",
            "90    80 200  80",
            "135  100 200 180",
            "180   60 100 230",
            "225  140  80 200",
            "270  230 140 200",
            "315  230 100  60",
            "360  230  60  60",
            "nv 0 0 0 0",
        ]
    ramp_path = work / f"{kind}_ramp.txt"
    ramp_path.write_text("\n".join(ramp) + "\n")
    run([
        "gdaldem", "color-relief", "-q",
        "-alpha",
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
        str(raw), str(ramp_path), str(dst),
    ])


def _build_terrain_rgb(src: Path, dst: Path, work: Path) -> None:
    """Encode elevation as Mapbox Terrain-RGB:
        height = -10000 + ((R * 256*256 + G * 256 + B) * 0.1)
    """
    # Read elevations as float32 -> compute encoded R, G, B bytes via gdal_calc.
    r = work / "trgb_R.tif"
    g = work / "trgb_G.tif"
    b = work / "trgb_B.tif"
    for p in (r, g, b):
        if p.exists():
            p.unlink()
    # h = elev; v = (h + 10000) / 0.1 = (h + 10000) * 10
    run([
        "gdal_calc.py", "--quiet", "-A", str(src),
        f"--outfile={r}",
        "--calc=numpy.floor(((A+10000.0)*10.0) / 65536.0).astype(numpy.uint8)",
        "--type=Byte",
        "--co=BIGTIFF=IF_SAFER",
    ])
    run([
        "gdal_calc.py", "--quiet", "-A", str(src),
        f"--outfile={g}",
        "--calc=numpy.floor(numpy.mod((A+10000.0)*10.0, 65536.0) / 256.0).astype(numpy.uint8)",
        "--type=Byte",
        "--co=BIGTIFF=IF_SAFER",
    ])
    run([
        "gdal_calc.py", "--quiet", "-A", str(src),
        f"--outfile={b}",
        "--calc=numpy.floor(numpy.mod((A+10000.0)*10.0, 256.0)).astype(numpy.uint8)",
        "--type=Byte",
        "--co=BIGTIFF=IF_SAFER",
    ])
    stacked = work / "trgb_stack.tif"
    if stacked.exists():
        stacked.unlink()
    run([
        "gdal_merge.py", "-q", "-separate", "-o", str(stacked),
        "-co", "BIGTIFF=IF_SAFER",
        str(r), str(g), str(b),
    ])
    shutil.copy(stacked, dst)


def _build_contours(src: Path, dst: Path, work: Path) -> None:
    """Generate 20-m contour lines from DEM, then rasterize to a transparent PNG.

    For visualization at web-mercator zoom 6-13, rasterize contours as 1-px
    lines on a transparent RGBA raster matching the DEM extent.
    """
    shp = work / "contours_20m.shp"
    if shp.exists():
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            (work / f"contours_20m{ext}").unlink(missing_ok=True)
    run([
        "gdal_contour", "-q",
        "-a", "elev",
        "-i", "20",
        str(src), str(shp),
    ])
    # Rasterize to RGBA matching the DEM extent at 30m px.
    info = subprocess.run(["gdalinfo", "-json", str(src)], capture_output=True, text=True, check=True)
    j = json.loads(info.stdout)
    xmin, ymax = j["geoTransform"][0], j["geoTransform"][3]
    px_w = j["geoTransform"][1]
    px_h = j["geoTransform"][5]
    width = j["size"][0]
    height = j["size"][1]
    xmax = xmin + width * px_w
    ymin = ymax + height * px_h

    out_tif = work / "contours_raster.tif"
    if out_tif.exists():
        out_tif.unlink()
    # Initialize a 4-band Byte raster (RGBA) with all-zero (transparent).
    run([
        "gdal_create", "-q",
        "-bands", "4",
        "-burn", "0", "-burn", "0", "-burn", "0", "-burn", "0",
        "-of", "GTiff", "-ot", "Byte",
        "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS",
        "-a_srs", "EPSG:3857",
        "-a_ullr", str(xmin), str(ymax), str(xmax), str(ymin),
        "-outsize", str(width), str(height),
        str(out_tif),
    ])
    # Burn solid brown lines (R=120 G=72 B=20 A=220) into bands 1..4.
    run([
        "gdal_rasterize", "-q",
        "-b", "1", "-b", "2", "-b", "3", "-b", "4",
        "-burn", "120", "-burn", "72", "-burn", "20", "-burn", "220",
        "-l", "contours_20m",
        str(shp), str(out_tif),
    ])
    shutil.copy(out_tif, dst)


# ---------------------------------------------------------------------------
# WorldCover pipeline
# ---------------------------------------------------------------------------
WC_PALETTE = {
    10: (0, 100, 0),       # Tree cover
    20: (255, 187, 34),    # Shrubland
    30: (255, 255, 76),    # Grassland
    40: (240, 150, 255),   # Cropland
    50: (250, 0, 0),       # Built-up
    60: (180, 180, 180),   # Bare / sparse vegetation
    70: (240, 240, 240),   # Snow and ice
    80: (0, 100, 200),     # Permanent water bodies
    90: (0, 150, 160),     # Herbaceous wetland
    95: (0, 207, 117),     # Mangroves
    100: (250, 230, 160),  # Moss and lichen
}


def build_worldcover(staging: Path, manifest: list[dict]) -> None:
    wc_root = staging / "worldcover"
    wc_root.mkdir(exist_ok=True, parents=True)

    # Outer cover-check: if the worldcover-2021 mbtile already covers
    # BBOX_WSEN at the full WC zoom span, skip the whole stage --- no
    # source download, no merge gdalwarp, no color-relief. Avoids
    # ~3 min of unconditional gdal cycles on every restart when the
    # output is already current.
    layer_id = "worldcover-2021"
    out = wc_root / f"{layer_id}.mbtiles"
    if (os.environ.get("FORCE") != "1"
            and _mbtile_already_covers(out, BBOX_WSEN, WC_ZOOM_MIN, WC_ZOOM_MAX)):
        log(f"=== ESA WorldCover v200 (2021) [SKIP: mbtile already covers bbox+zoom] ===")
        manifest.append({"id": layer_id, "file": str(out), "group": "landcover"})
        return

    work = WORK_DIR / "worldcover"
    work.mkdir(exist_ok=True, parents=True)

    log("=== ESA WorldCover v200 (2021) ===")
    tile_paths: list[Path] = []
    for lat, lon in WC_TILE_KEYS:
        name = f"ESA_WorldCover_10m_2021_v200_N{lat:02d}E{lon:03d}_Map.tif"
        url = f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/{name}"
        dest = work / name
        if not (dest.exists() and dest.stat().st_size > 1024):
            log(f"  GET {url}")
            r = requests.get(url, stream=True, timeout=180)
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8 * 1024 * 1024):
                    f.write(chunk)
        tile_paths.append(dest)

    merged = work / "wc_merged.tif"
    if merged.exists():
        merged.unlink()
    run([
        "gdalwarp","-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-q", "-te", *[str(v) for v in BBOX_WSEN],  # master preload bbox
        "-te_srs", "EPSG:4326",
        "-t_srs", "EPSG:3857",
        "-r", "near",
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
        *[str(p) for p in tile_paths], str(merged),
    ])
    # Color-relief from class -> RGB.
    ramp_path = work / "wc_ramp.txt"
    lines = []
    for cls, (r, g, b) in WC_PALETTE.items():
        lines.append(f"{cls} {r} {g} {b}")
    lines.append("nv 0 0 0 0")
    ramp_path.write_text("\n".join(lines) + "\n")
    colorized = work / "wc_color.tif"
    if colorized.exists():
        colorized.unlink()
    run([
        "gdaldem", "color-relief", "-q",
        "-alpha",
        "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
        str(merged), str(ramp_path), str(colorized),
    ])
    layer_id = "worldcover-2021"
    out = wc_root / f"{layer_id}.mbtiles"
    tile_vrt_into_mbtiles(colorized, out, layer_id, "png",
                          WC_ZOOM_MIN, WC_ZOOM_MAX,
                          "ESA WorldCover 2021 v200 | © ESA WorldCover project",
                          bbox=BBOX_WSEN)
    manifest.append({"id": layer_id, "file": str(out), "group": "landcover"})

    # Publish the raw classification GeoTIFFs to LANDCOVER_DIR. The mbtiles
    # above are colorized PNGs for tileserver-gl display — they LOSE the
    # ESA WorldCover classification codes (10=tree, 20=shrub, 30=grass, ...)
    # the geo-agent backend's rasterio-based land_cover sampler needs at
    # routing-cost-surface construction time. The raw tiles ARE the source
    # of truth for `worst_trafficability` per MacroTile in routing/tile_graph.py
    # which in turn drives MCOO avenue-of-approach width / canalization
    # analysis in routing/analysis.py:compute_corridor_widths. Without these
    # tiles in place, every tile defaults to land_cover_code=None →
    # trafficability=1.0 → no canalization → corridor width always returns
    # the perpendicular search cap.
    #
    # LANDCOVER_DIR defaults to a path computed from the spark-dev offline
    # asset stash convention: pytho-data/geo-agent/offline/landcover/.
    # The geo-agent landcover loader at landcover.py:_fetch_single_tile
    # looks for tiles at ${OFFLINE_DATA_DIR}/landcover/<tile_name>.
    landcover_dir = os.environ.get("LANDCOVER_DIR", "").strip()
    if landcover_dir:
        publish = Path(landcover_dir)
        publish.mkdir(parents=True, exist_ok=True)
        published = 0
        for tile_path in tile_paths:
            dst = publish / tile_path.name
            # Skip if already published with matching size + mtime (same
            # idempotency check the promote step uses for mbtiles).
            if (dst.exists()
                    and dst.stat().st_size == tile_path.stat().st_size
                    and int(dst.stat().st_mtime) >= int(tile_path.stat().st_mtime)):
                continue
            shutil.copyfile(tile_path, dst)
            published += 1
        log(f"  Published {published}/{len(tile_paths)} raw WorldCover GeoTIFFs to {publish}")
    else:
        log("  LANDCOVER_DIR unset — raw WorldCover GeoTIFFs left in staging "
            "(geo-agent backend sampler will fail to classify tiles). "
            "Set LANDCOVER_DIR=<path>/offline/landcover in the wrapper.")


# ---------------------------------------------------------------------------
# Maaamet pipeline
# ---------------------------------------------------------------------------
def maaamet_xyz_to_tms_y(z: int, y_xyz: int) -> int:
    return (2 ** z) - 1 - y_xyz


def maaamet_download_rgb(staging: Path, manifest: list[dict], zoom_max: int) -> None:
    """Pull Maaamet 25cm Ortofoto tiles directly into mbtiles (XYZ scheme).

    Source is TMS; we flip the y axis on fetch and store the tile in TMS row
    encoding to satisfy the mbtiles spec.
    """
    layer_id = "maaamet-ortho-rgb"
    out_dir = staging / "maaamet"
    out_dir.mkdir(exist_ok=True, parents=True)
    out = out_dir / f"{layer_id}.mbtiles"
    zoom_max = min(zoom_max, MAAAMET_ZOOM_MAX)  # hard cap at the policy max, ignore higher --zoom-max args
    force = os.environ.get("FORCE") == "1"
    # Resume is the default behaviour: if an mbtiles exists we open it and
    # only fetch the missing keys. This makes an OOM-kill (or any other
    # interruption) survivable — re-running picks up where it stopped.
    # FORCE=1 is the explicit redo-from-scratch escape hatch.
    resume = out.exists() and not force

    log(f"=== Maa-amet Ortofoto RGB (zoom {MAAAMET_ZOOM_MIN}-{zoom_max}) "
        f"{'[RESUME]' if resume else '[FRESH]'} ===")

    if resume:
        # Open existing mbtiles without deleting — pick up where the prior
        # run left off. Update the metadata to reflect the current bbox /
        # maxzoom (a wider bbox or deeper zoom may have been requested).
        conn = sqlite3.connect(str(out))
        cur = conn.cursor()
        cur.execute("UPDATE metadata SET value=? WHERE name='bounds'",
                    (",".join(f"{v:.6f}" for v in BBOX_WSEN),))
        cur.execute("UPDATE metadata SET value=? WHERE name='maxzoom'", (str(zoom_max),))
        conn.commit()
        # Load existing keys so we can skip them. (z, x, tms_y) tuples.
        # For a fully-built z=18 mbtiles this is ~42M rows and takes
        # several minutes; emit a heartbeat every 1M rows so the operator
        # can see the scan is alive (the prior version was silent for the
        # entire scan duration, which read as a hang).
        existing: set[tuple[int, int, int]] = set()
        log(f"  resume scan: loading existing (z,x,row) keys from "
            f"{out.name} (size={out.stat().st_size/1e9:.1f} GB)")
        scan_t0 = time.time()
        try:
            scan_total = cur.execute(
                "SELECT count(*) FROM tiles").fetchone()[0]
            log(f"  resume scan: target {scan_total:,} keys")
        except sqlite3.DatabaseError:
            scan_total = 0
        for n, row in enumerate(
                cur.execute("SELECT zoom_level, tile_column, tile_row FROM tiles"),
                start=1):
            existing.add(row)
            if n % 1_000_000 == 0:
                elapsed = time.time() - scan_t0
                rate = n / elapsed if elapsed > 0 else 0
                pct = f"{n/scan_total*100:.1f}%" if scan_total else "?"
                eta_s = (scan_total - n) / rate if (scan_total and rate) else 0
                log(f"    scan {n:>12,}/{scan_total:>12,}  ({pct}, "
                    f"{rate/1000:.0f} k/s, ETA {eta_s:.0f}s)")
        log(f"  resuming with {len(existing):,} tiles already on disk "
            f"(scan took {time.time()-scan_t0:.1f}s)")
    else:
        conn = init_mbtiles(
            out, layer_id, "jpg", tile_type="baselayer",
            attribution="Andmed: Maa- ja Ruumiamet (© 2025)",
            bbox=BBOX_WSEN, minzoom=MAAAMET_ZOOM_MIN, maxzoom=zoom_max,
        )
        cur = conn.cursor()
        existing = set()

    # Dynamic per-zoom coverage filter: at each target zoom z, skip any
    # candidate tile whose immediate parent at z-1 is NOT in the existing
    # tile set. Using z-1 (instead of a fixed coarse mask zoom like z=14)
    # gives near-perfect filter precision -- each parent has only 4 children
    # at z+1, so a parent with data effectively guarantees its 4 children
    # have data too, while a parent without data guarantees its 4 children
    # don't. The earlier fixed-z=14 mask was 256:1 coarse at z=18 and let
    # through too many border / coastal tiles that 404'd individually.
    #
    # Implementation note: we don't pre-build a separate mask set; the
    # parent-membership check is a direct lookup against the same `existing`
    # set we already loaded. For each (z, x_xyz, y_xyz) candidate, compute
    # the parent at z-1 in XYZ (parent_x = x_xyz >> 1, parent_y_xyz =
    # y_xyz >> 1), then convert to TMS row to match how `existing` stores
    # tile_row, and check membership. The pre-computed `existing_zooms`
    # set tells us which parent zooms have any data at all -- skip filter
    # when the parent zoom is empty (fresh run or unreached zoom).
    existing_zooms: set[int] = {zz for (zz, _, _) in existing} if existing else set()
    if existing:
        log(f"  existing tile zooms present: "
            f"{sorted(existing_zooms)}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "pytho-idx26-prep/1.0 (+https://pytho.ai/idx26; allen@pytho.ai)",
    })

    inserted = 0
    failed = 0
    skipped_existing = 0
    s, w, n_, e = BBOX_SWNE
    # Chunk size for the in-flight futures window. Previous implementation
    # held a single ThreadPoolExecutor + futures dict for the entire zoom
    # level, which on the IDX 26 Annex C bbox at z=17+ retains tens-of-
    # millions of completed-future references + JPEG blobs and OOM-kills
    # the pipeline (observed 2026-05-21: pid 1586986 killed at 30 GB RSS
    # working on the all-Estonia bbox z=16). Chunking caps peak resident
    # memory at ~chunk_tiles × avg_jpeg (~50 KB) ≈ 800 MB for 16k tiles.
    CHUNK_TILES = 16384
    for z in range(MAAAMET_ZOOM_MIN, zoom_max + 1):
        x0, y0 = deg2num(n_, w, z)
        x1, y1 = deg2num(s, e, z)
        all_coords = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        # Filter out tiles already on disk (resume path). For fresh runs
        # `existing` is empty so this is a no-op pass.
        if existing:
            coords = [
                (z_, x_, y_) for (z_, x_, y_) in all_coords
                if (z_, x_, maaamet_xyz_to_tms_y(z_, y_)) not in existing
            ]
            zoom_skipped = len(all_coords) - len(coords)
            skipped_existing += zoom_skipped
        else:
            coords = all_coords
            zoom_skipped = 0
        # Dynamic z-1 parent filter: drop candidates whose immediate
        # parent has no confirmed data in `existing`. Skip the filter
        # when there are no parents to check (z=MAAAMET_ZOOM_MIN or
        # parent zoom has no existing tiles -- a fresh run will fall
        # into this branch for every zoom and iterate the full bbox).
        parent_z = z - 1
        if z > MAAAMET_ZOOM_MIN and parent_z in existing_zooms:
            parent_max_yxyz = (1 << parent_z) - 1
            before = len(coords)
            coords = [
                (z_, x_, y_) for (z_, x_, y_) in coords
                if (parent_z, x_ >> 1, parent_max_yxyz - (y_ >> 1)) in existing
            ]
            coverage_skipped = before - len(coords)
            filter_descr = f"z={parent_z} parent set"
        else:
            coverage_skipped = 0
            filter_descr = "no parent filter"
        log(f"  z={z} tiles={len(coords)} (skipped {zoom_skipped} already on disk, "
            f"{coverage_skipped} outside {filter_descr}) "
            f"chunks={(len(coords) + CHUNK_TILES - 1) // CHUNK_TILES}")
        for chunk_start in range(0, len(coords), CHUNK_TILES):
            chunk = coords[chunk_start:chunk_start + CHUNK_TILES]
            with ThreadPoolExecutor(max_workers=128) as pool:
                future_to_coord = {
                    pool.submit(_maa_fetch_one, session, z, x, y): (z, x, y)
                    for (z, x, y) in chunk
                }
                for fut in as_completed(future_to_coord):
                    z_, x_, y_ = future_to_coord[fut]
                    blob = fut.result()
                    if blob is None:
                        failed += 1
                        continue
                    tms_y = maaamet_xyz_to_tms_y(z_, y_)
                    cur.execute(
                        "INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                        (z_, x_, tms_y, blob),
                    )
                    inserted += 1
            conn.commit()
            # Log every chunk (~16k tiles, ~1-3 sec at full throughput) so
            # the operator gets a steady heartbeat instead of waiting
            # multiple chunks for the next log line.
            done = chunk_start + len(chunk)
            pct = done / len(coords) * 100 if coords else 100
            log(f"    z={z} chunk {done:>10,}/{len(coords):,} ({pct:5.1f}%) "
                f"ok={inserted:,} fail={failed:,}")
    conn.close()
    log(f"  inserted={inserted} failed={failed} pre-existing-skipped={skipped_existing}")
    manifest.append({"id": layer_id, "file": str(out), "group": "basemap"})


def _maa_fetch_one(session: requests.Session, z: int, x: int, y_xyz: int) -> bytes | None:
    y_tms = (2 ** z) - 1 - y_xyz
    url = f"https://tiles.maaamet.ee/tm/tms/1.0.0/foto@GMC/{z}/{x}/{y_tms}.jpg"
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
            return resp.content
    except requests.RequestException:
        # Per-tile network failures are expected (Maaamet rate-limits,
        # transient 5xx). None tells the caller to fall back to a parent-zoom
        # tile. We do not log() per tile — a single run pulls thousands and
        # per-tile noise would bury the operator. The driver loop tracks the
        # aggregate skip count.
        return None
    return None


def maaamet_download_nrg_via_wms(staging: Path, manifest: list[dict], zoom_max: int) -> None:
    """Pull Maaamet CIR-NGR (Metsanduslik ortofoto) via WMS GetMap into a single
    EPSG:3857 GeoTIFF, then tile.

    WMS endpoint: https://kaart.maaamet.ee/wms/alus, layer "cir_ngr".
    """
    layer_id = "maaamet-ortho-nrg"
    out_dir = staging / "maaamet"
    out_dir.mkdir(exist_ok=True, parents=True)
    out = out_dir / f"{layer_id}.mbtiles"
    if out.exists() and os.environ.get("FORCE") != "1":
        log(f"skip {layer_id} (exists)")
        manifest.append({"id": layer_id, "file": str(out), "group": "multispectral",
                         "season": "all", "kind": "nrg-maaamet"})
        return

    log(f"=== Maa-amet CIR-NGR (WMS) ===")
    work = WORK_DIR / "maaamet_nrg"
    work.mkdir(exist_ok=True, parents=True)

    # Pre-fetch tiles via direct parallel HTTP, then mosaic locally.
    #
    # Why not GDAL_WMS XML: the driver processes the output in SEQUENTIAL
    # blocks. Within a block it can fetch in parallel up to MaxConnections,
    # but the block loop itself is serial. Measured throughput on this AOR
    # at MaxConnections=32 vs =128: identical 5 tiles/sec, 7% CPU, 110 KB/s
    # disk --- neither network nor CPU saturated. The block loop is the
    # wall. The maaamet RGB fetcher (which actually scales) uses a 128-
    # thread requests pool against the WMTS endpoint; we mirror that
    # pattern here against the WMS endpoint.
    #
    # Source CRS: EPSG:3301 (Maaamet only publishes cir_ngr in this SRS
    # per GetCapabilities; EPSG:3857 GetMap is rejected with "Invalid
    # SRS"). Bounds 365k..745k E, 6.375M..6.635M N covers the layer's
    # full Estonia footprint.
    NRG_X0, NRG_X1 = 365000, 745000        # meters east (EPSG:3301)
    NRG_Y0, NRG_Y1 = 6375000, 6635000      # meters north (EPSG:3301)
    NRG_RES_M = 5                          # source pixel resolution (m)
    NRG_TILE_PX = 1024                     # tile size in pixels
    NRG_TILE_M = NRG_RES_M * NRG_TILE_PX   # 5120 m per tile edge
    NRG_WORKERS = 128                      # match RGB fetcher concurrency
    NRG_UA = "pytho-idx26-prep/1.0 (+https://pytho.ai/idx26; allen@pytho.ai)"

    cache = work / "wms_tiles"
    cache.mkdir(exist_ok=True, parents=True)

    # Build the source-tile grid. Each tile is named by its (i,j) cell
    # index; bounds are in EPSG:3301 meters.
    tile_jobs: list[tuple[int, int, int, int, int, int]] = []
    i = 0
    x = NRG_X0
    while x < NRG_X1:
        j = 0
        y = NRG_Y0
        while y < NRG_Y1:
            x2 = min(x + NRG_TILE_M, NRG_X1)
            y2 = min(y + NRG_TILE_M, NRG_Y1)
            tile_jobs.append((i, j, x, y, x2, y2))
            j += 1
            y += NRG_TILE_M
        i += 1
        x += NRG_TILE_M
    log(f"  NRG tile grid: {len(tile_jobs)} tiles "
        f"({NRG_TILE_PX}x{NRG_TILE_PX} px each, {NRG_TILE_M}m edge in EPSG:3301)")

    # Per-tile resume via the .done marker pattern (ensure_step's
    # `is_complete`). A crashed/partial GetMap leaves the .png on disk
    # without a marker --- next run treats it as partial and refetches.
    session = requests.Session()
    session.headers.update({"User-Agent": NRG_UA})

    def _fetch_one(job):
        i_, j_, x_, y_, x2_, y2_ = job
        out_tile = cache / f"nrg_{i_:04d}_{j_:04d}.png"
        if is_complete(out_tile):
            return ("skip", i_, j_, 0)
        params = {
            "service": "WMS", "version": "1.1.1", "request": "GetMap",
            "layers": "cir_ngr", "srs": "EPSG:3301",
            "bbox": f"{x_},{y_},{x2_},{y2_}",
            "width": str(NRG_TILE_PX), "height": str(NRG_TILE_PX),
            "format": "image/png",
        }
        try:
            r = session.get(
                "https://kaart.maaamet.ee/wms/alus",
                params=params, timeout=60)
            ct = r.headers.get("Content-Type", "")
            if r.status_code != 200 or not ct.startswith("image/"):
                return ("fail", i_, j_, r.status_code)
            tmp = out_tile.with_suffix(".png.tmp")
            tmp.write_bytes(r.content)
            os.replace(tmp, out_tile)
            mark_complete(out_tile)
            return ("ok", i_, j_, len(r.content))
        except requests.RequestException as exc:
            return ("error", i_, j_, str(exc))

    fetch_t0 = time.time()
    ok_n = fail_n = skip_n = 0
    bytes_n = 0
    REPORT_EVERY = max(1, len(tile_jobs) // 50)  # ~50 progress lines total
    with ThreadPoolExecutor(max_workers=NRG_WORKERS) as pool:
        futures = [pool.submit(_fetch_one, j_) for j_ in tile_jobs]
        for k, fut in enumerate(as_completed(futures), start=1):
            status, _i, _j, payload = fut.result()
            if status == "ok":
                ok_n += 1
                bytes_n += payload
            elif status == "skip":
                skip_n += 1
            else:
                fail_n += 1
            if k % REPORT_EVERY == 0 or k == len(tile_jobs):
                elapsed = time.time() - fetch_t0
                rate = k / elapsed if elapsed else 0
                pct = k / len(tile_jobs) * 100
                eta_s = (len(tile_jobs) - k) / rate if rate else 0
                log(f"    NRG fetch {k:>6,}/{len(tile_jobs):,} ({pct:5.1f}%) "
                    f"ok={ok_n:,} skip={skip_n:,} fail={fail_n:,} "
                    f"{rate:.1f} tiles/s  {bytes_n/1e6:.0f} MB  ETA {eta_s:.0f}s")
    log(f"  NRG fetch complete: ok={ok_n:,} skip={skip_n:,} fail={fail_n:,} "
        f"in {time.time()-fetch_t0:.1f}s, {bytes_n/1e9:.2f} GB cached")

    # Sidecars (.wld + .prj) per cached PNG so gdalbuildvrt knows their
    # EPSG:3301 georeference. Cheap; written every run (idempotent).
    log("  writing world+prj sidecars for cached PNGs")
    pixel = NRG_TILE_M / NRG_TILE_PX  # always 5 m
    prj_wkt = (
        'PROJCS["Estonia_1997_Estonia_National_Grid",'
        'GEOGCS["GCS_Estonia_1997",DATUM["D_Estonia_1997",'
        'SPHEROID["GRS_1980",6378137,298.257222101]],'
        'PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]],'
        'PROJECTION["Lambert_Conformal_Conic"],'
        'PARAMETER["False_Easting",500000],'
        'PARAMETER["False_Northing",6375000],'
        'PARAMETER["Central_Meridian",24],'
        'PARAMETER["Standard_Parallel_1",58],'
        'PARAMETER["Standard_Parallel_2",59.33333333333334],'
        'PARAMETER["Latitude_Of_Origin",57.51755393055556],'
        'UNIT["Meter",1],AUTHORITY["EPSG","3301"]]'
    )
    for (i_, j_, x_, y_, _x2, y2_) in tile_jobs:
        png = cache / f"nrg_{i_:04d}_{j_:04d}.png"
        if not png.exists():
            continue
        # GDAL world file: pixel_x_size, 0, 0, -pixel_y_size, ul_x, ul_y
        (cache / f"nrg_{i_:04d}_{j_:04d}.wld").write_text(
            f"{pixel}\n0\n0\n-{pixel}\n{x_}\n{y2_}\n")
        (cache / f"nrg_{i_:04d}_{j_:04d}.prj").write_text(prj_wkt)

    vrt = work / "nrg_cache.vrt"
    def _build_vrt():
        inputs = sorted(str(p) for p in cache.glob("nrg_*.png"))
        if not inputs:
            raise RuntimeError("NRG: no cached PNG tiles to build VRT from")
        run(["gdalbuildvrt", "-q", str(vrt), *inputs])
    ensure_step(vrt, _build_vrt, label="nrg-vrt")

    # Mosaic to EPSG:3857 from the local VRT --- no network.
    # bbox -te in TARGET SRS (EPSG:3857). Estonia in EPSG:3857 is roughly
    # 2.40M..3.18M E, 7.93M..8.40M N.
    mosaic = work / "cir_ngr_mosaic.tif"
    def _build_mosaic():
        run([
            "gdalwarp",
            "-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-s_srs", "EPSG:3301",
            "-t_srs", "EPSG:3857",
            "-te", "2400000", "7930000", "3180000", "8400000",
            "-tr", "5", "5",
            "-r", "bilinear",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(vrt), str(mosaic),
        ])
    ensure_step(mosaic, _build_mosaic, label="nrg-mosaic")

    # Maaamet returns the WMS tiles as 8-bit palette PNGs (256-color
    # indexed). gdal2tiles refuses palette input with:
    #   "Please convert this file to RGB/RGBA and run gdal2tiles on
    #    the result."
    # so we expand to RGB/RGBA before tiling. -expand rgb (3 bands, no
    # alpha) keeps file size down; alpha isn't meaningful for the CIR
    # raster anyway.
    mosaic_rgb = work / "cir_ngr_mosaic_rgb.tif"
    def _expand_palette():
        run([
            "gdal_translate",
            "-expand", "rgb",
            "-of", "GTiff", "-co", "TILED=YES", "-co", "COMPRESS=ZSTD", "-co", "ZSTD_LEVEL=3", "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
            str(mosaic), str(mosaic_rgb),
        ])
    ensure_step(mosaic_rgb, _expand_palette, label="nrg-mosaic-rgb")

    # tile_vrt_into_mbtiles already has per-tile resume on the output mbtiles.
    # fmt MUST be "png" --- gdal2tiles writes PNG tiles by default and the
    # walker in tile_vrt_into_mbtiles filters by file extension. Passing
    # "jpg" silently skipped EVERY tile (0 inserted, 0 skipped, exit 0,
    # empty mbtiles) because no .jpg files exist in the gdal2tiles output.
    tile_vrt_into_mbtiles(
        mosaic_rgb, out, layer_id, "png",
        MAAAMET_ZOOM_MIN, min(zoom_max, 15),
        "Andmed: Maa- ja Ruumiamet (© 2025) | CIR-NGR ortofoto",
    )
    manifest.append({"id": layer_id, "file": str(out), "group": "multispectral",
                     "season": "all", "kind": "nrg-maaamet"})


# ---------------------------------------------------------------------------
# Maa-amet Place Names (Kohanimeregister) — INSPIRE WFS GN.GeographicalNames
# ---------------------------------------------------------------------------
# Replaces OpenMapTiles' partial `name:en` coverage with the authoritative
# Maa-amet gazetteer for Estonia. ~150k point features all of Estonia.
# Built as a vector MBTiles via `ogr2ogr -f MBTiles` so tileserver-gl serves
# it natively and the MapLibre client adds a single symbol layer keyed off
# `name` / `name_la` (Latin transliteration) / `localType` (settlement type
# for cartographic-scaling).
#
# Endpoint: https://inspire.geoportaal.ee/geoserver/ows
# Feature type: GN:GeographicalNames
# Schema (relevant fields): geometry (Point), name, language, script,
# transliteration, localType (EHAK code), nativeness, nameStatus.
# Pagination: GeoServer caps at 5000 features per GetFeature; iterate with
# startIndex.

PLACENAMES_WFS_BASE = "https://inspire.geoportaal.ee/geoserver/ows"
# Discovered via GetCapabilities probe — namespace prefix `GN_kohanimed`
# (the Estonian KNR/INSPIRE feature store), not the bare `GN`.
PLACENAMES_WFS_TYPENAME = "GN_kohanimed:GN.GeographicalNames"
PLACENAMES_PAGE_SIZE = 5000


def _wfs_get_page(typename: str, start_index: int, count: int,
                    bbox_4326: tuple[float, float, float, float] | None) -> dict:
    """Single GeoJSON page from a GeoServer WFS 2.0.0 GetFeature. Reprojected
    to EPSG:4326 so MapLibre's tileserver-gl serves usable coords (4326 is
    the OGC tile schema). Returns the parsed FeatureCollection dict."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "outputFormat": "application/json",
        "srsName": "urn:ogc:def:crs:EPSG::4326",
        "startIndex": str(start_index),
        "count": str(count),
    }
    if bbox_4326 is not None:
        # WFS 2.0 BBOX axis order with EPSG:4326 is lat,lon,lat,lon when
        # the CRS authority follows the EPSG axis-order spec. INSPIRE
        # GeoServers respect this — pass as min_lat,min_lon,max_lat,max_lon
        # plus CRS URN.
        w, s, e, n = bbox_4326
        params["bbox"] = f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326"
    resp = requests.get(PLACENAMES_WFS_BASE, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


def build_placenames(staging: Path, manifest: list[dict]) -> None:
    """Pull all Estonia place names from INSPIRE GN WFS, write GeoJSON, then
    convert to vector MBTiles for tileserver-gl. Cached by sha of bbox +
    typename so FORCE=0 reruns skip the download."""
    layer_id = "maaamet-placenames"
    out_dir = staging / "placenames"
    out_dir.mkdir(exist_ok=True, parents=True)
    out = out_dir / f"{layer_id}.mbtiles"
    geojson_path = out_dir / f"{layer_id}.geojson"

    if out.exists() and os.environ.get("FORCE") != "1":
        log(f"skip {layer_id} (exists)")
        manifest.append({"id": layer_id, "file": str(out), "group": "labels",
                         "kind": "placenames-maaamet"})
        return

    log("=== Maa-amet Place Names (INSPIRE GN WFS) ===")
    features: list[dict] = []
    start = 0
    while True:
        page = _wfs_get_page(
            PLACENAMES_WFS_TYPENAME, start, PLACENAMES_PAGE_SIZE,
            bbox_4326=BBOX_WSEN,
        )
        page_features = page.get("features") or []
        if not page_features:
            break
        features.extend(page_features)
        log(f"  WFS page start={start} got={len(page_features)} total={len(features)}")
        if len(page_features) < PLACENAMES_PAGE_SIZE:
            break
        start += PLACENAMES_PAGE_SIZE
        if start > 500_000:  # defensive — Estonia has ~150k, never expect more
            log("  WFS pagination exceeded 500k; bailing to avoid runaway")
            break

    # Flatten INSPIRE GeographicalNames properties. Per WFS probe, the
    # GeoServer returns a flat key/value shape (not the nested
    # SpellingOfName objects from the spec). Relevant keys observed:
    #   name_geographicalname_spelling_spellingofname_text — endonym text
    #     (Estonian names are already Latin script, so this IS the
    #     Latin form for IDX 26 purposes)
    #   name_geographicalname_namestatus_xlink_title         — official|other
    #   type_xlink_title    — INSPIRE NamedPlaceTypeValue codelist
    #     (administrativeUnit | populatedPlace | physiographic | hydrography | ...)
    #   name_geographicalname_language                       — usually "est"
    flattened: list[dict] = []
    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        text = (props.get("name_geographicalname_spelling_spellingofname_text") or "").strip()
        if not text:
            continue
        new_props = {
            "name": text,                                    # Latin Estonian form — usable as label as-is
            "name_la": text,                                 # alias for explicit consumers
            "place_type": (props.get("type_xlink_title") or "").strip(),
            "name_status": (props.get("name_geographicalname_namestatus_xlink_title") or "").strip(),
            "language": (props.get("name_geographicalname_language") or "").strip(),
        }
        flattened.append({
            "type": "Feature",
            "geometry": geom,
            "properties": new_props,
        })

    fc = {"type": "FeatureCollection", "features": flattened}
    with open(geojson_path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)
    log(f"  wrote {geojson_path} ({len(flattened)} features)")

    # Vector MBTiles via ogr2ogr. GDAL 3.10+ supports the MBTiles vector
    # output natively — no tippecanoe dependency. MAXZOOM=14 because labels
    # at z>14 cluster too densely without zoom-dependent filtering; the
    # MapLibre symbol layer can `text-allow-overlap` past that.
    if out.exists():
        out.unlink()
    run([
        "ogr2ogr",
        "-f", "MBTiles",
        str(out),
        str(geojson_path),
        "-dsco", "MAXZOOM=14",
        "-dsco", "MINZOOM=4",
        "-dsco", "NAME=Maa-amet Place Names",
        "-dsco", "DESCRIPTION=INSPIRE GN.GeographicalNames, all-Estonia",
        "-dsco", "TYPE=overlay",
        "-nln", "placenames",  # layer name inside the mbtiles
    ])
    log(f"  built {out}")
    manifest.append({"id": layer_id, "file": str(out), "group": "labels",
                     "kind": "placenames-maaamet"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _seed_manifest_from_existing_mbtiles(staging: Path, manifest: list[dict]) -> None:
    """Resume helper: scan staging/ for already-built .mbtiles files and
    seed the manifest so we don't have to re-run sources just to register
    them. Each source helper also re-registers itself if invoked, so this
    is purely a "if you skip a source via --sources=, its existing mbtile
    still ends up in the manifest" convenience.

    The schema-driven group/kind tags are inferred from filename. Unknown
    files get a generic 'unknown' group; downstream promotion still works
    because it only cares about file paths.
    """
    KNOWN: dict[str, dict[str, str]] = {
        "maaamet-ortho-rgb.mbtiles":     {"id": "maaamet-ortho-rgb",     "group": "imagery",  "kind": "ortho-rgb"},
        "maaamet-ortho-nrg.mbtiles":     {"id": "maaamet-ortho-nrg",     "group": "imagery",  "kind": "ortho-nrg"},
        "maaamet-placenames.mbtiles":    {"id": "maaamet-placenames",    "group": "labels",   "kind": "placenames-maaamet"},
        "worldcover-2021.mbtiles":       {"id": "worldcover-2021",       "group": "landcover","kind": "worldcover"},
        "dem-hillshade.mbtiles":         {"id": "dem-hillshade",         "group": "terrain",  "kind": "hillshade"},
        "dem-slope.mbtiles":             {"id": "dem-slope",             "group": "terrain",  "kind": "slope"},
        "dem-aspect.mbtiles":            {"id": "dem-aspect",            "group": "terrain",  "kind": "aspect"},
        "dem-contours-20m.mbtiles":      {"id": "dem-contours-20m",      "group": "terrain",  "kind": "contours"},
        "dem-terrain-rgb.mbtiles":       {"id": "dem-terrain-rgb",       "group": "terrain",  "kind": "terrain-rgb"},
    }
    seen = {e.get("file") for e in manifest}
    for sub in staging.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.glob("*.mbtiles"):
            entry_path = str(f)
            if entry_path in seen:
                continue
            base = f.name
            known = KNOWN.get(base)
            if known:
                manifest.append({**known, "file": entry_path})
            elif base.startswith("s2-"):
                stem = f.stem
                manifest.append({"id": stem, "group": "sentinel2", "kind": stem, "file": entry_path})
            else:
                manifest.append({"id": f.stem, "group": "unknown", "kind": f.stem, "file": entry_path})
            log(f"resume: registered existing mbtile {entry_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zoom-max", type=int, default=18,
                    help="Maximum zoom for Maaamet RGB orthophoto.")
    ap.add_argument("--sources", default="dem,worldcover,maaamet,sentinel2,placenames",
                    help="Comma-list: dem,worldcover,maaamet,sentinel2,placenames")
    ap.add_argument("--staging", default=str(Path.home() / "geo-agent-data-staging"),
                    help="Host staging dir. Default ~/geo-agent-data-staging.")
    ap.add_argument("--pid-file", default=None,
                    help="Write own PID here at startup; clear on clean exit.")
    args = ap.parse_args()

    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)
    # Pin WORK_DIR under the staging arg so all the build_* helpers (which
    # reference module-level WORK_DIR) see a writable scratch dir on the
    # host. Previously hardcoded to /staging/_work for the docker container.
    global WORK_DIR
    WORK_DIR = staging / "_work"
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []

    # Wire up the durability scaffolding BEFORE any work starts so signal
    # handlers can flush even if a source dies in its first second.
    install_durability(
        staging=staging,
        manifest=manifest,
        pid_file=Path(args.pid_file) if args.pid_file else None,
    )

    # Resume: load any existing manifest entries so re-runs don't lose
    # previously-recorded sources we don't intend to re-execute this run.
    existing_manifest_path = staging / "manifest.json"
    if existing_manifest_path.exists():
        try:
            prior = json.loads(existing_manifest_path.read_text())
            if isinstance(prior, list):
                manifest.extend(prior)
                log(f"resume: loaded {len(prior)} entries from existing manifest")
        except Exception as exc:
            log(f"resume: could not parse existing manifest ({exc!r}); starting fresh")

    # Also scan staging for built mbtiles not yet in the manifest.
    _seed_manifest_from_existing_mbtiles(staging, manifest)
    flush_manifest()

    sources = set(args.sources.split(","))
    log(f"starting pipeline staging={staging} sources={sorted(sources)} zoom_max={args.zoom_max}")

    # Each source is wrapped in its own try so one failure doesn't strand
    # later sources. We flush the manifest after every source, success
    # or failure, so the on-disk record always matches staging reality.
    def _run_source(name: str, fn) -> None:
        log(f"=== START {name} ===")
        t0 = time.time()
        try:
            fn()
        except Exception as exc:
            log(f"=== FAILED {name}: {exc!r}")
            log(traceback.format_exc())
        else:
            log(f"=== COMPLETED {name} in {time.time()-t0:.1f}s")
        finally:
            flush_manifest()

    if "dem" in sources:
        _run_source("dem",        lambda: build_dem(staging, manifest))
    if "worldcover" in sources:
        _run_source("worldcover", lambda: build_worldcover(staging, manifest))
    # Maaamet is two sub-sources. Accept both the bundle name ("maaamet"
    # = both) and the individual names ("maaamet-rgb" or "maaamet-nrg")
    # so you can re-run only what's actually pending. The RGB resume walk
    # over the 188 GB mbtiles takes ~15 min even when zero new tiles
    # land, so testing NRG / S2 changes shouldn't have to wait through it.
    if "maaamet" in sources or "maaamet-rgb" in sources:
        _run_source("maaamet-rgb", lambda: maaamet_download_rgb(staging, manifest, args.zoom_max))
    if "maaamet" in sources or "maaamet-nrg" in sources:
        _run_source("maaamet-nrg", lambda: maaamet_download_nrg_via_wms(staging, manifest, args.zoom_max))
    if "sentinel2" in sources:
        _run_source("sentinel2",  lambda: build_sentinel2(staging, manifest))
    if "placenames" in sources:
        _run_source("placenames", lambda: build_placenames(staging, manifest))

    # Final manifest write (also covered by atexit but written here so the
    # "wrote manifest" log line is the last visible thing on a clean run).
    flush_manifest()
    log(f"wrote manifest {existing_manifest_path} ({len(manifest)} layers)")
    log("pipeline COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

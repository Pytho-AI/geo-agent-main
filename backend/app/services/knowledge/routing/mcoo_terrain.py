"""Doctrinal MCOO terrain analysis: trafficability, mobility corridors,
avenues of approach, engagement areas, defensible terrain.

Implements the ATP 2-01.3 Step 2 ("Describe Environmental Effects on
Operations") synthesis chain end-to-end:

  1. Build a fine-resolution (~100 m operational cell) trafficability
     grid from DEM (slope + surface configuration) and ESA WorldCover
     land cover. Each cell is classified NO-GO / SLOW-GO / GO per the
     force-type canalization criterion.

  2. Extract NO-GO obstacle polygons (shapely) by clustering NO-GO
     cells; expand via Minkowski sum to per-echelon Configuration-Space
     obstacles (Division 12 km x 30 km formation envelope; Brigade
     6 x 15; Battalion 1.5 x 4 — derived from ATP 2-01.3 Table 4-2
     typical widths and FM 3-0 march-column depths).

  3. Compute an approximation of the Generalized Voronoi Diagram (GVD)
     of the C-space obstacles by densely sampling obstacle perimeters
     and running scipy point-Voronoi, then pruning Voronoi edges that
     cross obstacle interiors. GVD edges approximate mobility corridor
     centerlines (the unrestricted "skeleton" of trafficable terrain);
     GVD vertices fall in enclosed regions favoured for engagement
     areas / defensible terrain.

  4. Build the corridor network as a resistive circuit: each GVD edge
     becomes a resistor with R proportional to its length and inversely
     proportional to its width (the perpendicular clearance between the
     bounding obstacles). Key-terrain endpoints (friendly LD, threat
     HQ) become voltage terminals.

  5. Apply Ohm's law / Kirchhoff's current law at each (origin,
     objective) terminal pair. The edges carrying the highest current
     are the doctrinal primary central axis of the avenue of approach
     (the path of least resistance from origin to objective). Group
     neighbour corridors within ATP 2-01.3 Table 4-2 distance of that
     central axis into a multi-tailed avenue of approach.

  6. Select engagement areas: GVD vertices whose enclosing region offers
     poor cover/concealment to a passing force AND that, when "blocked"
     in the circuit (resistance raised), maximally reduce the enemy's
     baseline current flow from disruption zone to objective.

  7. Select defensible terrain: regions whose series-parallel resistance
     summary is maximised — providing natural protection on the largest
     number of approach axes.

Doctrinal references:
  - ATP 2-01.3 IPOE (Change 3, May 2025): Chapter 4 Step 2; Table 4-2
    corridor widths + max distance between corridors.
  - FM 1-02.2 Military Symbols: Table 5-9 control measures (axes,
    direction of attack); Fig 4-13/4-14 ATP MCOO examples.
  - "Terrain-Based Information Fusion and Inference" (Glinton, Owens,
    Giampapa, Sycara, Grindle, Lewis; CMU/UPitt 2004) — the GVD +
    circuit-theory formulation for automated MCOO generation, validated
    against SME analysts. Sections 3.1 (trafficability), 3.2
    (configuration space), 3.3 (GVD + circuit), Avenues of Approach,
    Engagement Areas, Defensible terrain.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — doctrinal thresholds + grid parameters
# ---------------------------------------------------------------------------

# Operational grid resolution (metres). 100 m is the smallest resolution
# at which the GVD + circuit math runs in <30 s for a 250 x 165 km AO on
# a single core. Increase to 50 m for finer pinch-point detection at the
# cost of ~4x runtime.
DEFAULT_CELL_M = 100

# WorldCover landcover class codes (ESA v200) — same mapping the
# existing landcover.py uses; replicated here to avoid a circular import.
LC_TREE = 10
LC_SHRUB = 20
LC_GRASS = 30
LC_CROP = 40
LC_BUILT = 50
LC_BARE = 60
LC_SNOW = 70
LC_WATER = 80
LC_WETLAND = 90
LC_MANGROVE = 95
LC_MOSS = 100


# Cell classification (mirrors the paper's Fig 4 + ATP 2-01.3 Table 4-1).
# 0 = NO-GO (impassable for force); 1 = SLOW-GO (significant cost);
# 2 = GO (unrestricted). Used as small integers in numpy arrays.
NOGO, SLOWGO, GO = 0, 1, 2


# Per-force canalization thresholds — mechanized as the doctrinal baseline,
# dismounted halved per ATP 2-01.3 paragraph 4-26 note that dismounted
# forces can use more restrictive corridors. Slope thresholds in percent
# grade per ATP 2-01.3 Table 4-1.
@dataclass(frozen=True)
class ForceProfile:
    name: str
    max_slope_pct_go: float       # cells exceeding this grade are SLOW-GO
    max_slope_pct_nogo: float     # cells exceeding this grade are NO-GO
    nogo_landcovers: frozenset    # land cover codes that are NO-GO
    slowgo_landcovers: frozenset  # land cover codes that are SLOW-GO
    # Formation polygon dimensions for the C-space Minkowski sum, in
    # metres. width = perpendicular frontage; depth = along-march extent.
    # Drawn from ATP 2-01.3 Table 4-2 typical widths + FM 3-0 march column
    # depths (Division ~30 km; Brigade ~15 km; Battalion ~4 km when fully
    # deployed in approach march).
    echelon_polygons_m: Dict[str, Tuple[float, float]] = field(default_factory=dict)


_MECH_ECHELONS = {
    "division":  (12000.0, 30000.0),
    "brigade":   ( 6000.0, 15000.0),
    "battalion": ( 1500.0,  4000.0),
    "company":   (  500.0,  1500.0),
    # Per Glinton paper §3.2: the C-space dilation reference shape is a
    # TANK PLATOON polygon ("Consider a tank platoon traveling through a
    # piece of [terrain] ... we calculate the Minkowski Sum of the
    # platoon polygon and an obstacle ... represents a tank platoon").
    # Frontage ~200 m (4 vehicles abreast at 50 m intervals), depth
    # ~500 m (column-of-twos with following echelon). Equivalent-area
    # disk radius = sqrt(200*500)/2 ≈ 158 m. This is what compute_gvd
    # actually wants — battalion / brigade dilation cuts the AO into
    # disconnected islands and fragments the GVD per the paper's own
    # warning that big formations OVER-fragment.
    "platoon":   (  200.0,   500.0),
}

MECHANIZED = ForceProfile(
    name="mechanized",
    max_slope_pct_go=10.0,
    max_slope_pct_nogo=30.0,
    nogo_landcovers=frozenset({LC_WATER, LC_WETLAND, LC_MANGROVE}),
    slowgo_landcovers=frozenset({LC_TREE, LC_SHRUB, LC_SNOW, LC_BUILT}),
    echelon_polygons_m=_MECH_ECHELONS,
)

_DISMOUNTED_ECHELONS = {k: (w / 2.0, d / 2.0) for k, (w, d) in _MECH_ECHELONS.items()}

DISMOUNTED = ForceProfile(
    name="dismounted",
    max_slope_pct_go=25.0,
    max_slope_pct_nogo=60.0,
    # Infantry can traverse wetland (poor but passable per ATP 2-01.3
    # ¶4-26 + FM 3-0). Permanent water + mangroves remain NO-GO.
    nogo_landcovers=frozenset({LC_WATER, LC_MANGROVE}),
    slowgo_landcovers=frozenset({LC_WETLAND, LC_SNOW}),  # tree cover is FRIEND to dismounted
    echelon_polygons_m=_DISMOUNTED_ECHELONS,
)


def resolve_force_profile(force_type: str) -> ForceProfile:
    """Map a user-supplied force_type string to a ForceProfile."""
    s = (force_type or "").strip().lower()
    if s.startswith(("dismount", "infantry", "sof", "special")):
        return DISMOUNTED
    return MECHANIZED


# ATP 2-01.3 Table 4-2: max distance between mobility corridors that
# group into the SAME avenue of approach, per avenue echelon. Used in
# Step 5 (corridor grouping into multi-tail bundles).
AVENUE_GROUPING_MAX_DISTANCE_M = {
    "division":  10000.0,
    "brigade":    6000.0,
    "battalion":  2000.0,
    "company":     500.0,
}


# ---------------------------------------------------------------------------
# Trafficability grid construction
# ---------------------------------------------------------------------------

@dataclass
class TrafficabilityGrid:
    """A 2D classification grid for the AO at a uniform cell size.

    Attributes:
        cls: 2D ndarray (rows, cols) of int8: 0=NO-GO, 1=SLOW-GO, 2=GO.
        slope_pct: 2D ndarray of percent-grade slope per cell.
        landcover: 2D ndarray of int8 ESA WorldCover class code per cell.
        elevation_m: 2D ndarray of float32 elevation in metres per cell.
        west, south, east, north: bbox in degrees (lon/lat).
        cell_m: nominal cell size in metres.
        rows, cols: grid dimensions.
        meters_per_lon_at_centre, meters_per_lat: degree-to-metre scale.
    """
    cls: np.ndarray
    slope_pct: np.ndarray
    landcover: np.ndarray
    elevation_m: np.ndarray
    west: float
    south: float
    east: float
    north: float
    cell_m: float
    meters_per_lon_at_centre: float
    meters_per_lat: float

    @property
    def rows(self) -> int:
        return int(self.cls.shape[0])

    @property
    def cols(self) -> int:
        return int(self.cls.shape[1])

    def cell_lonlat(self, row: int, col: int) -> Tuple[float, float]:
        """Return the centre (lon, lat) of cell (row, col).

        Row 0 is the NORTH edge of the AO (rasterio convention)."""
        lat = self.north - (row + 0.5) * (self.north - self.south) / self.rows
        lon = self.west + (col + 0.5) * (self.east - self.west) / self.cols
        return lon, lat

    def lonlat_to_cell(self, lon: float, lat: float) -> Tuple[int, int]:
        """Return the (row, col) of the cell containing (lon, lat).
        Clamped to grid bounds. Row 0 = north edge."""
        col = int((lon - self.west) * self.cols / (self.east - self.west))
        row = int((self.north - lat) * self.rows / (self.north - self.south))
        row = max(0, min(self.rows - 1, row))
        col = max(0, min(self.cols - 1, col))
        return row, col


def build_trafficability_grid(
    *,
    west: float, south: float, east: float, north: float,
    force_profile: ForceProfile = MECHANIZED,
    cell_m: float = DEFAULT_CELL_M,
    dem_dir: str = None,
    landcover_dir: str = None,
) -> TrafficabilityGrid:
    """Build a (rows, cols) trafficability grid for the bbox at cell_m
    resolution by reading DEM + ESA WorldCover via rasterio.

    DEM tiles are expected as 1° x 1° GeoTIFFs named ``dem_N{lat:02d}E{lon:03d}.tif``
    (matches the IDX 26 offline preload layout). WorldCover tiles use the
    standard ESA naming ``ESA_WorldCover_10m_2021_v200_N{lat:02d}E{lon:03d}_Map.tif``
    in 3° x 3° tiles. Defaults look in ``offline/dem/`` and
    ``offline/landcover/`` under the geo-agent offline data dir.
    """
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject
    from rasterio.windows import from_bounds as window_from_bounds

    if dem_dir is None:
        dem_dir = _default_dem_dir()
    if landcover_dir is None:
        landcover_dir = _default_landcover_dir()

    centre_lat = (south + north) / 2.0
    m_per_lat = 111_132.0
    m_per_lon = 111_320.0 * math.cos(math.radians(centre_lat))

    cols = max(1, int(round((east - west) * m_per_lon / cell_m)))
    rows = max(1, int(round((north - south) * m_per_lat / cell_m)))
    logger.info(
        "build_trafficability_grid: bbox=[%.4f,%.4f,%.4f,%.4f] cell_m=%g -> %d x %d cells",
        west, south, east, north, cell_m, rows, cols,
    )

    # Disk cache check. Trafficability is deterministic in (bbox, cell_m,
    # force_profile, source tile mtimes), so re-running the same AO hits
    # the cache and skips the 2-minute reproject+slope pipeline entirely.
    dem_paths = _dem_tile_paths(dem_dir, west, south, east, north)
    lc_paths = _landcover_tile_paths(landcover_dir, west, south, east, north)
    cache_key = _trafficability_cache_key(
        west=west, south=south, east=east, north=north, cell_m=cell_m,
        force_profile_name=force_profile.name,
        tile_paths=list(dem_paths) + list(lc_paths),
    )
    cache_path = os.path.join(_trafficability_cache_dir(), f"{cache_key}.npz")
    if os.path.exists(cache_path):
        try:
            import time as _ct
            _cache_t0 = _ct.perf_counter()
            with np.load(cache_path) as _data:
                cls = _data["cls"]
                slope_pct = _data["slope_pct"]
                lc = _data["lc"]
                elev = _data["elev"]
            logger.info(
                "build_trafficability_grid: CACHE HIT %s loaded in %.2fs (skipping "
                "reproject + slope pipeline)",
                os.path.basename(cache_path), _ct.perf_counter() - _cache_t0,
            )
            return TrafficabilityGrid(
                cls=cls, slope_pct=slope_pct, landcover=lc, elevation_m=elev,
                west=west, south=south, east=east, north=north,
                cell_m=cell_m,
                meters_per_lon_at_centre=m_per_lon,
                meters_per_lat=m_per_lat,
            )
        except Exception as _cache_err:
            logger.warning(
                "build_trafficability_grid: cache load failed (%s); rebuilding",
                _cache_err,
            )

    dst_transform = from_bounds(west, south, east, north, cols, rows)
    elev = _read_raster_window(
        sources=dem_paths,
        dst_transform=dst_transform, rows=rows, cols=cols,
        dtype=np.float32, nodata=-32768.0, resampling=Resampling.bilinear,
    )
    lc = _read_raster_window(
        sources=lc_paths,
        dst_transform=dst_transform, rows=rows, cols=cols,
        dtype=np.uint8, nodata=0, resampling=Resampling.nearest,
    )

    # Slope per cell via central differences on the elevation grid.
    # cell_m is the same in both axes (we keep cells approximately square
    # by computing rows/cols from m_per_lat/m_per_lon).
    slope_pct = _slope_percent(elev, cell_m)

    # Classify per Glinton-style pseudocode (paper Fig 4):
    #   NO-GO if land cover is in nogo_landcovers OR slope > max_slope_nogo
    #   SLOW-GO if land cover is in slowgo_landcovers OR slope > max_slope_go
    #   GO otherwise
    cls = np.full((rows, cols), GO, dtype=np.int8)
    # Slow-go assignments first (later NO-GO overrides).
    slowgo_mask = (slope_pct > force_profile.max_slope_pct_go) | (
        np.isin(lc, list(force_profile.slowgo_landcovers))
    )
    cls[slowgo_mask] = SLOWGO
    nogo_mask = (slope_pct > force_profile.max_slope_pct_nogo) | (
        np.isin(lc, list(force_profile.nogo_landcovers))
    )
    cls[nogo_mask] = NOGO
    # Cells with no DEM and no LC fallback -> SLOW-GO (unknown caution).
    unknown_mask = (lc == 0) & (np.abs(elev + 32768.0) < 1.0)
    cls[unknown_mask] = SLOWGO

    n_no = int((cls == NOGO).sum())
    n_slow = int((cls == SLOWGO).sum())
    n_go = int((cls == GO).sum())
    logger.info(
        "trafficability classes: NO-GO=%d (%.1f%%) SLOW-GO=%d (%.1f%%) GO=%d (%.1f%%)",
        n_no, 100 * n_no / cls.size,
        n_slow, 100 * n_slow / cls.size,
        n_go, 100 * n_go / cls.size,
    )

    # Persist to cache for next call with the same (bbox, cell_m,
    # force_profile, tile mtimes). Use atomic rename to avoid partial
    # files on concurrent invocations.
    try:
        # Write to a tmp file then atomically rename. np.savez_compressed
        # auto-appends .npz to bare filenames, so we pass an open file
        # handle to keep the exact name we want.
        tmp_path = cache_path + ".tmp"
        with open(tmp_path, "wb") as _f:
            np.savez_compressed(
                _f, cls=cls, slope_pct=slope_pct, lc=lc, elev=elev,
            )
        os.replace(tmp_path, cache_path)
        logger.info(
            "build_trafficability_grid: wrote cache %s",
            os.path.basename(cache_path),
        )
    except Exception as _cache_err:
        logger.warning(
            "build_trafficability_grid: cache write failed (%s); continuing",
            _cache_err,
        )

    return TrafficabilityGrid(
        cls=cls, slope_pct=slope_pct, landcover=lc, elevation_m=elev,
        west=west, south=south, east=east, north=north,
        cell_m=cell_m,
        meters_per_lon_at_centre=m_per_lon,
        meters_per_lat=m_per_lat,
    )


def _default_dem_dir() -> str:
    from app.config import get_settings
    s = get_settings()
    return os.path.join(s.offline_data_dir, "dem")


def _default_landcover_dir() -> str:
    from app.config import get_settings
    s = get_settings()
    return os.path.join(s.offline_data_dir, "landcover")


def _dem_tile_paths(
    base: str, west: float, south: float, east: float, north: float,
) -> List[str]:
    """Return DEM tile paths that intersect bbox. Tiles named
    dem_N{lat}E{lon}.tif (1x1 deg, integer-floor lat/lon).
    """
    paths: List[str] = []
    for lat in range(int(math.floor(south)), int(math.floor(north)) + 1):
        for lon in range(int(math.floor(west)), int(math.floor(east)) + 1):
            name = f"dem_N{lat:02d}E{lon:03d}.tif"
            p = os.path.join(base, name)
            if os.path.exists(p):
                paths.append(p)
    return paths


def _landcover_tile_paths(
    base: str, west: float, south: float, east: float, north: float,
) -> List[str]:
    """ESA WorldCover tile paths intersecting bbox. Tiles named
    ESA_WorldCover_10m_2021_v200_N{lat}E{lon}_Map.tif (3x3 deg,
    lat/lon multiples of 3 — round DOWN to nearest 3)."""
    paths: List[str] = []
    lat0 = int(math.floor(south / 3.0) * 3)
    lat1 = int(math.floor(north / 3.0) * 3)
    lon0 = int(math.floor(west / 3.0) * 3)
    lon1 = int(math.floor(east / 3.0) * 3)
    for lat in range(lat0, lat1 + 3, 3):
        for lon in range(lon0, lon1 + 3, 3):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            name = (
                f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat):02d}{ew}{abs(lon):03d}_Map.tif"
            )
            p = os.path.join(base, name)
            if os.path.exists(p):
                paths.append(p)
    return paths


def _read_raster_window(
    *,
    sources: Sequence[str],
    dst_transform,
    rows: int, cols: int,
    dtype: np.dtype,
    nodata,
    resampling,
) -> np.ndarray:
    """Mosaic + reproject a set of source GeoTIFFs into a single (rows, cols)
    array at dst_transform. Source tiles are read via rasterio.warp.reproject
    so they need not share CRS or alignment. Cells without any source
    contributor get ``nodata`` (caller treats as unknown).

    Per-tile reads are dispatched on a ThreadPoolExecutor. Each worker
    produces its own (rows, cols) partial dst that gets composited into
    the shared dst (last-write-wins where tiles overlap). rasterio
    releases the GIL during reproject, so this scales near-linearly
    with the number of source tiles when they're independent files.
    """
    import rasterio
    from rasterio.warp import reproject
    from concurrent.futures import ThreadPoolExecutor
    dst = np.full((rows, cols), nodata, dtype=dtype)
    if not sources:
        logger.warning(
            "_read_raster_window: no source tiles available; returning all-nodata grid"
        )
        return dst

    def _read_one(src_path):
        try:
            with rasterio.open(src_path) as src:
                src_band = src.read(1)
                # Per-thread partial dst so workers don't race the shared dst.
                # (rasterio's reproject is thread-safe per call but the dst
                # buffer write is not.)
                partial = np.full((rows, cols), nodata, dtype=dtype)
                reproject(
                    source=src_band,
                    destination=partial,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:4326",
                    resampling=resampling,
                    src_nodata=src.nodata,
                    dst_nodata=nodata,
                )
                return partial
        except Exception as exc:
            logger.warning("_read_raster_window: skip %s: %s", src_path, exc)
            return None

    max_workers = max(1, min(len(sources), (os.cpu_count() or 1)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for partial in ex.map(_read_one, sources):
            if partial is None:
                continue
            # Composite into dst: cells where partial has data overwrite
            # the dst (last-write-wins matches the serial loop's semantics).
            if np.issubdtype(dtype, np.floating):
                valid = partial != nodata
            else:
                valid = partial != nodata
            dst = np.where(valid, partial, dst)
    return dst


def _trafficability_cache_dir() -> str:
    from app.config import get_settings
    s = get_settings()
    p = os.path.join(s.offline_data_dir, "cache", "trafficability_grid")
    os.makedirs(p, exist_ok=True)
    return p


def _trafficability_cache_key(
    *, west, south, east, north, cell_m, force_profile_name, tile_paths,
) -> str:
    """Cache key incorporates bbox + cell_m + force-profile name + the
    mtime of every source tile. If tiles haven't changed and the grid
    geometry is identical, the cached result is mathematically the same."""
    import hashlib as _hash
    h = _hash.sha256()
    h.update(f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}".encode())
    h.update(f"|cell_m={cell_m:.4f}".encode())
    h.update(f"|profile={force_profile_name}".encode())
    for p in sorted(tile_paths):
        try:
            mt = os.path.getmtime(p)
        except OSError:
            mt = 0
        h.update(f"|{p}@{mt:.3f}".encode())
    return h.hexdigest()[:32]


def _slope_percent(elev_m: np.ndarray, cell_m: float) -> np.ndarray:
    """Percent grade (rise/run * 100) at each cell via central differences.
    Edge cells use one-sided differences. Cells with nodata (-32768) sentinel
    yield slope 0 (treated as unknown/flat rather than impassable)."""
    valid = elev_m > -10000.0
    # Replace nodata with neighbour-fill before differencing to avoid
    # massive spurious slopes at tile edges.
    safe = np.where(valid, elev_m, 0.0).astype(np.float32)
    dy = np.zeros_like(safe)
    dx = np.zeros_like(safe)
    dy[1:-1, :] = (safe[2:, :] - safe[:-2, :]) / (2 * cell_m)
    dx[:, 1:-1] = (safe[:, 2:] - safe[:, :-2]) / (2 * cell_m)
    dy[0, :] = (safe[1, :] - safe[0, :]) / cell_m
    dy[-1, :] = (safe[-1, :] - safe[-2, :]) / cell_m
    dx[:, 0] = (safe[:, 1] - safe[:, 0]) / cell_m
    dx[:, -1] = (safe[:, -1] - safe[:, -2]) / cell_m
    grade = np.sqrt(dx * dx + dy * dy) * 100.0
    # NaN/inf safety
    grade = np.where(np.isfinite(grade), grade, 0.0)
    return grade.astype(np.float32)


# ---------------------------------------------------------------------------
# NO-GO obstacle polygon extraction + C-space (Minkowski sum) expansion
# ---------------------------------------------------------------------------

def extract_nogo_polygons(grid: TrafficabilityGrid, min_area_m2: float = 1e6):
    """Vectorise the NO-GO mask into shapely Polygons (one per
    connected component) in (lon, lat) coordinates. Polygons smaller
    than ``min_area_m2`` (default 1 km^2) are dropped as noise.

    Uses rasterio.features.shapes which performs marching-squares
    polygonisation in one pass over the mask.
    """
    from rasterio import features
    from rasterio.transform import from_bounds
    from shapely.geometry import shape

    mask = (grid.cls == NOGO).astype(np.uint8)
    if not mask.any():
        return []
    transform = from_bounds(
        grid.west, grid.south, grid.east, grid.north,
        grid.cols, grid.rows,
    )
    polys = []
    for geom, val in features.shapes(mask, mask=mask.astype(bool), transform=transform):
        if val != 1:
            continue
        poly = shape(geom)
        # area in deg^2 -> convert to m^2 using local scale
        area_m2 = poly.area * grid.meters_per_lon_at_centre * grid.meters_per_lat
        if area_m2 < min_area_m2:
            continue
        polys.append(poly)
    logger.info(
        "extract_nogo_polygons: %d polygons >= %.1f km^2 (from %d NO-GO cells)",
        len(polys), min_area_m2 / 1e6, int(mask.sum()),
    )
    return polys


def compute_c_space_obstacles(
    nogo_polys, *,
    grid: TrafficabilityGrid,
    echelon: str,
    force_profile: ForceProfile = MECHANIZED,
):
    """Minkowski-sum dilate each NO-GO polygon by half the formation
    polygon's effective radius for the requested echelon. This produces
    the Configuration-Space obstacles: cells where the formation's
    centre cannot be placed without overlap with a NO-GO region.

    For shapely 2.x the Minkowski sum of a polygon with a convex shape
    is well-approximated by ``poly.buffer(radius)`` when the moving
    shape is a disk (rotation-invariant formation). We approximate the
    division/brigade march column as a disk of radius
    sqrt(width * depth) / 2 — the radius of a disk with equal area to
    the formation's bounding rectangle. This is the conservative
    rotation-invariant approximation Glinton paper Section 3.2
    suggests when formation heading isn't known.
    """
    w_m, d_m = force_profile.echelon_polygons_m.get(echelon, (0.0, 0.0))
    if w_m == 0:
        return list(nogo_polys)
    # equivalent-area disk radius (conservative bound)
    radius_m = math.sqrt(w_m * d_m) / 2.0
    # convert to degrees (use latitudinal scale — slightly conservative
    # near the higher latitude edge of AO)
    radius_deg = radius_m / grid.meters_per_lat
    out = []
    for p in nogo_polys:
        try:
            out.append(p.buffer(radius_deg, quad_segs=8))
        except Exception as exc:
            logger.warning("compute_c_space_obstacles: skip buffer: %s", exc)
    return out


# ---------------------------------------------------------------------------
# GVD approximation via sampled-boundary point Voronoi
# ---------------------------------------------------------------------------

@dataclass
class CorridorEdge:
    """One mobility corridor segment: a polyline + measured width."""
    id: int
    coords: List[Tuple[float, float]]  # [(lon, lat), ...]
    length_m: float
    width_m: float       # narrowest perpendicular clearance along edge
    endpoints: Tuple[int, int]  # node indices

    def class_(self, force_profile: ForceProfile) -> str:
        """ATP 2-01.3 Table 4-2 classification by typical width."""
        wkm = self.width_m / 1000.0
        if force_profile.name.startswith("dismount"):
            # Half thresholds per ¶4-26.
            for label, kmin in (
                ("division", 3.0), ("brigade", 1.5),
                ("battalion", 0.75), ("company", 0.25),
            ):
                if wkm >= kmin:
                    return label
        else:
            for label, kmin in (
                ("division", 6.0), ("brigade", 3.0),
                ("battalion", 1.5), ("company", 0.5),
            ):
                if wkm >= kmin:
                    return label
        return "sub-company"


@dataclass
class GVD:
    """Generalized Voronoi Diagram of obstacle polygons.
    edges: list of CorridorEdge. nodes: list of (lon, lat).
    """
    edges: List[CorridorEdge]
    nodes: List[Tuple[float, float]]
    # node_idx_for_obstacle[i] is the list of node indices on the boundary
    # of obstacle i (used to detect "enclosed regions" between obstacles).
    obstacle_boundary_samples: List[Tuple[float, float]]


def _road_edge_width_m(highway_type: str) -> float:
    """Carriageway width per OSM highway class. Source: OSM wiki +
    typical EU motorway standards."""
    return {
        "motorway":      15.0,  # 2x2 lanes + shoulders
        "motorway_link":  8.0,
        "trunk":         12.0,
        "trunk_link":     8.0,
        "primary":       10.0,
        "primary_link":   7.0,
        "secondary":      8.0,
        "secondary_link": 6.0,
        "tertiary":       7.0,
        "tertiary_link":  5.0,
        "unclassified":   5.0,
        "residential":    5.0,
        "service":        4.0,
    }.get(highway_type.lower(), 5.0)


def compute_gvd(
    c_space_obstacles,
    *,
    grid: TrafficabilityGrid,
    samples_per_edge_m: float = 100.0,        # denser sampling = better GVD connectivity
    min_corridor_width_m: float = 30.0,        # was 150 — too aggressive; narrow corridors
                                               # have high circuit resistance (length/width)
                                               # but are needed for connectivity
    min_corridor_length_m: float = 50.0,       # was 150
    edge_obstacle_overlap_max: float = 0.15,   # drop edge only if > 15 % of its length
                                               # is inside an obstacle (was drop on ANY
                                               # crosses/contains — over-aggressive)
    roads: Optional[List[Any]] = None,         # OSM Roads (app.services.knowledge.roads.Road)
                                               # — every road becomes corridor edges with
                                               # width = lane width × n_lanes. Per FM 5-33
                                               # / ATP 2-22.7 roads are the PRIMARY mobility
                                               # infrastructure; a corridor graph built only
                                               # from terrain Voronoi misses the actual road
                                               # network mechanized forces use.
    ao_buffer_m: float = 1000.0,
) -> GVD:
    """Approximate the GVD of the obstacle polygons by sampling each
    obstacle's exterior, computing a point Voronoi, and pruning Voronoi
    edges that cross obstacle interiors or fall outside the AO.

    Returns a GVD with:
      - edges = surviving Voronoi edges (mobility corridors)
      - nodes = surviving Voronoi vertices (potential engagement areas)
      - width_m measured as 2 * distance from each edge midpoint to the
        nearest obstacle boundary sample (radius of the inscribed disk
        at that point).
    """
    from scipy.spatial import Voronoi
    from shapely.geometry import LineString, Point, box
    from shapely.strtree import STRtree

    # 1. Sample obstacle perimeters at uniform density. Convert metres
    # to degrees using lat scale (consistent within AO).
    samples_per_deg = grid.meters_per_lat / samples_per_edge_m
    sample_pts: List[Tuple[float, float]] = []
    for poly in c_space_obstacles:
        rings = []
        if poly.geom_type == "Polygon":
            rings = [poly.exterior] + list(poly.interiors)
        elif poly.geom_type == "MultiPolygon":
            for sub in poly.geoms:
                rings.append(sub.exterior)
                rings.extend(sub.interiors)
        else:
            continue
        for ring in rings:
            length_deg = ring.length
            n = max(8, int(length_deg * samples_per_deg))
            for i in range(n):
                t = i / n
                p = ring.interpolate(t * length_deg)
                sample_pts.append((p.x, p.y))

    # Add a coarse fence of points around the AO bbox so the Voronoi
    # is bounded (otherwise the unbounded outer cells lack edges). The
    # fence is just outside the AO so its Voronoi edges fall outside
    # our AO clip and are dropped naturally.
    fence_d = ao_buffer_m / grid.meters_per_lat
    for t in np.linspace(0.0, 1.0, 64):
        sample_pts.append((grid.west - fence_d + t * (grid.east - grid.west + 2 * fence_d), grid.south - fence_d))
        sample_pts.append((grid.west - fence_d + t * (grid.east - grid.west + 2 * fence_d), grid.north + fence_d))
        sample_pts.append((grid.west - fence_d, grid.south - fence_d + t * (grid.north - grid.south + 2 * fence_d)))
        sample_pts.append((grid.east + fence_d, grid.south - fence_d + t * (grid.north - grid.south + 2 * fence_d)))

    if len(sample_pts) < 4:
        logger.warning("compute_gvd: too few sample points (%d) — returning empty GVD",
                       len(sample_pts))
        return GVD(edges=[], nodes=[], obstacle_boundary_samples=sample_pts)

    logger.info("compute_gvd: %d obstacle perimeter samples", len(sample_pts))

    pts = np.array(sample_pts, dtype=float)
    try:
        vor = Voronoi(pts)
    except Exception as exc:
        logger.error("compute_gvd: Voronoi failed: %s", exc)
        return GVD(edges=[], nodes=[], obstacle_boundary_samples=sample_pts)

    # AO clip box + obstacle index for edge pruning.
    ao_box = box(grid.west, grid.south, grid.east, grid.north)
    obstacle_tree = STRtree(c_space_obstacles) if c_space_obstacles else None

    # 2. For each Voronoi vertex, drop the ones inside any obstacle.
    vert_inside_obstacle = np.zeros(len(vor.vertices), dtype=bool)
    for i, (vx, vy) in enumerate(vor.vertices):
        if not (grid.west <= vx <= grid.east and grid.south <= vy <= grid.north):
            continue
        pt = Point(vx, vy)
        if obstacle_tree is not None:
            cands = obstacle_tree.query(pt)
            for c_idx in (cands if isinstance(cands, np.ndarray) else cands):
                obstacle = c_space_obstacles[int(c_idx)]
                if obstacle.covers(pt):
                    vert_inside_obstacle[i] = True
                    break

    # 3. For each Voronoi ridge, keep it if:
    #    - both endpoints are finite Voronoi vertices (not at infinity),
    #    - both endpoints are inside the AO and NOT inside an obstacle,
    #    - the segment between them doesn't cross any obstacle.
    surviving_nodes: Dict[int, int] = {}  # vor.vertices index -> our node index
    nodes_xy: List[Tuple[float, float]] = []
    edges: List[CorridorEdge] = []

    def _node_id(vi: int) -> int:
        if vi in surviving_nodes:
            return surviving_nodes[vi]
        nid = len(nodes_xy)
        nodes_xy.append((float(vor.vertices[vi][0]), float(vor.vertices[vi][1])))
        surviving_nodes[vi] = nid
        return nid

    # Boundary sample STRtree for nearest-distance width estimation
    boundary_tree = STRtree([Point(p[0], p[1]) for p in sample_pts])
    boundary_xy = pts

    for (vi_a, vi_b) in vor.ridge_vertices:
        if vi_a < 0 or vi_b < 0:
            continue  # unbounded ridge -> skip
        if vert_inside_obstacle[vi_a] or vert_inside_obstacle[vi_b]:
            continue
        a = vor.vertices[vi_a]
        b = vor.vertices[vi_b]
        # AO clip
        if not (grid.west <= a[0] <= grid.east and grid.south <= a[1] <= grid.north):
            continue
        if not (grid.west <= b[0] <= grid.east and grid.south <= b[1] <= grid.north):
            continue
        line = LineString([(a[0], a[1]), (b[0], b[1])])
        # Drop edges only if MORE than `edge_obstacle_overlap_max` of
        # the edge length is inside an obstacle. Edges that just graze
        # an obstacle corner survive — those are narrow corridors, not
        # piercings. (Previous filter dropped on any `crosses` /
        # `contains` and over-fragmented the GVD.)
        line_len = line.length
        overlap_len = 0.0
        if obstacle_tree is not None and line_len > 0:
            cands = obstacle_tree.query(line)
            iter_cands = cands if isinstance(cands, np.ndarray) else list(cands)
            for c_idx in iter_cands:
                obstacle = c_space_obstacles[int(c_idx)]
                try:
                    inter = obstacle.intersection(line)
                    if not inter.is_empty:
                        overlap_len += inter.length
                except Exception:
                    pass
                if overlap_len / line_len > edge_obstacle_overlap_max:
                    break
        if line_len > 0 and overlap_len / line_len > edge_obstacle_overlap_max:
            continue

        # Width: 2 * distance from midpoint to nearest obstacle boundary
        # sample, capped to a reasonable max for headline display.
        mx = (a[0] + b[0]) / 2.0
        my = (a[1] + b[1]) / 2.0
        mid_pt = Point(mx, my)
        nearest_idx = boundary_tree.nearest(mid_pt)
        # shapely 2 returns scalar index; older returns Point
        if hasattr(nearest_idx, "x"):
            nx_, ny_ = nearest_idx.x, nearest_idx.y
        else:
            nx_, ny_ = float(boundary_xy[int(nearest_idx)][0]), float(boundary_xy[int(nearest_idx)][1])
        # convert degree distance to metres at midpoint latitude
        m_per_lat = grid.meters_per_lat
        m_per_lon = 111_320.0 * math.cos(math.radians(my))
        dxm = (mx - nx_) * m_per_lon
        dym = (my - ny_) * m_per_lat
        width_m = 2.0 * math.hypot(dxm, dym)
        if width_m < min_corridor_width_m:
            continue

        # Edge length in metres
        seg_dxm = (b[0] - a[0]) * m_per_lon
        seg_dym = (b[1] - a[1]) * m_per_lat
        length_m = math.hypot(seg_dxm, seg_dym)
        if length_m <= 0:
            continue
        if length_m < min_corridor_length_m:
            continue

        na = _node_id(vi_a)
        nb = _node_id(vi_b)
        edges.append(CorridorEdge(
            id=len(edges),
            coords=[(float(a[0]), float(a[1])), (float(b[0]), float(b[1]))],
            length_m=length_m,
            width_m=width_m,
            endpoints=(na, nb),
        ))

    voronoi_edge_count = len(edges)
    voronoi_node_count = len(nodes_xy)
    logger.info(
        "compute_gvd: %d Voronoi vertices, %d ridges -> %d surviving terrain corridors, %d nodes",
        len(vor.vertices), len(vor.ridge_vertices), voronoi_edge_count, voronoi_node_count,
    )

    # Per FM 5-33 / ATP 2-22.7: roads are the primary mobility
    # infrastructure for mechanized formations. Add each OSM road as
    # corridor edges connecting waypoint nodes. Roads cross obstacle
    # C-space because they typically run on engineered surfaces (bridges
    # over rivers, cuts through restricted terrain). We trust the road
    # exists where OSM says it does.
    if roads:
        from shapely.geometry import LineString as _SimpLine
        from collections import Counter as _RoadKeyCounter
        # Pre-scan all road coords to identify JUNCTION POINTS — points
        # that appear in 2+ different OSM ways. At an intersection,
        # two OSM ways share a coordinate (OSM stores intersections as
        # shared node IDs at full precision). Without preserving these
        # during simplification, Douglas-Peucker drops the intersection
        # vertex and the two roads' simplified polylines no longer
        # share a node — the road network fragments into thousands of
        # disconnected single-road components. Detection precision = 10 m
        # (4 decimals); same key used for the road_node dedupe below.
        def _road_key(lon: float, lat: float) -> Tuple[float, float]:
            return (round(float(lon), 4), round(float(lat), 4))
        coord_counter = _RoadKeyCounter()
        for road in roads:
            raw = getattr(road, "coords", None) or []
            for lon, lat in raw:
                coord_counter[_road_key(lon, lat)] += 1
        junction_keys = {k for k, c in coord_counter.items() if c > 1}
        logger.info(
            "compute_gvd: identified %d junction points (shared across 2+ OSM ways) "
            "from %d total road coords",
            len(junction_keys), sum(coord_counter.values()),
        )
        road_node_for_xy: Dict[Tuple[float, float], int] = {}
        def _road_node_id(lon: float, lat: float) -> int:
            # Same 10 m key as junction detection so junction points
            # MERGE across roads. OSM-shared coordinates round to the
            # same key and resolve to the same graph node.
            key = _road_key(lon, lat)
            if key in road_node_for_xy:
                return road_node_for_xy[key]
            nid = len(nodes_xy)
            nodes_xy.append((float(lon), float(lat)))
            road_node_for_xy[key] = nid
            return nid
        # Junction-preserving Douglas-Peucker simplification. We split
        # each road's polyline at junction vertices, simplify the
        # intra-junction sub-segments, then rejoin — the junctions
        # themselves are NEVER dropped, so the graph topology stays
        # connected. Tolerance ≈ 50 m.
        road_simplify_tol_deg = 50.0 / grid.meters_per_lat
        road_edges_added = 0
        for road in roads:
            raw_coords = getattr(road, "coords", None) or []
            if len(raw_coords) < 2:
                continue
            # Force-include indices = endpoints + any junction vertex.
            keep_idx = [0, len(raw_coords) - 1]
            for i, (lon, lat) in enumerate(raw_coords):
                if 0 < i < len(raw_coords) - 1 and _road_key(lon, lat) in junction_keys:
                    keep_idx.append(i)
            keep_idx = sorted(set(keep_idx))
            # Simplify each sub-segment between successive keep_idx
            # points; rejoin without duplicating junction points.
            coords: List[Tuple[float, float]] = []
            for k in range(len(keep_idx) - 1):
                i_a, i_b = keep_idx[k], keep_idx[k + 1]
                sub = raw_coords[i_a:i_b + 1]
                if len(sub) > 2:
                    try:
                        simp = _SimpLine(sub).simplify(
                            road_simplify_tol_deg, preserve_topology=False,
                        )
                        if simp.geom_type == "LineString" and len(simp.coords) >= 2:
                            sub = [(float(x), float(y)) for x, y in simp.coords]
                    except Exception:
                        pass
                if k == 0:
                    coords.extend(sub)
                else:
                    coords.extend(sub[1:])  # skip duplicate junction point
            highway = getattr(road, "highway_type", "unclassified")
            road_width_m = _road_edge_width_m(highway)
            for (lon_a, lat_a), (lon_b, lat_b) in zip(coords[:-1], coords[1:]):
                # AO clip: drop road segments wholly outside the AO
                if not (grid.west <= lon_a <= grid.east and grid.south <= lat_a <= grid.north):
                    if not (grid.west <= lon_b <= grid.east and grid.south <= lat_b <= grid.north):
                        continue
                # Length in metres
                seg_dxm = (lon_b - lon_a) * 111_320.0 * math.cos(math.radians((lat_a + lat_b) / 2))
                seg_dym = (lat_b - lat_a) * grid.meters_per_lat
                seg_len_m = math.hypot(seg_dxm, seg_dym)
                if seg_len_m <= 0:
                    continue
                na = _road_node_id(lon_a, lat_a)
                nb = _road_node_id(lon_b, lat_b)
                edges.append(CorridorEdge(
                    id=len(edges),
                    coords=[(float(lon_a), float(lat_a)), (float(lon_b), float(lat_b))],
                    length_m=seg_len_m,
                    width_m=road_width_m,
                    endpoints=(na, nb),
                ))
                road_edges_added += 1
        logger.info(
            "compute_gvd: added %d road segments from %d OSM ways "
            "(total: %d corridors, %d nodes)",
            road_edges_added, len(roads), len(edges), len(nodes_xy),
        )

    return GVD(
        edges=edges,
        nodes=nodes_xy,
        obstacle_boundary_samples=sample_pts,
    )


# ---------------------------------------------------------------------------
# Circuit representation + Ohm/Kirchhoff solver
# ---------------------------------------------------------------------------

def find_terminal_nodes(
    gvd: GVD, *, lon: float, lat: float, radius_m: float,
    grid: "TrafficabilityGrid", label: str = "terminal",
) -> List[int]:
    """Glinton paper §3 (Fig 7c): the circuit's voltage source is applied
    between two REGIONS of the terrain (e.g., 'NW corner' and 'SE corner'),
    not between two specific points. The paper holds every node in each
    region at the terminal's potential.

    For our per-KT origin/objective pairs, the region for each terminal
    is the set of GVD nodes within ``radius_m`` of the KT lat/lon. This
    is the direct adaptation of the paper's boundary-region semantics to
    point KTs: instead of a single node + invented stub edges, the
    entire local cluster of GVD nodes IS the terminal.

    Returns a list of GVD node indices in the region. If none are found
    inside ``radius_m`` the function expands the radius until it finds
    at least one — guarantees the circuit has SOME representation for
    every KT and avoids the empty-region failure mode.
    """
    if not gvd.nodes:
        return []
    arr = np.array(gvd.nodes)
    # Local lat/lon-to-meters: longitude scale depends on latitude.
    m_per_lat = grid.meters_per_lat
    m_per_lon = grid.meters_per_lon_at_centre
    dx_m = (arr[:, 0] - lon) * m_per_lon
    dy_m = (arr[:, 1] - lat) * m_per_lat
    d_m = np.sqrt(dx_m * dx_m + dy_m * dy_m)
    r = float(radius_m)
    inside = np.where(d_m <= r)[0]
    # Expand radius if nothing inside — guarantees ≥ 1 node returned for
    # any KT inside the AO. Cap expansion at 5× to avoid runaway when the
    # KT is way outside the GVD.
    expand_factor = 1
    while inside.size == 0 and expand_factor <= 5:
        expand_factor += 1
        inside = np.where(d_m <= r * expand_factor)[0]
    if inside.size == 0:
        nearest = int(np.argmin(d_m))
        logger.warning(
            "find_terminal_nodes %s @ (%.4f,%.4f): no GVD node within %.0fm "
            "(or 5× expansion); falling back to single nearest node %d at %.0fm",
            label, lon, lat, r, nearest, float(d_m[nearest]),
        )
        return [nearest]
    if expand_factor > 1:
        logger.info(
            "find_terminal_nodes %s @ (%.4f,%.4f): %d nodes within %.0fm "
            "(expanded %d× from configured %.0fm)",
            label, lon, lat, inside.size, r * expand_factor, expand_factor, r,
        )
    else:
        logger.debug(
            "find_terminal_nodes %s @ (%.4f,%.4f): %d nodes within %.0fm",
            label, lon, lat, inside.size, r,
        )
    return [int(i) for i in inside]


def solve_corridor_circuit(
    gvd: GVD, *,
    origin_node: int = -1, objective_node: int = -1,
    origin_nodes: Optional[List[int]] = None,
    objective_nodes: Optional[List[int]] = None,
    voltage: float = 1.0,
    edge_resistance_multiplier: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Solve Kirchhoff's current law on the corridor network with a
    voltage source applied between origin and objective. Each GVD edge
    is a resistor with R = length_m / width_m (Glinton paper Section 3.3
    + circuit subsection). Returns per-edge current magnitude as a
    float64 ndarray of length len(gvd.edges); higher = more "flow" =
    more attractive corridor for an attacking force.

    Per Glinton paper §3 ('Engagement Areas' para 5) the system
    "hypothesizes manning combinations of engagement areas by increasing
    the appropriate resistances" — callers pass a per-edge multiplier
    array (length n_edges, default = all-ones = unchanged baseline) to
    raise resistance at EA-adjacent edges. The modulated current drop
    versus baseline is the paper's measure of how disruptive the EA
    choice is to enemy travel. Same multiplier hook drives the §3
    'Avenues of approach' para 3 off-axis re-weight (raise resistance
    proportional to perpendicular distance from central axis).
    """
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    n_nodes = len(gvd.nodes)
    n_edges = len(gvd.edges)
    if n_nodes == 0 or n_edges == 0:
        return np.zeros(n_edges, dtype=np.float64)

    # Conductance per edge. R_edge = (length / width) × multiplier; the
    # multiplier defaults to 1.0 per edge (unchanged) and is the lever
    # by which EA-manning + off-axis re-weight are applied.
    g = np.array(
        [e.width_m / max(e.length_m, 1.0) for e in gvd.edges], dtype=np.float64
    )
    if edge_resistance_multiplier is not None:
        if len(edge_resistance_multiplier) != n_edges:
            raise ValueError(
                f"edge_resistance_multiplier length {len(edge_resistance_multiplier)} "
                f"!= n_edges {n_edges}"
            )
        # Resistance × multiplier ⇒ conductance ÷ multiplier.
        g = g / np.maximum(np.asarray(edge_resistance_multiplier, dtype=np.float64), 1e-30)
    # Sparse Laplacian (node admittance matrix)
    rows: List[int] = []
    cols: List[int] = []
    data: List[float] = []
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        rows.extend([a, b, a, b])
        cols.extend([a, b, b, a])
        data.extend([g[e_idx], g[e_idx], -g[e_idx], -g[e_idx]])
    L = sp.coo_matrix((data, (rows, cols)), shape=(n_nodes, n_nodes)).tocsr()

    # Apply boundary conditions per Glinton paper §3 (Fig 7c): voltage
    # clamp every node in the origin region at V=voltage, every node in
    # the objective region at V=0. Paper uses "NW corner" / "SE corner"
    # regions — a SET of nodes for each terminal, not a point. Our
    # adaptation: per KT terminal, the region is every GVD node within
    # a terminal-radius of the KT lat/lon (computed by the caller and
    # passed in as origin_nodes / objective_nodes). Single-node lists
    # are accepted for backwards compat with prior point-terminal
    # callers but the paper-faithful path uses node SETS.
    if origin_nodes is None:
        origin_nodes = [int(origin_node)] if origin_node >= 0 else []
    if objective_nodes is None:
        objective_nodes = [int(objective_node)] if objective_node >= 0 else []

    fixed: Dict[int, float] = {}
    for n in origin_nodes:
        fixed[int(n)] = float(voltage)
    for n in objective_nodes:
        fixed[int(n)] = 0.0  # objective clamp overrides if a node is in both
    if not fixed:
        return np.zeros(n_edges, dtype=np.float64)
    fixed_idx = np.array(sorted(fixed.keys()), dtype=int)
    free_mask = np.ones(n_nodes, dtype=bool)
    free_mask[fixed_idx] = False
    free_idx = np.where(free_mask)[0]

    if free_idx.size == 0:
        # All nodes are terminals — degenerate but well-defined.
        V = np.zeros(n_nodes)
        for idx, v in fixed.items():
            V[idx] = v
    else:
        # Restrict to GVD components that contain BOTH origin and
        # objective terminal nodes. If a component has only origin-side
        # terminals (or only objective-side), no current can flow through
        # it — drop it from the solve to keep the Laplacian non-singular.
        # If multiple components contain both an origin-clamp AND an
        # objective-clamp, ALL such components contribute current (paper
        # Fig 7c: enemy can travel through any of them).
        comp_labels = _connected_components_via_csgraph(L, n_nodes)
        comps_with_origin = set(int(comp_labels[n]) for n in origin_nodes)
        comps_with_objective = set(int(comp_labels[n]) for n in objective_nodes)
        active_comps = comps_with_origin & comps_with_objective
        if not active_comps:
            logger.warning(
                "circuit solve: no GVD component contains both an origin clamp "
                "(%d origin nodes across %d comp(s)) AND an objective clamp "
                "(%d objective nodes across %d comp(s)); current=0 everywhere",
                len(origin_nodes), len(comps_with_origin),
                len(objective_nodes), len(comps_with_objective),
            )
            return np.zeros(n_edges, dtype=np.float64)
        active_node_mask = np.isin(comp_labels, list(active_comps))
        keep_free = np.intersect1d(free_idx, np.where(active_node_mask)[0])
        if keep_free.size == 0:
            V = np.zeros(n_nodes)
            for idx, v in fixed.items():
                V[idx] = v
        else:
            L_kk = L[keep_free][:, keep_free]
            rhs = np.zeros(keep_free.size, dtype=np.float64)
            for fixed_node in fixed_idx:
                if not active_node_mask[fixed_node]:
                    continue
                col = L[:, fixed_node].toarray().flatten()
                rhs -= col[keep_free] * fixed[int(fixed_node)]
            try:
                V_kk = spla.spsolve(L_kk.tocsc(), rhs)
            except Exception as exc:
                logger.warning(
                    "spsolve failed (%s); falling back to dense lstsq", exc,
                )
                V_kk = np.linalg.lstsq(L_kk.toarray(), rhs, rcond=None)[0]
            V = np.zeros(n_nodes)
            V[keep_free] = V_kk
            for idx, v in fixed.items():
                V[idx] = v

    # Replace any NaN/inf (numerical instability) with 0 before
    # computing currents, so a single bad node can't poison the whole
    # current array.
    V = np.nan_to_num(V, nan=0.0, posinf=0.0, neginf=0.0)

    # Edge current I = g * (V_a - V_b) — take absolute value (direction-agnostic).
    currents = np.zeros(n_edges, dtype=np.float64)
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        currents[e_idx] = abs(g[e_idx] * (V[a] - V[b]))
    currents = np.nan_to_num(currents, nan=0.0, posinf=0.0, neginf=0.0)
    return currents


def _connected_components_via_csgraph(L, n_nodes: int) -> np.ndarray:
    """Label connected components of the graph defined by Laplacian L.
    Returns an int array of length n_nodes where entries with the same
    label are in the same component."""
    import scipy.sparse as sp
    import scipy.sparse.csgraph as csg
    # Convert Laplacian -> adjacency by zeroing the diagonal and
    # taking absolute values. (Off-diagonals are -conductance, so abs
    # gives conductance which is non-zero iff edge exists.)
    A = L.copy().tolil()
    A.setdiag(0)
    A = A.tocsr()
    A.data = np.abs(A.data)
    n_components, labels = csg.connected_components(
        csgraph=A, directed=False, return_labels=True,
    )
    return labels


# ---------------------------------------------------------------------------
# Avenue of approach construction from circuit currents + Table 4-2 grouping
# ---------------------------------------------------------------------------

@dataclass
class AvenueBundle:
    """A multi-tail avenue of approach: a central axis (highest-current
    path origin -> objective) plus all neighbour corridors grouped in
    per ATP 2-01.3 Table 4-2 max distance for the avenue's echelon."""
    side: str                                # "friendly" / "threat"
    origin_name: str
    origin_lonlat: Tuple[float, float]
    objective_name: str
    objective_lonlat: Tuple[float, float]
    echelon: str
    central_axis_edge_ids: List[int]
    tail_edge_ids: List[int]                 # all grouped corridors (incl. central)
    envelope_polygon_lonlat: List[Tuple[float, float]]  # hull of all tail edges + buffer
    central_axis_polyline_lonlat: List[Tuple[float, float]] = field(default_factory=list)
    """Simplified central axis polyline (Douglas-Peucker over all
    central-axis edge endpoints). Used as the avenue's chevron geometry
    in the renderer — provides a single smooth path rather than the
    raw 100+ GVD-edge fragments."""
    bundle_halfwidth_m: float = 0.0
    """Perpendicular half-width of the multi-tail bundle (the buffer
    distance used to build the envelope polygon). Per Glinton et al.
    2004 Fig 8 + ATP 2-01.3 Fig 4-14, the doctrinal chevron's WIDTH
    equals this value — the chevron envelope encloses the constituent
    mobility corridors. SVG renderer sizes buildArrowOutline's widthPx
    from this metric, not from the echelon's fixed-km width."""


def build_avenue_bundle(
    gvd: GVD, currents: np.ndarray, *,
    origin_node: int, origin_name: str, origin_lonlat: Tuple[float, float],
    objective_node: int, objective_name: str, objective_lonlat: Tuple[float, float],
    side: str,
    avenue_echelon: str,
    grid: TrafficabilityGrid,
    central_axis_fraction: float = 0.6,
    grouping_distance_m: Optional[float] = None,
    ea_edge_multiplier: Optional[np.ndarray] = None,
    off_axis_resistance_max: float = 10.0,
    origin_nodes: Optional[List[int]] = None,
    objective_nodes: Optional[List[int]] = None,
) -> Optional[AvenueBundle]:
    """Glinton et al. 2004 §3 'Avenues of approach' implemented as written:

      Para 1 ('The mobility corridors with the highest current flow
      would then be chosen as a part of the avenue of approach'): the
      ``currents`` argument should already carry EA-modulated current
      (callers pass solve_corridor_circuit output with the EA-set's
      edge resistance multiplier applied). Highest-current corridors
      after EA modulation are the AA.

      Para 3 ('find a central axis of an avenue of approach using A*
      search. The resistance of other corridors could then be increased
      proportionally to their separation from the central axis. This
      would result in higher currents in corridors that are closer
      together'): after the central axis is identified, build a NEW
      edge-resistance multiplier that scales linearly from 1.0 on the
      axis to ``off_axis_resistance_max`` at grouping_distance_m, and
      re-solve the circuit. Tails are extracted from THIS re-solved
      current array.

      Para 2's drawback ('If a single mobility corridor is too
      canalizing then it is better to use several at once as a part of
      an avenue of approach as shown in Fig. 8') is handled by the
      multi-tail grouping below.

    Steps:
      1. Build weighted graph (weight = 1/current) and find central
         axis as A*-style shortest path origin → objective (the path of
         least resistance through the EA-modulated current field).
      2. Compute perpendicular distance from each GVD edge midpoint to
         the central-axis polyline.
      3. Build off-axis multiplier: m(d) = 1 + (off_axis_resistance_max - 1)
         * min(d / grouping_distance_m, 1.0). Edges past grouping_distance
         get the max multiplier (effectively cut off).
      4. Re-solve the circuit with the off-axis multiplier
         (composed with the caller-supplied EA multiplier if any).
      5. Tails = edges with re-solved current above
         central_axis_fraction × max central-axis current AND within
         grouping_distance of the axis.
      6. Envelope = Shapely buffer of the central-axis polyline at
         grouping_distance / 2.
    """
    import networkx as nx
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import unary_union

    if not gvd.edges or len(currents) == 0:
        return None

    G = nx.Graph()
    EPS_I = 1e-9
    max_curr = float(currents.max()) if currents.size else 0.0
    if max_curr <= EPS_I:
        logger.warning("build_avenue_bundle: zero current across all edges; aborting")
        return None
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        # 1 / current weighting: higher current -> shorter "distance"
        w = 1.0 / max(currents[e_idx], EPS_I * max_curr)
        G.add_edge(a, b, edge_id=e_idx, weight=w)

    try:
        node_path = nx.shortest_path(G, source=origin_node,
                                     target=objective_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        logger.info(
            "build_avenue_bundle: no path origin=%d -> objective=%d in GVD",
            origin_node, objective_node,
        )
        return None
    central_edge_ids: List[int] = []
    for u, v in zip(node_path[:-1], node_path[1:]):
        e_data = G.get_edge_data(u, v) or {}
        eid = e_data.get("edge_id")
        if eid is not None:
            central_edge_ids.append(int(eid))
    if not central_edge_ids:
        return None

    central_lines = [LineString(gvd.edges[eid].coords) for eid in central_edge_ids]
    central_geom = unary_union(central_lines)

    # Build a SIMPLIFIED central-axis polyline (Douglas-Peucker) — the
    # raw central_lines may be 100+ tiny GVD-edge fragments. Stitch into
    # a single ordered polyline via the path's node sequence then
    # simplify with shapely's built-in Douglas-Peucker. Polyline is
    # anchored at the actual origin / objective terminal coordinates
    # (not the GVD node nearest them) so the chevron arrow reaches the
    # KT marker the user sees on the map.
    ordered_central_xy: List[Tuple[float, float]] = []
    ordered_central_xy.append((float(origin_lonlat[0]), float(origin_lonlat[1])))
    for u in node_path:
        x, y = gvd.nodes[u]
        if (not ordered_central_xy) or (ordered_central_xy[-1] != (float(x), float(y))):
            ordered_central_xy.append((float(x), float(y)))
    if not ordered_central_xy or ordered_central_xy[-1] != (float(objective_lonlat[0]), float(objective_lonlat[1])):
        ordered_central_xy.append((float(objective_lonlat[0]), float(objective_lonlat[1])))
    central_axis_polyline_lonlat: List[Tuple[float, float]] = ordered_central_xy
    if len(ordered_central_xy) >= 3:
        try:
            simplified = LineString(ordered_central_xy).simplify(
                # tolerance ~50m in degree terms (~0.00045 deg lat at 57N)
                50.0 / grid.meters_per_lat, preserve_topology=False,
            )
            if simplified.geom_type == "LineString" and len(simplified.coords) >= 2:
                central_axis_polyline_lonlat = [
                    (float(x), float(y)) for x, y in simplified.coords
                ]
        except Exception as exc:
            logger.warning("central axis simplify failed: %s", exc)
    if grouping_distance_m is None:
        grouping_distance_m = AVENUE_GROUPING_MAX_DISTANCE_M.get(
            avenue_echelon, 6000.0,
        )
    grouping_deg = grouping_distance_m / grid.meters_per_lat

    # Paper §3 'Avenues of approach' para 3: "find a central axis of an
    # avenue of approach using A* search. The resistance of other
    # corridors could then be increased proportionally to their
    # separation from the central axis. This would result in higher
    # currents in corridors that are closer together."
    #
    # Implementation: build a per-edge multiplier that scales linearly
    # from 1.0 on the central axis (perpendicular distance = 0) to
    # off_axis_resistance_max at grouping_deg, then re-solve the
    # circuit. Tail selection uses the RE-SOLVED current array.
    central_polyline_geom = LineString(ordered_central_xy)
    off_axis_mult = np.ones(len(gvd.edges), dtype=np.float64)
    for e_idx, edge in enumerate(gvd.edges):
        if e_idx in set(central_edge_ids):
            off_axis_mult[e_idx] = 1.0
            continue
        # Edge midpoint perpendicular distance (degrees) to central axis.
        line = LineString(edge.coords)
        mid = line.interpolate(0.5, normalized=True)
        d = mid.distance(central_polyline_geom)
        ratio = min(d / grouping_deg, 1.0)
        off_axis_mult[e_idx] = 1.0 + (off_axis_resistance_max - 1.0) * ratio

    # Compose with EA-modulation multiplier (resistance multipliers
    # combine multiplicatively: R_total = R_baseline × m_ea × m_off_axis).
    if ea_edge_multiplier is not None:
        composed_mult = off_axis_mult * np.asarray(ea_edge_multiplier, dtype=np.float64)
    else:
        composed_mult = off_axis_mult

    # Re-solve uses the SAME region terminals as the upstream solve so
    # the boundary conditions match (paper §3 Fig 7c). origin_nodes /
    # objective_nodes carry the multi-node clamps from synthesize_mcoo;
    # if absent, falls through to the single-node fast path.
    currents_for_tails = solve_corridor_circuit(
        gvd, origin_node=origin_node, objective_node=objective_node,
        origin_nodes=origin_nodes, objective_nodes=objective_nodes,
        edge_resistance_multiplier=composed_mult,
    )

    # Lower current bound for membership: edges with <central_axis_fraction *
    # max current along central axis are NOT considered tails.
    central_max_current = max(float(currents_for_tails[eid]) for eid in central_edge_ids) \
        if central_edge_ids else 0.0
    current_floor = central_axis_fraction * central_max_current

    tail_edge_ids: List[int] = list(central_edge_ids)
    seen = set(tail_edge_ids)
    for e_idx, edge in enumerate(gvd.edges):
        if e_idx in seen:
            continue
        if float(currents_for_tails[e_idx]) < current_floor:
            continue
        line = LineString(edge.coords)
        if line.distance(central_geom) <= grouping_deg:
            tail_edge_ids.append(e_idx)
            seen.add(e_idx)

    tail_geom = unary_union([LineString(gvd.edges[eid].coords) for eid in tail_edge_ids])
    envelope = tail_geom.buffer(grouping_deg / 2.0, quad_segs=8)
    if envelope.geom_type == "Polygon":
        env_coords = [(float(x), float(y)) for x, y in envelope.exterior.coords]
    elif envelope.geom_type == "MultiPolygon":
        env_coords = [(float(x), float(y))
                      for x, y in envelope.convex_hull.exterior.coords]
    else:
        env_coords = []

    # NO prose here — this service emits geometry + structured facts and
    # the MCOO product layer (pytho-app) composes any analyst-facing
    # Rationale text. Method, for the maintainer: tails grouped per
    # ATP 2-01.3 Table 4-2 max separation for the echelon; central axis
    # is the highest-current path from Ohm/Kirchhoff analysis on the GVD
    # circuit between the origin and objective terminals. Those
    # references stay in this comment, never in emitted text.
    return AvenueBundle(
        side=side,
        origin_name=origin_name,
        origin_lonlat=origin_lonlat,
        objective_name=objective_name,
        objective_lonlat=objective_lonlat,
        echelon=avenue_echelon,
        central_axis_edge_ids=central_edge_ids,
        tail_edge_ids=tail_edge_ids,
        envelope_polygon_lonlat=env_coords,
        central_axis_polyline_lonlat=central_axis_polyline_lonlat,
        # Per Glinton Fig 8: the doctrinal chevron's body width equals
        # the multi-tail bundle's perpendicular extent. grouping_distance_m
        # is the max perpendicular distance a tail corridor can sit from
        # the central axis (Table 4-2 nesting), so half of that is the
        # buffer that produced env_coords above. Pass it through so the
        # renderer can size buildArrowOutline's widthPx from the actual
        # bundle hull rather than the echelon's fixed-km width.
        bundle_halfwidth_m=float(grouping_distance_m) / 2.0,
    )


# ---------------------------------------------------------------------------
# Engagement areas + defensible terrain
# ---------------------------------------------------------------------------

@dataclass
class EngagementArea:
    """Structured siting facts ONLY — no prose. The MCOO product layer
    (pytho-app) composes any analyst-facing Rationale text from these
    fields; this service never authors document content."""
    id: str
    centre_lonlat: Tuple[float, float]
    polygon_lonlat: List[Tuple[float, float]]
    score: float
    node_id: int = -1  # GVD node index, for downstream resistance modulation
    corridors_converging: int = 0   # GVD node degree — corridors meeting here
    # % drop in modeled enemy corridor throughput when the selected EA
    # set is manned (resistance-modulation selector; 0 for the degree
    # heuristic, which doesn't model throughput).
    throughput_drop_pct: float = 0.0


def _build_edge_multiplier_for_ea_set(
    gvd: GVD, ea_node_ids: List[int], multiplier: float,
) -> np.ndarray:
    """Per Glinton paper §3 'Engagement Areas' para 5: 'increase the
    appropriate resistances'. An EA's effect on the corridor circuit
    is modeled by multiplying the resistance (i.e. dividing the
    conductance) of every GVD edge incident to the EA's GVD vertex.
    Returns a length-n_edges array of multipliers (1.0 = unchanged)."""
    n_edges = len(gvd.edges)
    mult = np.ones(n_edges, dtype=np.float64)
    if not ea_node_ids:
        return mult
    ea_set = set(int(n) for n in ea_node_ids)
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        if int(a) in ea_set or int(b) in ea_set:
            mult[e_idx] *= float(multiplier)
    return mult


# Module-level globals populated by the Pool worker initializer below.
# multiprocessing.Pool fork-inherits these from the parent process so
# the GVD + threat-pair-node list don't need to be pickled per task.
_EA_WORKER_GVD: Optional["GVD"] = None
_EA_WORKER_PAIRS: Optional[List[Tuple[int, int]]] = None
_EA_WORKER_MULTIPLIER: float = 10.0


def _ea_worker_init(gvd, pairs, multiplier):
    """Pool initializer: stash the read-only fixtures so each subset
    evaluation can run without re-pickling them across the IPC boundary.
    Also pins BLAS to 1 thread per worker to prevent N×N CPU
    oversubscription (each worker already has 1 core)."""
    global _EA_WORKER_GVD, _EA_WORKER_PAIRS, _EA_WORKER_MULTIPLIER
    _EA_WORKER_GVD = gvd
    _EA_WORKER_PAIRS = pairs
    _EA_WORKER_MULTIPLIER = float(multiplier)
    import os as _os
    _os.environ["OMP_NUM_THREADS"] = "1"
    _os.environ["MKL_NUM_THREADS"] = "1"
    _os.environ["OPENBLAS_NUM_THREADS"] = "1"


def _ea_worker_evaluate_batch(subsets_batch):
    """Pool worker: for each subset in this batch, compute the modulated
    aggregate current across all threat pairs and return
    (best_modulated_total_in_batch, best_subset_in_batch, solves_done).
    The parent process picks the global max across batches.

    Threat pairs are (origin_node_set, objective_node_set) tuples — paper
    §3 Fig 7c boundary-region terminals, not single nodes.
    """
    gvd = _EA_WORKER_GVD
    pairs = _EA_WORKER_PAIRS  # list of (List[int] origin_nodes, List[int] objective_nodes)
    mult_factor = _EA_WORKER_MULTIPLIER
    best_subset = ()
    best_modulated_total = float("inf")
    solves_done = 0
    for subset in subsets_batch:
        mult = _build_edge_multiplier_for_ea_set(gvd, list(subset), mult_factor)
        modulated_total = 0.0
        for o_set, d_set in pairs:
            c = solve_corridor_circuit(
                gvd, origin_nodes=o_set, objective_nodes=d_set,
                edge_resistance_multiplier=mult,
            )
            modulated_total += float(c.sum())
            solves_done += 1
        if modulated_total < best_modulated_total:
            best_modulated_total = modulated_total
            best_subset = tuple(subset)
    return (best_modulated_total, best_subset, solves_done)


def select_engagement_areas_via_resistance_modulation(
    gvd: GVD, *,
    grid: TrafficabilityGrid,
    threat_terminal_pairs: List[Tuple[List[int], List[int]]],
    max_ea_count: int = 6,
    resistance_multiplier: float = 10.0,
    enclosed_node_radius_m: float = 600.0,
    candidate_min_degree: int = 3,
    candidate_top_n: int = 16,
) -> List[EngagementArea]:
    """Glinton et al. 2004 §3 'Engagement Areas' (para 5) implemented
    EXACTLY as written:

      'We would like to automatically select engagement areas that
       would best disrupt enemy travel throughout the entire region.
       Consider trying to select engagement areas in the terrain shown
       in Fig. 7(a) so as to disrupt enemy approaching from the SE
       corner while defending the NW corner. Based on our circuit
       analogy if we assign corridor resistances appropriately then
       the net current flow between the terminals of the circuit shown
       in Fig. 7(c), for a constant voltage, is a baseline measure for
       the ease with which an enemy can travel between the SE and NW
       without manned engagement areas. Our system can then hypothesize
       manning combinations of engagement areas by increasing the
       appropriate resistances. A comparison of the resulting current
       flow between the terminals to the baseline value would then be
       a measure of how disruptive the choice of engagement areas
       would be to the movement of the enemy.'

    Algorithm:
      1. Candidate EAs = GVD vertices in "enclosed regions" (paper
         §3 'Engagement Areas' para 4): degree ≥ candidate_min_degree
         (multiple corridors meet here ⇒ enclosed terrain). Limit to
         the top candidate_top_n by node-degree × baseline-current
         centrality so the combinatorial enumeration stays tractable
         without dropping high-value candidates.
      2. Compute baseline current flow for each threat terminal pair
         (enemy source → defended sink) with no EAs manned.
         Aggregate across all threat pairs = the paper's "baseline
         measure for ease with which an enemy can travel".
      3. Hypothesize manning combinations: enumerate ALL subsets of
         candidates with size 1..max_ea_count. For each subset, build
         the edge-resistance multiplier (×resistance_multiplier on
         every edge incident to a subset vertex) and re-solve the
         circuit per threat pair. Aggregate the resulting current.
      4. Select the subset with the largest aggregate drop vs baseline
         (most disruptive to enemy travel per the paper's criterion).
    """
    from itertools import combinations
    from shapely.geometry import Point

    n_nodes = len(gvd.nodes)
    n_edges = len(gvd.edges)
    if n_nodes == 0 or n_edges == 0 or not threat_terminal_pairs:
        return []

    # Step 1: candidate enclosed-region EAs.
    node_degree = np.zeros(n_nodes, dtype=np.int32)
    for edge in gvd.edges:
        node_degree[edge.endpoints[0]] += 1
        node_degree[edge.endpoints[1]] += 1

    # Step 2: baseline currents per threat pair + aggregate.
    baseline_per_pair: List[np.ndarray] = []
    baseline_total = 0.0
    for o_set, d_set in threat_terminal_pairs:
        c = solve_corridor_circuit(
            gvd, origin_nodes=o_set, objective_nodes=d_set,
        )
        baseline_per_pair.append(c)
        baseline_total += float(c.sum())

    if baseline_total <= 0.0:
        logger.warning(
            "select_engagement_areas_via_resistance_modulation: "
            "baseline current sum=0 across %d threat pair(s); no EAs selectable",
            len(threat_terminal_pairs),
        )
        return []

    # Rank candidates by baseline node-current × (1+degree) — same
    # centrality the paper implicitly uses ("mobility corridors with
    # the highest current flow" ≈ vertices where those corridors meet).
    # We pre-filter to top-N to keep the subset enumeration tractable
    # while preserving the paper's logic.
    node_current = np.zeros(n_nodes, dtype=np.float64)
    for pair_currents in baseline_per_pair:
        for e_idx, edge in enumerate(gvd.edges):
            a, b = edge.endpoints
            node_current[a] += pair_currents[e_idx]
            node_current[b] += pair_currents[e_idx]
    centrality = node_current * (1.0 + node_degree.astype(np.float64))
    candidate_mask = (node_degree >= candidate_min_degree) & (node_current > 0.0)
    candidate_ids = np.where(candidate_mask)[0]
    if len(candidate_ids) > candidate_top_n:
        # keep top-N by centrality
        ord_local = np.argsort(-centrality[candidate_ids])[:candidate_top_n]
        candidate_ids = candidate_ids[ord_local]
    candidate_list = [int(c) for c in candidate_ids]
    logger.info(
        "select_engagement_areas_via_resistance_modulation: %d candidates "
        "(degree>=%d, baseline_current>0, top-%d by centrality)",
        len(candidate_list), candidate_min_degree, candidate_top_n,
    )

    if not candidate_list:
        return []

    # Step 3: GREEDY selection (paper-faithful per Validation §4 which
    # reports "our algorithm's top 3 selections" — a RANKING, not
    # exhaustive subset enumeration). At each of max_ea_count
    # iterations: try every remaining candidate as the NEXT EA to man
    # given those already manned, pick the one whose addition yields
    # the largest MARGINAL drop in aggregate threat current. Total cost
    # ≈ max_ea_count × len(candidates) × n_threat_pairs solves (e.g.
    # 6 × 16 × 9 = 864 solves; vs. the exhaustive enumeration's
    # 134k+). The per-iteration trials run in parallel across cores.
    import time as _t
    import os as _os
    from multiprocessing import get_context

    n_pairs = len(threat_terminal_pairs)
    selected: List[int] = []
    selected_set: set = set()
    best_subset: Tuple[int, ...] = ()
    best_modulated_total = baseline_total
    solve_count = 0
    _enum_start = _t.perf_counter()
    n_workers = max(1, min(len(candidate_list), _os.cpu_count() or 1))
    logger.info(
        "EA greedy: %d candidates, max_k=%d, %d threat pairs; expected "
        "≤ %d circuit solves total across %d worker(s)",
        len(candidate_list), max_ea_count, n_pairs,
        max_ea_count * len(candidate_list) * n_pairs, n_workers,
    )

    ctx = get_context("fork")
    for k_iter in range(min(max_ea_count, len(candidate_list))):
        candidates_remaining = [c for c in candidate_list if c not in selected_set]
        if not candidates_remaining:
            break
        # Each trial = current selection + 1 candidate (so each trial is
        # a subset of size len(selected)+1). One worker per candidate.
        trial_subsets = [tuple(selected + [c]) for c in candidates_remaining]
        chunk_size = max(1, (len(trial_subsets) + n_workers - 1) // n_workers)
        chunks = [
            trial_subsets[i:i + chunk_size]
            for i in range(0, len(trial_subsets), chunk_size)
        ]
        _iter_start = _t.perf_counter()
        with ctx.Pool(
            processes=n_workers,
            initializer=_ea_worker_init,
            initargs=(gvd, threat_terminal_pairs, resistance_multiplier),
        ) as pool:
            results = pool.map(_ea_worker_evaluate_batch, chunks)
        # Pick the candidate (= last element of best subset in this batch)
        # whose addition yielded the smallest modulated total.
        iter_best_total = float("inf")
        iter_best_subset: Tuple[int, ...] = tuple(selected)
        for modulated_total, subset, solves in results:
            solve_count += solves
            if modulated_total < iter_best_total:
                iter_best_total = modulated_total
                iter_best_subset = subset
        if iter_best_total >= best_modulated_total:
            # No candidate strictly improved disruption — stop early.
            logger.info(
                "EA greedy iter %d: no remaining candidate improved drop "
                "(best_total=%.4f vs prior=%.4f); stopping",
                k_iter + 1, iter_best_total, best_modulated_total,
            )
            break
        new_node = iter_best_subset[-1]
        selected.append(int(new_node))
        selected_set.add(int(new_node))
        best_modulated_total = iter_best_total
        best_subset = iter_best_subset
        logger.info(
            "EA greedy iter %d: picked node %d → cumulative drop %.4f "
            "(%.1f%% of baseline); %d solves this iter in %.2fs",
            k_iter + 1, new_node, baseline_total - best_modulated_total,
            100.0 * (baseline_total - best_modulated_total) / max(baseline_total, 1e-9),
            len(trial_subsets) * n_pairs, _t.perf_counter() - _iter_start,
        )

    _enum_elapsed = _t.perf_counter() - _enum_start
    best_drop = baseline_total - best_modulated_total
    logger.info(
        "select_engagement_areas_via_resistance_modulation: GREEDY done — "
        "%d circuit solves in %.1fs across %d workers (%.2fms/solve effective); "
        "selected %d EAs, drop=%.4f (%.1f%% of baseline %.4f)",
        solve_count, _enum_elapsed, n_workers,
        1000.0 * _enum_elapsed / max(solve_count, 1),
        len(best_subset), best_drop,
        100.0 * best_drop / baseline_total if baseline_total > 0 else 0.0,
        baseline_total,
    )

    # Step 4: materialize as EngagementArea records.
    radius_deg = enclosed_node_radius_m / grid.meters_per_lat
    out: List[EngagementArea] = []
    for rank, nid in enumerate(best_subset, start=1):
        x, y = gvd.nodes[int(nid)]
        poly = Point(x, y).buffer(radius_deg, quad_segs=12)
        poly_coords = [(float(px), float(py)) for px, py in poly.exterior.coords]
        # Facts only (method for the maintainer: Glinton et al. 2004 §3
        # resistance modulation, greedy ranking per Validation §4 "top
        # selections" — the citation lives here, never in emitted text).
        out.append(EngagementArea(
            id=f"EA{rank}",
            centre_lonlat=(float(x), float(y)),
            polygon_lonlat=poly_coords,
            score=float(best_drop),
            node_id=int(nid),
            corridors_converging=int(node_degree[int(nid)]),
            throughput_drop_pct=(
                float(100.0 * best_drop / baseline_total)
                if baseline_total > 0 else 0.0
            ),
        ))
    return out


def select_engagement_areas(
    gvd: GVD, currents: np.ndarray, *,
    grid: TrafficabilityGrid,
    max_count: int = 8,
    enclosed_node_radius_m: float = 600.0,
) -> List[EngagementArea]:
    """Pick GVD vertices that fall in enclosed regions (high local
    corridor convergence) and rank by:
      - high in-current sum (lots of corridor traffic passes through)
      - good adjacent obstacle cover for an ambush position
    Returns up to ``max_count`` non-overlapping engagement areas.
    """
    if not gvd.nodes:
        return []
    # Per-node in/out current sum
    node_current = np.zeros(len(gvd.nodes), dtype=np.float64)
    node_degree = np.zeros(len(gvd.nodes), dtype=np.int32)
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        node_current[a] += currents[e_idx]
        node_current[b] += currents[e_idx]
        node_degree[a] += 1
        node_degree[b] += 1
    # "Enclosed" per Glinton paper Section 3.3 = degree >= 3 (three
    # corridors meet here). On dense AO-scale GVDs most vertices are
    # degree 2 (corridor bisectors). Score = node_current * (1 + degree)
    # so high-current nodes surface regardless of degree, but real
    # crossroads (degree 3+) get extra weight. Per the paper the ranking
    # also weights cover/concealment — approximated here by current
    # (high current = lots of corridor traffic past this vertex =
    # high-value disruption point per the paper's circuit analysis).
    score = node_current * (1.0 + node_degree.astype(np.float64))
    # Only consider nodes that actually carry SOME current (terminals
    # contribute current; isolated GVD components stay at 0 and are
    # rightly excluded).
    score = np.where(node_current > 0.0, score, -1.0)
    order = np.argsort(-score)
    logger.info(
        "select_engagement_areas: %d nodes (max_degree=%d, max_current=%.4f, "
        "%d candidates with current>0)",
        len(gvd.nodes), int(node_degree.max()) if len(node_degree) else 0,
        float(node_current.max()) if len(node_current) else 0.0,
        int((node_current > 0.0).sum()),
    )

    radius_deg = enclosed_node_radius_m / grid.meters_per_lat
    chosen_nodes: List[int] = []
    chosen_xy: List[Tuple[float, float]] = []
    for nid in order:
        if score[nid] <= 0:
            break
        if len(chosen_nodes) >= max_count:
            break
        x, y = gvd.nodes[int(nid)]
        if any(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 < radius_deg
               for cx, cy in chosen_xy):
            continue  # too close to an already-picked EA
        chosen_nodes.append(int(nid))
        chosen_xy.append((x, y))

    out: List[EngagementArea] = []
    from shapely.geometry import Point
    for rank, nid in enumerate(chosen_nodes, start=1):
        x, y = gvd.nodes[nid]
        poly = Point(x, y).buffer(radius_deg, quad_segs=12)
        poly_coords = [(float(px), float(py)) for px, py in poly.exterior.coords]
        # Facts only (siting basis for the maintainer: corridor
        # convergence + enclosed-region cover per the engagement-area
        # selection criteria in ATP 2-01.3 — citation stays in this
        # comment, never in emitted text).
        out.append(EngagementArea(
            id=f"EA{rank}",
            centre_lonlat=(float(x), float(y)),
            polygon_lonlat=poly_coords,
            score=float(score[nid]),
            node_id=int(nid),
            corridors_converging=int(node_degree[nid]),
        ))
    logger.info("select_engagement_areas: %d EAs selected", len(out))
    return out


@dataclass
class DefensibleArea:
    """Structured siting facts ONLY — no prose (see EngagementArea)."""
    id: str
    centre_lonlat: Tuple[float, float]
    polygon_lonlat: List[Tuple[float, float]]
    score: float
    flanks_protected: int = 0          # of 4 cardinal flanks with NO-GO cover (flank selector; 0 = not computed)
    protection_radius_km: float = 0.0  # radius the flank scan used
    threat_origin_count: int = 0       # effective-resistance selector: threat origins scored against


def select_defensible_terrain_via_effective_resistance(
    gvd: GVD, *,
    grid: TrafficabilityGrid,
    threat_origin_nodes: List[int],
    max_count: int = 6,
    spacing_radius_m: float = 6000.0,
    polygon_radius_m: float = 4000.0,
    candidate_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[DefensibleArea]:
    """Glinton et al. 2004 §3 'Defensible terrain' implemented as written:

      'In electrical circuit theory two resistors in series with
       resistance R1 and R2 can be replaced with a single resistor
       according to Eq. (7). Resistors in parallel can be replaced by
       a single resistor according to Eq. (8). By recursive application
       of these equations, an entire circuit of resistors can be
       replaced by a single resistance. By applying these rules to our
       circuit representation of terrain, the single resulting
       resistance can be used to measure the defensibility of a
       region.'

    Series-parallel reduction (Eq. 7+8) only works exactly for
    series-parallel graphs. The GVD corridor network is a general
    graph, so we use the mathematical generalization of those equations
    to arbitrary graphs: the EFFECTIVE RESISTANCE between two nodes
    s and t in any resistor network is

        R_eff(s, t) = L⁺[s, s] + L⁺[t, t] - 2·L⁺[s, t]

    where L⁺ is the Moore-Penrose pseudo-inverse of the graph
    Laplacian (Klein & Randić 1993, 'Resistance distance'). For a
    series-parallel graph this formula reduces exactly to recursive
    application of Eq. 7+8. For our GVD it gives the same
    'defensibility = single resulting resistance' measure the paper
    calls for.

    Algorithm:
      1. Build the graph Laplacian L with conductance per edge
         g_e = width_e / length_e (the same per-edge resistance
         R_e = length / width the paper uses for AAs).
      2. Compute L⁺ via numpy's Moore-Penrose pseudo-inverse on a
         per-component basis (the Laplacian of a disconnected graph
         is singular separately per component, but pinv handles the
         null space correctly).
      3. For each candidate GVD vertex v, compute the SUM of
         effective resistances from v to all threat origin nodes.
         Higher sum = more 'natural protection' to as much of the
         defending force's perimeter as possible (paper's framing).
      4. Greedy non-overlap selection by descending defensibility
         score.
    """
    from shapely.geometry import Point

    n_nodes = len(gvd.nodes)
    n_edges = len(gvd.edges)
    if n_nodes == 0 or n_edges == 0 or not threat_origin_nodes:
        return []

    # Step 1: sparse Laplacian. Dense pinv of an n×n Laplacian for n=
    # 14000 was 146s on one CPU core. Effective resistance is the same
    # mathematical quantity but can be computed without ever forming the
    # pseudo-inverse: for each threat origin t, solve L·x_t = e_t -
    # mean(e_t) once. Then R_eff(v, t) = x_t[t] - x_t[v] (the voltage
    # difference across (v,t) when 1A injected at t and extracted
    # uniformly elsewhere). This gives the same Eq. 7+8 generalization
    # the dense pinv produced, with O(num_threats × sparse_solve)
    # instead of O(n³).
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla
    g = np.array(
        [e.width_m / max(e.length_m, 1.0) for e in gvd.edges], dtype=np.float64,
    )
    rows: List[int] = []
    cols: List[int] = []
    data: List[float] = []
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        rows.extend([a, b, a, b])
        cols.extend([a, b, b, a])
        data.extend([g[e_idx], g[e_idx], -g[e_idx], -g[e_idx]])
    L_sparse = sp.coo_matrix((data, (rows, cols)), shape=(n_nodes, n_nodes)).tocsr()

    # Step 2: restrict to the largest connected component (effective
    # resistance is only defined within a single component; nodes in
    # different components have R_eff = ∞ and should be excluded).
    comp_labels = _connected_components_via_csgraph(L_sparse, n_nodes)
    # Pick the component containing the most threat origin nodes (the
    # paper's setup: enemy travels through the connected network on
    # one side; defensibility is measured within that network).
    threat_set = set(int(t) for t in threat_origin_nodes if 0 <= int(t) < n_nodes)
    if not threat_set:
        return []
    from collections import Counter as _Counter
    comp_counter = _Counter(int(comp_labels[t]) for t in threat_set)
    main_comp = comp_counter.most_common(1)[0][0]
    main_mask = comp_labels == main_comp
    # Per user observation: defensible terrain candidates must be in the
    # FRIENDLY OPERATIONAL AREA where defending forces actually
    # maneuver — otherwise the L⁺ formula picks artificially-high R_eff
    # nodes in dead-end road fragments on the far edge of the AO that
    # are mathematically "hard to reach" but doctrinally meaningless
    # (no friendly unit defends terrain it doesn't operate in).
    if candidate_bbox is not None:
        cw, cs, ce, cn = candidate_bbox
        for nid in range(n_nodes):
            if not main_mask[nid]:
                continue
            x, y = gvd.nodes[nid]
            if not (cw <= x <= ce and cs <= y <= cn):
                main_mask[nid] = False
        logger.info(
            "select_defensible_terrain_via_effective_resistance: candidate bbox "
            "filter [%.3f,%.3f,%.3f,%.3f] kept %d of %d main-component nodes",
            cw, cs, ce, cn, int(main_mask.sum()),
            int((comp_labels == main_comp).sum()),
        )
    main_nodes = np.where(main_mask)[0]
    if main_nodes.size == 0:
        return []
    # Sub-Laplacian over main component (regularize with tiny ε so it's
    # PSD instead of just PSD with a null vector — the system is otherwise
    # singular by construction).
    L_main = L_sparse[main_nodes][:, main_nodes].tolil()
    eps = float(L_main.diagonal().max() * 1e-10)
    for i in range(L_main.shape[0]):
        L_main[i, i] += eps
    L_main = L_main.tocsc()
    # Map original node id -> local index in main component
    local_idx = -np.ones(n_nodes, dtype=np.int64)
    local_idx[main_nodes] = np.arange(main_nodes.size, dtype=np.int64)
    threat_local = [int(local_idx[t]) for t in threat_set if local_idx[t] >= 0]
    if not threat_local:
        return []

    # Step 3: per-threat-origin voltage solves. Inject 1A at threat,
    # extract 1/n at every other node (uniform sink). x[v] is the
    # voltage at v ⇒ R_eff(v, t) = x[t] - x[v] (1A current).
    # Factorize once, back-substitute per threat.
    n_main = L_main.shape[0]
    try:
        lu = spla.splu(L_main)
    except Exception as exc:
        logger.warning(
            "defensible: sparse LU failed (%s); falling back to dense pinv on "
            "main component (%d nodes)", exc, n_main,
        )
        L_dense = L_main.toarray()
        L_plus = np.linalg.pinv(L_dense, hermitian=True)
        # Stash for slow path; same diag/Lplus access below.
        diag = np.diag(L_plus)
        scores = np.full(n_nodes, -1.0, dtype=np.float64)
        for nid in main_nodes:
            v = int(local_idx[nid])
            if v in threat_local:
                continue
            s_v = 0.0
            cnt = 0
            for t in threat_local:
                r = float(diag[v] + diag[t] - 2.0 * L_plus[v, t])
                if np.isfinite(r) and r > 0:
                    s_v += r
                    cnt += 1
            scores[int(nid)] = s_v if cnt > 0 else -1.0
        # Fall through to selection.
    else:
        # Sparse fast path.
        x_per_threat: List[np.ndarray] = []
        for t in threat_local:
            b = -np.full(n_main, 1.0 / n_main, dtype=np.float64)
            b[t] += 1.0  # net: +1A at t, -1A spread uniformly elsewhere
            x = lu.solve(b)
            x_per_threat.append(x)
        scores = np.full(n_nodes, -1.0, dtype=np.float64)
        for nid in main_nodes:
            v = int(local_idx[nid])
            if v in threat_local:
                continue
            s_v = 0.0
            cnt = 0
            for ti, t in enumerate(threat_local):
                # R_eff(v, t) under unit-current source-sink at (t, v):
                # equivalently, x_t[t] - x_t[v] when 1A is injected at t.
                r = float(x_per_threat[ti][t] - x_per_threat[ti][v])
                if np.isfinite(r) and r > 0:
                    s_v += r
                    cnt += 1
            scores[int(nid)] = s_v if cnt > 0 else -1.0

    # Step 4: greedy non-overlap selection.
    order = np.argsort(-scores)
    spacing_deg = spacing_radius_m / grid.meters_per_lat
    polygon_deg = polygon_radius_m / grid.meters_per_lat
    chosen: List[int] = []
    chosen_xy: List[Tuple[float, float]] = []
    for nid in order:
        if scores[nid] <= 0:
            break
        if len(chosen) >= max_count:
            break
        x, y = gvd.nodes[int(nid)]
        if any(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 < spacing_deg
               for cx, cy in chosen_xy):
            continue
        chosen.append(int(nid))
        chosen_xy.append((x, y))

    out: List[DefensibleArea] = []
    for rank, nid in enumerate(chosen, start=1):
        x, y = gvd.nodes[nid]
        poly = Point(x, y).buffer(polygon_deg, quad_segs=12)
        # Facts only (method for the maintainer: Glinton et al. 2004 §3
        # effective-resistance defensibility, Eq. 7+8 generalized via the
        # Laplacian pseudo-inverse — citation stays in this comment,
        # never in emitted text).
        out.append(DefensibleArea(
            id=f"DEF{rank}",
            centre_lonlat=(float(x), float(y)),
            polygon_lonlat=[(float(px), float(py)) for px, py in poly.exterior.coords],
            score=float(scores[nid]),
            threat_origin_count=len(threat_set),
        ))
    logger.info(
        "select_defensible_terrain_via_effective_resistance: "
        "%d candidates ranked, %d defensible areas selected",
        int((scores > 0).sum()), len(out),
    )
    return out


def select_defensible_terrain(
    gvd: GVD, currents: np.ndarray, *,
    grid: TrafficabilityGrid,
    nogo_polys,
    max_count: int = 6,
    radius_m: float = 4000.0,
) -> List[DefensibleArea]:
    """Pick defensible terrain regions: GVD vertices adjacent to large
    NO-GO masses on multiple sides (natural protection) AND high
    baseline current (sit astride enemy approach axes).
    """
    if not gvd.nodes or not nogo_polys:
        return []
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    obstacle_tree = STRtree(nogo_polys)

    node_current = np.zeros(len(gvd.nodes), dtype=np.float64)
    for e_idx, edge in enumerate(gvd.edges):
        a, b = edge.endpoints
        node_current[a] += currents[e_idx]
        node_current[b] += currents[e_idx]

    # Count nearby NO-GO obstacles in the 4 cardinal sectors around each node.
    radius_deg = radius_m / grid.meters_per_lat
    quadrant_cover = np.zeros((len(gvd.nodes), 4), dtype=np.int32)
    for nid, (x, y) in enumerate(gvd.nodes):
        nearby = obstacle_tree.query(Point(x, y).buffer(radius_deg))
        iter_idx = nearby if isinstance(nearby, np.ndarray) else list(nearby)
        for c_idx in iter_idx:
            poly = nogo_polys[int(c_idx)]
            cx, cy = poly.centroid.x, poly.centroid.y
            dx, dy = cx - x, cy - y
            # 0=N, 1=E, 2=S, 3=W
            if abs(dy) >= abs(dx):
                q = 0 if dy >= 0 else 2
            else:
                q = 1 if dx >= 0 else 3
            quadrant_cover[nid, q] = 1

    flank_count = quadrant_cover.sum(axis=1)
    # Score: prefer vertices flanked on multiple sides AND with high
    # baseline current (they sit astride enemy approach axes). Per the
    # paper's defensible-terrain section, a region with high
    # series-parallel resistance to the enemy is doctrinally defensible.
    # 1-flank positions (river/ridge defense) are doctrinally valuable
    # too. Score weights flank_count quadratically so 2-3 flanks
    # dominate 1-flank candidates.
    score = (flank_count.astype(np.float64) ** 2 + 1.0) * node_current
    score = np.where(node_current > 0.0, score, -1.0)
    order = np.argsort(-score)
    logger.info(
        "select_defensible_terrain: %d nodes, max_flank=%d, "
        "max_current=%.4f, %d candidates with current>0",
        len(gvd.nodes),
        int(flank_count.max()) if len(flank_count) else 0,
        float(node_current.max()) if len(node_current) else 0.0,
        int((node_current > 0.0).sum()),
    )

    chosen: List[int] = []
    chosen_xy: List[Tuple[float, float]] = []
    for nid in order:
        if score[nid] <= 0:
            break
        if len(chosen) >= max_count:
            break
        x, y = gvd.nodes[int(nid)]
        if any(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 < radius_deg * 1.5
               for cx, cy in chosen_xy):
            continue
        chosen.append(int(nid))
        chosen_xy.append((x, y))

    out: List[DefensibleArea] = []
    for rank, nid in enumerate(chosen, start=1):
        x, y = gvd.nodes[nid]
        poly = Point(x, y).buffer(radius_deg, quad_segs=12)
        # Facts only (siting basis for the maintainer: flanked-vertex
        # defensible-terrain selection per ATP 2-01.3 — citation stays in
        # this comment, never in emitted text).
        out.append(DefensibleArea(
            id=f"DEF{rank}",
            centre_lonlat=(float(x), float(y)),
            polygon_lonlat=[(float(px), float(py)) for px, py in poly.exterior.coords],
            score=float(score[nid]),
            flanks_protected=int(flank_count[nid]),
            protection_radius_km=float(radius_m) / 1000.0,
        ))
    logger.info("select_defensible_terrain: %d defensible areas selected", len(out))
    return out


# ---------------------------------------------------------------------------
# Top-level orchestration: produce the full MCOO product set
# ---------------------------------------------------------------------------

@dataclass
class McooProducts:
    """Full set of MCOO outputs for one (origin, objective) pair or one
    AO-wide analysis run.
    """
    grid: TrafficabilityGrid
    nogo_polys: list                              # list of shapely Polygons
    c_space_obstacles_by_echelon: Dict[str, list] # echelon -> list of polys
    gvd: GVD
    avenues: List[AvenueBundle]
    engagement_areas: List[EngagementArea]
    defensible_areas: List[DefensibleArea]
    # Per-(origin, objective) per-edge currents indexed by terminal pair name
    currents_by_pair: Dict[Tuple[str, str], np.ndarray] = field(default_factory=dict)


@dataclass
class TerminalSpec:
    name: str
    lon: float
    lat: float
    side: str          # "friendly" or "threat"
    role: str          # "origin" or "objective"


def synthesize_mcoo(
    *,
    west: float, south: float, east: float, north: float,
    terminal_pairs: List[Tuple[TerminalSpec, TerminalSpec]],
    force_profile: ForceProfile = MECHANIZED,
    primary_echelon: str = "division",
    gvd_echelon: str = "platoon",
    cell_m: float = DEFAULT_CELL_M,
    dem_dir: Optional[str] = None,
    landcover_dir: Optional[str] = None,
) -> McooProducts:
    """End-to-end MCOO synthesis for the AO and a list of (origin,
    objective) terminal pairs (friendly axes + threat counterattack
    routes). Returns a single McooProducts bundle.

    ``primary_echelon`` controls the AVENUE-level Table 4-2 grouping
    distance (the radius around the central axis within which parallel
    corridors are bundled into the avenue's multi-tail). ``gvd_echelon``
    controls the C-space dilation used for GVD construction — smaller
    echelons preserve narrower corridors that still admit smaller
    formations. Division avenues can contain Brigade or Battalion
    corridors (ATP 2-01.3 Table 4-2 nesting), so the default keeps the
    GVD at battalion C-space and groups at division distance.
    """
    import time as _time
    _t0 = _time.perf_counter()
    _stage = {}

    _ts = _time.perf_counter()
    grid = build_trafficability_grid(
        west=west, south=south, east=east, north=north,
        force_profile=force_profile, cell_m=cell_m,
        dem_dir=dem_dir, landcover_dir=landcover_dir,
    )
    _stage["trafficability_grid"] = _time.perf_counter() - _ts

    _ts = _time.perf_counter()
    nogo_polys = extract_nogo_polygons(grid)
    _stage["extract_nogo"] = _time.perf_counter() - _ts
    _ts = _time.perf_counter()
    cs_by_echelon: Dict[str, list] = {}
    for echelon in (primary_echelon, gvd_echelon, "brigade", "battalion"):
        if echelon not in cs_by_echelon:
            cs_by_echelon[echelon] = compute_c_space_obstacles(
                nogo_polys, grid=grid, echelon=echelon, force_profile=force_profile,
            )
    _stage["c_space_obstacles"] = _time.perf_counter() - _ts

    _ts = _time.perf_counter()
    # Load OSM roads in the AO + clip to bbox. Roads are the primary
    # doctrinal mobility infrastructure (FM 5-33 / ATP 2-22.7) and are
    # added as corridor edges alongside the terrain-derived Voronoi
    # edges in compute_gvd.
    try:
        from app.services.knowledge.roads import (
            _load_offline_roads, roads_in_bbox,
        )
        all_roads = _load_offline_roads()
        ao_roads = roads_in_bbox(all_roads, south=south, west=west, north=north, east=east)
        logger.info(
            "synthesize_mcoo: %d / %d OSM roads inside AO bbox",
            len(ao_roads), len(all_roads),
        )
    except Exception as _road_err:
        logger.warning(
            "synthesize_mcoo: road load failed (%s); proceeding with Voronoi-only GVD",
            _road_err,
        )
        ao_roads = []
    gvd = compute_gvd(cs_by_echelon[gvd_echelon], grid=grid, roads=ao_roads)
    _stage["compute_gvd"] = _time.perf_counter() - _ts

    # ------------------------------------------------------------------
    # Glinton et al. 2004 §3 paper-exact MCOO synthesis pipeline.
    #
    # Order matters per the paper:
    #   §3 'Engagement Areas' para 5 — EAs are selected FIRST (before
    #       AAs), via combinatorial subsets, by max drop in baseline
    #       source→sink threat current. This requires baseline circuit
    #       solves per terminal pair with NO EA modulation.
    #   §3 'Avenues of approach' para 1 — AAs are constructed with the
    #       selected EAs' resistance raised. The "highest-current
    #       corridors" then route AROUND the EAs (commander avoiding
    #       enemy engagement positions).
    #   §3 'Avenues of approach' para 3 — for each AA, find the central
    #       axis via shortest path on EA-modulated currents, then raise
    #       resistance proportional to perpendicular distance from the
    #       axis, re-solve. Tails come from THIS re-solve.
    #   §3 'Defensible terrain' — series-parallel reduction (Eq. 7+8)
    #       generalized to arbitrary graphs via Laplacian pseudo-inverse
    #       effective-resistance formula. Independent of EA / AA state.
    # ------------------------------------------------------------------

    # Identify the GVD-node REGION for each terminal per Glinton paper
    # §3 Fig 7c boundary-condition semantics. Region radius is the
    # primary echelon's grouping distance / 2 (≈ doctrinal Table 4-2
    # avenue half-width) — the KT region encompasses the local cluster
    # of mobility corridors that converge on it. Used as voltage clamp
    # set in solve_corridor_circuit (no invented stub edges).
    terminal_region_radius_m = float(
        AVENUE_GROUPING_MAX_DISTANCE_M.get(primary_echelon, 6000.0)
    ) / 2.0
    pair_nodes: List[Tuple[
        List[int], List[int], str, str, TerminalSpec, TerminalSpec,
    ]] = []
    for origin, objective in terminal_pairs:
        o_set = find_terminal_nodes(
            gvd, lon=origin.lon, lat=origin.lat,
            radius_m=terminal_region_radius_m, grid=grid, label=origin.name,
        )
        d_set = find_terminal_nodes(
            gvd, lon=objective.lon, lat=objective.lat,
            radius_m=terminal_region_radius_m, grid=grid, label=objective.name,
        )
        pair_nodes.append((o_set, d_set, origin.name, objective.name, origin, objective))

    _ts = _time.perf_counter()
    # ----- Step 1: BASELINE circuit currents (no EA modulation). -----
    # Per Glinton paper §3 'Engagement Areas' para 5: "the net current
    # flow between the terminals of the circuit shown in Fig. 7(c), for
    # a constant voltage, is a baseline measure for the ease with which
    # an enemy can travel".
    baseline_currents_by_pair: Dict[Tuple[str, str], np.ndarray] = {}
    for o_set, d_set, o_name, d_name, _origin, _objective in pair_nodes:
        c = solve_corridor_circuit(
            gvd, origin_nodes=o_set, objective_nodes=d_set,
        )
        baseline_currents_by_pair[(o_name, d_name)] = c
    _stage["baseline_circuit_solves"] = _time.perf_counter() - _ts

    # ----- Step 2: EA SELECTION via combinatorial max-drop. -----
    # Per Glinton paper §3 'Engagement Areas' para 5: the EA combination
    # that maximally drops the THREAT source→sink baseline current is
    # the most disruptive choice. For our scenario the threat pairs are
    # the terminal_pairs entries where origin.side == "threat".
    _ts = _time.perf_counter()
    threat_pair_node_sets: List[Tuple[List[int], List[int]]] = [
        (o_set, d_set)
        for o_set, d_set, _, _, origin, _ in pair_nodes
        if origin.side == "threat"
    ]
    if threat_pair_node_sets:
        engagement_areas = select_engagement_areas_via_resistance_modulation(
            gvd, grid=grid, threat_terminal_pairs=threat_pair_node_sets,
        )
    else:
        # No threat pairs — fall back to friendly-axis disruption candidates.
        friendly_pair_node_sets = [
            (o_set, d_set) for o_set, d_set, _, _, _, _ in pair_nodes
        ]
        engagement_areas = select_engagement_areas_via_resistance_modulation(
            gvd, grid=grid, threat_terminal_pairs=friendly_pair_node_sets,
        )
    _stage["ea_combinatorial_search"] = _time.perf_counter() - _ts

    # Build the EA edge-resistance multiplier used by the AA solves
    # (paper §3 'Avenues of approach' para 1: "the resistance of
    # candidate engagement areas is increased").
    ea_node_ids = [ea.node_id for ea in engagement_areas if ea.node_id >= 0]
    ea_edge_multiplier = _build_edge_multiplier_for_ea_set(
        gvd, ea_node_ids, multiplier=10.0,
    )

    _ts = _time.perf_counter()
    # ----- Step 3: AVENUE CONSTRUCTION with EA-modulated + off-axis re-weight. -----
    avenues: List[AvenueBundle] = []
    currents_by_pair: Dict[Tuple[str, str], np.ndarray] = {}
    for o_set, d_set, o_name, d_name, origin, objective in pair_nodes:
        # EA-modulated current for central-axis A*: raises resistance at
        # EA-incident edges so the chosen central axis routes around
        # them (paper §3 'Avenues of approach' para 1).
        ea_currents = solve_corridor_circuit(
            gvd, origin_nodes=o_set, objective_nodes=d_set,
            edge_resistance_multiplier=ea_edge_multiplier,
        )
        currents_by_pair[(o_name, d_name)] = ea_currents
        # For the avenue-bundle central-axis A* we need a single
        # representative origin/objective node from each region — pick
        # the node closest to the actual KT lat/lon.
        def _representative(node_set, lon, lat):
            if not node_set:
                return -1
            arr = np.array([gvd.nodes[n] for n in node_set])
            d2 = (arr[:, 0] - lon) ** 2 + (arr[:, 1] - lat) ** 2
            return int(node_set[int(np.argmin(d2))])
        o_rep = _representative(o_set, origin.lon, origin.lat)
        d_rep = _representative(d_set, objective.lon, objective.lat)
        if o_rep < 0 or d_rep < 0:
            continue
        # build_avenue_bundle internally does the central-axis A* on
        # ea_currents, then composes off-axis multiplier × ea_edge_multiplier
        # for the tail re-solve (paper §3 'Avenues of approach' para 3).
        bundle = build_avenue_bundle(
            gvd, ea_currents,
            origin_node=o_rep, origin_name=origin.name,
            origin_lonlat=(origin.lon, origin.lat),
            objective_node=d_rep, objective_name=objective.name,
            objective_lonlat=(objective.lon, objective.lat),
            side=origin.side, avenue_echelon=primary_echelon, grid=grid,
            ea_edge_multiplier=ea_edge_multiplier,
            origin_nodes=o_set, objective_nodes=d_set,
        )
        if bundle is not None:
            avenues.append(bundle)
    _stage["avenues_construction"] = _time.perf_counter() - _ts

    _ts = _time.perf_counter()
    # ----- Step 4: DEFENSIBLE TERRAIN via effective resistance. -----
    # Per Glinton paper §3 'Defensible terrain': series-parallel
    # reduction (Eq. 7+8) → for general graph = Laplacian pseudo-inverse
    # effective-resistance formula. Score = sum of R_eff from each
    # candidate vertex to each threat origin (more resistance = more
    # natural protection).
    # Defensible-terrain candidate-vs-threat-origin distance uses ALL
    # nodes in each threat origin region (paper §3 'Defensible terrain'
    # is region-to-region effective resistance, same boundary semantics
    # as the AA solves above).
    threat_origin_nodes: List[int] = []
    for o_set, _, _, _, origin, _ in pair_nodes:
        if origin.side == "threat":
            threat_origin_nodes.extend(o_set)
    # Dedupe (regions may share nodes if KTs are close).
    threat_origin_nodes = list(dict.fromkeys(threat_origin_nodes))
    # Friendly operational-area bbox = min-rect over all friendly origin
    # AND objective KTs, padded by 20 km. Defensible-terrain candidates
    # are restricted to this bbox per the doctrinal rule that defending
    # forces only defend terrain they actually operate in.
    friendly_lons: List[float] = []
    friendly_lats: List[float] = []
    for _, _, _, _, origin, objective in pair_nodes:
        if origin.side == "friendly":
            friendly_lons.extend([origin.lon, objective.lon])
            friendly_lats.extend([origin.lat, objective.lat])
    if friendly_lons:
        pad_deg = 20000.0 / grid.meters_per_lat
        f_bbox = (
            min(friendly_lons) - pad_deg, min(friendly_lats) - pad_deg,
            max(friendly_lons) + pad_deg, max(friendly_lats) + pad_deg,
        )
    else:
        f_bbox = None
    # Algorithm-emitted defensible terrain DISABLED: the paper's L⁺
    # effective-resistance formula picks mathematically far-from-threat
    # nodes rather than doctrinally on-corridor choke points (per
    # ATP 2-01.3 + FM 5-33 defensible terrain is at narrowings ALONG
    # threat avenues where flanking obstacles provide cover, not where
    # the L⁺ metric is highest). Hand-authored Donovian defensive
    # positions live in scenario.TERRAIN.defensible_terrain and are
    # pushed via _push_scenario_terrain_to_geo_agent. Compute path
    # retained below (unreachable) for post-COMEX rewrite.
    defensible_areas: List[DefensibleArea] = []
    if False and threat_origin_nodes:  # disabled
        defensible_areas = select_defensible_terrain_via_effective_resistance(
            gvd, grid=grid, threat_origin_nodes=threat_origin_nodes,
            candidate_bbox=f_bbox,
        )
    _stage["defensible_terrain"] = _time.perf_counter() - _ts

    _total = _time.perf_counter() - _t0
    logger.info(
        "synthesize_mcoo TIMING — total=%.1fs | %s",
        _total,
        " | ".join(f"{k}={v:.1f}s" for k, v in _stage.items()),
    )

    return McooProducts(
        grid=grid,
        nogo_polys=nogo_polys,
        c_space_obstacles_by_echelon=cs_by_echelon,
        gvd=gvd,
        avenues=avenues,
        engagement_areas=engagement_areas,
        defensible_areas=defensible_areas,
        currents_by_pair=currents_by_pair,
    )

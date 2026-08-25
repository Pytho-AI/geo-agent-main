"""Data classes, node types, and data structures for route planning."""

from typing import Dict, List, NamedTuple, Optional, Tuple, Any
from uuid import UUID
from dataclasses import dataclass, field

from app.services.knowledge.roads import Road

# Re-export constants from their single source of truth so existing
# ``from .models import X`` statements keep working.
from app.constants.terrain import (  # noqa: F401
    METERS_PER_MILE,
    TILE_SIZE_MI,
    TILE_SIZE_DEG,
    SAMPLES_PER_TILE_SIDE,
    INTERSECTION_THRESHOLD_M,
    DEFAULT_MAX_SLOPE_PCT,
    CONCEALMENT_SCORE,
    TRAFFICABILITY_COST,
)


# ---------------------------------------------------------------------------
# Node types (hashable, used as dict keys and in A* sets)
# ---------------------------------------------------------------------------

class RoadNode(NamedTuple):
    kind: str = "road"
    way_id: int = 0
    coord_index: int = 0

class TileNode(NamedTuple):
    kind: str = "tile"
    row: int = 0
    col: int = 0

Node = Tuple  # RoadNode or TileNode


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ThreatZone:
    lat: float
    lon: float
    radius_m: float
    weight: float

@dataclass
class NoGoZone:
    coords: List[Tuple[float, float]]

@dataclass
class NoGoLine:
    """A LineString barrier that routes must not cross."""
    coords: List[Tuple[float, float]]  # [(lon, lat), ...]

@dataclass
class BlockReason:
    """Why a tile is blocked. Multiple flags can be set simultaneously."""
    nogo_zone: bool = False
    nogo_line: bool = False
    slope: bool = False
    impassable: bool = False

    @property
    def is_blocked(self) -> bool:
        return self.nogo_zone or self.nogo_line or self.slope or self.impassable

    @property
    def reasons(self) -> List[str]:
        r = []
        if self.nogo_zone:
            r.append("nogo_zone")
        if self.nogo_line:
            r.append("nogo_line")
        if self.slope:
            r.append("slope")
        if self.impassable:
            r.append("impassable")
        return r


@dataclass
class MacroTile:
    row: int
    col: int
    south: float
    west: float
    north: float
    east: float

    # Terrain (from sample points)
    avg_elevation_ft: float = 0.0
    max_slope_pct: float = 0.0
    worst_trafficability: float = 1.0
    concealment_pct: float = 0.0
    dominant_land_cover: str = "Unknown"

    # Cost factors (computed from same sample points)
    worst_threat: float = 0.0
    block_reason: BlockReason = field(default_factory=BlockReason)
    terrain_cost_modifier: float = 1.0  # <1 = preferred terrain, >1 = avoided

    # Weather (populated by populate_tile_weather before A*)
    weather_precip_mm: float = 0.0       # rain or snow in 3h window
    weather_wind_ms: float = 0.0         # wind speed m/s
    weather_temp_c: Optional[float] = None
    weather_visibility_m: float = 10000  # default clear
    weather_condition: str = "Clear"     # OWM main condition
    weather_cost_modifier: float = 1.0   # computed from weather fields

    @property
    def blocked(self) -> bool:
        return self.block_reason.is_blocked

    @property
    def center_lat(self):
        return (self.south + self.north) / 2

    @property
    def center_lon(self):
        return (self.west + self.east) / 2

@dataclass
class ViewportData:
    roads: List[Road]
    sample_coords: List[Tuple[float, float]]
    elevations: List[Optional[float]]
    land_covers: List[Any]  # List[Optional[TerrainPoint]] from geodata
    sample_tile_map: List[Tuple[int, int]]

@dataclass
class RoutePreferences:
    """Optional knobs for route planning. Defaults preserve current behavior."""
    slope_weight: float = 1.0            # 0=ignore slope, 2=strongly avoid steep
    threat_weight: float = 1.0           # 0=ignore threats, 2=strongly avoid
    concealment_weight: float = 0.0      # 0=ignore (current), 1=prefer concealed routes
    max_slope_pct: float = DEFAULT_MAX_SLOPE_PCT  # tile blocking threshold override
    preferred_terrain: List[str] = field(default_factory=list)
    avoid_terrain: List[str] = field(default_factory=list)
    rate_of_advance_mph: float = 0.0     # 0 = use default (30 mph)
    weather_weight: float = 1.0          # 0=ignore weather in cost, 1=normal, 2=strongly avoid
    # Force type modulates the post-route corridor-width sampling pinch
    # criterion (see analysis.compute_corridor_widths). Mechanized treats
    # fair/poor terrain and steep slope as canalizing; dismounted is more
    # permissive (can traverse forest/swamp). Doesn't affect the planner's
    # own cost surface — the cost surface is mode-agnostic, only the AA
    # width derivation reads this.
    force_type: str = "mechanized"

@dataclass
class NoPathDiagnostic:
    """Diagnostics returned when A* finds no path."""
    reachable_from_start: int               # tiles the search reached
    total_tiles: int                        # tiles in the grid
    blocking_counts: Dict[str, int]         # block reasons across whole grid
    frontier_counts: Dict[str, int]         # block reasons at the search frontier
    impassable_terrain_types: Dict[str, int]  # land cover names causing impassable blocks at frontier
    suggestions: List[str]                  # human-readable relaxation hints


@dataclass
class PlanRequest:
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    route_mode: str
    map_id: UUID
    preferences: RoutePreferences = field(default_factory=RoutePreferences)

@dataclass
class PathResult:
    rank: int
    label: str
    coords: List[Tuple[float, float]]
    analysis: Dict[str, Any]

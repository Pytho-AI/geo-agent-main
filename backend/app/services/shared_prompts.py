"""Shared prompt building blocks for COP and NL agent prompts.

Centralizes operation definitions, reference values, and overlay type lists
so that COP and NL chat prompts stay in sync.
"""

from app.constants.overlays import (
    LINE_OVERLAY_TYPES,
    PROTECTION_LINE_TYPES,
    PROTECTION_OBSTACLE_LINE_TYPES,
    POLYGON_OVERLAY_TYPES,
    POINT_OVERLAY_TYPES,
)


def _values_csv(types: list) -> str:
    """Build a comma-separated, quoted list of overlay 'value' keys."""
    return ", ".join(f'"{t["value"]}"' for t in types)


# ---------------------------------------------------------------------------
# Reference values
# ---------------------------------------------------------------------------

AFFILIATION_VALUES = """\
## Affiliation Values
- "Friend" (friendly/allied/blue forces)
- "Hostile" (enemy/red forces)
- "Neutral" (neutral/green)
- "Unknown" (unknown/pending)"""

ECHELON_VALUES = """\
## Echelon Values
- "Team", "Squad", "Section", "Platoon", "Company", "Battalion", "Regiment", "Brigade", "Division", "Corps", "Army\""""

# ---------------------------------------------------------------------------
# Overlay type catalogues (pick per-prompt)
# ---------------------------------------------------------------------------

# The vocabularies DERIVE from the full catalog so the prompt can never
# rot behind it again — the old hand-picked group list silently dropped
# every kind added since (IPB terrain: avenue_of_approach,
# mobility_corridor, intervisibility_line; fire-support and airspace
# lines; mission tasks; every point graphic), leaving the agent unable
# to draw them.

# Obstacle / engineer overlays (both protection groups: wire AND
# obstacle/crossing kinds).
_OBSTACLE_TYPES = PROTECTION_LINE_TYPES + PROTECTION_OBSTACLE_LINE_TYPES
_OBSTACLE_VALUES = {t["value"] for t in _OBSTACLE_TYPES}
OVERLAY_LINE_TYPES_OBSTACLE = _values_csv(_OBSTACLE_TYPES)

# Every other line kind in the catalog: command & control, maneuver,
# fires, airspace, maritime, intelligence, sustainment, mission tasks,
# IPB terrain.
OVERLAY_LINE_TYPES_TACTICAL = _values_csv(
    [t for t in LINE_OVERLAY_TYPES if t["value"] not in _OBSTACLE_VALUES]
)

OVERLAY_AREA_TYPES = _values_csv(POLYGON_OVERLAY_TYPES)

# Point graphics: decision points, key terrain, choke points, strong
# points, obstacle points, range fans, threat objectives, and the
# sustainment/medical point set.
OVERLAY_POINT_TYPES = _values_csv(POINT_OVERLAY_TYPES)

# ---------------------------------------------------------------------------
# Operation descriptions
# ---------------------------------------------------------------------------

CREATE_ENTITY_OP = """\
**create_entity**: Create a military unit
   - kind: always "mil_unit"
   - attrs MUST include: name, affiliation, echelon
   - Include the unit type in the name (e.g., "1st Armor Company", "Infantry Battalion")
   - geom: Point geometry"""

CREATE_ROUTE_OP = """\
**create_route**: Plan a route between two points using A* pathfinding with terrain analysis
   - name: route designation (e.g., "MSR Tampa", "Route Alpha", "Supply Route North")
   - start_geom: {"type": "Point", "coordinates": [lon, lat]} — start location
   - end_geom: {"type": "Point", "coordinates": [lon, lat]} — end location
   - route_mode: "on_road" (roads only), "off_road" (cross-country), or "mixed" (default — uses both)
   - attrs: optional preferences — { "slope_weight": 1.0, "threat_weight": 1.0, "concealment_weight": 0.0, "max_slope_pct": 58 }"""

DELETE_ROUTE_OP = """\
**delete_route**: Delete a route (requires route ID)
   - id: UUID of the route"""

MOVE_ENTITY_OP = """\
**move_entity**: Move an existing entity (requires entity ID)
   - id: UUID of the entity to move
   - geom: new location"""

UPDATE_ENTITY_OP = """\
**update_entity**: Update entity attributes (requires entity ID)
   - id: UUID of the entity
   - attrs: attributes to update"""

DELETE_ENTITY_OP = """\
**delete_entity**: Delete an entity (requires entity ID)
   - id: UUID of the entity"""

DELETE_OVERLAY_OP = """\
**delete_overlay**: Delete an overlay (requires overlay ID)
   - id: UUID of the overlay"""


# ---------------------------------------------------------------------------
# Helpers to build the "Available Operations" section
# ---------------------------------------------------------------------------

def build_create_overlay_op(line_types: str) -> str:
    """Build the create_overlay operation description with the given line types."""
    return f"""\
**create_overlay**: Create a tactical overlay (obstacle, boundary, area, point graphic)
   - Line types (use LineString geometry): {line_types}
   - Area types (use Polygon geometry): {OVERLAY_AREA_TYPES}
   - Point types (use Point geometry): {OVERLAY_POINT_TYPES}
   - name: designation (e.g., "PL ALPHA", "EA DOG", "OBJ TIGER", "AA LION")
   - For lines: geom is LineString with coordinates array
   - For areas: geom is Polygon with coordinates array
   - For points: geom is Point with a single [lon, lat] coordinate
   - attrs should include: affiliation"""


def build_ops_section(ops: list[str]) -> str:
    """Number and join operation descriptions into an '## Available Operations' section."""
    numbered = "\n\n".join(f"{i+1}. {op}" for i, op in enumerate(ops))
    return f"## Available Operations\n\n{numbered}"

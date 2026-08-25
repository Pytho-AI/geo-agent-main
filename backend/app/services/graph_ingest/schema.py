"""Canonical extraction schema — the CONTRACT between any extractor
(VLM, Sonnet agent, fixture) and the deterministic ingest core.

Deliberately close to the schema the catalog/OOB extraction agents
already emit: entities with a ref, type, affiliation, echelon,
position, parent ref, and holdings; typed edges by ref; a coverage
note. Positions are lon/lat OR an MGRS/place string (the ingest core
converts MGRS, leaves place-names unplaced). Nothing here references
graph_nodes uuids — the ingest core mints them and resolves refs.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class AreaOfOperations(BaseModel):
    """The geographic frame for a document ingest — established FIRST,
    before any unit is extracted, so every downstream placement is a
    lookup inside it. A place name that resolves nowhere in this bbox
    stays unplaced (no model call rejects it — the bbox does)."""
    theater: Optional[str] = None            # free-text region the doc names
    countries: List[str] = Field(default_factory=list)
    west: float = -180.0
    south: float = -85.0
    east: float = 180.0
    north: float = 85.0
    # Anchors that defined the box: [{name, lon, lat, kind}]. Provenance
    # for the report + the render caption.
    anchors: List[dict] = Field(default_factory=list)
    note: Optional[str] = None
    resolved: bool = False                    # False => fell back to world/hint

    @property
    def bbox(self) -> tuple:
        return (self.west, self.south, self.east, self.north)

    @property
    def center(self) -> tuple:
        return ((self.west + self.east) / 2.0, (self.south + self.north) / 2.0)


class ExtractedHolding(BaseModel):
    nomenclature: str                      # verbatim, resolved via alias
    count_authorized: Optional[int] = None
    count_current: Optional[int] = None


class ExtractedPosition(BaseModel):
    """One DATED position observation. A road to war narrates a unit
    moving through positions over time; each dated entry is one of these.
    The ingest appends them as an append-only track; the newest is the
    current position."""
    dtg: Optional[str] = None              # date-time group as written
    mgrs: Optional[str] = None
    location_text: Optional[str] = None    # named place / assembly area
    activity: Optional[str] = None         # posture/activity at that time
    # THE SPECIFIC CITATION for this observation — document + entry
    # ("2CR Road to War, 06 APR 26 entry"), never a bundle label. The
    # placard shows it verbatim as the position's provenance.
    source: Optional[str] = None
    # filled by resolve_placements:
    lon: Optional[float] = None
    lat: Optional[float] = None
    observed_at: Optional[str] = None      # ISO-8601, parsed from dtg


class ExtractedEntity(BaseModel):
    ref: str                               # stable local id for cross-refs
    name: str
    # entity_type is a registry key; unknown values resolve to a
    # sensible default and are reported, never dropped.
    entity_type: str = "unit"
    affiliation: str = "Unknown"           # Friend|Hostile|Neutral|Unknown
    echelon: Optional[str] = None
    unit_type: Optional[str] = None
    category: Optional[str] = None
    parent_ref: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    mgrs: Optional[str] = None             # current/only position, if single
    location_text: Optional[str] = None    # place-name; leaves unplaced
    # Citation for the CURRENT/single position above — the specific
    # document and entry that states it. Positions in the track carry
    # their own per-observation source fields.
    position_source: Optional[str] = None
    # The unit's POSITION TRACK from a road-to-war-style timeline: every
    # dated position it held, oldest to newest. The newest is the current
    # laydown; the whole track is append-only history (scrub/replay). When
    # a doc states only one position, use mgrs/location_text above.
    positions: List["ExtractedPosition"] = Field(default_factory=list)
    # CONTROL MEASURES / linear features: grid vertex sequences. `line`
    # for phase lines / boundaries / corridors / LOCs; `area` for
    # engagement areas / objectives / assembly areas (ring closes
    # automatically). Mutually exclusive with point placement.
    line: List[str] = Field(default_factory=list)   # MGRS vertices, in order
    area: List[str] = Field(default_factory=list)   # MGRS vertices, in order
    # Center + radius notation ("Point / Circle, 2.5 km radius" — the
    # planning placeholder sources use when the exact boundary is TBD):
    # {"mgrs": "34UEE 64392 54490", "radius_m": 2500}. The server
    # generates the ring; callers never hand-extrapolate vertices.
    circle: Optional[dict] = None
    # filled by resolve_placements:
    line_coords: Optional[List[List[float]]] = None   # [[lon,lat],...]
    area_coords: Optional[List[List[float]]] = None
    posture: Optional[str] = None
    personnel_authorized: Optional[int] = None
    personnel_current: Optional[int] = None
    significance: Optional[str] = None
    significance_note: Optional[str] = None
    notes: Optional[str] = None
    # Templated defaults: when a source names a unit at echelon without
    # its internal structure, a template_key instantiates that standard
    # structure as the unit's subtree (OPORD → filled TO&E).
    template_key: Optional[str] = None
    # FRAGO / status change: destroyed | withdrawn | ... maps to the
    # combat_effectiveness assessment on update.
    status: Optional[str] = None
    holdings: List[ExtractedHolding] = Field(default_factory=list)
    # True when the source states this unit's COMPLETE equipment table
    # (a full MTOE): template default equipment does not apply at all.
    # False (default): holdings are partial statements; template
    # defaults layer underneath them.
    holdings_complete: bool = False


class ExtractedEdge(BaseModel):
    from_ref: str
    to_ref: str
    relationship_type: str                 # registry key
    note: Optional[str] = None


class ExtractedOOB(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list)
    edges: List[ExtractedEdge] = Field(default_factory=list)
    coverage_note: Optional[str] = None    # what the source did/didn't specify
    source_label: Optional[str] = None     # provenance for the report
    # A FRAGO/update document sets this so ingest matches existing
    # entities (by name in-project) and applies deltas instead of
    # creating duplicates.
    document_kind: Optional[str] = None    # "oob" (default) | "frago"


class IngestReport(BaseModel):
    """Returned by ingest_oob — everything a caller (analyst, DAG,
    agent) needs to know what landed and what needs attention."""
    entities_created: int = 0
    entities_updated: int = 0            # FRAGO: matched an existing unit
    positions_recorded: int = 0          # append-only track observations written
    templates_filled: int = 0            # instantiated a template subtree
    edges_created: int = 0
    holdings_created: int = 0
    holdings_resolved: int = 0             # matched to a catalog weg_id
    holdings_unresolved: int = 0           # kept as nomenclature_raw
    entities_unplaced: int = 0            # no coordinate resolved
    unknown_entity_types: List[str] = Field(default_factory=list)
    unknown_relationship_types: List[str] = Field(default_factory=list)
    unresolved_parent_refs: List[str] = Field(default_factory=list)
    dropped_edges: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

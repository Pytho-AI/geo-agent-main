"""Entity graph — the system of record for entities and relationships.

Design of record: scratch/docs/oob/oob-design.md (decisions 1-21).
graph_nodes are typed entities (units, fixed infrastructure, equipment
instances); graph_edges are typed relationships; graph_holdings are
AGGREGATE equipment counts on any entity. The ORDER OF BATTLE is a
subset read of this graph, not its own store.

Rows are scoped by exactly one of project_id (a maps row) or
template_id (a force_templates row) — template bodies deliberately
have no maps row so map CRUD can never touch the template library.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from geoalchemy2 import Geometry

from app.models.base import Base

# Closed doctrinal sets (design 3.1). The FM 3-60 App. C functional
# categories are shared verbatim with weg_equipment.category and
# entity_types.default_category.
AFFILIATIONS = ("Friend", "Hostile", "Neutral", "Unknown")
CATEGORIES = (
    "command_and_control", "fire_support", "maneuver",
    "air_defense_artillery", "engineer", "reconnaissance_and_surveillance",
    "cyberspace_electromagnetic_activities", "information",
    "chemical_biological_radiological_nuclear", "sustainment",
    "lift", "line_of_communication",
)
# Ordered smallest -> largest; roll-ups and ORBAT collapse read this order.
ECHELONS = (
    "Team", "Squad", "Section", "Platoon", "Company", "Battalion",
    "Regiment", "Brigade", "Division", "Corps", "Army",
)
EFFECTIVENESS = ("effective", "degraded", "ineffective", "destroyed")
SIGNIFICANCE = ("high", "medium", "low")
# Closed posture set — every array mode the disposition engine supports,
# by its canonical analyst-facing word. The record enforces it
# (_MIRROR_COLUMNS validation + ck_graph_nodes_posture) because posture
# is a tracked temporal attribute: the as-of resolver and the placard
# selector both read this vocabulary, so an off-enum value would be a
# shape the engine cannot draw.
POSTURES = ("assembly", "march", "defense", "attack", "screen")

GRAPH_MODES = ("authored", "consumed")

# THE entity-type registry (single authority). The DB entity_types
# table seeds from this; the extraction prompt enum, the MCP shape-kind
# enum, and GRAPHIC_TYPES all DERIVE from it — never hand-mirror this
# list anywhere.
# Set-20 land-installation entity codes verified against
# backend/app/data/milstd/"2525E 20 land-installation.json":
# Ammunition Cache 110300; Energy Facility > Petroleum/Gas/Oil 120505;
# Military > Airport/Air Base 120803; Transportation > Railhead/
# Railroad Station 121307. pipeline_junction and pump_station share
# 120505 (set 20 has no pipeline/POL-pump entity — deliberate, design
# decision 20); c2_bunker has NO mapping (plain-frame fallback; CPs are
# unit-kind entities, never this type).
ENTITY_TYPE_SEED = [
    # (type_key, label, is_fixed, symbol_set, symbol_entity_code, default_category)
    ("unit", "Unit", False, None, None, None),
    ("equipment", "Equipment", False, None, None, None),
    # World-model reference object types (design S6.1). Not painted as
    # infrastructure; they live in reference_nodes, addressed by name.
    # `event` is registry-defined now, populated when event data arrives (S6.5).
    ("weapon", "Weapon", False, None, None, None),
    ("munition", "Munition", False, None, None, None),
    ("component", "Component", False, None, None, None),
    ("event", "Event", False, None, None, None),
    ("pol_storage", "POL Storage", True, "20", "120505", "sustainment"),
    ("pipeline_junction", "Pipeline Junction", True, "20", "120505", "sustainment"),
    ("pump_station", "Pump Station", True, "20", "120505", "sustainment"),
    ("rail_hub", "Rail Hub", True, "20", "121307", "line_of_communication"),
    ("c2_bunker", "C2 Bunker", True, None, None, "command_and_control"),
    ("airfield", "Airfield", True, "20", "120803", "lift"),
    ("ammunition", "Ammunition Storage", True, "20", "110300", "sustainment"),
    # Bridge 110701 verified in "2525E 20 land-installation.json"
    # (Engineering Equipment Production > Bridge).
    ("bridge", "Bridge", True, "20", "110701", "line_of_communication"),
    # Garrison / training area / barracks — 120802 Military > Military Base
    # (verified in the set-20 table). Was falling back to "airfield".
    ("garrison", "Garrison / Base", True, "20", "120802", None),
    # Point infrastructure owed by the trace-driven decision spec —
    # "closest match" is a data-set failure. Codes verified in
    # "2525E 20 land-installation.json": Telecommunications 121202,
    # Water Treatment 121411, Medical Treatment Facility (Hospital)
    # 120702, Warehouse/Storage Facility 112000. A headquarters is a
    # UNIT (command_and_control), never an installation type.
    ("communications_node", "Communications Node", True, "20", "121202", "command_and_control"),
    ("water_treatment", "Water Treatment Facility", True, "20", "121411", None),
    ("medical_facility", "Medical Facility", True, "20", "120702", "sustainment"),
    ("logistics_site", "Logistics Site", True, "20", "112000", "sustainment"),
    # CONTROL MEASURES — tactical graphics, first-class graph entities
    # (line/polygon/point geometry). No SIDC: map_state emits them with
    # kind == type_key and the overlay-catalog renderer contract paints
    # them (GRAPHIC_TYPES below derives by catalog membership).
    ("phase_line", "Phase Line", True, None, None, None),
    ("boundary", "Boundary", True, None, None, None),
    # Operational-area graphics are their own kinds (2026-07-21) — an
    # AO box or AOI ellipse is not a boundary borrowed to draw a ring;
    # each gets its own overlay-selector chip and catalog styling.
    ("area_of_operations", "Area of Operations", True, None, None, None),
    ("area_of_interest", "Area of Interest", True, None, None, None),
    ("engagement_area", "Engagement Area", True, None, None, None),
    ("objective", "Objective", True, None, None, None),
    ("assembly_area", "Assembly Area", True, None, None, None),
    ("named_area_of_interest", "Named Area of Interest", True, None, None, None),
    ("targeted_area_of_interest", "Targeted Area of Interest", True, None, None, None),
    ("battle_position", "Battle Position", True, None, None, None),
    ("air_corridor", "Air Corridor", True, None, None, None),
    ("decision_point", "Decision Point", True, None, None, None),
    ("fire_support_coord_measure", "Fire Support Coordination Measure", True, None, None, None),
    # IPOE terrain classes (phase-0 registry completion, 2026-07-22):
    # catalog contracts already existed under these exact keys; the
    # seed rows make them mintable. Avenues and corridors are
    # ANALYST-PRODUCED (step-2 synthesis writes), key terrain and
    # obstacles are doc-stated ingest classes. `obstacle` is ONE kind
    # for every doctrinal obstacle form — point (subkind-keyed glyph),
    # line, and belt/area resolve by geometry class in the catalog.
    ("key_terrain", "Key Terrain", True, None, None, None),
    ("avenue_of_approach", "Avenue of Approach", True, None, None, None),
    ("mobility_corridor", "Mobility Corridor", True, None, None, None),
    ("obstacle", "Obstacle", True, None, None, None),
    # Linear route control measures (line geometry). No SIDC — painted
    # by the frontend tacticalLayers route renderers.
    ("main_supply_route", "Main Supply Route", True, None, None, "line_of_communication"),
    ("alternate_supply_route", "Alternate Supply Route", True, None, None, "line_of_communication"),
    ("route", "Route", True, None, None, "line_of_communication"),
]


# Reference-store object types (design S6.1): registry-defined,
# addressed by name in reference_nodes — never emitted as project
# entities by extraction.
REFERENCE_ONLY_TYPES = frozenset({"weapon", "munition", "component", "event"})

# The entities:civil read's kind set (registry-level declaration — the
# retrieval readers derive from HERE, never a hand-list in a reader).
# Civil/dual-use infrastructure for ASCOPE civil-considerations reads;
# explicitly-military installations (garrison, ammunition, c2_bunker)
# stay out — they surface through entities:<kind> reads directly.
CIVIL_KINDS = tuple(
    k for (k, *_rest) in ENTITY_TYPE_SEED if k in (
        "pol_storage", "pipeline_junction", "pump_station", "rail_hub",
        "airfield", "bridge", "communications_node", "water_treatment",
        "medical_facility", "logistics_site",
    ))

# Entity types an extractor may emit for a project (derived).
EXTRACTABLE_ENTITY_TYPES = tuple(
    k for (k, *_rest) in ENTITY_TYPE_SEED if k not in REFERENCE_ONLY_TYPES)

# Entity types painted as TACTICAL GRAPHICS (lines/polygons/graphic
# points), never as SIDC unit frames — DERIVED, not hand-mirrored: an
# entity type is a graphic exactly when the overlay catalog defines its
# renderer contract (constants/overlays.py stamps the primitive
# map_state serves and the frontend dispatch draws).
from app.constants.overlays import OVERLAY_KINDS as _OVERLAY_KINDS
GRAPHIC_TYPES = frozenset(
    k for (k, *_rest) in ENTITY_TYPE_SEED if k in _OVERLAY_KINDS)


def _in(col: str, values: tuple) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{col} IS NULL OR {col} IN ({quoted})"


class ForceTemplate(Base):
    """Template HEADER only — bodies are ordinary graph rows scoped by
    template_id. Bundled rows are read-only in the UI
    (duplicate-to-custom); user rows edit in place."""
    __tablename__ = "force_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    echelon = Column(String(32))
    tier = Column(Integer)
    # Full doctrinal citation — the htfs_ org-guide templates cite page-by-page
    # sourcing (300-400 chars), so TEXT, not the original VARCHAR(255).
    doctrine_source = Column(Text)
    as_of = Column(String(64))
    # Doctrinal disposition norms for THIS force type, in kilometers —
    # the placement engine reads them when arraying an instance's
    # subordinates (frontage across the threat-facing axis, echeloned
    # in depth). Values come from the doctrine library extraction
    # (ATP 7-100.x threat norms; US FM/ATP norms), recorded with their
    # source in doctrine_source. NULL = doctrine states no value at
    # this echelon; the engine falls back to echelon defaults.
    frontage_defense_km = Column(Float)
    depth_defense_km = Column(Float)
    frontage_offense_km = Column(Float)
    depth_offense_km = Column(Float)
    source = Column(String(16), nullable=False, server_default="user")
    # The subtree root; nullable while a template is being assembled.
    root_node_id = Column(UUID(as_uuid=True))
    created_by = Column(String(255))
    updated_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("source IN ('bundled', 'user')", name="ck_force_templates_source"),
    )


# ASCOPE — the closed category vocabulary an entity may be tagged with
# (2026-07-27 ruling: ASCOPE tags REFERENTS — what a thing is — one layer
# up from the PMESII facets that tag clause statements). A matrix cell is
# the mechanical join across the two tag layers: entities tagged <column>
# that are subjects of clauses tagged <row>.
ASCOPE_CATEGORIES = ("areas", "structures", "capabilities",
                     "organizations", "people", "events")


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey("force_templates.id", ondelete="CASCADE"), nullable=True, index=True)

    entity_type = Column(String(64), ForeignKey("entity_types.type_key"), nullable=False)
    # Set when this entity IS an individual piece of equipment (this
    # tank, this TELAR): identity/parameters/symbol come from the
    # catalog row; crew rides the personnel columns; ammo/components
    # are holdings ON the instance.
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id"), nullable=True)

    # Reserved for the future mirrored source (consumed mode is NOT
    # designed yet — columns only, per design decision 19).
    external_id = Column(Text, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)

    name = Column(String(512), nullable=False)
    long_name = Column(String(1024))
    affiliation = Column(String(16), nullable=False, server_default="Unknown")
    category = Column(String(64))
    # Generic geometry: POINT for units/facilities, LINESTRING/POLYGON
    # for control measures and linear infrastructure (phase lines,
    # boundaries, engagement areas, LOCs). The paint plane renders all
    # of them; the record stores all of them.
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=True)
    posture = Column(Text)
    organic_parent_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="SET NULL"), nullable=True)

    # Force columns (movable types; nullable everywhere — a garrisoned
    # site or an equipment instance's crew may carry them). TEXT, not
    # VARCHAR(255): the htfs_ org-guide templates carry rich functional-role
    # descriptions in unit_type (staff-section duties, etc.).
    unit_type = Column(Text)
    echelon = Column(String(32))
    personnel_authorized = Column(Integer)
    personnel_current = Column(Integer)
    personnel_killed = Column(Integer, server_default=text("0"))
    personnel_wounded = Column(Integer, server_default=text("0"))
    personnel_captured = Column(Integer, server_default=text("0"))

    combat_effectiveness = Column(String(16))
    assessment_basis = Column(Text)
    significance = Column(String(8))
    significance_note = Column(Text)
    current_activity = Column(Text)
    notes = Column(Text)
    template_key = Column(String(255))
    # The source stated this unit's COMPLETE equipment table (an MTOE):
    # template default equipment does not apply to it at all. False =
    # source spoke partially or not at all; template defaults layer
    # underneath whatever the source states.
    holdings_complete = Column(Boolean, server_default=text("false"))
    # §6.7 volumes-as-extrusions: airspace measures carry an altitude
    # block on 2D geometry (a corridor's floor and ceiling). Meters MSL.
    altitude_floor_m = Column(Float)
    altitude_ceiling_m = Column(Float)
    # DRAFT-LAYER MODEL (fifth edition §2.2): rows a generation writes
    # carry origin_record_id + layer='draft' and are invisible to every
    # default read; APPROVE flips layer to 'project' (the merge);
    # superseding an approved edition flips its rows to 'superseded'.
    # Rows are NEVER deleted — layer flags only. Ordinary writes default
    # to 'project' and carry no origin.
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)
    # Doctrinal sub-type discriminator for kinds whose PAINT dispatches
    # on it (obstacle: minefield/road_block/abatis/... via the catalog's
    # subkind_from_property contract; FSCM subkinds may adopt it later).
    # A TYPED column, not a NodeField — design decision 16 promotes any
    # field paint must read.
    subkind = Column(String(64))
    # Mock-target marking (2026-07-22 ruling): a marked entity is an
    # ORDINARY entity with a marking FIELD — never a separate kind,
    # read, or store. NULL = unmarked; non-null carries the marking
    # label the exercise assigns. entities:marked reads filter on it.
    marking = Column(Text)
    # ASCOPE categories of the REFERENT (2026-07-27 ruling): what this
    # thing IS in civil-considerations terms (ASCOPE_CATEGORIES below).
    # Stamped by the ingestion agent at ingestion (propagated from the
    # occurrence at alias resolution), corrected/backfilled through the
    # repair surface. NEVER derived from entity_type — the kind
    # vocabulary is open and a kind->category registry cannot exist.
    # NULL = unstated; an unstated entity joins no ASCOPE column read.
    ascope = Column(ARRAY(Text))

    # Analyst symbol picker SELECTION; null = derived at paint time.
    # No SIDC is ever stored (design decision 11).
    symbol_set = Column(String(2))
    symbol_entity_code = Column(String(10))
    symbol_mod1 = Column(String(2))
    symbol_mod2 = Column(String(2))

    created_by = Column(String(255))
    updated_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "(project_id IS NULL) != (template_id IS NULL)",
            name="ck_graph_nodes_one_scope",
        ),
        CheckConstraint(
            "affiliation IN ('Friend', 'Hostile', 'Neutral', 'Unknown')",
            name="ck_graph_nodes_affiliation",
        ),
        CheckConstraint(_in("category", CATEGORIES), name="ck_graph_nodes_category"),
        CheckConstraint(_in("echelon", ECHELONS), name="ck_graph_nodes_echelon"),
        CheckConstraint(_in("posture", POSTURES), name="ck_graph_nodes_posture"),
        CheckConstraint(_in("combat_effectiveness", EFFECTIVENESS), name="ck_graph_nodes_effectiveness"),
        CheckConstraint(_in("significance", SIGNIFICANCE), name="ck_graph_nodes_significance"),
        Index(
            "ux_graph_nodes_project_external",
            "project_id", "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )


class GraphEdge(Base):
    """Typed, dated, directed. ONE row per relationship; direction is a
    write contract (from = subordinate/dependent as the type's label
    reads, to = superior/provider); the inverse reading renders from
    relationship_types.inverse_label. Open = effective_to IS NULL.

    One-open-hierarchical-parent per from_id and the cycle check are
    enforced in the write path inside the transaction (the predicate is
    registry-driven — is_hierarchical lives on relationship_types — so
    a static partial index cannot express it)."""
    __tablename__ = "graph_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    to_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String(64), ForeignKey("relationship_types.type_key"), nullable=False)
    effective_from = Column(DateTime(timezone=True), default=datetime.utcnow)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True))


class GraphHolding(Base):
    """AGGREGATE holdings: a count of a catalog type on any entity —
    a battalion's guns, a SAM site's launchers, a tank instance's ammo.
    An individual system that matters is a GraphNode with weg_id
    instead (design decision 21)."""
    __tablename__ = "graph_holdings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id"), nullable=True)
    # Audit + unresolved capture only — never a join key.
    nomenclature_raw = Column(Text)
    count_authorized = Column(Integer)
    count_current = Column(Integer)
    # BDA (FM 3-60 2-72), cumulative.
    count_degraded = Column(Integer, server_default=text("0"))
    count_neutralized = Column(Integer, server_default=text("0"))
    count_destroyed = Column(Integer, server_default=text("0"))
    count_captured_abandoned = Column(Integer, server_default=text("0"))
    created_by = Column(String(255))
    updated_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index(
            "ux_graph_holdings_node_weg",
            "node_id", "weg_id",
            unique=True,
            postgresql_where=text("weg_id IS NOT NULL"),
        ),
    )


class GraphNodePosition(Base):
    """APPEND-ONLY position observation — one timestamped fix of where an
    entity was. A road to war NARRATES a unit moving through positions over
    time (tactical assembly area -> forward staging -> final attack
    position); each dated position is an observation here, never
    overwritten. The entity's CURRENT position is the row with the greatest
    observed_at (mirrored to graph_nodes.geom for the default paint path);
    timeline SCRUB/REPLAY reads the latest observation with observed_at <=
    the scrub time. Disposition (IPOE 5-27 — arraying forces INCLUDING
    movement history) is a first-class stored fact, not a discarded one."""
    __tablename__ = "graph_node_positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    # Generic like graph_nodes.geom — a FRAGO can redraw a phase line;
    # that redraw is an append-only observation like any reposition.
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=True)
    mgrs = Column(String(32))
    location_text = Column(Text)              # named place / FAA / description
    # The DTG — the record's ONE temporal dimension (2026-07-21 ruling).
    # NEVER null: a stated DTG carries the source's time; an unstated
    # assertion is stamped at the moment it is made (track.py). The
    # created_at column below is ingest bookkeeping only — never
    # resolved, replayed, or surfaced.
    observed_at = Column(DateTime(timezone=True), index=True,
                         nullable=False)
    dtg_label = Column(String(64))            # raw DTG string as written
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True))
    activity = Column(Text)                   # posture/activity at that time
    # Full provenance citation (document + entry, inference basis,
    # grid-vs-prose conflict note) — TEXT, not a short varchar (rich
    # citations overflowed VARCHAR(255) and blocked control-measure
    # writes).
    source = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_graph_node_positions_node_obs", "node_id", "observed_at"),
    )

    # §6.7 observables: the two values energy state derives from at
    # reasoning time. Z is meters MSL; ground entities omit both.
    altitude_m = Column(Float)
    speed_kph = Column(Float)

class NodeField(Base):
    """Extensible field VALUE on an entity. Description only —
    derivations, joins, and paint never read these; a fact code needs
    gets promoted to a real column (design decision 16)."""
    __tablename__ = "graph_node_fields"

    node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), primary_key=True)
    field_key = Column(String(128), ForeignKey("field_defs.field_key"), primary_key=True)
    value = Column(Text, nullable=False)
    created_by = Column(String(255))
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EdgeField(Base):
    __tablename__ = "graph_edge_fields"

    edge_id = Column(UUID(as_uuid=True), ForeignKey("graph_edges.id", ondelete="CASCADE"), primary_key=True)
    field_key = Column(String(128), ForeignKey("field_defs.field_key"), primary_key=True)
    value = Column(Text, nullable=False)
    created_by = Column(String(255))
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GraphSnapshot(Base):
    """Full-project graph snapshot — the recovery net for bulk writers.
    Captured AUTOMATICALLY before every document ingest and every wipe
    (and on demand), so a wrong-file ingest into a hand-curated event is
    one restore away instead of permanent damage. payload holds complete
    row dumps (nodes, edges, holdings, positions, node fields, episodic
    clauses) with geometry as WKT; restore deletes the project's current
    rows and re-inserts, auto-capturing a pre_restore snapshot first so
    restore itself is undoable."""
    __tablename__ = "graph_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    label = Column(String(255))
    trigger = Column(String(32), nullable=False, server_default="manual")
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    payload = Column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('pre_ingest', 'pre_wipe', 'pre_restore', 'manual')",
            name="ck_graph_snapshots_trigger",
        ),
    )


class SourceDocument(Base):
    """L0 for the episodic register: the verbatim text of every ingested
    document, per project — the provenance root a clause's source_locus
    names, so Sources can quote the actual document instead of pointing
    at a filename that left the building."""
    __tablename__ = "source_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    doc_text = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True))

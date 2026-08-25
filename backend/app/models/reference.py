"""Reference registries + WEG equipment catalog (entity graph).

Reference data beside the record: entity/relationship kinds, extensible
field defs, and the WEG-derived equipment catalog. All are seeded
through the versioned seed machinery (reference_seed_meta; baselines as
LIKE-tables created in the lifespan bootstrap) and edited via API —
never by file rebuild or redeploy.

Invariant (design §3.5): code branches on registry COLUMNS (is_fixed,
is_hierarchical, symbol mapping), never on type_key. Structural columns
(is_fixed, is_hierarchical, value_type) are immutable once referenced —
enforced in the write path.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
import uuid

from app.models.base import Base

FIELD_VALUE_TYPES = ("text", "number", "timestamp", "boolean")
VERIFICATION_STATUSES = ("curated", "extracted", "unverified")


class EntityType(Base):
    __tablename__ = "entity_types"

    type_key = Column(String(64), primary_key=True)
    label = Column(String(255), nullable=False)
    # Link-view display; deterministic fallback palette when null.
    color = Column(String(16))
    # THE structural discriminator: movable force vs fixed
    # infrastructure. Every mechanical branch keys on this column.
    is_fixed = Column(Boolean, nullable=False)
    # Default symbol mapping: fixed types map to 2525E set-20
    # installation entities; movable types leave null (units derive
    # from holdings + echelon; equipment instances from their catalog
    # row).
    symbol_set = Column(String(2))
    symbol_entity_code = Column(String(10))
    default_category = Column(String(64))
    source = Column(String(16), nullable=False, server_default="user")
    created_by = Column(String(255))
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("source IN ('bundled', 'user')", name="ck_entity_types_source"),
    )


class RelationshipType(Base):
    __tablename__ = "relationship_types"

    type_key = Column(String(64), primary_key=True)
    # label reads from -> to ("supplies"); inverse_label reads
    # to -> from ("depends on"). ONE stored row per relationship.
    label = Column(String(255), nullable=False)
    inverse_label = Column(String(255), nullable=False)
    color = Column(String(16))
    # True: task-org overlay + walk-up cycle check; false: network
    # annotation, cycles legal.
    is_hierarchical = Column(Boolean, nullable=False)
    source = Column(String(16), nullable=False, server_default="user")
    created_by = Column(String(255))
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("source IN ('bundled', 'user')", name="ck_relationship_types_source"),
    )


class FieldDef(Base):
    """Extensible-field registry. Fields are DESCRIPTION — derivations,
    joins, and paint never read them (design decision 16)."""
    __tablename__ = "field_defs"

    field_key = Column(String(128), primary_key=True)
    label = Column(String(255), nullable=False)
    value_type = Column(String(16), nullable=False, server_default="text")
    source = Column(String(16), nullable=False, server_default="user")
    created_by = Column(String(255))
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "value_type IN ('text', 'number', 'timestamp', 'boolean')",
            name="ck_field_defs_value_type",
        ),
        CheckConstraint("source IN ('bundled', 'user')", name="ck_field_defs_source"),
    )


class WegEquipment(Base):
    __tablename__ = "weg_equipment"

    # Edition-independent canonical system identity (design §3.4).
    weg_id = Column(String(128), primary_key=True)
    name = Column(String(512), nullable=False)
    domain = Column(String(32))
    equipment_class = Column("class", Text)
    # The SOURCE's classification hierarchy: category is the leaf,
    # category_group the level above it, category_path the whole walk.
    # (The merge's extraction bins are NOT a taxonomy and never land here.)
    category = Column(Text)
    category_group = Column(Text)
    category_path = Column(JSONB)
    # The seed DEFAULT engagement range (the is_default range candidate).
    # This is REFERENCE data — immutable at runtime. An analyst's
    # per-map range choice is PROJECT config that layers on top at paint
    # time (map.attrs.equipment_range_overrides), never written back
    # here. The catalog is rebuilt wholesale from the authoritative seed.
    engagement_range_m = Column(Integer)
    detection_range_m = Column(Integer)
    road_speed_kph = Column(Integer)
    # Full crew breakdown as the sheet states it (string, e.g.
    # "(driver, commander, gunner): 3") — not just a count.
    crew = Column(Text)
    # Real caliber only (or null) — NEVER a blob. The cleaned seed
    # splits caliber from the sheet body.
    caliber = Column(Text)
    # Full sheet characteristics / prose description (the WEG page body).
    characteristics = Column(Text)
    # WEG sheet header fields, captured in the total extraction.
    # country_of_origin is the joined display string; countries is the
    # canonical per-country ORIGIN list and operators the canonical
    # PROLIFERATION list — two distinct filter axes, both read by the
    # facet/filter machinery.
    country_of_origin = Column(Text)
    countries = Column(JSONB)
    operators = Column(JSONB)
    introduction_year = Column(Integer)
    # Wikipedia-style figure list: every image the record carries, with
    # name, object path, origin (live original / PDF extraction), and
    # licence/author where the source states them.
    images = Column(JSONB)
    # Everything searchable about the record in one lowercase text blob
    # (name, designations, origin, operators, description, every
    # specification label and value) — the q filter reaches CONTENT, not
    # just names, for humans and the agent tools alike. GIN trigram
    # indexed at bootstrap.
    search_blob = Column(Text)
    alternative_designations = Column(Text)
    date_of_introduction = Column(Text)
    proliferation_note = Column(Text)
    combat_weight = Column(Text)
    # Prose Description paragraph(s) from the sheet.
    description = Column(Text)
    # The complete-seed catch-all (design: schema adapts to data, data
    # is never trimmed to schema). Holds the sheet's every performance /
    # specification field (`specs`), non-uniform leftovers
    # (`sheet_extras`), and `raw_sheet_text` verbatim — so nothing the
    # sheet carries is ever lost even before it has a promoted column.
    sheet_data = Column(JSONB)
    symbol_entity_code = Column(String(10))
    symbol_mod1 = Column(String(2))
    symbol_mod2 = Column(String(2))
    image_path = Column(Text)
    # No verification tier exists (decision 24): WEG data IS verified
    # data. Paint gates on VALUE PRESENCE only.
    source_page = Column(Text)
    source = Column(String(16), nullable=False, server_default="user")
    updated_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("source IN ('weg_import', 'user')", name="ck_weg_equipment_source"),
    )


class WegEquipmentAlias(Base):
    __tablename__ = "weg_equipment_aliases"

    alias = Column(String(512), primary_key=True)
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id", ondelete="CASCADE"), nullable=False, index=True)


class WegEquipmentEmitter(Base):
    """Component rows — a Pantsir is a weapon WITH radars. Detection
    rings derive from emitter presence on any weg_id reference.
    emitter_type is TEXT: extraction rows carry full descriptive
    strings (a 143-char LTAMDS description overflowed the old
    VARCHAR(128) and silently dropped the whole system row)."""
    __tablename__ = "weg_equipment_emitters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id", ondelete="CASCADE"), nullable=False, index=True)
    # Extraction emits descriptive band/type text (ELINT sheets carry
    # multi-band strings) — keep these wide.
    emitter_type = Column(Text)
    frequency_band = Column(String(255))
    frequency_ghz = Column(Float)
    sweep_rate_rpm = Column(Float)
    effective_range_km = Column(Float)
    tracking_range_km = Column(Float)
    effective_altitude_km = Column(Float)
    max_tracks = Column(Integer)
    emplacement_min = Column(Integer)
    displacement_min = Column(Integer)


class WegEquipmentRangeCandidate(Base):
    """Every range figure the WEG sheet carries — ALL of them, exposed
    as mutually exclusive toggles. Each is a real effective range
    under some scenario (decision 24): `condition` tags the scenario
    (standard/minimum/day/night/extended/variant/...), `is_default`
    marks the most applicable one, which the loader applies to
    weg_equipment.engagement_range_m so fans paint by default with
    clear visibility of WHICH range is showing. The map's
    attrs.range_condition (weather hook) re-resolves fans to a
    condition-matched candidate at paint time."""
    __tablename__ = "weg_equipment_range_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    range_m = Column(Integer, nullable=False)
    # The verbatim scenario qualifier from the sheet — a full descriptive
    # string in the v2 capture ("apfsds-t, day (band minimum, printed
    # 1200-1500)"), so TEXT, not the original VARCHAR(32).
    condition = Column(Text)
    is_default = Column(Boolean, nullable=False, server_default="false")
    # §6.7: envelopes generalize rings — the altitude band and
    # trajectory class make the 2D ring the ground-plane slice of the
    # is_default envelope.
    min_altitude_m = Column(Integer)
    max_altitude_m = Column(Integer)
    trajectory = Column(String(16))  # direct|ballistic|cruise|loiter

class WegEquipmentVariant(Base):
    __tablename__ = "weg_equipment_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    weg_id = Column(String(128), ForeignKey("weg_equipment.weg_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(512), nullable=False)
    note = Column(Text)


class ReferenceSeedMeta(Base):
    """One row per seeded reference set (weg_catalog, entity_types,
    relationship_types, field_defs, force_templates). Boot compares
    seed_version instead of emptiness; upgrade is per-column three-way
    against the retained *_seed_baseline LIKE-tables (design §3.4)."""
    __tablename__ = "reference_seed_meta"

    registry = Column(String(64), primary_key=True)
    seed_version = Column(String(64), nullable=False)
    checksum = Column(String(128))
    seeded_at = Column(DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------
# The world-model reference store (design weg-catalog-schema-design.md S6).
#
# An IMMUTABLE reference graph, rebuilt wholesale from seed, that the project/
# event graph interconnects into by weg_id. Parallel to graph_nodes/graph_edges
# by design (S10 physical partition): a wholesale seed rebuild here is
# physically incapable of touching live project rows. The existing consumer
# tables (weg_equipment + child tables) are MATERIALIZED from this store at
# seed time (S10/F3 migration by projection), so every current consumer keeps
# reading exactly what it reads today.
#
# Object types (reference_nodes.object_type): equipment / weapon / munition /
# component (registered in entity_types). Link types (reference_links.link_type):
# mounts / fires / equipped_with / variant_of / component_of / associated_with
# (registered in relationship_types). Specs are (value, condition) tuples scoped
# to an object OR a link (F1). Clauses are the L1 layer — atomic NL assertions,
# entity-indexed by the keys they are ABOUT, embedding reserved but unused (F6).
# --------------------------------------------------------------------------

REFERENCE_OBJECT_TYPES = ("equipment", "weapon", "munition", "component")
SPEC_OWNER_KINDS = ("object", "link")
CLAUSE_REGISTERS = ("gnomic", "episodic", "predictive")


class ReferenceNode(Base):
    """A reference object: a fielded platform (equipment), a shared weapon, a
    munition/round, or a mounted component. Keyed by a stable edition-
    independent string (weg_id-style for catalog roots; a synthesized key for
    minted sub-objects). sheet_data holds the verbatim capture so nothing the
    source carries is ever lost (F8)."""
    __tablename__ = "reference_nodes"

    key = Column(String(256), primary_key=True)
    object_type = Column(String(64), ForeignKey("entity_types.type_key"), nullable=False)
    name = Column(Text, nullable=False)
    # TEXT, not VARCHAR(128): citations and provenance are extracted
    # verbatim from the sources and must never truncate a seed (a
    # single overlong derived field skipped the ENTIRE bootstrap).
    country_of_origin = Column(Text)
    date_of_introduction = Column(Text)
    source_page = Column(Text)
    # The verbatim captured row (datasheet sheet{} / narrative
    # stated{}+prior_curation{}) for catalog roots; the captured sub-record for
    # minted objects. The provenance root (L0) — never trimmed to the schema.
    sheet_data = Column(JSONB)
    image_path = Column(Text)
    # Catalog roots are the 799 original weg_ids projected to weg_equipment;
    # minted weapon/munition/component/variant nodes are False.
    is_catalog_root = Column(Boolean, nullable=False, server_default="false")
    source = Column(String(16), nullable=False, server_default="weg_import")

    __table_args__ = (
        Index("ix_reference_nodes_object_type", "object_type"),
        Index("ix_reference_nodes_catalog_root", "is_catalog_root"),
    )


class ReferenceLink(Base):
    """A directional reference relationship carrying the frame's elements as
    properties (S6.2). from_key is always a reference object; to_key resolves
    to a reference object when one exists, else to_name_raw carries the prose
    sub-component name until curation mints an object (S6.2)."""
    __tablename__ = "reference_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_key = Column(String(256), ForeignKey("reference_nodes.key", ondelete="CASCADE"), nullable=False, index=True)
    to_key = Column(String(256), ForeignKey("reference_nodes.key", ondelete="SET NULL"), nullable=True, index=True)
    to_name_raw = Column(Text)
    link_type = Column(String(64), ForeignKey("relationship_types.type_key"), nullable=False, index=True)
    # Weapon station (main / coax / aux / roof / atgm) or component/assembly
    # role (radar / command / reload / host / sensor / fire_control / payload).
    station = Column(String(64))
    role = Column(String(64))
    count = Column(Integer)
    is_primary = Column(Boolean, nullable=False, server_default="false")
    is_default = Column(Boolean, nullable=False, server_default="false")
    props = Column(JSONB)


class ReferenceSpec(Base):
    """A typed (value, condition) tuple scoped to a reference object OR a
    reference link (F1). Ranges/envelopes, armor, speeds, weights, dimensions,
    and temporal-performance figures that feed reachability. Envelope columns
    (min/max altitude, trajectory) generalize the 2D range ring into the 3D
    engagement/detection envelope (S6.7); the ground-plane slice of the
    is_default engagement spec is what paint reads today."""
    __tablename__ = "reference_specs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_kind = Column(String(8), nullable=False)
    owner_id = Column(String(256), nullable=False)
    attribute = Column(String(128), nullable=False)
    value_num = Column(Float)
    value_text = Column(Text)
    unit = Column(String(64))
    condition = Column(Text)
    min_altitude_m = Column(Float)
    max_altitude_m = Column(Float)
    trajectory = Column(String(32))
    is_default = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        CheckConstraint("owner_kind IN ('object', 'link')", name="ck_reference_specs_owner_kind"),
        Index("ix_reference_specs_owner", "owner_kind", "owner_id"),
        Index("ix_reference_specs_attribute", "attribute"),
    )


class FactClause(Base):
    """L1 clause store: an atomic natural-language assertion carrying its text,
    the object/template keys it is ABOUT, temporal bounds where stated, and a
    pointer to its L0 locus (S4.4, S6.5). register distinguishes gnomic
    (statements about types — catalog + doctrine), episodic (about instances),
    and predictive (future valid time). The embedding column is reserved and
    UNUSED in v1 — nothing depends on pgvector existing on staging (F6)."""
    __tablename__ = "fact_clauses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text = Column(Text, nullable=False)
    register = Column(String(16), nullable=False, server_default="gnomic")
    # Speaker/evidential provenance (F9) and the kind of source it came from
    # (weg_catalog / doctrine / document_ingest / ...), used to scope
    # wholesale rebuilds and to attribute statements in the UI.
    speaker = Column(String(128))
    source_kind = Column(String(32), nullable=False, server_default="weg_catalog")
    source_locus = Column(Text)
    about = Column(ARRAY(Text), nullable=False, server_default="{}")
    valid_from = Column(DateTime(timezone=True))
    valid_to = Column(DateTime(timezone=True))
    observed_at = Column(DateTime(timezone=True))
    # Episodic-register columns. project_id scopes episodic clauses to one
    # project/event (gnomic reference clauses stay NULL — they are global).
    # slot is the updatable-state key ("<entity>.<attribute>") that drives
    # deterministic bitemporal supersession; kind mirrors the extraction
    # taxonomy (state | event | preference | task); superseded_by points at
    # the clause that invalidated this one. created_at is the system-time
    # bookkeeping stamp (observed_at remains the in-world known-time axis).
    project_id = Column(UUID(as_uuid=True), index=True)
    # Draft-layer model: engine-written clauses ride layer='draft' with
    # their origin record until approve merges them (layer flags only,
    # rows never deleted).
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)
    slot = Column(Text)
    kind = Column(String(16))
    superseded_by = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    # Typed observation payload — a state observation carries its value
    # so the node column can MIRROR the chain's current value (the
    # position-track pattern generalized to attributes). text remains
    # the human sentence; value_text/value_num are what mirrors read.
    value_text = Column(Text)
    value_num = Column(Float)
    # Reserved for semantic retrieval; nullable and never written in v1 so the
    # build has zero pgvector dependency (F6). A future migration types this to
    # a pgvector column once the extension is provisioned.
    embedding = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "register IN ('gnomic', 'episodic', 'predictive')",
            name="ck_fact_clauses_register",
        ),
        Index("ix_fact_clauses_source_kind", "source_kind"),
        Index("ix_fact_clauses_about", "about", postgresql_using="gin"),
    )

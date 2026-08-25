"""World-model provenance and ingestion records — the L0/L1/L2 rewrite.

Design of record: scratch/docs/oob/tool-surface-consolidation.md
(S3 source model, S4 provenance/time/lifecycle, S5 product branch,
S6 ingestion run) grounded on the ontology
scratch/docs/oob/weg_schema/weg-catalog-schema-design.md
(S4.4 three layers, S6 structure, S10 decisions).

Why this module exists: the prior ingestion (services/graph_ingest) minted
L2 typed rows (graph_nodes / graph_edges / graph_holdings) with no L1 clause
and no L0 locus, and it stored whole sections AS clauses. That collapsed the
three layers and left the 2CR ORBAT with zero document-derived facts, so no
product could cite it. This module lands the real layering:

    L0  Source / SourceRevision / SourceView         immutable capture
          |  segmentation + attribution
    L1  Section  ->  Clause  ->  EntityOccurrence     verbatim passage,
          |  parsing                                   atomic assertion,
    L2  Assertion  ---materializes-->                  section-local occurrence
          graph_edge / graph_holding / graph_node property / position

Every Assertion carries its basis back to the Clause(s) that support it, each
Clause back to its Section, each Section back to its SourceRevision — the
L2 -> L1 -> L0 chain the ontology is built on ("nothing exists only in L2",
ontology S4.4). Sections and clauses are DISTINCT records and never substitute
for one another (design S2 invariant 22): a verbatim product field reads
Section.text; Clause.text is an atomic interpretation and is never the passage.

The L2 typed objects themselves stay in graph.py (GraphNode / GraphEdge /
GraphHolding / GraphNodePosition); this module adds the provenance layer
beneath them, the occurrence + alias-resolution model, first-class assertions,
ingestion runs with run-scoped staging, and product branches.

Built alongside the legacy source_documents (L0) and fact_clauses (L1) during
the parallel-run + reconciliation period (design S15). Table names are
descriptive and distinct from the legacy tables; cutover retires the legacy
pair after the reconciliation is verified.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.models.base import Base

# ---------------------------------------------------------------------------
# Closed sets
# ---------------------------------------------------------------------------

# The immutable origin a Section derives from (design S3.3). Exactly one form
# per Section; the columns for the other two stay NULL.
SECTION_ORIGIN_KINDS = ("external_source", "field_snapshot", "product_artifact")

# PMESII-PT — the closed facet vocabulary a Clause may be tagged with
# (2026-07-27 ruling: facets tag STATEMENTS, at the clause layer). Closable
# because it is doctrinally fixed at eight; the entity-kind vocabulary is
# open (mint-on-first-use) and therefore can never carry facet defaults.
PMESII_FACETS = ("political", "military", "economic", "social",
                 "information", "infrastructure", "physical_environment",
                 "time")

# A SourceView is one system-defined presentation unit (design S3.2). The whole
# unit is the smallest visual provenance grain; the agent never crops a region.
SOURCE_VIEW_KINDS = ("page", "slide", "sheet", "image", "frame", "interval")

# What an Assertion asserts (design S3.6). property/state ride a subject + an
# attribute + a value; relationship rides from/to/relation; holding is a count;
# position is a located observation. All four are first-class provenance
# records; each may MATERIALIZE the matching legacy L2 row for fast traversal.
ASSERTION_KINDS = ("property", "state", "relationship", "holding", "position")

# An ingestion run ingests exactly one kind of thing (design S6, S7.1). An
# external-source run reads source views; a stored-section run attaches
# semantics to system-created branch Sections.
INGESTION_MODES = ("external_source", "stored_section")

# One system-owned queue; at most one active run (design S2 invariant 24).
INGESTION_STATES = (
    "queued", "active", "resolving", "reviewing", "committing",
    "complete", "failed", "cancelled",
)

# Where a completed run commits its staged content (design S2 invariant 8).
COMMIT_DESTINATIONS = ("project", "product_branch")

# Product-branch lifecycle is system-owned runtime progress, NOT epistemic
# validity (design S4.5). The analyst-facing product lifecycle (draft / final /
# approved) lives on the product record; this tracks the branch merge state.
BRANCH_LIFECYCLES = ("open", "generating", "draft", "final", "merged", "abandoned")

# Register of a clause (ontology S4.6, S6.5): gnomic = about types / doctrine;
# episodic = about project instances; predictive = future valid time.
CLAUSE_REGISTERS = ("gnomic", "episodic", "predictive")

# Staged vs committed. Pre-resolution staged rows are physically removable;
# committed rows are history-preserving (design S4.5, S9.3).
RECORD_STATES = ("staged", "committed")


# ---------------------------------------------------------------------------
# L0 — source, revision, view
# ---------------------------------------------------------------------------

class Source(Base):
    """Durable source identity (design S3.1). A Source is the thing; a
    SourceRevision is one immutable capture of it. Documents are ONE subkind
    of source, not the whole of L0."""
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    # Human identity of the source, carried across revisions when known.
    title = Column(Text)
    issuer = Column(Text)
    author = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)


class SourceRevision(Base):
    """One immutable capture of a Source (design S3.1). Raw bytes are the
    fidelity anchor; everything extracted from them is re-runnable and
    correctable without touching this row."""
    __tablename__ = "source_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)

    # Raw bytes live in object storage (MinIO primary, S3 mirror); this is the
    # storage handle, not the bytes.
    object_ref = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    media_type = Column(String(128))
    encoding = Column(String(64))
    size_bytes = Column(Integer)
    filename = Column(String(512))

    # Source-stated metadata, when present. NOT a memory time axis (design
    # S4.2): issue/publication times remain source metadata here.
    title = Column(Text)
    issuer = Column(Text)
    author = Column(Text)
    issue_time = Column(DateTime(timezone=True))

    # Capture bookkeeping.
    capture_time = Column(DateTime(timezone=True), default=datetime.utcnow)
    capture_actor = Column(String(255))
    capture_run = Column(UUID(as_uuid=True))
    # The presentation build (renderer version) that produced the views; a new
    # rendering version reissues stable-within-version view references.
    rendering_version = Column(String(64))

    __table_args__ = (
        # A byte-identical recapture of the same source is the same revision.
        UniqueConstraint("source_id", "sha256", name="ux_source_revisions_source_hash"),
    )


class SourceView(Base):
    """One system-defined presentation unit of a revision — a page, slide,
    sheet, image, frame, or interval (design S3.2). The opaque reference is
    stable within its revision + rendering version. It is a provenance handle,
    never a character offset or a crop; a view carrying several figures keeps
    one reference and the Sections/Clauses distinguish its content."""
    __tablename__ = "source_views"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_revision_id = Column(UUID(as_uuid=True), ForeignKey("source_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    # Server-assigned position within the revision, and the human label.
    ordinal = Column(Integer, nullable=False)
    label = Column(String(128))
    # Optional multimodal embedding of the view (design S3.8); reserved,
    # nullable, never written in v1 (no pgvector dependency).
    embedding = Column(Text)

    __table_args__ = (
        UniqueConstraint("source_revision_id", "ordinal", name="ux_source_views_revision_ordinal"),
        CheckConstraint(
            "kind IN ('page', 'slide', 'sheet', 'image', 'frame', 'interval')",
            name="ck_source_views_kind",
        ),
    )


# ---------------------------------------------------------------------------
# L1 — heading hierarchy, section, clause, occurrence
# ---------------------------------------------------------------------------

class HeadingOccurrence(Base):
    """A resolved heading in a source's hierarchy (design S3.3). The server
    resolves each Section's copied heading list against the active path from
    the preceding asserted Section: it reuses the longest common active prefix
    and mints occurrences for the remaining suffix. Equal heading text outside
    the active path never merges globally, and similarity is never used to
    resolve headings. This resolves structure the model DECLARED; it does not
    parse the source."""
    __tablename__ = "heading_occurrences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_revision_id = Column(UUID(as_uuid=True), ForeignKey("source_revisions.id", ondelete="CASCADE"), nullable=True, index=True)
    # A stored-section (generated-product) heading path is template-owned and
    # scoped to the branch instead of a source revision.
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("heading_occurrences.id", ondelete="CASCADE"), nullable=True, index=True)
    text = Column(Text, nullable=False)
    depth = Column(Integer, nullable=False)
    # Server-assigned sibling order under the same parent.
    order_index = Column(Integer, nullable=False)


class Section(Base):
    """One complete coherent passage (design S3.3). In an external source the
    multimodal ingestion agent identifies it; for generated analytical prose
    the product engine creates it mechanically from the immutable field
    snapshot before rendering; during FINAL, safely aligned edited text
    produces one from the locked artifact revision.

    A Section stores its own VERBATIM text (the passage), copied heading path,
    every source-view it appears on, an origin-local sequence, and a text hash.
    A verbatim product field reads Section.text directly; a Clause is never
    used as the passage (design S2 invariant 22)."""
    __tablename__ = "sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Exactly one immutable origin (design S3.3). The kind discriminator says
    # which of the three ref columns is populated.
    origin_kind = Column(String(24), nullable=False)
    # external_source: the revision + a server-assigned source occurrence.
    source_revision_id = Column(UUID(as_uuid=True), ForeignKey("source_revisions.id", ondelete="CASCADE"), nullable=True, index=True)
    # field_snapshot / product_artifact origins reference product-engine rows
    # landed with the product-DAG bridge (design S12); the discriminator and
    # anchor carry them until those FKs are wired at that milestone.
    field_snapshot_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    product_artifact_revision_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # Template field anchor or document anchor for the generated origins.
    origin_anchor = Column(Text)

    # Scope: an external section is project-scoped once committed; a
    # system-created product section is branch-owned.
    project_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)

    # Copied heading list, outermost -> innermost, WITHOUT levels/keys/order
    # numbers (design S3.3); empty array for an unheaded passage. Array
    # position expresses depth. The resolved hierarchy leaf is heading_leaf_id.
    headings = Column(ARRAY(Text), nullable=False, server_default="{}")
    heading_leaf_id = Column(UUID(as_uuid=True), ForeignKey("heading_occurrences.id", ondelete="SET NULL"), nullable=True)

    # The complete passage. May be empty when the content is purely visual;
    # the view references and clauses still make it searchable.
    body_text = Column(Text, nullable=False, server_default="")
    text_hash = Column(String(64), nullable=False)

    # Origin-local ordering: server-assigned assertion order for an external
    # source, product-engine field/document order for a stored section.
    origin_sequence = Column(Integer, nullable=False)

    creation_run_id = Column(UUID(as_uuid=True), index=True)
    extraction_model_version = Column(String(64))

    # Staging discipline (design S6, S9.3). A pre-resolution staged external
    # section is physically removable as a unit; committed sections are
    # history-preserving.
    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)

    # Draft-layer parity with graph.py: engine-written sections ride a layer
    # until approve merges them; rows are never deleted, layer flags only.
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)

    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "origin_kind IN ('external_source', 'field_snapshot', 'product_artifact')",
            name="ck_sections_origin_kind",
        ),
        CheckConstraint(
            "record_state IN ('staged', 'committed')",
            name="ck_sections_record_state",
        ),
        # Exactly the origin's own ref column is populated.
        CheckConstraint(
            "(origin_kind = 'external_source') = (source_revision_id IS NOT NULL)",
            name="ck_sections_external_ref",
        ),
        Index("ix_sections_run", "ingestion_run_id"),
        Index("ix_sections_project_seq", "project_id", "origin_sequence"),
    )


class SectionSourceView(Base):
    """A Section-to-SourceView link (design S3.3): a section spanning several
    pages carries all of their view references; a view holding several sections
    is linked from each. Only external-source sections carry views."""
    __tablename__ = "section_source_views"

    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True)
    source_view_id = Column(UUID(as_uuid=True), ForeignKey("source_views.id", ondelete="CASCADE"), primary_key=True)


class Clause(Base):
    """L1 — one atomic natural-language interpretation of a Section (design
    S3.4). Its text may restore an omitted subject, split coordinated
    statements, or normalize an embedded purpose; it need NOT be a substring
    of the section text. Its verbatim basis is the whole Section (no separate
    quote field). Two clauses with the same statement stay separate when they
    come from different revisions, sections, or views."""
    __tablename__ = "clauses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False, index=True)
    # Order of the clause within its section, as extracted.
    order_index = Column(Integer, nullable=False, server_default=text("0"))

    text = Column(Text, nullable=False)
    register = Column(String(16), nullable=False, server_default="episodic")
    # Attribution when the source attributes the statement to a speaker,
    # author, planner, or organization (design S3.4; evidentiality, ontology
    # S4.1). NULL when unattributed.
    attribution = Column(Text)
    # PMESII-PT facets of the STATEMENT (2026-07-27 ruling): a facet is a
    # property of what is being said, not of the referent — the same bridge
    # is infrastructure in a construction clause and military in an
    # obstacle-crossing clause. Stamped by the ingestion agent at
    # assert_section (the moment the interpretation is made), backfilled
    # through the repair surface, NEVER derived from a kind registry (kind
    # vocabulary is open; the facet vocabulary is the closed PMESII_FACETS).
    # NULL = untagged. Entity facet membership DERIVES through clause_about.
    pmesii = Column(ARRAY(Text))

    # Optional stated valid interval on the clause; a nested entity-value or
    # relationship interval overrides this for that assertion only (design
    # S7.6).
    valid_from = Column(DateTime(timezone=True))
    valid_to = Column(DateTime(timezone=True))

    project_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)
    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)

    # Reserved for semantic retrieval (design S3.8); nullable, never written in
    # v1 so the build has zero pgvector dependency (ontology F6).
    embedding = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "register IN ('gnomic', 'episodic', 'predictive')",
            name="ck_clauses_register",
        ),
        CheckConstraint(
            "record_state IN ('staged', 'committed')",
            name="ck_clauses_record_state",
        ),
    )


class EntityOccurrence(Base):
    """A section-local entity occurrence (design S3.5, S2 invariant 18). A name
    declared in a section's entities array creates one occurrence; the same
    designation in another section creates another. It makes NO canonical
    identity claim by matching a name or alias — every occurrence-to-entity
    binding is an ingestion-agent decision in the alias-resolution phase
    (design S2 invariant 6). Resolution sets canonical_node_id; until then the
    occurrence's dependent assertions stay pending."""
    __tablename__ = "entity_occurrences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id = Column(UUID(as_uuid=True), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False, index=True)

    # The section-local handle every entity/from/to field in that section
    # refers to; unique within the section.
    designation = Column(Text, nullable=False)
    entity_type = Column(String(64), ForeignKey("entity_types.type_key"), nullable=False)
    # Identifiers copied EXACTLY as the section states them; identity-candidate
    # signals only, never an automatic binding (design S3.5).
    identifiers = Column(ARRAY(Text), nullable=False, server_default="{}")
    # ASCOPE categories of the REFERENT (2026-07-27 ruling): what kind of
    # thing this is in civil-considerations terms (graph.ASCOPE_CATEGORIES).
    # Stated by the ingestion agent with the page in front of it; alias
    # resolution propagates the first stated value set onto the canonical
    # node when the node has none. NULL = unstated.
    ascope = Column(ARRAY(Text))

    # Set by resolve_entity_aliases: the canonical entity this occurrence binds
    # to. A project canonical entity is a graph_nodes row (its identity is
    # name + type; state/relationships are assertion-backed, graph.py).
    canonical_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="SET NULL"), nullable=True, index=True)

    extraction_run_id = Column(UUID(as_uuid=True), index=True)
    extraction_model_version = Column(String(64))
    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("section_id", "designation", name="ux_entity_occurrences_section_designation"),
        Index("ix_entity_occurrences_run", "ingestion_run_id"),
    )


class ClauseAbout(Base):
    """Clause -> occurrence ABOUT link (design S3.4, ontology S6.5). Records
    which section-local occurrences a clause concerns; the occurrence's
    supporting clauses are the reverse read. The clause layer is entity-indexed
    through this table."""
    __tablename__ = "clause_about"

    clause_id = Column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), primary_key=True)
    occurrence_id = Column(UUID(as_uuid=True), ForeignKey("entity_occurrences.id", ondelete="CASCADE"), primary_key=True)


# ---------------------------------------------------------------------------
# L2 — assertions, basis, derivations, supersession, retraction
# ---------------------------------------------------------------------------

class Assertion(Base):
    """A first-class typed proposition (design S3.6). Properties, state
    dimensions, relationships, holdings, and positions are ALL assertions; a
    relationship assertion may materialize a graph_edge for fast traversal, a
    holding a graph_holding, a position a graph_node_position, but the
    assertion remains the provenance-bearing record. This is the L2 the
    ontology means — every one carries its basis to L1 and thence to L0
    ("nothing exists only in L2").

    While an occurrence is unresolved the endpoints reference occurrences;
    resolution rewrites them to graph_nodes and materialization fills the
    matching legacy row (design S7.8). valid_from is NON-NULL for every
    project-world assertion (design S4.2 population contract)."""
    __tablename__ = "assertions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(16), nullable=False)

    project_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)

    # Subject — pending form (occurrence) and resolved form (node). property /
    # state / holding / position ride the subject; relationship rides from/to.
    subject_occurrence_id = Column(UUID(as_uuid=True), ForeignKey("entity_occurrences.id", ondelete="CASCADE"), nullable=True, index=True)
    subject_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=True, index=True)

    # relationship endpoints.
    from_occurrence_id = Column(UUID(as_uuid=True), ForeignKey("entity_occurrences.id", ondelete="CASCADE"), nullable=True)
    from_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=True)
    to_occurrence_id = Column(UUID(as_uuid=True), ForeignKey("entity_occurrences.id", ondelete="CASCADE"), nullable=True)
    to_node_id = Column(UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=True)
    relation = Column(String(64), ForeignKey("relationship_types.type_key"), nullable=True)

    # property / state payload — the attribute and its typed value; the
    # registry decides how each is stored (mirrors reference.ReferenceSpec).
    attribute = Column(String(128))
    value_text = Column(Text)
    value_num = Column(Float)
    unit = Column(String(32))
    condition = Column(Text)
    # holding count; position geometry rides the materialized row.
    count = Column(Integer)
    # free frame properties for a relationship (design S7.6 links[].properties).
    properties = Column(JSONB)

    # Bitemporal (design S4.2). valid_from NON-NULL for project-world
    # assertions (population contract); recorded_at is server-set memory time.
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True))
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # The materialized legacy L2 row this assertion projects into, if any.
    materialized_edge_id = Column(UUID(as_uuid=True), ForeignKey("graph_edges.id", ondelete="SET NULL"), nullable=True)
    materialized_holding_id = Column(UUID(as_uuid=True), ForeignKey("graph_holdings.id", ondelete="SET NULL"), nullable=True)
    materialized_position_id = Column(UUID(as_uuid=True), ForeignKey("graph_node_positions.id", ondelete="SET NULL"), nullable=True)

    # Activity — visibility, supersession, retraction are derived from graph
    # structure (design S4.5); these point at the record that changed each.
    # Plain UUID back-pointers (not DB FKs), matching the FactClause /
    # graph.py convention and avoiding the assertions<->retractions FK cycle.
    superseded_by = Column(UUID(as_uuid=True), index=True)
    retracted_by = Column(UUID(as_uuid=True), index=True)

    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('property', 'state', 'relationship', 'holding', 'position')",
            name="ck_assertions_kind",
        ),
        CheckConstraint(
            "record_state IN ('staged', 'committed')",
            name="ck_assertions_record_state",
        ),
        # The population contract, armed once reconciliation stops staging
        # anything without a resolved time (design S4.2, S14): a COMMITTED
        # project-world assertion has a non-null valid_from. Staged rows may be
        # briefly time-pending inside a run; doctrine/reference assertions are
        # not project-world and are exempt.
        CheckConstraint(
            "record_state <> 'committed' OR project_id IS NULL OR valid_from IS NOT NULL",
            name="ck_assertions_valid_from_committed",
        ),
        Index("ix_assertions_subject_node", "subject_node_id"),
        Index("ix_assertions_run", "ingestion_run_id"),
        Index("ix_assertions_attribute", "attribute"),
    )


class AssertionBasis(Base):
    """The basis link (design S4.1): one assertion to the clause(s) that
    support it, OR to the derivation that produced it. This is the L2 -> L1
    (and, via clause.section, L2 -> L1 -> L0) back-pointer chain the ontology
    requires. An assertion has clause basis or derivation basis, never
    neither."""
    __tablename__ = "assertion_basis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assertion_id = Column(UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="CASCADE"), nullable=False, index=True)
    clause_id = Column(UUID(as_uuid=True), ForeignKey("clauses.id", ondelete="CASCADE"), nullable=True)
    derivation_id = Column(UUID(as_uuid=True), ForeignKey("derivations.id", ondelete="CASCADE"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(clause_id IS NULL) != (derivation_id IS NULL)",
            name="ck_assertion_basis_one_source",
        ),
        UniqueConstraint("assertion_id", "clause_id", "derivation_id", name="ux_assertion_basis"),
    )


class Derivation(Base):
    """A substantive result produced from existing world-model content (design
    S3.7). Stores enough to reproduce or audit the operation — method + version,
    the input clauses/assertions, the doctrine applied, the parameter hash, and
    the outputs — but never hidden chain-of-thought. Route, terrain, and
    coverage calculations record derivations; they are not agent-facing tools
    (design S11)."""
    __tablename__ = "derivations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)

    method = Column(String(128), nullable=False)
    method_version = Column(String(64), nullable=False)
    # Input clause/assertion ids and doctrine references, captured for audit.
    input_refs = Column(JSONB, nullable=False, server_default="{}")
    doctrine_refs = Column(JSONB, nullable=False, server_default="{}")
    parameter_hash = Column(String(64))

    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    execution_run = Column(UUID(as_uuid=True))
    layer = Column(String(16), nullable=False, server_default="project")
    origin_record_id = Column(UUID(as_uuid=True), index=True)


class Supersession(Base):
    """An explicit, basis-backed replacement of one assertion by another
    (design S4.5, S7.10). Proposed only when the source or stored Section
    explicitly identifies a prior claim as replaced; it never mutates the
    superseded assertion's history."""
    __tablename__ = "supersessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    old_assertion_id = Column(UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="CASCADE"), nullable=False, index=True)
    replacement_assertion_id = Column(UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="CASCADE"), nullable=False)
    # basis clause(s) live in assertion_basis on the replacement; this note is
    # the explicit textual warrant for the replacement.
    basis_note = Column(Text)
    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class Retraction(Base):
    """A logical, history-preserving withdrawal of destination-visible content
    (design S4.5, S7.11). Requires a basis; never physically erases published
    history. Pre-resolution staged-content cleanup is NOT a retraction — that
    physically removes an unpublished aggregate and writes no record here."""
    __tablename__ = "retractions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assertion_id = Column(UUID(as_uuid=True), ForeignKey("assertions.id", ondelete="CASCADE"), nullable=False, index=True)
    basis_note = Column(Text, nullable=False)
    record_state = Column(String(16), nullable=False, server_default="staged")
    ingestion_run_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    recorded_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Orchestration — ingestion run, product branch
# ---------------------------------------------------------------------------

class ProductBranch(Base):
    """The system-owned draft delta for one product edition (design S5). It
    pins a base project revision and doctrine version, owns the branch's
    proposed assertions/derivations/supersessions/retractions and its
    system-created Sections, and carries a current branch revision and a
    system-owned lifecycle. An agent never receives a branch identifier as an
    argument; the product engine binds a generated-product ingestion run to the
    branch before the agent starts. Approval performs an atomic merge."""
    __tablename__ = "product_branches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # The product record this branch belongs to (product_records, models/
    # products.py); FK wired with the product-DAG bridge (design S12).
    owning_product_record_id = Column(UUID(as_uuid=True), index=True)

    base_project_revision = Column(UUID(as_uuid=True))
    doctrine_version = Column(String(64))
    current_revision = Column(Integer, nullable=False, server_default=text("0"))
    lifecycle = Column(String(16), nullable=False, server_default="open")

    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('open', 'generating', 'draft', 'final', 'merged', 'abandoned')",
            name="ck_product_branches_lifecycle",
        ),
    )


class IngestionRun(Base):
    """One ingestion run through the single system-owned queue (design S6, S7).
    At most one run is active across source and generated-product ingestion
    (design S2 invariant 24). A run owns durable run-scoped staging (the section
    / clause / occurrence / assertion rows carrying its id in record_state
    'staged') and a progress tree for steering. On completion the system
    atomically commits the staged records to the bound destination — the
    project world model for a source run, the bound product branch for a
    generated-product run — and advances the queue."""
    __tablename__ = "ingestion_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    mode = Column(String(24), nullable=False)

    # An external-source run binds a source revision; a stored-section run
    # binds a product branch and its ordered system-created Sections.
    source_revision_id = Column(UUID(as_uuid=True), ForeignKey("source_revisions.id", ondelete="SET NULL"), nullable=True)
    product_branch_id = Column(UUID(as_uuid=True), ForeignKey("product_branches.id", ondelete="CASCADE"), nullable=True, index=True)

    pinned_project_revision = Column(UUID(as_uuid=True))
    doctrine_version = Column(String(64))
    actor = Column(String(255))
    commit_destination = Column(String(16), nullable=False)

    status = Column(String(16), nullable=False, server_default="queued")
    # FIFO admission position on the single queue; the admission path assigns
    # it monotonically when a run enters the queue (design S6).
    queue_seq = Column(Integer, index=True)

    # Runtime navigation state (design S7.2). The persistent progress tree the
    # server rehydrates into every tool response; the model never recreates it.
    progress_tree = Column(JSONB, nullable=False, server_default="{}")
    progress_revision = Column(Integer, nullable=False, server_default=text("0"))
    # Terminal failure/cancel reason, human-readable.
    error = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    committed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "mode IN ('external_source', 'stored_section')",
            name="ck_ingestion_runs_mode",
        ),
        CheckConstraint(
            "commit_destination IN ('project', 'product_branch')",
            name="ck_ingestion_runs_destination",
        ),
        CheckConstraint(
            "status IN ('queued', 'active', 'resolving', 'reviewing', "
            "'committing', 'complete', 'failed', 'cancelled')",
            name="ck_ingestion_runs_status",
        ),
        # At most ONE non-terminal active run across the whole system (design
        # S2 invariant 24). Enforced by a partial unique index on a constant.
        Index(
            "ux_ingestion_runs_single_active",
            text("(1)"),
            unique=True,
            postgresql_where=text(
                "status IN ('active', 'resolving', 'reviewing', 'committing')"
            ),
        ),
    )

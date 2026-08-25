"""The single invariant-enforcing domain action layer — milestone 2.

Design of record: scratch/docs/oob/tool-surface-consolidation.md — S2.3 (single
semantic write path), S7 (agent-facing actions), S14 (shared domain function
surface), S4 (provenance / time / lifecycle). Records: app/models/world.py.

EVERY semantic write reaches the world model through this layer — the MCP
handlers (ingestion agent), the product-DAG nodes (direct, system identity),
reconciliation, approval merge, and trusted import. MCP is a transport over
these functions, never an alternate storage path (design S2.3, S14).

The layer owns registry validation, basis validation, the valid_from
population contract, occurrence binding + assertion resolution, idempotency,
run-scoped staging isolation, and the L2 -> L1 -> L0 basis chain. It reuses the
proven track.py time contract rather than reinventing it.

Two write shapes:

  AGGREGATE (ingestion agent, staged in a run): assert_ingested_section and
  assert_stored_section_semantics stage a section with its clauses, section-
  local occurrences, and pending assertions; resolve_entity_aliases binds the
  occurrences and forms assertion candidates; override_assertion_duplicates,
  supersede, and retract finish the run; commit_run atomically publishes it.

  GRANULAR (product-DAG nodes, and the resolution / commit path internally):
  assert_property / assert_state / assert_relationship / assert_holding /
  assert_position each create an Assertion, attach its basis, and — on commit —
  materialize the legacy graph row (graph_edges / graph_holdings /
  graph_node_positions, or a mirrored graph_nodes column) for fast
  traversal and paint.

Nothing here mints an L2 typed fact without an L1 clause (or a derivation)
behind it: the hole that produced provenance-less 2CR entities is closed by
construction (ontology S4.4, "nothing exists only in L2").

Note: parse_dtg / parse_relative_dtg are imported from the graph_ingest module
being replaced; they are generic time utilities and relocate to a shared home
at cutover (design S15).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import (
    AFFILIATIONS, ASCOPE_CATEGORIES, CATEGORIES, ECHELONS, EFFECTIVENESS,
    POSTURES, SIGNIFICANCE, GraphNode, GraphEdge, GraphHolding,
    GraphNodePosition,
)
from app.models.reference import EntityType, RelationshipType
from app.models.world import (
    PMESII_FACETS, Assertion, AssertionBasis, Clause, ClauseAbout,
    EntityOccurrence, HeadingOccurrence, IngestionRun,
    Retraction, Section, SectionSourceView, SourceView, Supersession,
)
from app.services.graph_ingest.track import (
    parse_dtg, parse_relative_dtg, UnanchoredRelativeTime)


# ---------------------------------------------------------------------------
# Errors and bound context
# ---------------------------------------------------------------------------

class DomainError(ValueError):
    """A validation or contract failure. `path` names the exact payload
    location (e.g. clauses[2].links[0].relation) for the per-item echo
    (design S7.6)."""

    def __init__(self, message: str, path: Optional[str] = None):
        super().__init__(message)
        self.path = path


@dataclass
class BoundContext:
    """System-supplied write context (design S5, S7.1). The model NEVER
    supplies any of these; the MCP handler or the product engine binds them
    from the session and the run. A product-DAG granular call binds project +
    branch + system actor; an ingestion-agent call also binds the run and the
    source revision."""

    project_id: Optional[UUID]
    actor: str
    commit_destination: str = "project"          # 'project' | 'product_branch'
    product_branch_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    doctrine_version: Optional[str] = None
    source_revision_id: Optional[UUID] = None
    # map attrs.temporal_anchors {h_hour, d_day, ...} for relative DTGs.
    anchors: Optional[dict] = None
    # Draft-layer flag for engine/branch writes (graph.py convention).
    layer: str = "project"
    origin_record_id: Optional[UUID] = None

    def scope_kwargs(self) -> dict:
        """The scope + audit columns every world row carries."""
        return {
            "project_id": self.project_id,
            "product_branch_id": self.product_branch_id,
            "ingestion_run_id": self.run_id,
            "layer": self.layer,
            "origin_record_id": self.origin_record_id,
        }


# ---------------------------------------------------------------------------
# Time — the valid_from population contract (design S4.2), reusing track.py
# ---------------------------------------------------------------------------

def resolve_time(raw: Optional[str], label: str, anchors: Optional[dict]):
    """Stated time -> parsed datetime; empty -> None (the caller decides
    whether to stamp now()). Absolute parses; relative resolves against the
    project anchors or REJECTS; unparseable REJECTS — never silently stamped
    (design S4.2 — the one DTG-resolution contract every write path
    shares)."""
    if not raw:
        return None
    t = parse_dtg(raw)
    if t is None:
        try:
            t = parse_relative_dtg(raw, anchors)
        except UnanchoredRelativeTime as e:
            # A relative time with no project anchor is rejected per item, not
            # guessed (design S4.2); surface it as one DomainError type.
            raise DomainError(f"{label}: {e}") from e
    if t is None:
        raise DomainError(
            f"unparseable {label} '{raw}' — the statement keeps its stated "
            "time or the item is rejected, never silently stamped")
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _fold(v: str) -> str:
    """Lightweight name normalizer for candidate SUGGESTION only. Occurrence
    binding is always an agent decision (design S2 invariant 6); a fold never
    binds mechanically, so an approximate fold is safe here."""
    s = (v or "").strip().casefold()
    # Army-styled ordinals (2d/3d) -> standard (2nd/3rd) so candidates match.
    s = re.sub(r"\b(\d*)([23])d\b", lambda m: f"{m.group(1)}{m.group(2)}"
               + ("nd" if m.group(2) == "2" else "rd"), s)
    return re.sub(r"\s+", " ", s)


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Registry validation (design S14) — reuse the graph.py constants + db tables
# ---------------------------------------------------------------------------

# Promoted graph_nodes columns an attribute assertion may mirror onto (design
# S3.6 materialization). The registry decides how each value is stored; a known
# attribute mirrors onto its typed column, an unknown one stays an assertion
# only (never lost — ontology F8). Value validation for the closed-set columns
# reuses the graph.py CheckConstraint sets.
_MIRROR_COLUMNS = {
    "affiliation": ("affiliation", AFFILIATIONS),
    "echelon": ("echelon", ECHELONS),
    "category": ("category", CATEGORIES),
    "combat_effectiveness": ("combat_effectiveness", EFFECTIVENESS),
    "significance": ("significance", SIGNIFICANCE),
    # Closed 2026-07-28: posture is a tracked temporal attribute (the
    # as-of resolver replays it); an off-enum value is a shape the
    # disposition engine cannot draw, so the vocabulary is enforced at
    # the record like every other doctrinal set.
    "posture": ("posture", POSTURES),
    "current_activity": ("current_activity", None),
    "long_name": ("long_name", None),
    "unit_type": ("unit_type", None),
    "notes": ("notes", None),
}


def _norm_key(value: str) -> str:
    """Slug a free-text label into a stable registry type_key (lowercase,
    alnum runs joined by single underscores, <=64 chars). Shared by
    relationship-type and entity-type minting."""
    out, prev_us = [], False
    for ch in (value or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_")[:64]


class _Registries:
    """Per-call cache of the entity_type and relationship_type registries so a
    batch validates against one snapshot without re-querying per item."""

    def __init__(self, entity_types: set[str], relationship_types: set[str]):
        self.entity_types = entity_types
        self.relationship_types = relationship_types

    @classmethod
    async def load(cls, db: AsyncSession) -> "_Registries":
        ets = set((await db.execute(select(EntityType.type_key))).scalars())
        rels = set((await db.execute(select(RelationshipType.type_key))).scalars())
        return cls(ets, rels)

    async def ensure_entity_type(self, db: AsyncSession, value: str, path: str,
                                 *, created_by: Optional[str] = None) -> str:
        """Resolve an entity's type to a registry type_key, MINTING a new
        user-defined type on first use so every referenced subject can be an
        entity — a CCIR, a PIR, a phase, a report — instead of being dropped.
        A seeded kind matches as-is. A minted kind is non-geospatial
        (is_fixed=False, no symbol): it carries no position and never touches
        the render/SIDC path, which is why only the closed seeded kinds drive
        map symbology. A geospatial subject uses an existing rendered kind."""
        raw = (value or "").strip()
        if not raw:
            raise DomainError("entity_type is required", path)
        if raw in self.entity_types:
            return raw
        key = _norm_key(raw)
        if not key:
            raise DomainError(f"entity_type '{value}' has no usable key", path)
        if key not in self.entity_types:
            db.add(EntityType(
                type_key=key, label=raw.replace("_", " "), is_fixed=False,
                source="user", created_by=created_by))
            await db.flush()
            self.entity_types.add(key)
        return key

    async def ensure_relation(self, db: AsyncSession, value: str, path: str,
                              *, created_by: Optional[str] = None) -> str:
        """Resolve a link's relation to a registry type_key, MINTING a new
        user-defined relationship type on first use — the same freedom a new
        entity gets — instead of rejecting an unseen predicate. A doctrine-
        seeded ('bundled') key matches as-is; any new predicate the source
        states becomes a 'user' row so it can be wired as a typed link rather
        than buried in free text."""
        raw = (value or "").strip()
        if not raw:
            raise DomainError("relation is required", path)
        if raw in self.relationship_types:
            return raw
        key = _norm_key(raw)
        if not key:
            raise DomainError(f"relation '{value}' has no usable key", path)
        if key not in self.relationship_types:
            label = raw.replace("_", " ")
            db.add(RelationshipType(
                type_key=key, label=label, inverse_label=label,
                is_hierarchical=False, source="user", created_by=created_by))
            await db.flush()
            self.relationship_types.add(key)
        return key


def _check_value(attribute: str, value_text: Optional[str], path: str):
    """A closed-set mirror column's value must be in its doctrinal set."""
    col = _MIRROR_COLUMNS.get(attribute)
    if col and col[1] is not None and value_text is not None:
        if value_text not in col[1]:
            raise DomainError(
                f"'{value_text}' is not a valid {attribute} "
                f"(one of {', '.join(col[1])})", path)


def check_tags(raw, allowed: tuple, label: str, path: str):
    """Validate a tag list against its closed vocabulary (PMESII_FACETS /
    ASCOPE_CATEGORIES). None passes through (untagged); anything stated must
    normalize into the set — an unknown tag REJECTS the item, per-item, like
    every other closed-set violation. Shared by the ingestion contract and
    the repair surface so both write paths enforce the same vocabulary."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise DomainError(f"{label} must be a non-empty list of tags", path)
    out: list[str] = []
    for v in raw:
        key = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        if key not in allowed:
            raise DomainError(
                f"'{v}' is not a valid {label} tag "
                f"(one of {', '.join(allowed)})", path)
        if key not in out:
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# Granular actions — create an Assertion, attach basis, (later) materialize
# ---------------------------------------------------------------------------

def _mk_assertion(ctx: BoundContext, *, kind: str, record_state: str = "staged",
                  **cols) -> Assertion:
    """Construct an Assertion row with the bound scope + audit columns. Endpoint
    columns (subject/from/to as occurrence OR node) and payload columns come in
    via cols. valid_from population is the caller's (the clause/derivation
    supplies the time)."""
    return Assertion(
        id=uuid4(), kind=kind, record_state=record_state,
        recorded_at=datetime.now(timezone.utc), **ctx.scope_kwargs(), **cols)


def _attach_basis(assertion: Assertion, *, clause_id: Optional[UUID] = None,
                  derivation_id: Optional[UUID] = None) -> AssertionBasis:
    """The L2 -> L1 (or L2 -> derivation) back-pointer (design S4.1). Exactly
    one of clause_id / derivation_id (the model check enforces it too)."""
    if (clause_id is None) == (derivation_id is None):
        raise DomainError("an assertion has clause XOR derivation basis")
    return AssertionBasis(id=uuid4(), assertion_id=assertion.id,
                          clause_id=clause_id, derivation_id=derivation_id)


async def assert_property(db: AsyncSession, ctx: BoundContext, *, subject_node_id: UUID,
                          attribute: str, value_text=None, value_num=None, unit=None,
                          condition=None, clause_id=None, derivation_id=None,
                          valid_from=None, valid_to=None, path="") -> Assertion:
    """A durable/identity property on a resolved entity (design S3.6). Materializes
    onto its mirror column at commit; unknown attributes stay assertion-only."""
    _check_value(attribute, value_text, f"{path}.{attribute}" if path else attribute)
    a = _mk_assertion(ctx, kind="property", subject_node_id=subject_node_id,
                      attribute=attribute, value_text=value_text, value_num=value_num,
                      unit=unit, condition=condition, valid_from=valid_from,
                      valid_to=valid_to, record_state="committed")
    db.add(a)
    await db.flush()
    db.add(_attach_basis(a, clause_id=clause_id, derivation_id=derivation_id))
    return a


async def assert_state(db, ctx, *, subject_node_id, attribute, value_text=None,
                       value_num=None, unit=None, condition=None, clause_id=None,
                       derivation_id=None, valid_from=None, valid_to=None, path="") -> Assertion:
    """A time-varying state observation on a resolved entity (design S3.6, S4.2).
    valid_from is REQUIRED for a committed project-world state assertion — the
    caller resolves it via the time contract before calling here."""
    _check_value(attribute, value_text, f"{path}.{attribute}" if path else attribute)
    a = _mk_assertion(ctx, kind="state", subject_node_id=subject_node_id,
                      attribute=attribute, value_text=value_text, value_num=value_num,
                      unit=unit, condition=condition, valid_from=valid_from,
                      valid_to=valid_to, record_state="committed")
    db.add(a)
    await db.flush()
    db.add(_attach_basis(a, clause_id=clause_id, derivation_id=derivation_id))
    return a


async def assert_relationship(db, ctx, *, from_node_id, to_node_id, relation,
                              properties=None, clause_id=None, derivation_id=None,
                              valid_from=None, valid_to=None, registries=None, path="") -> Assertion:
    """A relationship between two resolved entities (design S3.6). Materializes a
    graph_edge at commit; the assertion stays the provenance-bearing record."""
    if registries is not None:
        relation = await registries.ensure_relation(
            db, relation, f"{path}.relation" if path else "relation",
            created_by=getattr(ctx, "actor", None))
    a = _mk_assertion(ctx, kind="relationship", from_node_id=from_node_id,
                      to_node_id=to_node_id, relation=relation, properties=properties,
                      valid_from=valid_from, valid_to=valid_to, record_state="committed")
    db.add(a)
    await db.flush()
    db.add(_attach_basis(a, clause_id=clause_id, derivation_id=derivation_id))
    return a


async def assert_holding(db, ctx, *, subject_node_id, count, unit=None, condition=None,
                         clause_id=None, derivation_id=None, valid_from=None,
                         valid_to=None, path="") -> Assertion:
    """A count assertion on a resolved entity (design S3.6). Materializes a
    graph_holding at commit."""
    a = _mk_assertion(ctx, kind="holding", subject_node_id=subject_node_id, count=count,
                      unit=unit, condition=condition, valid_from=valid_from,
                      valid_to=valid_to, record_state="committed")
    db.add(a)
    await db.flush()
    db.add(_attach_basis(a, clause_id=clause_id, derivation_id=derivation_id))
    return a


# ---------------------------------------------------------------------------
# Aggregate staging — assert_ingested_section, assert_stored_section_semantics
# ---------------------------------------------------------------------------

async def _resolve_heading_leaf(db, ctx, headings: list[str]) -> Optional[UUID]:
    """Resolve the copied heading list into source hierarchy (design S3.3):
    reuse the longest prefix shared with the preceding asserted section in this
    source revision, then mint occurrences for the remaining suffix. Equal
    heading text outside the reused chain never merges globally; similarity is
    never used. Returns the innermost heading occurrence id (None if unheaded)."""
    if not headings:
        return None
    # The active path = the heading chain of the most recent staged/committed
    # section in the same source revision, walked leaf -> root.
    prev = (await db.execute(
        select(Section)
        .where(Section.source_revision_id == ctx.source_revision_id,
               Section.heading_leaf_id.isnot(None))
        .order_by(Section.origin_sequence.desc()).limit(1))).scalar_one_or_none()
    active: list[HeadingOccurrence] = []
    if prev is not None and prev.heading_leaf_id is not None:
        node = await db.get(HeadingOccurrence, prev.heading_leaf_id)
        while node is not None:
            active.append(node)
            node = (await db.get(HeadingOccurrence, node.parent_id)
                    if node.parent_id else None)
        active.reverse()   # root -> leaf
    parent_id = None
    leaf_id = None
    for depth, text in enumerate(headings):
        reuse = (depth < len(active) and active[depth].text == text
                 and (active[depth].parent_id == parent_id))
        if reuse:
            node = active[depth]
        else:
            order = (await db.execute(
                select(HeadingOccurrence.id).where(
                    HeadingOccurrence.source_revision_id == ctx.source_revision_id,
                    HeadingOccurrence.depth == depth))).all()
            node = HeadingOccurrence(
                id=uuid4(), source_revision_id=ctx.source_revision_id,
                parent_id=parent_id, text=text, depth=depth, order_index=len(order))
            db.add(node)
            await db.flush()
            # A minted suffix node means the rest of the active path is exited.
            active = active[:depth]
        parent_id = node.id
        leaf_id = node.id
    return leaf_id


async def _next_origin_sequence(db, ctx) -> int:
    """Server-assigned source-order for this run's sections (design S3.3)."""
    rows = (await db.execute(
        select(Section.origin_sequence)
        .where(Section.ingestion_run_id == ctx.run_id))).scalars().all()
    return (max(rows) + 1) if rows else 0


def _resolve_point(pos: dict, path: str):
    """A stated position -> geometry for a position assertion (design S3.6).
    Returns (lat, lon, normalized_mgrs|None, geom_wkt|None): a POINT yields
    lat/lon (+ the raw grid for the note, geom_wkt None); a line/area yields a
    geom_wkt (lat/lon None). Accepted forms:
      - mgrs (a grid) or lat + lon        -> POINT
      - mgrs_line: [grid, grid, ...]      -> LINESTRING (FSCL, phase line,
                                             boundary — a linear control measure)
      - mgrs_polygon: [grid, grid, ...]   -> POLYGON, auto-closed (engagement
                                             area, AO — an area control measure)
      - geom_wkt: "<WKT>"                 -> passed through verbatim
    Every MGRS is converted at STAGE time so a bad grid rejects the section with
    its payload path (never a silent failure at commit). Materialization
    (record_position) owns land-snap + newest-wins geom mirroring; for a route
    kind it also road-routes the linestring."""
    from app.utils.mgrs_utils import mgrs_to_latlng

    def _ll(grid: str, p: str):
        try:
            lat, lon = mgrs_to_latlng(grid)
        except Exception as e:
            raise DomainError(f"unparseable MGRS '{grid}' ({e.__class__.__name__})", p)
        return float(lat), float(lon)

    if pos.get("geom_wkt"):
        return None, None, None, str(pos["geom_wkt"])

    grids = pos.get("mgrs_line") or pos.get("mgrs_polygon")
    if grids is not None:
        is_poly = pos.get("mgrs_polygon") is not None
        if not isinstance(grids, list) or len(grids) < 2:
            raise DomainError(
                "mgrs_line/mgrs_polygon needs a list of at least 2 grids", path)
        pts = [_ll(str(g), f"{path}[{i}]") for i, g in enumerate(grids)]
        coords = [f"{lon} {lat}" for lat, lon in pts]
        if is_poly:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geom = f"POLYGON(({', '.join(coords)}))"
        else:
            geom = f"LINESTRING({', '.join(coords)})"
        return None, None, None, geom

    mgrs_raw = (pos.get("mgrs") or "").strip()
    if mgrs_raw:
        lat, lon = _ll(mgrs_raw, f"{path}.mgrs")
        return lat, lon, mgrs_raw, None
    lat, lon = pos.get("lat"), pos.get("lon")
    if lat is None or lon is None:
        raise DomainError(
            "position needs mgrs / lat+lon / mgrs_line / mgrs_polygon / geom_wkt",
            path)
    try:
        return float(lat), float(lon), None, None
    except (TypeError, ValueError):
        raise DomainError("lat/lon must be numbers", path)


async def _stage_semantics(db, ctx, section: Section, entities, clauses, registries,
                           run_source_state: str = "staged") -> dict:
    """Stage the entities, clauses, ABOUT links, and pending assertions of one
    section (shared by both aggregate paths). Occurrences are section-local;
    entity_values/links become PENDING assertions keyed by occurrence designation
    until alias resolution binds them (design S3.5, S7.6, S7.8)."""
    occ_by_designation: dict[str, EntityOccurrence] = {}
    for i, e in enumerate(entities or []):
        name = (e.get("name") or "").strip()
        if not name:
            raise DomainError("entity name is required", f"entities[{i}].name")
        if name in occ_by_designation:
            raise DomainError(f"designation '{name}' declared twice in the section",
                              f"entities[{i}].name")
        etype = await registries.ensure_entity_type(
            db, (e.get("entity_type") or "").strip(), f"entities[{i}].entity_type",
            created_by=ctx.actor)
        occ = EntityOccurrence(
            id=uuid4(), section_id=section.id, designation=name, entity_type=etype,
            identifiers=list(e.get("identifiers") or []),
            ascope=check_tags(e.get("ascope"), ASCOPE_CATEGORIES, "ascope",
                              f"entities[{i}].ascope"),
            extraction_run_id=ctx.run_id, record_state=run_source_state,
            ingestion_run_id=ctx.run_id)
        db.add(occ)
        occ_by_designation[name] = occ
    await db.flush()

    def _occ(designation: str, path: str) -> EntityOccurrence:
        occ = occ_by_designation.get((designation or "").strip())
        if occ is None:
            raise DomainError(
                f"'{designation}' is not declared in this section's entities", path)
        return occ

    n_clauses = n_pending = 0
    for ci, c in enumerate(clauses or []):
        cp = f"clauses[{ci}]"
        text = (c.get("text") or "").strip()
        if not text:
            raise DomainError("clause text is required", f"{cp}.text")
        c_valid_from = resolve_time(c.get("valid_from"), f"{cp}.valid_from", ctx.anchors)
        c_valid_to = resolve_time(c.get("valid_to"), f"{cp}.valid_to", ctx.anchors)
        clause = Clause(
            id=uuid4(), section_id=section.id, order_index=ci, text=text,
            register=(c.get("register") or "episodic"),
            attribution=(c.get("attribution") or None),
            pmesii=check_tags(c.get("pmesii"), PMESII_FACETS, "pmesii",
                              f"{cp}.pmesii"),
            valid_from=c_valid_from, valid_to=c_valid_to,
            project_id=ctx.project_id, product_branch_id=ctx.product_branch_id,
            record_state=run_source_state, ingestion_run_id=ctx.run_id,
            layer=ctx.layer, origin_record_id=ctx.origin_record_id)
        db.add(clause)
        await db.flush()
        n_clauses += 1
        about_occ: set[UUID] = set()

        for vi, ev in enumerate(c.get("entity_values") or []):
            vp = f"{cp}.entity_values[{vi}]"
            occ = _occ(ev.get("entity"), f"{vp}.entity")
            about_occ.add(occ.id)
            vf = resolve_time(ev.get("valid_from"), f"{vp}.valid_from", ctx.anchors) or c_valid_from
            vt = resolve_time(ev.get("valid_to"), f"{vp}.valid_to", ctx.anchors) or c_valid_to
            for attr, val in (ev.get("values") or {}).items():
                vtext = str(val) if not isinstance(val, (int, float)) else None
                vnum = float(val) if isinstance(val, (int, float)) else None
                _check_value(attr, vtext, f"{vp}.values.{attr}")
                a = _mk_assertion(
                    ctx, kind="state", subject_occurrence_id=occ.id, attribute=attr,
                    value_text=vtext, value_num=vnum, valid_from=vf, valid_to=vt)
                db.add(a)
                await db.flush()
                db.add(_attach_basis(a, clause_id=clause.id))
                n_pending += 1

        for li, lk in enumerate(c.get("links") or []):
            lp = f"{cp}.links[{li}]"
            f_occ = _occ(lk.get("from"), f"{lp}.from")
            t_occ = _occ(lk.get("to"), f"{lp}.to")
            about_occ.add(f_occ.id)
            about_occ.add(t_occ.id)
            relation = await registries.ensure_relation(
                db, (lk.get("relation") or "").strip(), f"{lp}.relation",
                created_by=ctx.actor)
            lf = resolve_time(lk.get("valid_from"), f"{lp}.valid_from", ctx.anchors) or c_valid_from
            lt = resolve_time(lk.get("valid_to"), f"{lp}.valid_to", ctx.anchors) or c_valid_to
            a = _mk_assertion(
                ctx, kind="relationship", from_occurrence_id=f_occ.id,
                to_occurrence_id=t_occ.id, relation=relation,
                properties=lk.get("properties"), valid_from=lf, valid_to=lt)
            db.add(a)
            await db.flush()
            db.add(_attach_basis(a, clause_id=clause.id))
            n_pending += 1

        for pi, pos in enumerate(c.get("positions") or []):
            pp = f"{cp}.positions[{pi}]"
            occ = _occ(pos.get("entity"), f"{pp}.entity")
            about_occ.add(occ.id)
            lat, lon, mgrs_norm, geom_wkt = _resolve_point(pos, pp)
            pf = resolve_time(pos.get("valid_from"), f"{pp}.valid_from", ctx.anchors) or c_valid_from
            pt = resolve_time(pos.get("valid_to"), f"{pp}.valid_to", ctx.anchors) or c_valid_to
            a = _mk_assertion(
                ctx, kind="position", subject_occurrence_id=occ.id,
                value_text=mgrs_norm, valid_from=pf, valid_to=pt,
                properties={"lat": lat, "lon": lon, "mgrs": mgrs_norm,
                            "geom_wkt": geom_wkt})
            db.add(a)
            await db.flush()
            db.add(_attach_basis(a, clause_id=clause.id))
            n_pending += 1

        for occ_id in about_occ:
            db.add(ClauseAbout(clause_id=clause.id, occurrence_id=occ_id))

    return {"clauses": n_clauses, "pending_facts": n_pending,
            "entities": len(occ_by_designation)}


async def assert_ingested_section(db: AsyncSession, ctx: BoundContext,
                                  payload: dict) -> dict:
    """Stage ONE complete external-source section and its semantic extraction
    atomically in the run (design S7.6). payload: {headings[], text, source_refs[],
    entities[], clauses[]}. The model supplies no ids, keys, parent refs, order,
    quotes, or offsets — the server assigns sequence, resolves the heading path,
    stores the verbatim text, and derives every nested basis from the clause. A
    validation error rejects the WHOLE aggregate with its payload path."""
    if ctx.run_id is None or ctx.source_revision_id is None:
        raise DomainError("assert_ingested_section requires a bound external-source run")
    registries = await _Registries.load(db)

    headings = list(payload.get("headings") or [])
    text = payload.get("text")
    if text is None:
        raise DomainError("section text is required (may be empty for a visual section)",
                          "text")
    text_hash = _hash_text(text)

    # Idempotency (design S8.2): a replay of the same section aggregate in the
    # same run + source revision is a no-op returning the existing section.
    existing = (await db.execute(
        select(Section).where(
            Section.ingestion_run_id == ctx.run_id,
            Section.source_revision_id == ctx.source_revision_id,
            Section.text_hash == text_hash,
            Section.headings == headings))).scalar_one_or_none()
    if existing is not None:
        return {"outcome": "noop", "section_ref": str(existing.id),
                "source_sequence": existing.origin_sequence,
                "resolved_heading_path": existing.headings}

    leaf_id = await _resolve_heading_leaf(db, ctx, headings)
    seq = await _next_origin_sequence(db, ctx)
    section = Section(
        id=uuid4(), origin_kind="external_source",
        source_revision_id=ctx.source_revision_id, project_id=ctx.project_id,
        headings=headings, heading_leaf_id=leaf_id, body_text=text,
        text_hash=text_hash, origin_sequence=seq, creation_run_id=ctx.run_id,
        record_state="staged", ingestion_run_id=ctx.run_id, layer=ctx.layer,
        origin_record_id=ctx.origin_record_id)
    db.add(section)
    await db.flush()

    for ref in (payload.get("source_refs") or []):
        view = await db.get(SourceView, UUID(str(ref))) if _is_uuid(ref) else None
        if view is None or view.source_revision_id != ctx.source_revision_id:
            raise DomainError(f"source_ref '{ref}' is not a view of the bound revision",
                              "source_refs")
        db.add(SectionSourceView(section_id=section.id, source_view_id=view.id))

    counts = await _stage_semantics(db, ctx, section, payload.get("entities"),
                                    payload.get("clauses"), registries)
    return {"outcome": "staged", "section_ref": str(section.id),
            "resolved_heading_path": headings, "source_sequence": seq, **counts}


async def assert_stored_section_semantics(db: AsyncSession, ctx: BoundContext,
                                          section_id: UUID, payload: dict) -> dict:
    """Attach semantics to the current system-created branch Section (design
    S7.7). The section text/headings/views are already stored and bound; the
    model supplies ONLY entities + clauses (with nested entity_values/links).
    No section ref, headings, text, source refs, anchor, or page refs are
    accepted from the model — they are ignored if present."""
    section = await db.get(Section, section_id)
    if section is None or section.product_branch_id != ctx.product_branch_id:
        raise DomainError("bound Section not found for this branch")
    if section.origin_kind == "external_source":
        raise DomainError("assert_section_semantics is for system-created sections only")
    registries = await _Registries.load(db)
    counts = await _stage_semantics(db, ctx, section, payload.get("entities"),
                                    payload.get("clauses"), registries)
    return {"outcome": "staged", "section_ref": str(section.id), **counts}


def _is_uuid(v: Any) -> bool:
    try:
        UUID(str(v))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Entity alias resolution — bind occurrences to canonical graph_nodes
# ---------------------------------------------------------------------------

async def resolve_entity_aliases(db: AsyncSession, ctx: BoundContext,
                                 decisions: list[dict]) -> list[dict]:
    """Bind section-local occurrences to canonical entities (design S7.8). Each
    decision groups occurrence_refs and names exactly one of entity_ref (bind to
    an existing graph_node) or new_entity (mint one). Binding sets
    occurrence.canonical_node_id; pending assertions whose occurrence endpoints
    are now all resolved get their node endpoints filled and become materializable
    candidates. Every binding is the model's decision — no mechanical merge."""
    results = []
    for di, d in enumerate(decisions or []):
        try:
            occ_refs = [UUID(str(r)) for r in (d.get("occurrence_refs") or [])]
            if not occ_refs:
                raise DomainError("a decision needs occurrence_refs", f"decisions[{di}]")
            occs = [await db.get(EntityOccurrence, oid) for oid in occ_refs]
            if any(o is None or o.ingestion_run_id != ctx.run_id for o in occs):
                raise DomainError("occurrence not found in this run", f"decisions[{di}]")
            has_ref = bool(d.get("entity_ref"))
            has_new = bool(d.get("new_entity"))
            if has_ref == has_new:
                raise DomainError("exactly one of entity_ref / new_entity",
                                  f"decisions[{di}]")
            etype = occs[0].entity_type
            if any(o.entity_type != etype for o in occs):
                raise DomainError("occurrences in one decision must share entity_type",
                                  f"decisions[{di}]")

            # The referent's ASCOPE categories ride the occurrences (stated
            # at assert time, page in hand); a decision-level statement on
            # new_entity outranks them. Propagation fills a canonical node
            # that has none — an already-tagged node keeps its tags (repair
            # is the correction path, not a later occurrence).
            occ_ascope = next((o.ascope for o in occs if o.ascope), None)
            if has_ref:
                node = await db.get(GraphNode, UUID(str(d["entity_ref"])))
                if node is None or node.project_id != ctx.project_id:
                    raise DomainError("entity_ref not found in project",
                                      f"decisions[{di}].entity_ref")
                if node.ascope is None and occ_ascope:
                    node.ascope = occ_ascope
                outcome = "matched"
            else:
                ne = d["new_entity"]
                node = GraphNode(
                    id=uuid4(), project_id=ctx.project_id, entity_type=etype,
                    name=(ne.get("canonical_name") or occs[0].designation),
                    affiliation="Unknown", layer=ctx.layer,
                    ascope=(check_tags(ne.get("ascope"), ASCOPE_CATEGORIES,
                                       "ascope",
                                       f"decisions[{di}].new_entity.ascope")
                            or occ_ascope),
                    origin_record_id=ctx.origin_record_id)
                db.add(node)
                await db.flush()
                outcome = "created"

            for o in occs:
                o.canonical_node_id = node.id
            await db.flush()
            candidate_refs = await _bind_pending_assertions(db, ctx, occ_refs)
            results.append({"decision_index": di, "outcome": outcome,
                            "entity_ref": str(node.id),
                            "resolved_assertion_candidate_refs": candidate_refs})
        except DomainError as e:
            results.append({"decision_index": di, "outcome": "rejected",
                            "error": str(e), "path": e.path})
    return results


async def _bind_pending_assertions(db, ctx, occ_ids: list[UUID]) -> list[str]:
    """Fill the node endpoints of pending assertions whose occurrence endpoints
    just resolved; an assertion with all endpoints bound is a materializable
    candidate (design S7.8). Returns the refs that became fully bound."""
    occ_ids = set(occ_ids)
    q = select(Assertion).where(
        Assertion.ingestion_run_id == ctx.run_id,
        Assertion.record_state == "staged")
    candidates = []
    for a in (await db.execute(q)).scalars():
        touched = False
        if a.subject_occurrence_id in occ_ids and a.subject_node_id is None:
            a.subject_node_id = (await db.get(
                EntityOccurrence, a.subject_occurrence_id)).canonical_node_id
            touched = True
        if a.from_occurrence_id in occ_ids and a.from_node_id is None:
            a.from_node_id = (await db.get(
                EntityOccurrence, a.from_occurrence_id)).canonical_node_id
            touched = True
        if a.to_occurrence_id in occ_ids and a.to_node_id is None:
            a.to_node_id = (await db.get(
                EntityOccurrence, a.to_occurrence_id)).canonical_node_id
            touched = True
        if touched and _endpoints_bound(a):
            candidates.append(str(a.id))
    await db.flush()
    return candidates


def _endpoints_bound(a: Assertion) -> bool:
    if a.kind == "relationship":
        return a.from_node_id is not None and a.to_node_id is not None
    return a.subject_node_id is not None


# ---------------------------------------------------------------------------
# Supersede / retract (design S7.10, S7.11)
# ---------------------------------------------------------------------------

async def supersede(db: AsyncSession, ctx: BoundContext, items: list[dict]) -> list[dict]:
    """Stage explicit, basis-backed replacements (design S7.10). The replacement
    must already exist in the run's staging or the bound branch."""
    out = []
    for i, it in enumerate(items or []):
        try:
            old = await db.get(Assertion, UUID(str(it["old"])))
            repl = await db.get(Assertion, UUID(str(it["replacement"])))
            if old is None or repl is None:
                raise DomainError("old/replacement assertion not found", f"items[{i}]")
            rec = Supersession(
                id=uuid4(), old_assertion_id=old.id, replacement_assertion_id=repl.id,
                basis_note=(it.get("basis") or None), record_state="staged",
                ingestion_run_id=ctx.run_id)
            db.add(rec)
            old.superseded_by = repl.id
            if old.valid_to is None:
                old.valid_to = repl.valid_from
            out.append({"index": i, "outcome": "staged", "ref": str(rec.id)})
        except (DomainError, KeyError) as e:
            out.append({"index": i, "outcome": "rejected", "error": str(e)})
    return out


async def retract(db: AsyncSession, ctx: BoundContext, items: list[dict]) -> list[dict]:
    """Basis-backed logical retraction of destination-visible content (design
    S7.11). Pre-resolution staged-content cleanup is handled by the run
    lifecycle (physical removal), not here — this writes history-preserving
    retraction records that require a basis."""
    out = []
    for i, it in enumerate(items or []):
        try:
            a = await db.get(Assertion, UUID(str(it["ref"])))
            if a is None:
                raise DomainError("assertion not found", f"items[{i}].ref")
            basis = (it.get("basis") or "").strip()
            if not basis:
                raise DomainError("retract of visible content requires a basis",
                                  f"items[{i}].basis")
            rec = Retraction(id=uuid4(), assertion_id=a.id, basis_note=basis,
                             record_state="staged", ingestion_run_id=ctx.run_id)
            db.add(rec)
            await db.flush()
            a.retracted_by = rec.id
            out.append({"index": i, "outcome": "staged", "ref": str(rec.id)})
        except (DomainError, KeyError) as e:
            out.append({"index": i, "outcome": "rejected", "error": str(e)})
    return out


# ---------------------------------------------------------------------------
# Commit — publish a run's staged records + materialize the legacy L2 rows
# ---------------------------------------------------------------------------

async def commit_run(db: AsyncSession, ctx: BoundContext, run: IngestionRun) -> dict:
    """Atomically publish a completed run's staged records into its bound
    destination (design S6). Flips staged -> committed, enforces the valid_from
    population contract on committed project-world assertions, and MATERIALIZES
    each resolved assertion into its legacy graph row so paint and traversal
    keep working. Returns the commit counts."""
    n_sections = n_clauses = n_assertions = n_materialized = 0

    for section in (await db.execute(select(Section).where(
            Section.ingestion_run_id == run.id,
            Section.record_state == "staged"))).scalars():
        section.record_state = "committed"
        n_sections += 1
    for clause in (await db.execute(select(Clause).where(
            Clause.ingestion_run_id == run.id,
            Clause.record_state == "staged"))).scalars():
        clause.record_state = "committed"
        n_clauses += 1
    for occ in (await db.execute(select(EntityOccurrence).where(
            EntityOccurrence.ingestion_run_id == run.id,
            EntityOccurrence.record_state == "staged"))).scalars():
        occ.record_state = "committed"

    for a in (await db.execute(select(Assertion).where(
            Assertion.ingestion_run_id == run.id,
            Assertion.record_state == "staged"))).scalars():
        if not _endpoints_bound(a):
            raise DomainError(
                f"assertion {a.id} has an unresolved occurrence endpoint at commit")
        if a.project_id is not None and a.valid_from is None:
            # A committed project-world assertion has a non-null valid_from
            # (design S4.2). An unstated time was already stamped upstream; a
            # still-null one here is a contract breach, not a silent stamp.
            raise DomainError(f"assertion {a.id} reached commit without a valid_from")
        a.record_state = "committed"
        n_assertions += 1
        if await _materialize(db, ctx, a):
            n_materialized += 1

    await db.flush()
    return {"sections": n_sections, "clauses": n_clauses,
            "assertions": n_assertions, "materialized": n_materialized}


async def _materialize(db: AsyncSession, ctx: BoundContext, a: Assertion) -> bool:
    """Project a committed assertion into its legacy L2 row for fast traversal
    and paint (design S3.6). The assertion stays the provenance-bearing record;
    the graph row is the derived projection. property/state mirror onto the
    graph_nodes column (known attrs) or stay assertion-only (unknown); a
    relationship materializes a graph_edge; a holding a graph_holding; a
    position a graph_node_position."""
    if a.kind in ("property", "state") and a.subject_node_id is not None:
        col = _MIRROR_COLUMNS.get(a.attribute)
        if col is not None:
            node = await db.get(GraphNode, a.subject_node_id)
            if node is not None:
                setattr(node, col[0], a.value_text if a.value_num is None
                        else a.value_num)
                return True
        return False

    if a.kind == "relationship" and a.from_node_id and a.to_node_id:
        edge = GraphEdge(
            id=uuid4(), from_id=a.from_node_id, to_id=a.to_node_id,
            relationship_type=a.relation, effective_from=a.valid_from,
            effective_to=a.valid_to, layer=ctx.layer,
            origin_record_id=ctx.origin_record_id)
        db.add(edge)
        await db.flush()
        a.materialized_edge_id = edge.id
        return True

    if a.kind == "holding" and a.subject_node_id is not None:
        # Catalog resolution at materialization (S17.3 absorption from
        # the removed add_holdings writer): the stated nomenclature
        # resolves against the WEG catalog so the holding lands
        # weg-linked when it matches — symbols, range fans, and rollups
        # all key off weg_id. Unmatched stays nomenclature_raw,
        # resolvable later by the alias sweep. The assertion keeps the
        # VERBATIM stated string either way.
        from app.services.graph_ingest.ingest import _resolve_nomenclature
        holding = GraphHolding(
            id=uuid4(), node_id=a.subject_node_id, count_current=a.count,
            nomenclature_raw=a.value_text,
            weg_id=await _resolve_nomenclature(db, a.value_text))
        db.add(holding)
        await db.flush()
        a.materialized_holding_id = holding.id
        return True

    if a.kind == "position" and a.subject_node_id is not None:
        from app.services.graph_ingest.track import record_position
        props = a.properties or {}
        geom_wkt = props.get("geom_wkt")
        lat, lon = props.get("lat"), props.get("lon")
        if geom_wkt is None and (lat is None or lon is None):
            return False
        node = await db.get(GraphNode, a.subject_node_id)
        if node is None:
            return False
        # record_position owns the append-only track, land-snap, and
        # newest-wins geom mirror. valid_from is the observation time; render
        # it in an ISO form parse_dtg accepts (it re-derives observed_at). A
        # geom_wkt carries a line/area control measure; lat/lon a point.
        dtg = a.valid_from.strftime("%Y-%m-%dT%H:%M") if a.valid_from else None
        if geom_wkt is not None:
            row, _ = await record_position(
                db, node, geom_wkt=geom_wkt, mgrs=props.get("mgrs"),
                dtg=dtg, source="world-ingestion",
                created_by=(ctx.actor or "_ingestion"))
        else:
            row, _ = await record_position(
                db, node, lat=lat, lon=lon, mgrs=props.get("mgrs"),
                dtg=dtg, source="world-ingestion",
                created_by=(ctx.actor or "_ingestion"))
        a.materialized_position_id = row.id
        return True

    return False

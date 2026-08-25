"""World-model REPAIR surface — the correction interface of design S14.

tool-surface-consolidation.md S14 names "analyst correction interfaces" and
"migration and trusted import tools" as callers of the SAME domain layer the
ingestion surface uses. This router is that caller: a minimal, GENERIC set of
batched operations able to correct anything in a committed project world model
without a re-ingestion pass and without ever bypassing the record system.

The four writes and four finders:

- GET  /repair/{pid}/clauses     — find committed clauses (basis candidates;
  q optional, so it also enumerates for tag backfill).
- GET  /repair/{pid}/entities    — list project-layer entities (id, name,
  kind, ascope) — names duplicate, so tag work addresses rows by UUID.
- GET  /repair/{pid}/assertions  — list an entity's committed assertions.
- GET  /repair/{pid}/positions   — list an entity's track rows + backing.
- POST /repair/{pid}/assert      — create any committed assertion. Clause
  basis REQUIRED (an unsupported value is rejected, never fabricated — S15.8);
  valid_from comes from a stated DTG or the basis clause, never silently
  stamped; materializes through the same _materialize path ingestion uses.
- POST /repair/{pid}/retract     — logical, history-preserving retraction of a
  committed assertion (mandatory reason) + removal of its DERIVED projection
  row so paint re-derives (the assertion and retraction records remain).
- POST /repair/{pid}/update      — correction through the record's OWN
  mechanics (2026-07-28 ruling: repair is top-down and repairs ALL THE WAY
  DOWN the stack; nothing mutates in place, nothing is annotated): a
  mis-read assertion TIME or VALUE lands as a NEW assertion with the SAME
  basis SUPERSEDING the old; entity RECORD-BEARING attributes (every
  domain._MIRROR_COLUMNS attribute) require basis_clause and land as
  property assertions — correction supersedes priors, change (change: true)
  closes the prior's valid_to and appends; entity ADDRESSING/STRUCTURE
  columns (name/template_key/entity_type/organic parent — entity_type
  registry-validated, no minting) stay direct and audited; the entity's
  ASCOPE tags; or a clause's PMESII facet tags (2026-07-27 tag layers).
  Every item's echo (priors included) lands in the events log
  (world.repair.* rows) — the record itself carries NO operational notes.
- POST /repair/{pid}/purge       — delete a projection row ONLY when no
  assertion backs it (bypass-writer corruption cleanup); refuses backed rows.

Every batched item echoes independently; one bad item never rolls back the
rest of the batch.
"""
import uuid as uuid_mod
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from geoalchemy2 import WKTElement
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session, get_db
from app.models.graph import (GraphEdge, GraphHolding, GraphNode,
                              GraphNodePosition)
from app.models.reference import RelationshipType
from app.models.world import (Assertion, AssertionBasis, Clause, Retraction,
                              Section)

router = APIRouter()

_KINDS = ("property", "state", "relationship", "holding", "position")
# Assert builds BOTTOM-UP from L0; repair enters TOP-DOWN and must land
# all the way back at the record layer (2026-07-28 ruling). Fields with
# a mirror column in the world model (domain._MIRROR_COLUMNS: echelon,
# affiliation, unit_type, posture, ...) are RECORD-BEARING: correcting
# one writes a property ASSERTION with clause basis, supersedes the
# prior assertions on that attribute, and materializes onto the column
# — never a bare column write, which is exactly the provenance-free
# bypass the world-model rewrite exists to kill. Only ADDRESSING and
# STRUCTURE stay direct (audited) column ops: name, template_key,
# entity_type (registry-validated, no minting), organic parent.
_DIRECT_IDENTITY_FIELDS = ("name", "template_key", "organic_parent",
                           "entity_type")

_ctx = SimpleNamespace(layer="project", origin_record_id=None, actor="_repair")


async def _entity(db: AsyncSession, pid: UUID, ref: str) -> GraphNode:
    """Resolve an entity by UUID or fold-insensitive name (project layer)."""
    try:
        node = await db.get(GraphNode, UUID(str(ref)))
        if node is not None and node.project_id == pid:
            return node
    except (ValueError, AttributeError, TypeError):
        pass
    from app.services.graph_ingest.tools import _find_node
    return await _find_node(db, pid, str(ref))


async def _remirror(db: AsyncSession, node: GraphNode) -> Optional[str]:
    """Recompute node.geom from the newest remaining track row (newest
    OBSERVATION wins — track.py's rule, re-run after a row is removed or its
    observed_at corrected)."""
    newest = (await db.execute(
        select(GraphNodePosition)
        .where(GraphNodePosition.node_id == node.id)
        .order_by(GraphNodePosition.observed_at.desc())
        .limit(1))).scalars().first()
    node.geom = newest.geom if newest is not None else None
    return str(newest.id) if newest is not None else None


def _parse_time(raw: Optional[str], path: str):
    if raw is None:
        return None
    from app.services.graph_ingest.track import parse_dtg
    parsed = parse_dtg(raw)
    if parsed is None:
        raise ValueError(f"{path}: unparseable DTG {raw!r}")
    return parsed


def _position_props(item: dict) -> dict:
    """Point/line/polygon payload -> assertion properties (+geom_wkt for
    non-points). Mirrors the ingestion staging resolution: MGRS is resolved at
    write time so a bad grid rejects the item. Server-drawn notations
    (S17.3 absorption from the removed set_shapes writer): circle_mgrs +
    radius_m, rect_mgrs opposite-corner pair, ellipse_mgrs + semi axes +
    orientation — the server generates every ring; hand-extrapolated
    vertex lists stay banned."""
    import math
    from app.utils.mgrs_utils import mgrs_to_latlng

    def _poly(pts) -> dict:
        ring = pts + ([pts[0]] if pts[0] != pts[-1] else [])
        wkt = "POLYGON((" + ", ".join(
            f"{lo} {la}" for (la, lo) in ring) + "))"
        la0, lo0 = pts[0]
        return {"geom_wkt": wkt, "lat": la0, "lon": lo0}

    if item.get("circle_mgrs"):
        la, lo = mgrs_to_latlng(item["circle_mgrs"])
        r = float(item.get("radius_m") or 0)
        if r <= 0:
            raise ValueError("circle_mgrs needs radius_m > 0")
        pts = []
        lon_m = 111320.0 * max(0.2, math.cos(math.radians(la)))
        for i in range(24):
            th = 2.0 * math.pi * i / 24
            pts.append((la + (r * math.cos(th)) / 111320.0,
                        lo + (r * math.sin(th)) / lon_m))
        return {**_poly(pts), "mgrs": item["circle_mgrs"]}
    if item.get("rect_mgrs"):
        corners = item["rect_mgrs"]
        if not (isinstance(corners, list) and len(corners) == 2):
            raise ValueError("rect_mgrs needs exactly two opposite-corner "
                             "MGRS grids")
        (la1, lo1), (la2, lo2) = (mgrs_to_latlng(corners[0]),
                                  mgrs_to_latlng(corners[1]))
        w, e = min(lo1, lo2), max(lo1, lo2)
        s_, n_ = min(la1, la2), max(la1, la2)
        return {**_poly([(s_, w), (s_, e), (n_, e), (n_, w)]),
                "mgrs": corners[0]}
    if item.get("ellipse_mgrs"):
        la, lo = mgrs_to_latlng(item["ellipse_mgrs"])
        a = float(item.get("semi_major_m") or 0)
        b = float(item.get("semi_minor_m") or 0)
        if a <= 0 or b <= 0:
            raise ValueError("ellipse_mgrs needs semi_major_m and "
                             "semi_minor_m > 0")
        theta = math.radians(float(item.get("orientation_deg") or 0.0))
        lat_m = 111320.0
        lon_m = 111320.0 * max(0.2, math.cos(math.radians(la)))
        pts = []
        for i in range(36):
            t = 2.0 * math.pi * i / 36
            east = (a * math.cos(t) * math.sin(theta)
                    + b * math.sin(t) * math.cos(theta))
            north = (a * math.cos(t) * math.cos(theta)
                     - b * math.sin(t) * math.sin(theta))
            pts.append((la + north / lat_m, lo + east / lon_m))
        return {**_poly(pts), "mgrs": item["ellipse_mgrs"]}
    if item.get("mgrs_line") or item.get("mgrs_polygon"):
        grids = item.get("mgrs_line") or item.get("mgrs_polygon")
        pts = [mgrs_to_latlng(g) for g in grids]
        coords = [f"{lon} {lat}" for (lat, lon) in pts]
        if item.get("mgrs_polygon"):
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            wkt = f"POLYGON(({', '.join(coords)}))"
        else:
            wkt = f"LINESTRING({', '.join(coords)})"
        la, lo = pts[0]
        return {"geom_wkt": wkt, "lat": la, "lon": lo,
                "mgrs": grids[0]}
    if item.get("mgrs"):
        la, lo = mgrs_to_latlng(item["mgrs"])
        return {"lat": la, "lon": lo, "mgrs": item["mgrs"]}
    if item.get("lat") is not None and item.get("lon") is not None:
        return {"lat": item["lat"], "lon": item["lon"]}
    raise ValueError("position item needs mgrs, lat+lon, mgrs_line, "
                     "mgrs_polygon, circle_mgrs + radius_m, rect_mgrs "
                     "(two opposite corners), or ellipse_mgrs + "
                     "semi_major_m + semi_minor_m + orientation_deg")


# ── Finders ──────────────────────────────────────────────────────────

@router.get("/repair/{project_id}/clauses")
async def find_clauses(project_id: UUID, q: Optional[str] = Query(None),
                       untagged: bool = Query(False),
                       limit: int = Query(10, le=600),
                       db: AsyncSession = Depends(get_db)):
    """Committed-clause finder: ILIKE over clause text when q is given;
    without q it enumerates (tag-backfill listing). untagged=true narrows to
    clauses with no PMESII facets."""
    stmt = (select(Clause, Section)
            .join(Section, Section.id == Clause.section_id)
            .where(Clause.project_id == project_id,
                   Clause.record_state == "committed"))
    if q:
        stmt = stmt.where(Clause.text.ilike(f"%{q}%"))
    if untagged:
        stmt = stmt.where(Clause.pmesii.is_(None))
    rows = (await db.execute(
        stmt.order_by(Clause.created_at, Clause.order_index)
        .limit(limit))).all()
    return {"clauses": [
        {"id": str(c.id), "text": c.text, "pmesii": c.pmesii,
         "valid_from": c.valid_from.isoformat() if c.valid_from else None,
         "headings": s.headings} for c, s in rows]}


@router.get("/repair/{project_id}/entities")
async def find_entities(project_id: UUID, kind: Optional[str] = Query(None),
                        untagged: bool = Query(False),
                        unbound: bool = Query(False),
                        limit: int = Query(400, le=600),
                        db: AsyncSession = Depends(get_db)):
    """Project-layer entity listing for tag work — names duplicate across
    kinds and regions, so corrections address rows by UUID. untagged=true
    narrows to entities with no ASCOPE categories. unbound=true switches
    to the UNRESOLVED-OCCURRENCE listing instead: committed occurrences
    with no canonical entity binding (L1 defects awaiting resolution —
    the review queue occurrence corrections feed)."""
    if unbound:
        from app.models.world import EntityOccurrence
        rows = (await db.execute(
            select(EntityOccurrence, Section)
            .join(Section, Section.id == EntityOccurrence.section_id)
            .where(Section.project_id == project_id,
                   EntityOccurrence.record_state == "committed",
                   EntityOccurrence.canonical_node_id.is_(None))
            .order_by(EntityOccurrence.designation)
            .limit(limit))).all()
        return {"occurrences": [
            {"id": str(o.id), "designation": o.designation,
             "entity_type": o.entity_type, "headings": s.headings}
            for o, s in rows], "count": len(rows)}
    stmt = select(GraphNode).where(GraphNode.project_id == project_id,
                                   GraphNode.layer == "project")
    if kind:
        stmt = stmt.where(GraphNode.entity_type == kind)
    if untagged:
        stmt = stmt.where(GraphNode.ascope.is_(None))
    rows = (await db.execute(
        stmt.order_by(GraphNode.entity_type, GraphNode.name, GraphNode.id)
        .limit(limit))).scalars().all()
    return {"entities": [
        {"id": str(n.id), "name": n.name, "entity_type": n.entity_type,
         "ascope": n.ascope} for n in rows], "count": len(rows)}


@router.get("/repair/{project_id}/assertions")
async def find_assertions(project_id: UUID, entity: str = Query(...),
                          kind: Optional[str] = Query(None),
                          attribute: Optional[str] = Query(None),
                          db: AsyncSession = Depends(get_db)):
    """Every committed assertion whose subject/from/to is the entity."""
    node = await _entity(db, project_id, entity)
    stmt = select(Assertion).where(
        Assertion.project_id == project_id,
        Assertion.record_state == "committed",
        (Assertion.subject_node_id == node.id)
        | (Assertion.from_node_id == node.id)
        | (Assertion.to_node_id == node.id))
    if kind:
        stmt = stmt.where(Assertion.kind == kind)
    if attribute:
        stmt = stmt.where(Assertion.attribute == attribute)
    rows = (await db.execute(stmt.order_by(Assertion.valid_from))).scalars().all()
    out = []
    for a in rows:
        to_name = from_name = None
        if a.to_node_id:
            to = await db.get(GraphNode, a.to_node_id)
            to_name = to.name if to else None
        if a.from_node_id:
            fr = await db.get(GraphNode, a.from_node_id)
            from_name = fr.name if fr else None
        out.append({
            "id": str(a.id), "kind": a.kind, "attribute": a.attribute,
            "value": a.value_text if a.value_num is None else a.value_num,
            "relation": a.relation, "from": from_name, "to": to_name,
            "properties": a.properties,
            "valid_from": a.valid_from.isoformat() if a.valid_from else None,
            "valid_to": a.valid_to.isoformat() if a.valid_to else None,
            "retracted": a.retracted_by is not None,
            "superseded": a.superseded_by is not None,
            "materialized_position": (str(a.materialized_position_id)
                                      if a.materialized_position_id else None),
            "materialized_edge": (str(a.materialized_edge_id)
                                  if a.materialized_edge_id else None),
        })
    return {"entity": node.name, "entity_id": str(node.id), "assertions": out}


@router.get("/repair/{project_id}/positions")
async def find_positions(project_id: UUID, entity: str = Query(...),
                         db: AsyncSession = Depends(get_db)):
    """The entity's full track, each row with the assertion backing it (or
    unbacked = bypass-writer row, purgeable)."""
    node = await _entity(db, project_id, entity)
    rows = (await db.execute(
        select(GraphNodePosition)
        .where(GraphNodePosition.node_id == node.id)
        .order_by(GraphNodePosition.observed_at))).scalars().all()
    backing = {a.materialized_position_id: a for a in (await db.execute(
        select(Assertion).where(
            Assertion.materialized_position_id.in_([r.id for r in rows])
        ))).scalars().all()} if rows else {}
    return {"entity": node.name, "entity_id": str(node.id), "track": [
        {"row": str(r.id), "mgrs": r.mgrs,
         "observed_at": r.observed_at.isoformat() if r.observed_at else None,
         "dtg_label": r.dtg_label,
         "source": getattr(r, "source", None),
         "backed_by": (str(backing[r.id].id) if r.id in backing else None),
         "backing_retracted": (backing[r.id].retracted_by is not None
                               if r.id in backing else None)}
        for r in rows]}


# ── Writes ───────────────────────────────────────────────────────────

class Batch(BaseModel):
    items: List[dict]


async def _emit_events(db: AsyncSession, project_id: UUID, op: str,
                       echoes: List[dict]) -> None:
    """Operational audit goes to THE granular logging system
    (analyst_events), never onto the record (2026-07-28 ruling). Each
    batch item logs one event carrying its full echo — priors, refs,
    reconciliation context, and the caller's note all live HERE. The
    record itself stays statements + basis + its own mechanics
    (supersession / retraction / valid windows)."""
    import time as _time
    from app.models.analyst_event import AnalystEvent
    now_ms = int(_time.time() * 1000)
    for e in echoes:
        db.add(AnalystEvent(
            occurred_at_ms=None, received_at_ms=now_ms,
            user_id="_repair", map_id=str(project_id),
            surface="world_repair",
            event_type=f"world.repair.{op}"
                       + (".error" if "error" in e else ""),
            detail=e))
    await db.commit()


@router.post("/repair/{project_id}/assert")
async def repair_assert(project_id: UUID, body: Batch,
                        db: AsyncSession = Depends(get_db)):
    """Create any committed assertion, clause basis REQUIRED. Item:
    {entity, kind, basis_clause, dtg?, valid_to?, attribute?, value?,
    relation?, to?, properties?, count?, mgrs?|lat+lon?|mgrs_line?|
    mgrs_polygon?|circle_mgrs?|rect_mgrs?|ellipse_mgrs?, note?}.
    valid_from = stated dtg, else the basis clause's valid_from; an item
    with neither is rejected (a repair never invents an observation
    time).

    CLAUSE-AUTHORING FORM (S17.1 entry form b — the L1 entry): instead
    of basis_clause, new_clause: {section (committed section UUID),
    text} authors a NEW atomic reading of already-captured text — the
    clause lands committed under that section, about-linked to the
    subject entity's occurrence there (bound or created), and becomes
    THIS item's basis. It grounds in the existing revision: no new
    source, no actor-as-source."""
    from app.services.world.domain import _materialize
    echoes = []
    for i, item in enumerate(body.items):
        try:
            kind = item.get("kind")
            if kind not in _KINDS:
                raise ValueError(f"kind must be one of {_KINDS}")
            node = await _entity(db, project_id, item.get("entity") or "")
            if item.get("new_clause"):
                from app.models.world import ClauseAbout, EntityOccurrence
                nc = item["new_clause"]
                section = await db.get(Section,
                                       UUID(str(nc.get("section"))))
                if section is None or section.project_id != project_id \
                        or section.record_state != "committed":
                    raise ValueError("new_clause.section is not a committed "
                                     "section of this project")
                text_ = (nc.get("text") or "").strip()
                if not text_:
                    raise ValueError("new_clause needs text — the atomic "
                                     "reading of the section's captured "
                                     "passage")
                cl_time = _parse_time(item.get("dtg"), f"items[{i}].dtg")
                if cl_time is None:
                    raise ValueError("a new clause needs the item's stated "
                                     "dtg — an authored reading never "
                                     "invents an observation time")
                next_ix = (await db.execute(
                    select(func.max(Clause.order_index))
                    .where(Clause.section_id == section.id))).scalar()
                clause = Clause(
                    id=uuid_mod.uuid4(), project_id=project_id,
                    section_id=section.id,
                    order_index=(next_ix or 0) + 1,
                    text=text_, valid_from=cl_time,
                    record_state="committed")
                db.add(clause)
                await db.flush()
                occ = (await db.execute(
                    select(EntityOccurrence).where(
                        EntityOccurrence.section_id == section.id,
                        EntityOccurrence.designation == node.name)
                )).scalars().first()
                if occ is None:
                    occ = EntityOccurrence(
                        id=uuid_mod.uuid4(), section_id=section.id,
                        designation=node.name,
                        entity_type=node.entity_type,
                        record_state="committed",
                        canonical_node_id=node.id)
                    db.add(occ)
                    await db.flush()
                elif occ.canonical_node_id is None:
                    occ.canonical_node_id = node.id
                db.add(ClauseAbout(clause_id=clause.id,
                                   occurrence_id=occ.id))
            else:
                clause = await db.get(
                    Clause, UUID(str(item.get("basis_clause"))))
                if clause is None or clause.project_id != project_id \
                        or clause.record_state != "committed":
                    raise ValueError("basis_clause is not a committed "
                                     "clause of this project")
            valid_from = (_parse_time(item.get("dtg"), f"items[{i}].dtg")
                          or clause.valid_from)
            if valid_from is None:
                raise ValueError("no observation time: item has no dtg and "
                                 "the basis clause has no valid_from")
            a = Assertion(
                id=uuid_mod.uuid4(), kind=kind, project_id=project_id,
                subject_node_id=node.id if kind != "relationship" else None,
                attribute=item.get("attribute"),
                value_text=(str(item["value"])
                            if item.get("value") is not None else None),
                count=item.get("count"),
                properties=None, valid_from=valid_from,
                valid_to=_parse_time(item.get("valid_to"),
                                     f"items[{i}].valid_to"),
                record_state="committed", layer="project")
            if kind == "relationship":
                rel = item.get("relation") or ""
                if await db.get(RelationshipType, rel) is None:
                    raise ValueError(f"unknown relation {rel!r} (repair does "
                                     "not mint types)")
                to = await _entity(db, project_id, item.get("to") or "")
                a.from_node_id, a.to_node_id = node.id, to.id
                a.relation = rel
                a.properties = item.get("properties")
            if kind == "position":
                a.properties = _position_props(item)
            # The caller's note goes to the EVENT LOG below, never onto
            # the record — the assertion carries statement + basis only.
            db.add(a)
            await db.flush()
            db.add(AssertionBasis(id=uuid_mod.uuid4(), assertion_id=a.id,
                                  clause_id=clause.id))
            materialized = await _materialize(db, _ctx, a)
            await db.commit()
            echoes.append({"index": i, "entity": node.name,
                           "assertion": str(a.id), "kind": kind,
                           "valid_from": valid_from.isoformat(),
                           "materialized": bool(materialized),
                           **({"clause": str(clause.id)}
                              if item.get("new_clause") else {}),
                           **({"lat": a.properties.get("lat"),
                               "lon": a.properties.get("lon")}
                              if kind == "position" and a.properties
                              else {}),
                           **({"note": item["note"]}
                              if item.get("note") else {})})
        except (ValueError, KeyError, TypeError) as e:
            await db.rollback()
            echoes.append({"index": i, "error": str(e)})
    # Position echoes carry the nearest named place (the old writer's
    # verification echo, absorbed per S17.3) — read-only context.
    from app.services.graph_ingest.tools import _enrich_nearest, _nudge
    await _enrich_nearest(echoes)
    await _nudge(project_id)
    await _emit_events(db, project_id, "assert", echoes)
    return {"results": echoes}


@router.post("/repair/{project_id}/retract")
async def repair_retract(project_id: UUID, body: Batch,
                         db: AsyncSession = Depends(get_db)):
    """Logical retraction. Item: {assertion, reason}. History is preserved
    (assertion + retraction records remain); the DERIVED projection row is
    removed so paint re-derives from the surviving record."""
    echoes = []
    for i, item in enumerate(body.items):
        try:
            a = await db.get(Assertion, UUID(str(item.get("assertion"))))
            if a is None or a.project_id != project_id:
                raise ValueError("assertion not found in this project")
            reason = (item.get("reason") or "").strip()
            if not reason:
                raise ValueError("reason is required")
            r = Retraction(id=uuid_mod.uuid4(), assertion_id=a.id,
                           basis_note=reason, record_state="committed")
            db.add(r)
            a.retracted_by = r.id
            undone = None
            if a.materialized_position_id:
                row = await db.get(GraphNodePosition,
                                   a.materialized_position_id)
                node = await db.get(GraphNode, a.subject_node_id)
                if row is not None:
                    await db.delete(row)
                    await db.flush()
                a.materialized_position_id = None
                if node is not None:
                    undone = await _remirror(db, node)
            if a.materialized_edge_id:
                edge = await db.get(GraphEdge, a.materialized_edge_id)
                if edge is not None:
                    await db.delete(edge)
                a.materialized_edge_id = None
            if a.materialized_holding_id:
                h = await db.get(GraphHolding, a.materialized_holding_id)
                if h is not None:
                    await db.delete(h)
                a.materialized_holding_id = None
            await db.commit()
            echoes.append({"index": i, "assertion": str(a.id),
                           "retraction": str(r.id),
                           "reason": reason,
                           "projection_now": undone})
        except (ValueError, KeyError, TypeError) as e:
            await db.rollback()
            echoes.append({"index": i, "error": str(e)})
    from app.services.graph_ingest.tools import _nudge
    await _nudge(project_id)
    await _emit_events(db, project_id, "retract", echoes)
    return {"results": echoes}


@router.post("/repair/{project_id}/update")
async def repair_update(project_id: UUID, body: Batch,
                        db: AsyncSession = Depends(get_db)):
    """Record correction through the record's OWN mechanics — never an
    in-place mutation, never annotation prose (2026-07-28 ruling: repair
    is top-down and repairs all the way down the stack; history lives IN
    the record; the operational narrative lives in the events log).
    Items:
    {target: "assertion", ref, valid_from?|valid_to?, value?|count?|
    mgrs?|lat+lon?|mgrs_line?|mgrs_polygon?, note?} — a mis-read TIME or
    VALUE correction: a NEW assertion with the corrected fields and the
    SAME basis SUPERSEDES the old one; the old materialized row is
    removed and the new assertion materializes fresh.
    {target: "entity", ref, <fields>, change?, basis_clause?, dtg?,
    ascope?, note?} — record-bearing attributes route through property
    assertions (correction = supersession; change: true = the prior stays
    true for its interval, gets valid_to closed, nothing superseded);
    addressing/structure columns stay direct and audited.
    {target: "clause", ref, pmesii, note?} — the clause's PMESII facet
    list (closed vocabulary; the statement itself is immutable)."""
    from app.services.world.domain import (DomainError, check_tags,
                                           _materialize)
    from app.models.graph import ASCOPE_CATEGORIES
    from app.models.world import PMESII_FACETS
    echoes = []
    for i, item in enumerate(body.items):
        try:
            note = item.get("note")
            if item.get("target") == "assertion":
                a = await db.get(Assertion, UUID(str(item.get("ref"))))
                if a is None or a.project_id != project_id:
                    raise ValueError("assertion not found in this project")
                if a.retracted_by is not None or a.superseded_by is not None:
                    raise ValueError("assertion already retracted or "
                                     "superseded — correct the current one")
                geom_fix = any(k in item for k in
                               ("mgrs", "lat", "mgrs_line", "mgrs_polygon"))
                if geom_fix and a.kind != "position":
                    raise ValueError("geometry correction applies to a "
                                     "position assertion")
                prior = {"valid_from": (a.valid_from.isoformat()
                                        if a.valid_from else None),
                         "valid_to": (a.valid_to.isoformat()
                                      if a.valid_to else None),
                         "value": a.value_text, "count": a.count,
                         "properties": a.properties}
                # The correcting assertion: corrected fields over the
                # old ones, everything else carried, SAME basis.
                new_a = Assertion(
                    id=uuid_mod.uuid4(), kind=a.kind,
                    project_id=project_id,
                    subject_node_id=a.subject_node_id,
                    from_node_id=a.from_node_id, to_node_id=a.to_node_id,
                    relation=a.relation, attribute=a.attribute,
                    value_text=(str(item["value"])
                                if item.get("value") is not None
                                else a.value_text),
                    count=(item["count"] if item.get("count") is not None
                           else a.count),
                    properties=(_position_props(item) if geom_fix
                                else a.properties),
                    valid_from=(_parse_time(item.get("valid_from"),
                                            f"items[{i}].valid_from")
                                or a.valid_from),
                    valid_to=(_parse_time(item.get("valid_to"),
                                          f"items[{i}].valid_to")
                              or a.valid_to),
                    record_state="committed", layer=a.layer)
                db.add(new_a)
                await db.flush()
                for b in (await db.execute(
                        select(AssertionBasis).where(
                            AssertionBasis.assertion_id == a.id)
                )).scalars().all():
                    db.add(AssertionBasis(id=uuid_mod.uuid4(),
                                          assertion_id=new_a.id,
                                          clause_id=b.clause_id))
                a.superseded_by = new_a.id
                # The superseded projection row goes; the correction
                # materializes fresh through the one write path.
                node = (await db.get(GraphNode, a.subject_node_id)
                        if a.subject_node_id else None)
                if a.materialized_position_id:
                    row = await db.get(GraphNodePosition,
                                       a.materialized_position_id)
                    if row is not None:
                        await db.delete(row)
                        await db.flush()
                    a.materialized_position_id = None
                if a.materialized_edge_id:
                    edge = await db.get(GraphEdge, a.materialized_edge_id)
                    if edge is not None:
                        await db.delete(edge)
                    a.materialized_edge_id = None
                if a.materialized_holding_id:
                    h = await db.get(GraphHolding, a.materialized_holding_id)
                    if h is not None:
                        await db.delete(h)
                    a.materialized_holding_id = None
                materialized = await _materialize(db, _ctx, new_a)
                mirrored = (await _remirror(db, node)
                            if node is not None and a.kind == "position"
                            else None)
                await db.commit()
                echoes.append({"index": i, "superseded": str(a.id),
                               "assertion": str(new_a.id), "prior": prior,
                               "materialized": bool(materialized),
                               "projection_now": mirrored,
                               **({"note": note} if note else {})})
            elif item.get("target") == "clause":
                clause = await db.get(Clause, UUID(str(item.get("ref"))))
                if clause is None or clause.project_id != project_id \
                        or clause.record_state != "committed":
                    raise ValueError("clause not found committed in this "
                                     "project")
                if "pmesii" not in item:
                    raise ValueError("clause target corrects pmesii only")
                prior = {"pmesii": clause.pmesii}
                clause.pmesii = check_tags(item["pmesii"], PMESII_FACETS,
                                           "pmesii", f"items[{i}].pmesii")
                await db.commit()
                echoes.append({"index": i, "clause": str(clause.id),
                               "applied": {"pmesii": clause.pmesii},
                               "prior": prior,
                               **({"note": note} if note else {})})
            elif item.get("target") == "entity":
                from app.services.world.domain import (_MIRROR_COLUMNS,
                                                       _check_value,
                                                       _materialize)
                from app.models.reference import EntityType
                from app.models.world import (ClauseAbout, Derivation,
                                              EntityOccurrence)

                # ── MERGE (alias-correction repair): the ingestion minted
                # two entities for ONE referent. Everything the duplicate
                # anchors — occurrences, assertions, track rows, holdings,
                # edges, children, fields — repoints to the canonical
                # entity, then the empty duplicate projection row goes.
                # The record (occurrences + assertions) survives intact,
                # now chained to the one true entity.
                if item.get("merge_into"):
                    from sqlalchemy import update as _upd
                    from app.models.graph import NodeField
                    dup = await _entity(db, project_id, item.get("ref") or "")
                    canon = await _entity(db, project_id,
                                          str(item["merge_into"]))
                    if dup.id == canon.id:
                        raise ValueError("merge_into targets the same entity")
                    moved = {}
                    for label, model, col in (
                            ("occurrences", EntityOccurrence,
                             EntityOccurrence.canonical_node_id),
                            ("positions", GraphNodePosition,
                             GraphNodePosition.node_id),
                            ("holdings", GraphHolding, GraphHolding.node_id),
                            ("node_fields", NodeField, NodeField.node_id),
                            ("children", GraphNode,
                             GraphNode.organic_parent_id)):
                        r = await db.execute(
                            _upd(model).where(col == dup.id)
                            .values({col.key: canon.id}))
                        moved[label] = r.rowcount
                    for label, col in (
                            ("assertions_subject", Assertion.subject_node_id),
                            ("assertions_from", Assertion.from_node_id),
                            ("assertions_to", Assertion.to_node_id)):
                        r = await db.execute(
                            _upd(Assertion).where(col == dup.id)
                            .values({col.key: canon.id}))
                        moved[label] = r.rowcount
                    for label, col in (("edges_from", GraphEdge.from_id),
                                       ("edges_to", GraphEdge.to_id)):
                        r = await db.execute(
                            _upd(GraphEdge).where(col == dup.id)
                            .values({col.key: canon.id}))
                        moved[label] = r.rowcount
                    dup_name = dup.name
                    await db.delete(dup)
                    await db.flush()
                    await _remirror(db, canon)
                    await db.commit()
                    echoes.append({"index": i, "merged": dup_name,
                                   "into": canon.name,
                                   "canonical": str(canon.id),
                                   "moved": moved,
                                   **({"note": note} if note else {})})
                    continue

                # ── CREATE (ingestion-gap repair, top-down to L0): the
                # source text NAMES the entity — the basis clause proves
                # it — but the ingestion never minted it. The repair
                # mints it CHAINED: node + occurrence in the basis
                # clause's section (bound to any occurrence the section
                # already declared) + the clause_about index; attributes
                # then flow through the record-bearing path below with
                # the same basis.
                if item.get("create"):
                    if not item.get("basis_clause"):
                        raise ValueError("create needs basis_clause — the "
                                         "clause that names the entity")
                    c_clause = await db.get(
                        Clause, UUID(str(item["basis_clause"])))
                    if c_clause is None or c_clause.project_id != project_id \
                            or c_clause.record_state != "committed":
                        raise ValueError("basis_clause is not a committed "
                                         "clause of this project")
                    etype = item.get("entity_type") or "unit"
                    if await db.get(EntityType, etype) is None:
                        raise ValueError(f"unknown entity_type {etype!r} "
                                         "(repair does not mint types)")
                    name = (item.get("name") or "").strip()
                    if not name:
                        raise ValueError("create needs name")
                    node = GraphNode(
                        id=uuid_mod.uuid4(), project_id=project_id,
                        entity_type=etype, name=name, layer="project",
                        created_by="_repair")
                    db.add(node)
                    await db.flush()
                    occ = (await db.execute(
                        select(EntityOccurrence).where(
                            EntityOccurrence.section_id
                            == c_clause.section_id,
                            EntityOccurrence.designation == name)
                    )).scalars().first()
                    if occ is None:
                        occ = EntityOccurrence(
                            id=uuid_mod.uuid4(),
                            section_id=c_clause.section_id,
                            designation=name, entity_type=etype,
                            record_state="committed",
                            canonical_node_id=node.id)
                        db.add(occ)
                        await db.flush()
                        db.add(ClauseAbout(clause_id=c_clause.id,
                                           occurrence_id=occ.id))
                    else:
                        occ.canonical_node_id = node.id
                    item = {**item, "ref": str(node.id)}
                else:
                    node = await _entity(db, project_id,
                                         item.get("ref") or "")
                prior, applied = {}, {}
                if item.get("create"):
                    applied["created"] = str(node.id)
                if "ascope" in item:
                    prior["ascope"] = node.ascope
                    node.ascope = check_tags(item["ascope"],
                                             ASCOPE_CATEGORIES, "ascope",
                                             f"items[{i}].ascope")
                    applied["ascope"] = node.ascope
                # Record-bearing corrections — through the full stack:
                # property assertion + REQUIRED clause basis, priors
                # superseded, column set by materialization.
                record_fields = [f for f in _MIRROR_COLUMNS if f in item]
                designation_basis = item.get("basis") == "designation"
                clause = None
                if record_fields:
                    basis_err = (
                        f"{record_fields} are record-bearing: the "
                        "correction needs basis_clause (a committed "
                        "clause of this project) or basis: "
                        "'designation' when the entity's own recorded "
                        "designation states the value — it lands as a "
                        "property assertion, never a bare column write")
                    if designation_basis:
                        # The designation IS record data (it was ingested
                        # from the source): "10th Army Corps" states its
                        # own echelon. The basis is a DERIVATION from the
                        # recorded designation — existing schema
                        # (assertion_basis.derivation_id), no clause hunt.
                        pass
                    elif not item.get("basis_clause"):
                        raise ValueError(basis_err)
                    else:
                        clause = await db.get(
                            Clause, UUID(str(item["basis_clause"])))
                        if clause is None \
                                or clause.project_id != project_id \
                                or clause.record_state != "committed":
                            raise ValueError(basis_err)
                    # TIME CONTRACT (2026-07-21): stated DTG → source
                    # time; else the basis clause's time; unstated →
                    # assertion-moment stamp.
                    valid_from = (_parse_time(item.get("dtg"),
                                              f"items[{i}].dtg")
                                  or (clause.valid_from if clause is not None
                                      else None)
                                  or datetime.now(timezone.utc))
                    # change: true = the value CHANGED at valid_from (the
                    # prior was true for its interval — it gets valid_to
                    # closed, never superseded). Default = correction
                    # (the prior was wrong ab initio — superseded).
                    is_change = bool(item.get("change"))
                    for f in record_fields:
                        value = (str(item[f])
                                 if item[f] is not None else None)
                        _check_value(f, value, f"items[{i}].{f}")
                        priors = (await db.execute(
                            select(Assertion).where(
                                Assertion.project_id == project_id,
                                Assertion.subject_node_id == node.id,
                                Assertion.kind.in_(("property", "state")),
                                Assertion.attribute == f,
                                Assertion.record_state == "committed",
                                Assertion.superseded_by.is_(None),
                                Assertion.retracted_by.is_(None),
                            ))).scalars().all()
                        if is_change:
                            for p in priors:
                                if (p.valid_from is not None
                                        and valid_from is not None
                                        and p.valid_from > valid_from):
                                    raise ValueError(
                                        f"{f}: change at "
                                        f"{valid_from.isoformat()} predates "
                                        "the newest assertion — out-of-order "
                                        "history is a correction, not a "
                                        "change")
                        a = Assertion(
                            id=uuid_mod.uuid4(), kind="property",
                            project_id=project_id,
                            subject_node_id=node.id, attribute=f,
                            value_text=value, valid_from=valid_from,
                            record_state="committed", layer="project")
                        db.add(a)
                        await db.flush()
                        for p in priors:
                            if is_change:
                                if p.valid_to is None:
                                    p.valid_to = valid_from
                            else:
                                p.superseded_by = a.id
                        if designation_basis:
                            d = Derivation(
                                id=uuid_mod.uuid4(),
                                project_id=project_id,
                                method="attribute_from_designation",
                                method_version="1",
                                input_refs={"node_id": str(node.id),
                                            "designation": node.name,
                                            "attribute": f},
                                layer="project")
                            db.add(d)
                            await db.flush()
                            db.add(AssertionBasis(id=uuid_mod.uuid4(),
                                                  assertion_id=a.id,
                                                  derivation_id=d.id))
                        else:
                            db.add(AssertionBasis(id=uuid_mod.uuid4(),
                                                  assertion_id=a.id,
                                                  clause_id=clause.id))
                        prior[f] = getattr(node, f)
                        await _materialize(db, _ctx, a)
                        applied[f] = value
                for f in _DIRECT_IDENTITY_FIELDS:
                    if f not in item:
                        continue
                    if f == "organic_parent":
                        parent = (await _entity(db, project_id, item[f])
                                  if item[f] else None)
                        pid_walk = parent
                        while pid_walk is not None:
                            if pid_walk.id == node.id:
                                raise ValueError("organic_parent cycle")
                            pid_walk = (await db.get(
                                GraphNode, pid_walk.organic_parent_id)
                                if pid_walk.organic_parent_id else None)
                        prior[f] = (str(node.organic_parent_id)
                                    if node.organic_parent_id else None)
                        node.organic_parent_id = parent.id if parent else None
                        applied[f] = parent.name if parent else None
                    elif f == "entity_type":
                        from app.models.reference import EntityType
                        if await db.get(EntityType, item[f]) is None:
                            raise ValueError(
                                f"unknown entity_type {item[f]!r} (repair "
                                "does not mint types)")
                        prior[f] = node.entity_type
                        node.entity_type = item[f]
                        applied[f] = item[f]
                    else:
                        prior[f] = getattr(node, f)
                        setattr(node, f, item[f])
                        applied[f] = item[f]
                node.updated_by = "_repair"
                await db.commit()
                echoes.append({"index": i, "entity": node.name,
                               "applied": applied, "prior": prior,
                               **({"note": note} if note else {})})
            elif item.get("target") == "occurrence":
                # L1 occurrence correction (2026-07-28 taxonomy): an
                # identity the source never actually named is an
                # OCCURRENCE defect, fixed at L1 — re-bind the misread
                # occurrence to what the section actually named, or
                # clear the binding (cleared occurrences surface in the
                # unbound finder — the review queue). Entity removal is
                # never an operation; an entity left with no bindings
                # and no live assertions is an empty projection row.
                from app.models.world import EntityOccurrence
                occ = await db.get(EntityOccurrence,
                                   UUID(str(item.get("ref"))))
                sec = (await db.get(Section, occ.section_id)
                       if occ is not None else None)
                if occ is None or sec is None \
                        or sec.project_id != project_id:
                    raise ValueError("occurrence not found in this project")
                if "bind_to" not in item:
                    raise ValueError("occurrence target needs bind_to — an "
                                     "entity ref to re-bind, or null to "
                                     "clear the binding")
                prior_binding = (str(occ.canonical_node_id)
                                 if occ.canonical_node_id else None)
                if item["bind_to"]:
                    target_node = await _entity(db, project_id,
                                                str(item["bind_to"]))
                    occ.canonical_node_id = target_node.id
                    bound = target_node.name
                else:
                    occ.canonical_node_id = None
                    bound = None
                await db.commit()
                echoes.append({"index": i, "occurrence": str(occ.id),
                               "designation": occ.designation,
                               "bound_to": bound,
                               "prior": {"canonical_node_id": prior_binding},
                               **({"note": note} if note else {})})
            else:
                raise ValueError("target must be 'assertion', 'entity', "
                                 "'clause', or 'occurrence'")
        except (ValueError, KeyError, TypeError, DomainError) as e:
            await db.rollback()
            echoes.append({"index": i, "error": str(e)})
    from app.services.graph_ingest.tools import _nudge
    await _nudge(project_id)
    await _emit_events(db, project_id, "update", echoes)
    return {"results": echoes}


@router.post("/repair/{project_id}/purge")
async def repair_purge(project_id: UUID, body: Batch,
                       db: AsyncSession = Depends(get_db)):
    """Delete an UNBACKED projection row (bypass-writer corruption). Item:
    {kind: "position"|"edge"|"holding", row}. A row referenced by any
    assertion is REFUSED — that correction is retract, not purge."""
    echoes = []
    for i, item in enumerate(body.items):
        try:
            kind = item.get("kind")
            rid = UUID(str(item.get("row")))
            col = {"position": Assertion.materialized_position_id,
                   "edge": Assertion.materialized_edge_id,
                   "holding": Assertion.materialized_holding_id}.get(kind)
            if col is None:
                raise ValueError("kind must be position|edge|holding")
            backing = (await db.execute(
                select(Assertion.id).where(col == rid))).scalars().first()
            if backing is not None:
                raise ValueError(f"row is backed by assertion {backing} — "
                                 "use retract")
            model = {"position": GraphNodePosition, "edge": GraphEdge,
                     "holding": GraphHolding}[kind]
            row = await db.get(model, rid)
            if row is None:
                raise ValueError("row not found")
            node = (await db.get(GraphNode, row.node_id)
                    if kind == "position" else None)
            await db.delete(row)
            await db.flush()
            now = await _remirror(db, node) if node is not None else None
            await db.commit()
            echoes.append({"index": i, "purged": str(rid), "kind": kind,
                           "entity": node.name if node else None,
                           "projection_now": now})
        except (ValueError, KeyError, TypeError) as e:
            await db.rollback()
            echoes.append({"index": i, "error": str(e)})
    from app.services.graph_ingest.tools import _nudge
    await _nudge(project_id)
    await _emit_events(db, project_id, "purge", echoes)
    return {"results": echoes}


# ── MCP adapters ─────────────────────────────────────────────────────
# S17.2: the general verbs get MCP registration alongside the OOB tools
# so agents reach every entry layer. Each adapter owns its session (the
# graph_ingest/tools.py convention); mcp_server.py only adapts these to
# tool registrations. Same handlers as the REST routes — one write path,
# every echo in the events log.

async def tool_assert(project_id: str, items: List[dict]) -> dict:
    async with async_session() as db:
        return await repair_assert(UUID(str(project_id)),
                                   Batch(items=items), db=db)


async def tool_update(project_id: str, items: List[dict]) -> dict:
    async with async_session() as db:
        return await repair_update(UUID(str(project_id)),
                                   Batch(items=items), db=db)


async def tool_retract(project_id: str, items: List[dict]) -> dict:
    async with async_session() as db:
        return await repair_retract(UUID(str(project_id)),
                                    Batch(items=items), db=db)


async def tool_purge(project_id: str, items: List[dict]) -> dict:
    async with async_session() as db:
        return await repair_purge(UUID(str(project_id)),
                                  Batch(items=items), db=db)


async def tool_find_clauses(project_id: str, q: Optional[str] = None,
                            untagged: bool = False,
                            limit: int = 10) -> dict:
    async with async_session() as db:
        return await find_clauses(UUID(str(project_id)), q=q,
                                  untagged=untagged, limit=limit, db=db)


async def tool_find_entities(project_id: str, kind: Optional[str] = None,
                             untagged: bool = False,
                             limit: int = 400,
                             unbound: bool = False) -> dict:
    async with async_session() as db:
        return await find_entities(UUID(str(project_id)), kind=kind,
                                   untagged=untagged, unbound=unbound,
                                   limit=limit, db=db)


async def tool_find_assertions(project_id: str, entity: str,
                               kind: Optional[str] = None,
                               attribute: Optional[str] = None) -> dict:
    async with async_session() as db:
        return await find_assertions(UUID(str(project_id)), entity=entity,
                                     kind=kind, attribute=attribute, db=db)


async def tool_find_positions(project_id: str, entity: str) -> dict:
    async with async_session() as db:
        return await find_positions(UUID(str(project_id)), entity=entity,
                                    db=db)


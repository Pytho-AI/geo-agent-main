"""Entity-graph API — READS + reference/registry curation (S17 cutover,
2026-07-28).

Reads: GET /graph/{project_id} (bulk, snapshot-consistent, carries the
registries so consumers interpret typed rows without a second call),
GET /oob/{project_id} (the ORDER OF BATTLE read), cards/briefs/clauses/
coverage, the equipment catalog, and display-field routes (working
layer). Project-record writes live on the world surface
(app/api/v1/world_repair.py) — the legacy CRUD, template instantiate,
import pipeline, wipe, and graph snapshots are GONE (2026-07-28
rulings: material enters through the world-model ingestion pipeline;
deleting the project is the wipe; the record is the history).
Registry/equipment writes remain API-only curation (no UI).
"""
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.graph import (
    ECHELONS, EdgeField, ForceTemplate, GraphEdge, GraphHolding, GraphNode,
    GraphNodePosition, NodeField,
)
from app.models.reference import (
    EntityType, FactClause, FieldDef, RelationshipType, WegEquipment,
    WegEquipmentAlias, WegEquipmentEmitter, WegEquipmentRangeCandidate,
)
from app.services.graph_ingest.tools import equipment_conditions as _equipment_conditions
from app.schemas.graph import (
    EntityTypeUpsert, EquipmentUpsert, FieldDefUpsert, FieldValuePut,
    RelationshipTypeUpsert,
)

log = logging.getLogger(__name__)
router = APIRouter()

_NODE_FIELDS = (
    "entity_type", "weg_id", "external_id", "name", "long_name",
    "affiliation", "category", "posture", "organic_parent_id", "unit_type",
    "echelon", "personnel_authorized", "personnel_current",
    "personnel_killed", "personnel_wounded", "personnel_captured",
    "combat_effectiveness", "assessment_basis", "significance",
    "significance_note", "current_activity", "notes", "template_key",
    "symbol_set", "symbol_entity_code", "symbol_mod1", "symbol_mod2",
)



async def _nudge(project_id, entity_count: Optional[int] = None):
    """Post-commit coalesced graph_updated frame — refetch trigger,
    never a data channel. Best-effort by the sync_complete rule."""
    try:
        from app.services.realtime.manager import manager
        await manager.notify_change(
            str(project_id), "graph_updated",
            {"project_id": str(project_id), "entity_count": entity_count},
        )
    except Exception:
        log.exception("graph_updated broadcast failed (non-fatal)")


async def _entity_count(db: AsyncSession, project_id) -> int:
    return (await db.execute(
        select(func.count()).select_from(GraphNode)
        .where(GraphNode.project_id == project_id, GraphNode.layer == "project"))).scalar_one()




async def _alias_sweep(db: AsyncSession) -> set:
    """Deployment-wide re-resolution of weg_id-null holdings.
    MERGE-AWARE in one transaction (design §3.4): plain resolve where
    (node_id, weg_id) is free; the §3.3 merge (counts summed, duplicate
    dropped, raw string kept on the survivor's audit trail) where it
    collides. Returns affected project ids for per-project nudges."""
    rows = (await db.execute(
        select(GraphHolding, WegEquipmentAlias.weg_id.label("resolved"))
        .join(WegEquipmentAlias, WegEquipmentAlias.alias == GraphHolding.nomenclature_raw)
        .where(GraphHolding.weg_id.is_(None)))).all()
    projects = set()
    for holding, resolved in rows:
        existing = (await db.execute(
            select(GraphHolding).where(
                GraphHolding.node_id == holding.node_id,
                GraphHolding.weg_id == resolved))).scalar_one_or_none()
        if existing is None:
            holding.weg_id = resolved
        else:
            for col in ("count_authorized", "count_current", "count_degraded",
                        "count_neutralized", "count_destroyed",
                        "count_captured_abandoned"):
                a, b = getattr(existing, col), getattr(holding, col)
                if a is not None or b is not None:
                    setattr(existing, col, (a or 0) + (b or 0))
            await db.delete(holding)
        proj = (await db.execute(
            select(GraphNode.project_id).where(GraphNode.id == holding.node_id)
        )).scalar_one_or_none()
        if proj:
            projects.add(proj)
    return projects


def _node_out(n: GraphNode, lon, lat) -> dict:
    d = {"id": str(n.id), "project_id": str(n.project_id) if n.project_id else None,
         "lon": lon, "lat": lat,
         "created_by": n.created_by, "updated_by": n.updated_by}
    for f in _NODE_FIELDS:
        v = getattr(n, f)
        d[f] = str(v) if isinstance(v, UUID) else v
    return d


@router.get("/graph/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ForceTemplate).order_by(ForceTemplate.name))).scalars().all()
    return [{"key": t.key, "name": t.name, "echelon": t.echelon,
             "tier": t.tier, "doctrine_source": t.doctrine_source,
             "as_of": t.as_of, "source": t.source} for t in rows]


@router.get("/graph/postures")
async def list_postures():
    """The posture values the disposition engine supports — the
    placard's posture selector reads this list, never a hardcoded
    copy (registered before /graph/{project_id} so 'postures' never
    parses as a project UUID)."""
    from app.services.graph_ingest.disposition import SUPPORTED_POSTURES
    return {"postures": list(SUPPORTED_POSTURES)}


# ── Reads ────────────────────────────────────────────────────────────

async def _read_graph(db: AsyncSession, project_id: UUID) -> dict:
    await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

    # ST_X/ST_Y ONLY on point geometry — control measures are
    # LINESTRING/POLYGON rows in the same table and ST_X on those is a
    # database ERROR (the whole bulk read 500'd once the first boundary
    # landed in a project). Lines/areas read lon/lat as their centroid
    # so the link view can still focus the camera on them.
    _pt = case(
        (func.ST_GeometryType(GraphNode.geom) == "ST_Point", GraphNode.geom),
        else_=func.ST_Centroid(GraphNode.geom))
    nodes = (await db.execute(
        select(GraphNode, func.ST_X(_pt), func.ST_Y(_pt))
        .where(GraphNode.project_id == project_id, GraphNode.layer == "project"))).all()
    node_ids = [n.GraphNode.id for n in nodes]

    holdings = (await db.execute(
        select(GraphHolding, WegEquipment)
        .outerjoin(WegEquipment, WegEquipment.weg_id == GraphHolding.weg_id)
        .where(GraphHolding.node_id.in_(node_ids)))).all() if node_ids else []
    edges = (await db.execute(select(GraphEdge).where(
        GraphEdge.from_id.in_(node_ids) | GraphEdge.to_id.in_(node_ids)
    ))).scalars().all() if node_ids else []
    nfields = (await db.execute(select(NodeField).where(
        NodeField.node_id.in_(node_ids)))).scalars().all() if node_ids else []
    efields = (await db.execute(select(EdgeField).where(
        EdgeField.edge_id.in_([e.id for e in edges])))).scalars().all() if edges else []
    etypes = (await db.execute(select(EntityType))).scalars().all()
    rtypes = (await db.execute(select(RelationshipType))).scalars().all()
    fdefs = (await db.execute(select(FieldDef))).scalars().all()

    # Rate-of-march: min road speed over holdings' catalog rows
    # (extracted sheet values count — decision 23).
    rom: dict = {}
    for h, cat in holdings:
        if cat and cat.road_speed_kph:
            k = str(h.node_id)
            rom[k] = min(rom.get(k, 10**9), cat.road_speed_kph)

    # Composed SIDC per node — the link view draws the same doctrinal
    # symbols the map does (plain colored dots made the chain-of-command
    # view unreadable). Same composition as the map paint path: entity
    # type, dominant holding's equipment class, instance catalog row.
    from app.utils.graph_symbols import compose_node_sidc
    etypes_by_key = {t.type_key: t for t in etypes}
    dominant: dict = {}
    for h, cat in holdings:
        if cat is None:
            continue
        k = str(h.node_id)
        n_count = h.count_current or h.count_authorized or 0
        if k not in dominant or n_count > dominant[k][0]:
            dominant[k] = (n_count, cat.equipment_class)
    inst_ids = {n.GraphNode.weg_id for n in nodes if n.GraphNode.weg_id}
    inst_cat = {c.weg_id: c for c in (await db.execute(
        select(WegEquipment).where(WegEquipment.weg_id.in_(inst_ids))
    )).scalars().all()} if inst_ids else {}

    def _sidc(n):
        try:
            return compose_node_sidc(
                n, etypes_by_key.get(n.entity_type),
                (dominant.get(str(n.id)) or (0, None))[1],
                inst_cat.get(n.weg_id))
        except Exception:
            return None

    return {
        "project_id": str(project_id),
        "entities": [
            {**_node_out(n.GraphNode, n[1], n[2]),
             "sidc": _sidc(n.GraphNode),
             "rate_of_march_kph": rom.get(str(n.GraphNode.id))}
            for n in nodes],
        "holdings": [
            {"id": str(h.id), "node_id": str(h.node_id), "weg_id": h.weg_id,
             "nomenclature_raw": h.nomenclature_raw,
             "count_authorized": h.count_authorized,
             "count_current": h.count_current,
             "count_degraded": h.count_degraded,
             "count_neutralized": h.count_neutralized,
             "count_destroyed": h.count_destroyed,
             "count_captured_abandoned": h.count_captured_abandoned,
             "catalog": None if not cat else {
                 "name": cat.name, "class": cat.equipment_class,
                 "category": cat.category,
                 "engagement_range_m": cat.engagement_range_m,
                 "detection_range_m": cat.detection_range_m}}
            for h, cat in holdings],
        "edges": [
            {"id": str(e.id), "from_id": str(e.from_id), "to_id": str(e.to_id),
             "relationship_type": e.relationship_type,
             "effective_from": e.effective_from.isoformat() if e.effective_from else None,
             "effective_to": e.effective_to.isoformat() if e.effective_to else None,
             "note": e.note} for e in edges],
        "node_fields": [
            {"node_id": str(f.node_id), "field_key": f.field_key, "value": f.value}
            for f in nfields],
        "edge_fields": [
            {"edge_id": str(f.edge_id), "field_key": f.field_key, "value": f.value}
            for f in efields],
        "entity_types": [
            {"type_key": t.type_key, "label": t.label, "color": t.color,
             "is_fixed": t.is_fixed, "symbol_set": t.symbol_set,
             "symbol_entity_code": t.symbol_entity_code,
             "default_category": t.default_category} for t in etypes],
        "relationship_types": [
            {"type_key": t.type_key, "label": t.label,
             "inverse_label": t.inverse_label, "color": t.color,
             "is_hierarchical": t.is_hierarchical} for t in rtypes],
        "field_defs": [
            {"field_key": f.field_key, "label": f.label,
             "value_type": f.value_type} for f in fdefs],
    }


@router.get("/graph/{project_id}")
async def bulk_read(project_id: UUID, db: AsyncSession = Depends(get_db)):
    return await _read_graph(db, project_id)


@router.get("/graph/nodes/{node_id}/card")
async def node_card(node_id: UUID, db: AsyncSession = Depends(get_db)):
    """Placard-shaped read for ONE node: the unit, its organic parent,
    its organic children (each with a composed SIDC + position so the
    placard can draw the symbol and fly the camera to it), equipment
    rolled up across the organic subtree, and the governing position
    observation (provenance). One fetch per placard open."""
    from app.utils.graph_symbols import compose_node_sidc
    node = await db.get(GraphNode, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    _pt = case(
        (func.ST_GeometryType(GraphNode.geom) == "ST_Point", GraphNode.geom),
        else_=func.ST_Centroid(GraphNode.geom))
    project_nodes = (await db.execute(
        select(GraphNode, func.ST_X(_pt), func.ST_Y(_pt))
        .where(GraphNode.project_id == node.project_id, GraphNode.layer == "project"))).all()
    by_id = {str(r.GraphNode.id): r for r in project_nodes}
    children_ix: dict = {}
    for r in project_nodes:
        gp = r.GraphNode.organic_parent_id
        if gp:
            children_ix.setdefault(str(gp), []).append(r)

    etypes = {t.type_key: t for t in
              (await db.execute(select(EntityType))).scalars().all()}
    node_ids = [r.GraphNode.id for r in project_nodes]
    holdings = (await db.execute(
        select(GraphHolding, WegEquipment)
        .outerjoin(WegEquipment, WegEquipment.weg_id == GraphHolding.weg_id)
        .where(GraphHolding.node_id.in_(node_ids)))).all() if node_ids else []
    by_node: dict = {}
    dominant: dict = {}
    for h, cat in holdings:
        k = str(h.node_id)
        by_node.setdefault(k, []).append((h, cat))
        n_count = h.count_current or h.count_authorized or 0
        if cat is not None and (k not in dominant or n_count > dominant[k][0]):
            dominant[k] = (n_count, cat.equipment_class)

    # THE SAME reference walk the map paints from (template_walk) — the
    # placard and the map must never disagree about a unit's doctrinal
    # equipment and subtree. Derived holdings key onto real nodes;
    # derived subordinates join the traversal as virtual holders marked
    # `derived` (view-only, never rows).
    from app.services.view.template_walk import derive_reference_walk
    _walk_pairs = [(r.GraphNode, None) for r in project_nodes]
    _walk_children = {pid: [r.GraphNode for r in rows]
                      for pid, rows in children_ix.items()}
    derived_holdings, derived_units = await derive_reference_walk(
        db, _walk_pairs, by_node, _walk_children)
    for k, rows in derived_holdings.items():
        by_node.setdefault(k, []).extend(rows)
    derived_children: dict = {}
    du_by_vid: dict = {}
    for du in derived_units:
        derived_children.setdefault(du["parent_ref"], []).append(
            du["virtual_id"])
        du_by_vid[du["virtual_id"]] = du
        if du.get("holdings"):
            by_node[du["virtual_id"]] = du["holdings"]

    def _sidc(n):
        try:
            return compose_node_sidc(
                n, etypes.get(n.entity_type),
                (dominant.get(str(n.id)) or (0, None))[1], None)
        except Exception:
            return None

    def _virtual_brief(du):
        shim = SimpleNamespace(
            affiliation=du["affiliation"], echelon=du["echelon"],
            entity_type=du["entity_type"], unit_type=du["unit_type"],
            symbol_set=du["symbol_set"],
            symbol_entity_code=du["symbol_entity_code"],
            symbol_mod1=du["symbol_mod1"], symbol_mod2=du["symbol_mod2"],
            weg_id=None, name=du["name"], category=du.get("category"),
            id=du["virtual_id"])
        try:
            sidc = compose_node_sidc(
                shim, etypes.get(du["entity_type"]), None, None,
                anticipated=True)
        except Exception:
            sidc = None
        return {"id": du["virtual_id"], "name": du["name"],
                "echelon": du["echelon"], "affiliation": du["affiliation"],
                "entity_type": du["entity_type"],
                "unit_type": du["unit_type"], "sidc": sidc,
                "lon": None, "lat": None, "derived": True}

    def _brief(r):
        n = r.GraphNode
        return {"id": str(n.id), "name": n.name, "echelon": n.echelon,
                "affiliation": n.affiliation, "entity_type": n.entity_type,
                "unit_type": n.unit_type, "sidc": _sidc(n),
                "lon": r[1], "lat": r[2]}

    # Equipment rollup: own + organic descendants, recorded AND derived
    # (same shape the map emit's composition_rollup carries).
    # `composition` carries the DETAILED rows (weg_id + display name +
    # count); `composition_by_unit` breaks the same holdings out PER
    # HOLDING UNIT (the analyst asked a formation placard "which unit is
    # the Orlan-10 even attached to" — the aggregate list could not
    # answer). Hover flows key off each holder's unit id (bearer-scoped
    # ring highlight; virtual ids match the map's derived feature ids).
    rollup: dict = {}
    comp_detail: dict = {}
    by_unit: list = []
    stack, seen = [str(node.id)], {str(node.id)}
    while stack:
        cur = stack.pop()
        cur_row = by_id.get(cur)
        cur_du = du_by_vid.get(cur)
        cur_items = []
        for h, cat in by_node.get(cur, []):
            key = (cat.name if cat
                   else (h.nomenclature_raw or h.weg_id
                         or "unresolved equipment"))
            n_count = h.count_current or h.count_authorized or 0
            rollup[key] = rollup.get(key, 0) + n_count
            d = comp_detail.setdefault(key, {
                "weg_id": h.weg_id, "name": key, "count": 0})
            d["count"] += n_count
            if d["weg_id"] is None and h.weg_id:
                d["weg_id"] = h.weg_id
            cur_items.append({"weg_id": h.weg_id, "name": key,
                              "count": n_count})
        if cur_items and cur_row is not None:
            n_cur = cur_row.GraphNode
            cur_items.sort(key=lambda d: (-d["count"], d["name"]))
            by_unit.append({
                "unit_id": str(n_cur.id), "unit_name": n_cur.name,
                "echelon": n_cur.echelon, "sidc": _sidc(n_cur),
                "is_self": str(n_cur.id) == str(node.id),
                "items": cur_items,
            })
        elif cur_items and cur_du is not None:
            cur_items.sort(key=lambda d: (-d["count"], d["name"]))
            vb = _virtual_brief(cur_du)
            by_unit.append({
                "unit_id": cur, "unit_name": vb["name"],
                "echelon": vb["echelon"], "sidc": vb["sidc"],
                "is_self": False, "derived": True,
                "items": cur_items,
            })
        for r in children_ix.get(cur, []):
            cid = str(r.GraphNode.id)
            if cid not in seen:
                seen.add(cid)
                stack.append(cid)
        for vid in derived_children.get(cur, []):
            if vid not in seen:
                seen.add(vid)
                stack.append(vid)
    # Self first, then holders in name order.
    by_unit.sort(key=lambda u: (not u["is_self"], u["unit_name"]))

    eff = func.coalesce(GraphNodePosition.observed_at,
                        GraphNodePosition.created_at)
    obs = (await db.execute(
        select(GraphNodePosition)
        .where(GraphNodePosition.node_id == node_id,
               GraphNodePosition.geom.isnot(None))
        .order_by(eff.desc()).limit(1))).scalar_one_or_none()
    # Chain-derived provenance for the placard Source line (2026-07-28
    # ruling) — same composer the map uses; stored string = fallback for
    # unbacked rows only.
    obs_source = None
    if obs is not None:
        from app.services.view.provenance import provenance_for_rows
        obs_source = ((await provenance_for_rows(db, [obs.id]))
                      .get(str(obs.id)) or obs.source)

    # The working-layer visual override (2026-07-28 ruling) — display
    # state the placard shows BESIDE the record posture, never as it.
    override_row = await db.get(NodeField, (node_id, "posture_override"))
    self_row = by_id.get(str(node_id))
    parent_row = (by_id.get(str(node.organic_parent_id))
                  if node.organic_parent_id else None)
    kids = children_ix.get(str(node_id), [])
    _ech_rank = {e: i for i, e in enumerate(ECHELONS)}
    kids.sort(key=lambda r: (-(_ech_rank.get(r.GraphNode.echelon, -1)),
                             r.GraphNode.name or ""))
    return {
        "unit": {**(_brief(self_row) if self_row else
                    {"id": str(node.id), "name": node.name,
                     "echelon": node.echelon,
                     "affiliation": node.affiliation,
                     "entity_type": node.entity_type,
                     "unit_type": node.unit_type,
                     "sidc": _sidc(node), "lon": None, "lat": None}),
                 "notes": node.notes, "significance": node.significance,
                 "posture": node.posture,
                 "posture_override": (override_row.value
                                      if override_row else None),
                 "combat_effectiveness": node.combat_effectiveness,
                 "personnel_authorized": node.personnel_authorized,
                 "personnel_current": node.personnel_current,
                 "template_key": node.template_key},
        "parent": _brief(parent_row) if parent_row else None,
        # Recorded children first (echelon-ranked), then this node's
        # DERIVED doctrinal subordinates in template order, each marked
        # `derived` — the placard shows the same subtree the map paints.
        "children": ([_brief(r) for r in kids]
                     + [_virtual_brief(du_by_vid[v])
                        for v in derived_children.get(str(node_id), [])]),
        "composition_rollup": rollup or None,
        "composition": sorted(comp_detail.values(),
                              key=lambda d: (-d["count"], d["name"])) or None,
        "composition_by_unit": by_unit or None,
        "position": None if obs is None else {
            "source": obs_source, "dtg": obs.dtg_label,
            "observed_at": (obs.observed_at.isoformat()
                            if obs.observed_at else None),
        },
    }


@router.get("/graph/nodes/{node_id}/brief")
async def node_brief(node_id: UUID,
                     as_of: Optional[datetime] = Query(
                         None, description="resolve state at this instant; "
                         "omitted = now"),
                     db: AsyncSession = Depends(get_db)):
    """The as-of resolver — the world model's placard read: the node's
    updatable attributes as supersession CHAINS (History), every
    statement's provenance (Sources), the doctrine clauses governing its
    template (Doctrine), and the position resolved at the scrub time
    (observed_at — the record's one temporal dimension). One shape
    serves the placard now and the timeline scrub at any t."""
    from app.services.entity_brief import build_brief
    node = await db.get(GraphNode, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    return await build_brief(db, node, as_of=as_of)


@router.get("/oob/{project_id}")
async def oob_read(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """The ORDER OF BATTLE read — the movable-force subset. Pruning
    contract: parents elide through fixed ancestors to the nearest
    MOVABLE ancestor (parent_elided: true); fixed children are pruned;
    no dangling parent uuids, ever."""
    full = await _read_graph(db, project_id)
    fixed_keys = {t["type_key"] for t in full["entity_types"] if t["is_fixed"]}
    by_id = {e["id"]: e for e in full["entities"]}

    def nearest_movable(pid):
        elided = False
        while pid is not None:
            p = by_id.get(pid)
            if p is None:
                return None, elided
            if p["entity_type"] not in fixed_keys:
                return pid, elided
            pid, elided = p["organic_parent_id"], True
        return None, elided

    entities = []
    kept = set()
    for e in full["entities"]:
        if e["entity_type"] in fixed_keys:
            continue
        pid, elided = nearest_movable(e["organic_parent_id"])
        e = dict(e, organic_parent_id=pid, parent_elided=elided)
        entities.append(e)
        kept.add(e["id"])
    return {
        "project_id": full["project_id"],
        "entities": entities,
        "holdings": [h for h in full["holdings"] if h["node_id"] in kept],
        "edges": [e for e in full["edges"]
                  if e["from_id"] in kept and e["to_id"] in kept],
        "node_fields": [f for f in full["node_fields"] if f["node_id"] in kept],
        "entity_types": full["entity_types"],
        "relationship_types": full["relationship_types"],
        "field_defs": full["field_defs"],
    }


# ── Legacy CRUD routes REMOVED (S17 cutover, 2026-07-28) ─────────────
# Node create/update/delete, edge CRUD, holdings CRUD, rearray, and the
# fact_clauses write endpoint are GONE: every project-record write goes
# through the world surface's general verbs (app/api/v1/world_repair.py
# — assert / update / retract / purge, MCP-registered), where it lands
# as a committed assertion chained to captured L0. An analyst action
# that cites no source is not a record write (working/draft layers
# only — e.g. the placard posture selector writes the posture_override
# NodeField below). Reads and display-field routes remain.


# ── Extensible fields ────────────────────────────────────────────────

def _validate_field_value(fd: FieldDef, value: str):
    try:
        if fd.value_type == "number":
            float(value)
        elif fd.value_type == "boolean":
            assert value.lower() in ("true", "false")
        elif fd.value_type == "timestamp":
            datetime.fromisoformat(value)
    except Exception:
        raise HTTPException(422, f"value does not validate as {fd.value_type}")


@router.put("/graph/nodes/{node_id}/fields/{field_key}")
async def put_node_field(node_id: UUID, field_key: str, body: FieldValuePut,
                         db: AsyncSession = Depends(get_db)):
    node = await db.get(GraphNode, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    fd = await db.get(FieldDef, field_key)
    if fd is None:
        raise HTTPException(422, "unknown field_key — create the def first")
    _validate_field_value(fd, body.value)
    row = await db.get(NodeField, (node_id, field_key))
    if row is None:
        db.add(NodeField(node_id=node_id, field_key=field_key,
                         value=body.value, updated_by=body.updated_by))
    else:
        row.value, row.updated_by = body.value, body.updated_by
    await db.commit()
    if node.project_id:
        await _nudge(node.project_id)
    return {"ok": True}


@router.delete("/graph/nodes/{node_id}/fields/{field_key}")
async def delete_node_field(node_id: UUID, field_key: str,
                            db: AsyncSession = Depends(get_db)):
    row = await db.get(NodeField, (node_id, field_key))
    if row is None:
        raise HTTPException(404, "field not set")
    node = await db.get(GraphNode, node_id)
    await db.delete(row)
    await db.commit()
    if node and node.project_id:
        await _nudge(node.project_id)
    return {"ok": True}


# ── Registries (structural columns immutable once referenced) ────────

async def _referenced(db: AsyncSession, model, col, key) -> bool:
    return (await db.execute(
        select(func.count()).select_from(model).where(col == key)
    )).scalar_one() > 0


@router.get("/graph-registries")
async def list_registries(db: AsyncSession = Depends(get_db)):
    """The registries' READ side. The tabs only ever had POST/DELETE —
    they rendered empty against fully seeded registries."""
    etypes = (await db.execute(
        select(EntityType).order_by(EntityType.type_key))).scalars().all()
    rtypes = (await db.execute(
        select(RelationshipType).order_by(RelationshipType.type_key))).scalars().all()
    fdefs = (await db.execute(
        select(FieldDef).order_by(FieldDef.field_key))).scalars().all()
    return {
        "entity_types": [
            {"type_key": t.type_key, "label": t.label, "is_fixed": t.is_fixed,
             "symbol_set": t.symbol_set,
             "symbol_entity_code": t.symbol_entity_code,
             "default_category": t.default_category,
             "color": getattr(t, "color", None), "source": t.source}
            for t in etypes],
        "relationship_types": [
            {"type_key": t.type_key, "label": t.label,
             "inverse_label": t.inverse_label,
             "is_hierarchical": t.is_hierarchical, "source": t.source}
            for t in rtypes],
        "field_defs": [
            {"field_key": f.field_key, "label": f.label,
             "value_type": f.value_type, "source": f.source}
            for f in fdefs],
    }


@router.post("/graph-registries/entity-types")
async def upsert_entity_type(body: EntityTypeUpsert,
                             db: AsyncSession = Depends(get_db)):
    row = await db.get(EntityType, body.type_key)
    data = body.model_dump(exclude_unset=True)
    if row is None:
        if data.get("is_fixed") is None:
            raise HTTPException(422, "is_fixed required on create")
        db.add(EntityType(**data, source="user"))
    else:
        if ("is_fixed" in data and data["is_fixed"] != row.is_fixed
                and await _referenced(db, GraphNode, GraphNode.entity_type, body.type_key)):
            raise HTTPException(409, "is_fixed is immutable while entities reference this type")
        for k, v in data.items():
            setattr(row, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/graph-registries/entity-types/{type_key}")
async def delete_entity_type(type_key: str, db: AsyncSession = Depends(get_db)):
    if await _referenced(db, GraphNode, GraphNode.entity_type, type_key):
        raise HTTPException(409, "type in use")
    row = await db.get(EntityType, type_key)
    if row is None:
        raise HTTPException(404, "unknown type")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/graph-registries/relationship-types")
async def upsert_relationship_type(body: RelationshipTypeUpsert,
                                   db: AsyncSession = Depends(get_db)):
    row = await db.get(RelationshipType, body.type_key)
    data = body.model_dump(exclude_unset=True)
    if row is None:
        if data.get("is_hierarchical") is None:
            raise HTTPException(422, "is_hierarchical required on create")
        db.add(RelationshipType(**data, source="user"))
    else:
        if ("is_hierarchical" in data and data["is_hierarchical"] != row.is_hierarchical
                and await _referenced(db, GraphEdge, GraphEdge.relationship_type, body.type_key)):
            raise HTTPException(409, "is_hierarchical is immutable while edges reference this type")
        for k, v in data.items():
            setattr(row, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/graph-registries/relationship-types/{type_key}")
async def delete_relationship_type(type_key: str, db: AsyncSession = Depends(get_db)):
    if await _referenced(db, GraphEdge, GraphEdge.relationship_type, type_key):
        raise HTTPException(409, "type in use")
    row = await db.get(RelationshipType, type_key)
    if row is None:
        raise HTTPException(404, "unknown type")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/graph-registries/field-defs")
async def upsert_field_def(body: FieldDefUpsert, db: AsyncSession = Depends(get_db)):
    row = await db.get(FieldDef, body.field_key)
    data = body.model_dump(exclude_unset=True)
    if row is None:
        db.add(FieldDef(**data, source="user"))
    else:
        if ("value_type" in data and data["value_type"] != row.value_type
                and (await _referenced(db, NodeField, NodeField.field_key, body.field_key)
                     or await _referenced(db, EdgeField, EdgeField.field_key, body.field_key))):
            raise HTTPException(409, "value_type is immutable while values reference this def")
        for k, v in data.items():
            setattr(row, k, v)
    await db.commit()
    return {"ok": True}


@router.delete("/graph-registries/field-defs/{field_key}")
async def delete_field_def(field_key: str, db: AsyncSession = Depends(get_db)):
    if (await _referenced(db, NodeField, NodeField.field_key, field_key)
            or await _referenced(db, EdgeField, EdgeField.field_key, field_key)):
        raise HTTPException(409, "def in use")
    row = await db.get(FieldDef, field_key)
    if row is None:
        raise HTTPException(404, "unknown def")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ── Catalog ──────────────────────────────────────────────────────────

@router.get("/equipment")
async def list_equipment(q: Optional[str] = Query(None),
                         domain: Optional[str] = Query(None),
                         equipment_class: Optional[str] = Query(None, alias="class"),
                         category: Optional[str] = Query(None),
                         category_group: Optional[str] = Query(None),
                         country: Optional[str] = Query(None),
                         operator: Optional[str] = Query(None),
                         year_min: Optional[int] = Query(None),
                         year_max: Optional[int] = Query(None),
                         offset: int = Query(0, ge=0),
                         limit: int = Query(50, ge=1, le=500),
                         db: AsyncSession = Depends(get_db)):
    """Paginated, filterable catalog read: {total, rows}. Search also
    matches taught aliases (a query for a reporting name like DOG EAR
    must find its system). Two distinct country axes: `country` filters
    ORIGIN, `operator` filters PROLIFERATION — both by membership in the
    canonical lists, so a joint program matches every partner and an
    operator query finds every system a country fields."""
    stmt = select(WegEquipment)
    for cond in _equipment_conditions(q, domain, equipment_class, category,
                                      country, operator, year_min, year_max,
                                      category_group=category_group):
        stmt = stmt.where(cond)
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery()))).scalar_one()
    # Relevance order on a text search (name/alias carriers above
    # content mentions), alphabetical browse otherwise — same ranking
    # the agent's search tool uses, with the same zero-result trigram
    # fallback so a typo still lands.
    from app.services.graph_ingest.tools import (
        equipment_ranking, _fuzzy_equipment_stmt)
    rows = (await db.execute(
        stmt.order_by(*equipment_ranking(q)).offset(offset).limit(limit)
    )).scalars().all()
    if not rows and q and not offset:
        rows = (await db.execute(
            _fuzzy_equipment_stmt(q, limit))).scalars().all()
        total = len(rows)
    ids = [r.weg_id for r in rows]
    emitters = (await db.execute(select(WegEquipmentEmitter).where(
        WegEquipmentEmitter.weg_id.in_(ids)))).scalars().all() if ids else []
    alias_rows = (await db.execute(select(WegEquipmentAlias).where(
        WegEquipmentAlias.weg_id.in_(ids)))).scalars().all() if ids else []
    aliases_by_weg: dict = {}
    for a in alias_rows:
        aliases_by_weg.setdefault(a.weg_id, []).append(a.alias)
    candidates = (await db.execute(select(WegEquipmentRangeCandidate).where(
        WegEquipmentRangeCandidate.weg_id.in_(ids))
        .order_by(WegEquipmentRangeCandidate.range_m))).scalars().all() if ids else []
    by_weg: dict = {}
    for e in emitters:
        by_weg.setdefault(e.weg_id, []).append({
            "emitter_type": e.emitter_type, "frequency_band": e.frequency_band,
            "frequency_ghz": e.frequency_ghz, "effective_range_km": e.effective_range_km,
            "tracking_range_km": e.tracking_range_km})
    cand_by_weg: dict = {}
    for c in candidates:
        cand_by_weg.setdefault(c.weg_id, []).append(
            {"label": c.label, "range_m": c.range_m,
             "condition": c.condition, "is_default": c.is_default})
    out = [{
        "weg_id": r.weg_id, "name": r.name, "domain": r.domain,
        "class": r.equipment_class, "category": r.category,
        "category_group": r.category_group,
        "category_path": r.category_path or [],
        "countries": r.countries or [],
        "operators": r.operators or [],
        "introduction_year": r.introduction_year,
        "images": r.images or [],
        "engagement_range_m": r.engagement_range_m,
        "range_candidates": cand_by_weg.get(r.weg_id, []),
        "detection_range_m": r.detection_range_m,
        "road_speed_kph": r.road_speed_kph, "crew": r.crew,
        "caliber": r.caliber,
        "characteristics": r.characteristics,
        "description": r.description,
        "alternative_designations": r.alternative_designations,
        "combat_weight": r.combat_weight,
        "date_of_introduction": r.date_of_introduction,
        "proliferation_note": r.proliferation_note,
        # The complete-seed catch-all: every performance/spec field the
        # sheet carries (specs), non-uniform leftovers, and raw_sheet_text.
        "sheet_data": r.sheet_data,
        "image_url": f"/equipment/{r.weg_id}/image" if r.image_path else None,
        "country_of_origin": r.country_of_origin,
        "emitters": by_weg.get(r.weg_id, []),
        "aliases": aliases_by_weg.get(r.weg_id, []),
    } for r in rows]
    return {"total": total, "offset": offset, "rows": out}


@router.get("/equipment/facets")
async def equipment_facets(q: Optional[str] = Query(None),
                           domain: Optional[str] = Query(None),
                           equipment_class: Optional[str] = Query(None, alias="class"),
                           category: Optional[str] = Query(None),
                           category_group: Optional[str] = Query(None),
                           country: Optional[str] = Query(None),
                           operator: Optional[str] = Query(None),
                           year_min: Optional[int] = Query(None),
                           year_max: Optional[int] = Query(None),
                           db: AsyncSession = Depends(get_db)):
    """Filter values + counts for the catalog pickers, SCOPED: each facet
    is computed with every OTHER active filter applied (standard faceted
    search), so the pickers behave hierarchically — pick domain=land and
    the class/category lists narrow to land holdings with land counts.
    Alphabetical, always: a picker is for FINDING a value. Origin and
    operator count per country across the canonical lists."""
    params = dict(q=q, domain=domain, equipment_class=equipment_class,
                  category=category, category_group=category_group,
                  country=country, operator=operator,
                  year_min=year_min, year_max=year_max)
    out = {}
    for name, col, excl in (
            ("domain", WegEquipment.domain, ("domain",)),
            ("category_group", WegEquipment.category_group,
             ("category_group",)),
            ("class", WegEquipment.equipment_class, ("class",))):
        stmt = (select(col, func.count()).where(col.isnot(None))
                .group_by(col).order_by(col.asc()))
        for cond in _equipment_conditions(exclude=excl, **params):
            stmt = stmt.where(cond)
        rows = (await db.execute(stmt)).all()
        out[name] = [{"value": v, "count": c} for v, c in rows]
    # Category rows carry their GROUP so the picker renders the source's
    # tree (group headers over leaf categories), not a flat list.
    stmt = (select(WegEquipment.category_group, WegEquipment.category,
                   func.count())
            .where(WegEquipment.category.isnot(None))
            .group_by(WegEquipment.category_group, WegEquipment.category)
            .order_by(WegEquipment.category_group.asc().nullsfirst(),
                      WegEquipment.category.asc()))
    for cond in _equipment_conditions(exclude=("category",), **params):
        stmt = stmt.where(cond)
    rows = (await db.execute(stmt)).all()
    out["category"] = [{"value": cat, "count": c, "group": grp}
                       for grp, cat, c in rows]
    for name, json_col, excl in (("country", WegEquipment.countries, ("country",)),
                                 ("operator", WegEquipment.operators, ("operator",))):
        elem = func.jsonb_array_elements_text(json_col).table_valued("value")
        stmt = (select(elem.c.value, func.count())
                .select_from(WegEquipment, elem)
                .group_by(elem.c.value).order_by(elem.c.value.asc()))
        for cond in _equipment_conditions(exclude=excl, **params):
            stmt = stmt.where(cond)
        rows = (await db.execute(stmt)).all()
        out[name] = [{"value": v, "count": c} for v, c in rows]
    yr = select(func.min(WegEquipment.introduction_year),
                func.max(WegEquipment.introduction_year))
    for cond in _equipment_conditions(exclude=("year",), **params):
        yr = yr.where(cond)
    lo, hi = (await db.execute(yr)).one()
    out["year_range"] = {"min": lo, "max": hi}
    return out


@router.get("/equipment/tokens")
async def equipment_tokens(db: AsyncSession = Depends(get_db)):
    """Lightweight full-catalog token feed for the WEG-sheet cross-link
    matcher: every system's id, name, and taught aliases — never
    paginated, so a late-alphabet system can always be linked."""
    rows = (await db.execute(
        select(WegEquipment.weg_id, WegEquipment.name))).all()
    aliases = (await db.execute(
        select(WegEquipmentAlias.weg_id, WegEquipmentAlias.alias))).all()
    by_weg: dict = {}
    for wid, alias in aliases:
        by_weg.setdefault(wid, []).append(alias)
    return [{"weg_id": wid, "name": name, "aliases": by_weg.get(wid, [])}
            for wid, name in rows]


WEG_IMAGES_BUCKET = "weg-images"
_THUMB_LONG_EDGE = 320


def _load_image_bytes(image_path: str):
    """Full-size bytes for a catalog image path: odin/ paths from the
    object store (missing object = visible error), legacy paths from the
    bundled weg_images/ files."""
    if image_path.startswith("odin/"):
        from app.services.products import artifacts
        body, content_type = artifacts.get_object(
            image_path, bucket=WEG_IMAGES_BUCKET)
        return body, content_type or "image/jpeg"
    from pathlib import Path
    img = (Path(__file__).resolve().parent.parent.parent
           / "data" / "weg_images" / image_path)
    if ".." in image_path or not img.is_file():
        raise FileNotFoundError(image_path)
    return img.read_bytes(), "image/jpeg"


def _thumb_bytes(image_path: str):
    """Aspect-preserving thumbnail (NEVER cropped — Wikipedia-style
    figures keep their shape), generated once and cached in the bucket
    under thumbs/."""
    from app.services.products import artifacts
    key = "thumbs/" + image_path
    try:
        return artifacts.get_object(key, bucket=WEG_IMAGES_BUCKET)
    except Exception:
        pass
    import io
    from PIL import Image
    body, _ = _load_image_bytes(image_path)
    im = Image.open(io.BytesIO(body))
    im.thumbnail((_THUMB_LONG_EDGE, _THUMB_LONG_EDGE))
    out = io.BytesIO()
    im.convert("RGB").save(out, format="JPEG", quality=82)
    data = out.getvalue()
    artifacts.put_bytes(key, data, "image/jpeg", bucket=WEG_IMAGES_BUCKET)
    return data, "image/jpeg"


def _serve_image(image_path: str, size: str):
    from fastapi.responses import Response
    try:
        if size == "thumb":
            body, content_type = _thumb_bytes(image_path)
        else:
            body, content_type = _load_image_bytes(image_path)
    except Exception:
        raise HTTPException(
            404, "image not provisioned "
                 "(scripts/load_weg_images.py loads the set)")
    return Response(content=body, media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/equipment/images/{object_path:path}")
async def get_equipment_image_object(object_path: str,
                                     size: Optional[str] = Query(None)):
    """Serve any catalog image by its figure path (the gallery reads
    this); ?size=thumb returns the cached aspect-preserving thumbnail."""
    if ".." in object_path:
        raise HTTPException(400, "bad path")
    return _serve_image(object_path, size or "full")


@router.get("/equipment/{weg_id}/image")
async def equipment_image(weg_id: str, size: Optional[str] = Query(None),
                          db: AsyncSession = Depends(get_db)):
    """The system's primary photograph (first figure); ?size=thumb for
    the list-row thumbnail."""
    row = await db.get(WegEquipment, weg_id)
    if row is None or not row.image_path:
        raise HTTPException(404, "no image for this system")
    return _serve_image(row.image_path, size or "full")


@router.put("/equipment/images/{object_path:path}")
async def put_equipment_image(object_path: str, request: Request):
    """Provisioning ingest for the full-resolution WEG image set: raw
    image bytes -> the weg-images bucket (MinIO primary; the S3 mirror
    rides the established artifact direction). Keys are the seed's
    images_index paths, so only the odin/ namespace is writable.

    Gate: when WEG_IMAGES_INGEST_TOKEN is set in the environment (any
    proxied deployment), the request must carry it in
    X-Provisioning-Token. Unset = open, the dev-box posture."""
    import os
    expected = os.environ.get("WEG_IMAGES_INGEST_TOKEN")
    if expected and request.headers.get("x-provisioning-token") != expected:
        raise HTTPException(403, "provisioning token required")
    if not object_path.startswith("odin/") or ".." in object_path:
        raise HTTPException(400, "image objects live under odin/")
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    content_type = request.headers.get("content-type") or "image/jpeg"
    from app.services.products import artifacts
    artifacts.put_bytes(object_path, body, content_type,
                        bucket=WEG_IMAGES_BUCKET)
    return {"ok": True, "object": object_path, "bytes": len(body)}


@router.post("/equipment")
async def upsert_equipment(body: EquipmentUpsert, db: AsyncSession = Depends(get_db)):
    row = await db.get(WegEquipment, body.weg_id)
    data = body.model_dump(exclude_unset=True, by_alias=False)
    if row is None:
        db.add(WegEquipment(**data, source="user"))
    else:
        for k, v in data.items():
            setattr(row, k, v)
    await db.commit()
    return {"ok": True}


@router.post("/equipment/{weg_id}/aliases")
async def add_alias(weg_id: str, alias: str = Query(...),
                    db: AsyncSession = Depends(get_db)):
    if await db.get(WegEquipment, weg_id) is None:
        raise HTTPException(404, "unknown weg_id")
    if await db.get(WegEquipmentAlias, alias) is not None:
        raise HTTPException(409, "alias already claimed")
    db.add(WegEquipmentAlias(alias=alias, weg_id=weg_id))
    projects = await _alias_sweep(db)
    await db.commit()
    for p in projects:
        await _nudge(p)
    return {"ok": True, "resolved_projects": len(projects)}


# ── Template instantiate/save removed (2026-07-28 ruling): doctrine paints from the reference walk; nothing instantiates template subtrees into projects. Template READS remain above. ──
# Import pipeline endpoints removed (S17 cutover): material enters through the world-model ingestion pipeline (world_sources capture + world_runs).
# Graph snapshots/restore removed (2026-07-28 ruling): the record is the history.
@router.get("/graph/{project_id}/source-documents")
async def list_source_documents(project_id: UUID,
                                include_text: bool = Query(False),
                                db: AsyncSession = Depends(get_db)):
    """L0 reads: the verbatim ingested documents (the provenance roots
    the register's clauses cite). include_text=true returns the full
    text for the Sources quote view."""
    from app.models.graph import SourceDocument
    rows = (await db.execute(
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id,
               SourceDocument.layer == "project")
        .order_by(SourceDocument.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "filename": r.filename,
             "created_by": r.created_by,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             **({"doc_text": r.doc_text} if include_text else
                {"chars": len(r.doc_text or "")})}
            for r in rows]


# Wipe removed (2026-07-28 ruling): deleting the PROJECT is the wipe.
@router.get("/graph/{project_id}/clause-stats")
async def clause_stats(project_id: UUID,
                       db: AsyncSession = Depends(get_db)):
    """Project clause-coverage statistics — the measurement read behind
    the per-project data-coverage audit (deterministic aggregate
    counts; no clause text). Counts episodic clauses by register /
    kind / source_kind, slot-bearing vs free statements, ABOUT
    resolution (entity-resolved vs unresolved), and the top source
    loci — which source documents actually contributed how many
    statements. Every per-project count is register-scoped: the
    project's rows split by register so predictive write-back and
    project-scoped gnomic material land in their own buckets, never
    silently inside the episodic numbers. Truly-global gnomic
    reference clauses (project_id NULL) are reported separately for
    context."""
    from sqlalchemy import case, func as sa_func
    from app.models.reference import FactClause
    proj = ((FactClause.project_id == project_id)
            & (FactClause.layer == "project"))
    ep = (proj) & (FactClause.register == "episodic")
    def _counts(col, where):
        return select(col, sa_func.count()).where(where).group_by(col)
    out: dict = {"project_id": str(project_id)}
    out["by_register"] = {str(k): c for k, c in (await db.execute(
        _counts(FactClause.register, proj))).all()}
    out["episodic_total"] = (await db.execute(
        select(sa_func.count()).where(ep))).scalar_one()
    for name, col in (("by_kind", FactClause.kind),
                      ("by_source_kind", FactClause.source_kind)):
        rows = (await db.execute(_counts(col, ep))).all()
        out[name] = {str(k): c for k, c in rows}
    out["slot_bearing"] = (await db.execute(select(sa_func.count()).where(
        ep, FactClause.slot.isnot(None)))).scalar_one()
    out["about_unresolved"] = (await db.execute(
        select(sa_func.count()).where(
            ep, FactClause.about.any("_unresolved")))).scalar_one()
    out["with_valid_time"] = (await db.execute(
        select(sa_func.count()).where(
            ep, FactClause.valid_from.isnot(None)))).scalar_one()
    locus_rows = (await db.execute(
        select(FactClause.source_locus, sa_func.count())
        .where(ep).group_by(FactClause.source_locus)
        .order_by(sa_func.count().desc()).limit(20))).all()
    out["top_source_loci"] = [{"locus": (l or "")[:120], "count": c}
                              for l, c in locus_rows]
    out["gnomic_global_total"] = (await db.execute(
        select(sa_func.count()).where(
            FactClause.register == "gnomic",
            FactClause.project_id.is_(None)))).scalar_one()
    out["gnomic_project_total"] = (await db.execute(
        select(sa_func.count()).where(
            FactClause.register == "gnomic", proj))).scalar_one()
    return out


@router.get("/graph/{project_id}/clauses")
async def list_clauses(project_id: UUID,
                       register: Optional[str] = Query(None),
                       kind: Optional[str] = Query(None),
                       about: Optional[str] = Query(None),
                       source_document: Optional[str] = Query(None),
                       q: Optional[str] = Query(None),
                       include_superseded: bool = Query(False),
                       include_global: bool = Query(True),
                       limit: int = Query(200, le=1000),
                       offset: int = Query(0, ge=0),
                       db: AsyncSession = Depends(get_db)):
    """PROJECT-SCOPED CLAUSE RETRIEVAL — the writer-context read
    (phase-0 step 6): filter by register / kind / ABOUT (entity id or
    name; names resolve via the graph) / source document (matched
    against the quote-bearing source_locus) / free text. Deterministic
    total ordering (observed_at desc, id desc — the retrieval half of
    the determinism contract). include_global adds the global gnomic
    reference layer beside this project's clauses; superseded rows are
    excluded unless asked for."""
    from sqlalchemy import or_
    from app.models.reference import FactClause
    scope = (FactClause.project_id == project_id)
    if include_global:
        scope = or_(scope, FactClause.project_id.is_(None))
    stmt = select(FactClause).where(scope,
                                    FactClause.layer == "project")
    if register:
        stmt = stmt.where(FactClause.register == register)
    if kind:
        stmt = stmt.where(FactClause.kind == kind)
    if about:
        key = about
        try:
            UUID(about)
        except ValueError:
            from app.services.graph_ingest.tools import _resolve_about
            resolved, _un = await _resolve_about(db, project_id, [about])
            key = resolved[0] if resolved else about
        stmt = stmt.where(FactClause.about.any(str(key)))
    if source_document:
        stmt = stmt.where(
            FactClause.source_locus.ilike(f"%{source_document}%"))
    if q:
        stmt = stmt.where(FactClause.text.ilike(f"%{q}%"))
    if not include_superseded:
        stmt = stmt.where(FactClause.superseded_by.is_(None))
    stmt = (stmt.order_by(FactClause.observed_at.desc().nulls_last(),
                          FactClause.id.desc())
            .limit(limit).offset(offset))
    rows = (await db.execute(stmt)).scalars().all()
    return {"clauses": [{
        "id": str(r.id), "text": r.text, "register": r.register,
        "kind": r.kind, "about": list(r.about or []), "slot": r.slot,
        "speaker": r.speaker, "source_kind": r.source_kind,
        "source_locus": r.source_locus,
        "scope": ("project" if r.project_id else "global"),
        "observed_at": (r.observed_at.isoformat()
                        if r.observed_at else None),
        "valid_from": (r.valid_from.isoformat()
                       if r.valid_from else None),
        "valid_to": (r.valid_to.isoformat() if r.valid_to else None),
        "superseded_by": (str(r.superseded_by)
                          if r.superseded_by else None),
    } for r in rows], "count": len(rows)}


@router.get("/graph/{project_id}/coverage")
async def coverage_audit(project_id: UUID,
                         db: AsyncSession = Depends(get_db)):
    """THE PHASE-0 GATE AUDIT: walks the per-(project, fact_class)
    EXPECTATION CONFIG in map attrs (key `coverage_expectations`:
    {fact_class: expected | scenario_empty | produced_in_step:<N>})
    and joins per-class counts. Class keys: an entity-type key counts
    graph nodes of that kind; "clause:<register>:<kind>" counts this
    project's non-superseded clauses of that pair. GREEN = every
    `expected` class non-empty (the other two states are honest
    emptiness declarations). Data only — no engine, no catalog."""
    from sqlalchemy import func as sa_func
    from app.models.graph import GraphNode
    from app.models.map import Map as _Map
    from app.models.reference import FactClause
    mrow = await db.get(_Map, project_id)
    expectations = ((mrow.attrs or {}).get("coverage_expectations")
                    if mrow is not None else None) or {}
    if not expectations:
        return {"green": False, "classes": [],
                "error": "no coverage_expectations set in map attrs"}
    out, gaps = [], []
    for fact_class, expectation in sorted(expectations.items()):
        if fact_class.startswith("clause:"):
            parts = fact_class.split(":", 2)
            reg = parts[1] if len(parts) > 1 else ""
            knd = parts[2] if len(parts) > 2 else ""
            stmt = select(sa_func.count()).where(
                FactClause.project_id == project_id,
                FactClause.layer == "project",
                FactClause.superseded_by.is_(None))
            if reg:
                stmt = stmt.where(FactClause.register == reg)
            if knd:
                stmt = stmt.where(FactClause.kind == knd)
            count = (await db.execute(stmt)).scalar_one()
        else:
            count = (await db.execute(
                select(sa_func.count()).where(
                    GraphNode.project_id == project_id, GraphNode.layer == "project",
                    GraphNode.entity_type == fact_class))).scalar_one()
        green = (count > 0) if expectation == "expected" else True
        out.append({"fact_class": fact_class,
                    "expectation": expectation,
                    "count": count, "green": green})
        if not green:
            gaps.append(fact_class)
    return {"green": not gaps, "classes": out, "gaps": gaps}

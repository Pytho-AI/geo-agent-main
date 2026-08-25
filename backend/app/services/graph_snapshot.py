"""Graph snapshots — the recovery net for bulk writers.

capture() serializes a project's COMPLETE graph state (nodes, edges,
holdings, positions, node fields, episodic clauses) into one JSONB
payload; restore() deletes the project's current rows and re-inserts
from a snapshot, auto-capturing a pre_restore snapshot first so restore
is itself undoable. Document ingest and wipe call capture() before
mutating anything, so a wrong-file ingest into a hand-curated event is
one restore away instead of permanent damage.
"""
import logging
import uuid as uuid_mod
from datetime import datetime

from geoalchemy2.elements import WKTElement
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import (
    GraphEdge, GraphHolding, GraphNode, GraphNodePosition, GraphSnapshot,
    NodeField,
)
from app.models.reference import FactClause

log = logging.getLogger("app.graph_snapshot")


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _row(obj, cols, geom_wkt=None):
    d = {}
    for c in cols:
        v = getattr(obj, c)
        if isinstance(v, uuid_mod.UUID):
            v = str(v)
        d[c] = _iso(v)
    if geom_wkt is not None:
        d["geom_wkt"] = geom_wkt
    return d


_NODE_COLS = (
    "id", "project_id", "template_id", "entity_type", "weg_id",
    "external_id", "observed_at", "name", "long_name", "affiliation",
    "category", "posture", "organic_parent_id", "unit_type", "echelon",
    "personnel_authorized", "personnel_current", "personnel_killed",
    "personnel_wounded", "personnel_captured", "combat_effectiveness",
    "assessment_basis", "significance", "significance_note",
    "current_activity", "notes", "template_key", "symbol_set",
    "symbol_entity_code", "symbol_mod1", "symbol_mod2", "created_by",
    "updated_by", "created_at", "updated_at",
)
_EDGE_COLS = ("id", "from_id", "to_id", "relationship_type",
              "effective_from", "effective_to", "note", "created_by",
              "created_at")
_HOLD_COLS = ("id", "node_id", "weg_id", "nomenclature_raw",
              "count_authorized", "count_current", "count_degraded",
              "count_neutralized", "count_destroyed",
              "count_captured_abandoned", "created_by", "updated_by",
              "created_at", "updated_at")
_POS_COLS = ("id", "node_id", "mgrs", "location_text", "observed_at",
             "dtg_label", "activity", "source", "created_by", "created_at")
_FIELD_COLS = ("node_id", "field_key", "value", "created_by",
               "updated_by", "updated_at")
_CLAUSE_COLS = ("id", "text", "register", "speaker", "source_kind",
                "source_locus", "about", "valid_from", "valid_to",
                "observed_at", "project_id", "slot", "kind",
                "superseded_by", "created_at")


async def capture(db: AsyncSession, project_id, *, label: str = None,
                  trigger: str = "manual",
                  created_by: str = "_system") -> str:
    """Serialize the project's whole graph into one snapshot row."""
    nodes = (await db.execute(
        select(GraphNode, func.ST_AsText(GraphNode.geom))
        .where(GraphNode.project_id == project_id))).all()
    node_ids = [r.GraphNode.id for r in nodes]
    edges = (await db.execute(select(GraphEdge).where(
        GraphEdge.from_id.in_(node_ids)))).scalars().all() if node_ids else []
    holds = (await db.execute(select(GraphHolding).where(
        GraphHolding.node_id.in_(node_ids)))).scalars().all() if node_ids else []
    poss = (await db.execute(
        select(GraphNodePosition, func.ST_AsText(GraphNodePosition.geom))
        .where(GraphNodePosition.node_id.in_(node_ids)))).all() if node_ids else []
    fields = (await db.execute(select(NodeField).where(
        NodeField.node_id.in_(node_ids)))).scalars().all() if node_ids else []
    clauses = (await db.execute(select(FactClause).where(
        FactClause.project_id == project_id))).scalars().all()

    payload = {
        "nodes": [_row(r.GraphNode, _NODE_COLS, r[1]) for r in nodes],
        "edges": [_row(e, _EDGE_COLS) for e in edges],
        "holdings": [_row(h, _HOLD_COLS) for h in holds],
        "positions": [_row(r.GraphNodePosition, _POS_COLS, r[1])
                      for r in poss],
        "node_fields": [_row(f, _FIELD_COLS) for f in fields],
        "clauses": [_row(c, _CLAUSE_COLS) for c in clauses],
    }
    snap = GraphSnapshot(project_id=project_id, label=(label or "")[:255],
                         trigger=trigger, created_by=created_by,
                         payload=payload)
    db.add(snap)
    await db.commit()
    log.info("graph snapshot %s captured for %s (%s): %d nodes / %d "
             "positions / %d clauses", snap.id, project_id, trigger,
             len(payload["nodes"]), len(payload["positions"]),
             len(payload["clauses"]))
    return str(snap.id)


_DT_KEYS = {"observed_at", "created_at", "updated_at", "effective_from",
            "effective_to", "valid_from", "valid_to"}


def _mk(model, row, geom_key="geom_wkt"):
    d = dict(row)
    wkt = d.pop(geom_key, None)
    for k in list(d):
        if k in _DT_KEYS and isinstance(d[k], str):
            d[k] = datetime.fromisoformat(d[k])
    obj = model(**d)
    if wkt:
        obj.geom = WKTElement(wkt, srid=4326)
    return obj


async def restore(db: AsyncSession, snapshot_id) -> dict:
    """Replace the project's current graph with the snapshot's rows.
    Captures a pre_restore snapshot of the current state first."""
    snap = await db.get(GraphSnapshot, snapshot_id)
    if snap is None:
        raise ValueError("snapshot not found")
    project_id = snap.project_id
    undo_id = await capture(db, project_id,
                            label=f"before restoring {snapshot_id}",
                            trigger="pre_restore")

    node_ids = [r[0] for r in (await db.execute(
        select(GraphNode.id).where(
            GraphNode.project_id == project_id))).all()]
    if node_ids:
        await db.execute(delete(NodeField).where(
            NodeField.node_id.in_(node_ids)))
        await db.execute(delete(GraphNodePosition).where(
            GraphNodePosition.node_id.in_(node_ids)))
        await db.execute(delete(GraphHolding).where(
            GraphHolding.node_id.in_(node_ids)))
        await db.execute(delete(GraphEdge).where(
            GraphEdge.from_id.in_(node_ids)))
    await db.execute(delete(FactClause).where(
        FactClause.project_id == project_id))
    await db.execute(delete(GraphNode).where(
        GraphNode.project_id == project_id))
    await db.flush()

    p = snap.payload or {}
    # Nodes first without parents (self-FK), then set parents.
    parents = {}
    for row in p.get("nodes", []):
        row = dict(row)
        parent = row.pop("organic_parent_id", None)
        if parent:
            parents[row["id"]] = parent
        db.add(_mk(GraphNode, row))
    await db.flush()
    for nid, parent in parents.items():
        node = await db.get(GraphNode, nid)
        if node is not None:
            node.organic_parent_id = parent
    for row in p.get("edges", []):
        db.add(_mk(GraphEdge, row))
    for row in p.get("holdings", []):
        db.add(_mk(GraphHolding, row))
    for row in p.get("positions", []):
        db.add(_mk(GraphNodePosition, row))
    for row in p.get("node_fields", []):
        db.add(_mk(NodeField, row))
    for row in p.get("clauses", []):
        db.add(_mk(FactClause, row))
    await db.commit()
    counts = {k: len(p.get(k, [])) for k in
              ("nodes", "edges", "holdings", "positions", "node_fields",
               "clauses")}
    log.info("graph snapshot %s restored onto %s: %s (undo: %s)",
             snapshot_id, project_id, counts, undo_id)
    return {"restored": counts, "undo_snapshot_id": undo_id}

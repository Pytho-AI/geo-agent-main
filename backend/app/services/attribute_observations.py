"""Attribute observations — ONE write primitive for state attributes.

The position-track pattern generalized: a state attribute's value is an
append-only chain of OBSERVATIONS (episodic clauses carrying a typed
payload), deterministic supersession orders the chain, and the node's
scalar column is a derived MIRROR of the chain's current value. Every
writer — analyst edit, document ingest, agent tool — records an
observation; nothing overwrites history; the placard History IS the
record; consumers keep reading columns without knowing they became a
cache.

Identity attributes (name, echelon, entity_type, unit_type,
affiliation) stay direct CRUD — renaming a unit is a correction to
identity, never an observation about the world.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import GraphNode
from app.models.reference import FactClause

log = logging.getLogger("app.attribute_observations")

# The mirrored state attributes: analyst-visible, updatable world state.
STATE_ATTRS = {
    "posture": "text",
    "personnel_current": "num",
    "combat_effectiveness": "text",
    "significance": "text",
    "current_activity": "text",
}

_SENTENCES = {
    "posture": "{name} posture: {value}.",
    "personnel_current": "{name} current personnel strength: {value}.",
    "combat_effectiveness": "{name} combat effectiveness assessed as "
                            "{value}.",
    "significance": "{name} significance assessed as {value}.",
    "current_activity": "{name} current activity: {value}.",
}


def _now():
    return datetime.now(timezone.utc)


async def _supersede_slot(db: AsyncSession, project_id, slot: str) -> None:
    """Recompute the one slot's chain (strictly-later rule, idempotent —
    same semantics as clauses.invalidate_slots, scoped to one slot)."""
    group = (await db.execute(
        select(FactClause).where(
            FactClause.project_id == project_id, FactClause.layer == "project",
            FactClause.register == "episodic",
            FactClause.slot == slot))).scalars().all()
    floor = datetime.min.replace(tzinfo=timezone.utc)
    group.sort(key=lambda c: (c.observed_at or floor, str(c.id)))
    for i, cur in enumerate(group):
        want_to, want_by = None, None
        for nxt in group[i + 1:]:
            if (cur.observed_at and nxt.observed_at
                    and nxt.observed_at > cur.observed_at
                    and (nxt.value_text != cur.value_text
                         or nxt.value_num != cur.value_num)):
                want_to, want_by = nxt.observed_at, nxt.id
                break
        cur.valid_to = want_to
        cur.superseded_by = want_by


def _current(group):
    """The chain's current observation: latest unsuperseded."""
    floor = datetime.min.replace(tzinfo=timezone.utc)
    live = [c for c in group if c.superseded_by is None]
    if not live:
        return None
    return max(live, key=lambda c: (c.observed_at or floor, str(c.id)))


async def mirror_node(db: AsyncSession, node: GraphNode, attr: str) -> None:
    """node column <- the chain's current typed value."""
    slot = f"{node.id}.{attr}"
    group = (await db.execute(
        select(FactClause).where(
            FactClause.project_id == node.project_id, FactClause.layer == "project",
            FactClause.register == "episodic",
            FactClause.slot == slot))).scalars().all()
    cur = _current(group)
    if cur is None:
        return
    kind = STATE_ATTRS.get(attr)
    value = cur.value_num if kind == "num" else cur.value_text
    if value is not None:
        if kind == "num":
            value = int(value)
        setattr(node, attr, value)


async def record_attribute(db: AsyncSession, node: GraphNode, attr: str,
                           value, *, speaker: str, source: str,
                           observed_at: datetime = None,
                           text: str = None) -> None:
    """THE state-attribute write: append the observation, recompute the
    slot's supersession, mirror the column. Never a silent overwrite."""
    if attr not in STATE_ATTRS or value is None:
        return
    obs = observed_at or _now()
    if obs.tzinfo is None:
        obs = obs.replace(tzinfo=timezone.utc)
    kind = STATE_ATTRS[attr]
    sentence = text or _SENTENCES[attr].format(
        name=node.name or "the unit", value=value)
    db.add(FactClause(
        text=sentence, register="episodic", speaker=speaker,
        source_kind="observation", source_locus=source,
        about=[str(node.id)], kind="state",
        slot=f"{node.id}.{attr}",
        value_text=None if kind == "num" else str(value),
        value_num=float(value) if kind == "num" else None,
        observed_at=obs, project_id=node.project_id,
    ))
    await db.flush()
    await _supersede_slot(db, node.project_id, f"{node.id}.{attr}")
    await mirror_node(db, node, attr)


async def backfill_project(db: AsyncSession, project_id) -> int:
    """Chain roots for curated state: every node column value with NO
    existing chain becomes the initial observation (speaker curation),
    so hand-set state survives all future ingests as history."""
    nodes = (await db.execute(select(GraphNode).where(
        GraphNode.project_id == project_id, GraphNode.layer == "project"))).scalars().all()
    slotted = {c.slot for c in (await db.execute(
        select(FactClause).where(
            FactClause.project_id == project_id, FactClause.layer == "project",
            FactClause.register == "episodic",
            FactClause.slot.isnot(None)))).scalars().all()}
    added = 0
    for node in nodes:
        for attr in STATE_ATTRS:
            value = getattr(node, attr)
            if value is None or f"{node.id}.{attr}" in slotted:
                continue
            await record_attribute(
                db, node, attr, value, speaker="curation",
                source="curated state (backfill)",
                observed_at=node.updated_at or node.created_at)
            added += 1
    await db.commit()
    log.info("attribute backfill for %s: %d chain roots", project_id, added)
    return added

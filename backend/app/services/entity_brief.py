"""Entity brief — the as-of resolver shared by the placard endpoint
and the agent MCP tool: attribute supersession chains (History),
statements with provenance (Reporting), doctrine for the node's
template, and the position resolved at the scrub time. observed_at
is THE temporal dimension (2026-07-21 ruling): the record only ever
holds reports; created_at is ingest bookkeeping, never resolved or
surfaced."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import GraphNode, GraphNodePosition
from app.models.reference import FactClause


async def build_brief(db: AsyncSession, node: GraphNode,
                      as_of: datetime = None) -> dict:
    node_id = node.id
    from datetime import timezone as _tz
    t = as_of
    if t is not None and t.tzinfo is None:
        t = t.replace(tzinfo=_tz.utc)

    def _iso(dt):
        return dt.isoformat() if dt else None

    def _clause_out(c: FactClause, superseded: bool):
        return {
            "id": str(c.id), "text": c.text, "kind": c.kind,
            "speaker": c.speaker, "source": c.source_locus,
            "observed_at": _iso(c.observed_at),
            "valid_from": _iso(c.valid_from), "valid_to": _iso(c.valid_to),
            "superseded": superseded,
        }

    # Episodic clauses about this node (about[] carries node UUIDs).
    eps = (await db.execute(
        select(FactClause)
        .where(FactClause.project_id == node.project_id, FactClause.layer == "project",
               FactClause.register == "episodic",
               FactClause.about.any(str(node_id)))
        .order_by(FactClause.observed_at))).scalars().all()

    def _visible(c):
        # observed_at is the one temporal dimension: under scrub a
        # statement is visible once it was observed/stated. Episodic
        # clauses ALWAYS carry observed_at (write-path stamp + DB
        # CHECK — bootstrap migration).
        return t is None or c.observed_at <= t

    slots: dict = {}
    statements = []
    for c in eps:
        if c.slot:
            slots.setdefault(c.slot, []).append(c)
        else:
            if _visible(c):
                statements.append(_clause_out(c, False))

    slot_out = []
    for slot, chain in sorted(slots.items()):
        chain.sort(key=lambda c: (c.observed_at, str(c.id)))
        visible = [c for c in chain if _visible(c)]
        if not visible:
            continue
        current = visible[-1]
        attribute = slot.rsplit(".", 1)[-1] if "." in slot else slot
        slot_out.append({
            "attribute": attribute.replace("_", " "),
            "current": _clause_out(current, False),
            # superseded reflects the clause's OWN supersession state —
            # concurrent statements (same report) are all unsuperseded
            # even though only one renders as the headline value.
            "history": [_clause_out(c, c.superseded_by is not None)
                        for c in visible],
        })

    # Doctrine — gnomic clauses about the node's template key.
    doctrine = []
    if node.template_key:
        docs = (await db.execute(
            select(FactClause)
            .where(FactClause.register == "gnomic",
                   FactClause.source_kind == "doctrine",
                   FactClause.about.any(node.template_key))
            .limit(12))).scalars().all()
        doctrine = [{"text": c.text, "source": c.source_locus}
                    for c in docs]

    # Position at the scrub time. observed_at is NEVER null (write-path
    # stamp + NOT NULL); created_at is ingest bookkeeping and never
    # enters resolution.
    pos_q = (select(GraphNodePosition)
             .where(GraphNodePosition.node_id == node_id,
                    GraphNodePosition.geom.isnot(None)))
    if t is not None:
        pos_q = pos_q.where(GraphNodePosition.observed_at <= t)
    obs = (await db.execute(
        pos_q.order_by(GraphNodePosition.observed_at.desc())
        .limit(1))).scalar_one_or_none()

    return {
        "node_id": str(node_id),
        "as_of": _iso(t),
        "attributes": slot_out,
        "statements": statements[-40:],
        # Enumeration counts (mechanical, deduplicated by normalized
        # text) — counting is computation, never the reader's job.
        "counts": (lambda kinds: {k: len({(st["text"] or "").strip().lower()
                                          for st in statements
                                          if st.get("kind") == k})
                                  for k in kinds
                                  if any(st.get("kind") == k
                                         for st in statements)})(
            ("task", "event", "preference", "state")),
        "doctrine": doctrine,
        "position": None if obs is None else {
            "source": obs.source, "dtg": obs.dtg_label,
            "observed_at": _iso(obs.observed_at),
        },
    }



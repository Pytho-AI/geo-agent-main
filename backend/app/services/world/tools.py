"""World-model tool-surface handlers — milestone 4.

Design of record: scratch/docs/oob/tool-surface-consolidation.md — S7 (agent-
facing tool surface), S7.1 (bound session context), S7.13 (operations that are
NOT agent tools), S10 (read/query contracts). These are the thin handlers the
MCP server (app/mcp_world.py) adapts; each resolves the ONE active ingestion
run for its bound context (the model never names a run — design S7.1), calls
the domain + run services, and returns the steering envelope.

Two groups:

  CONTROL PLANE (operator / API / product engine — NOT agent tools, design
  S7.13): capture_source, start_source_run, start_product_run, activate,
  begin_resolution, begin_review, commit, run_status. The agent cannot capture
  a source, create/close a run, choose a destination, or commit.

  AGENT TOOLS (the ingestion agent's surface): read_source, search_world,
  read_world, assert_section, assert_section_semantics, resolve_entity_aliases,
  supersede, retract. Each returns the recomputed ingestion_context + steering
  (run.envelope). The same-origin duplicate-review tool
  (override_assertion_duplicates, design S7.9) lands with reingestion: on a
  first ingestion of an origin the review phase is empty, and its similarity
  comparison rides the clause embeddings deferred in ontology F6 — the exact-
  match dedup and the override tool are built when reingestion is first
  exercised.

The handlers own the transaction boundary the domain layer requires: a
DomainError rolls the aggregate back atomically and returns a per-item /
whole-call rejection; the run's progress_revision bumps only on a successful
mutation.
"""
from __future__ import annotations

import hashlib
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from app.db.session import async_session
from app.models.graph import GraphNode
from app.models.world import (
    Assertion, IngestionRun, Source, SourceRevision, SourceView,
)
from app.services.world import domain, run as run_svc
from app.services.world.domain import BoundContext, DomainError


# ---------------------------------------------------------------------------
# Control plane (design S7.13 — operator / API / product engine, not agent)
# ---------------------------------------------------------------------------

# Source capture is a DATA-PLANE step, not an operator/agent tool — the bytes
# travel via multipart upload (POST /api/v1/sources -> services.world.sources.
# capture_source_bytes), never through an MCP tool call, and no model judgment
# is involved. The revision + rendered page images land in MinIO there;
# read_source below serves those page images one page per call.


async def start_source_run(*, project_id: str, source_revision_id: str, actor: str,
                           doctrine_version: Optional[str] = None,
                           anchors: Optional[dict] = None,
                           auto_activate: bool = True) -> dict:
    async with async_session() as db:
        r = await run_svc.create_source_run(
            db, project_id=UUID(project_id),
            source_revision_id=UUID(source_revision_id), actor=actor,
            doctrine_version=doctrine_version, anchors=anchors)
        if auto_activate:
            await run_svc.activate_next(db)
        await db.commit()
        return {"run_id": str(r.id), "status": r.status}


async def start_product_run(*, project_id: str, product_branch_id: str, actor: str,
                            anchors: Optional[dict] = None,
                            auto_activate: bool = True) -> dict:
    async with async_session() as db:
        r = await run_svc.create_product_run(
            db, project_id=UUID(project_id),
            product_branch_id=UUID(product_branch_id), actor=actor, anchors=anchors)
        if auto_activate:
            await run_svc.activate_next(db)
        await db.commit()
        return {"run_id": str(r.id), "status": r.status}


async def activate() -> dict:
    async with async_session() as db:
        r = await run_svc.activate_next(db)
        await db.commit()
        return {"activated": (str(r.id) if r else None)}


async def _transition(kind: str) -> dict:
    async with async_session() as db:
        run = await run_svc.active_run(db)
        if run is None:
            return {"error": "no active run"}
        run_id = run.id  # capture before commit/rollback (rollback expires run)
        try:
            if kind == "resolve":
                await run_svc.begin_resolution(db, run)
                out = {"outcome": "resolving"}
            elif kind == "review":
                await run_svc.begin_review(db, run)
                out = {"outcome": "reviewing"}
            elif kind == "commit":
                out = await run_svc.complete_run(db, run)
            await db.commit()
        except DomainError as e:
            await db.rollback()
            return {"error": str(e)}
        async with async_session() as db2:
            run2 = await db2.get(IngestionRun, run_id)
            return await run_svc.envelope(db2, run2, out)


async def begin_resolution() -> dict:
    return await _transition("resolve")


async def begin_review() -> dict:
    return await _transition("review")


async def commit() -> dict:
    """Commit the active run to its bound destination and free the queue
    (design S6). System action, not agent-facing."""
    result = await _transition("commit")
    async with async_session() as db:
        await run_svc.activate_next(db)
        await db.commit()
    return result


async def run_status(run_id: Optional[str] = None) -> dict:
    async with async_session() as db:
        run = (await db.get(IngestionRun, UUID(run_id)) if run_id
               else await run_svc.active_run(db))
        if run is None:
            return {"active_run": None}
        return {"run_id": str(run.id), "status": run.status,
                "phase": run_svc.phase_of(run), "mode": run.mode,
                "commit_destination": run.commit_destination}


async def advance() -> dict:
    """AGENT-DECLARED phase transition. The agent calls this to declare the
    current phase complete and move the active run forward: asserting ->
    resolving (after the final section is asserted); resolving -> reviewing
    (after every occurrence is bound); reviewing -> commit (publishes the source
    and admits the next queued source). The agent, not any system, decides when
    it is done; this is a declaration, not a control-plane action."""
    async with async_session() as db:
        run = await run_svc.active_run(db)
        status = run.status if run else None
    if status is None:
        return {"error": "no active run"}
    if status == "active":
        return await begin_resolution()
    if status == "resolving":
        return await begin_review()
    if status == "reviewing":
        return await commit()
    return {"error": f"run in phase '{status}' cannot advance"}


# ---------------------------------------------------------------------------
# Agent-tool plumbing — resolve the active run, own the transaction, envelope
# ---------------------------------------------------------------------------

async def _run_mutation(expect_mode: Optional[str], body) -> dict:
    """Resolve the active run, run a mutation body(db, run, ctx) in a
    transaction, bump progress on success, and return the recomputed envelope.
    A DomainError rolls back atomically and rides in the outcome slot."""
    async with async_session() as db:
        run = await run_svc.active_run(db)
        if run is None:
            return {"error": "no active ingestion run"}
        if expect_mode and run.mode != expect_mode:
            return {"error": f"active run is {run.mode}, not {expect_mode}"}
        run_id = run.id  # capture before commit/rollback — a rollback EXPIRES run,
        # so touching run.id afterward would fire a sync lazy-refresh (MissingGreenlet)
        ctx = run_svc.bound_context(run)
        try:
            outcome = await body(db, run, ctx)
            run.progress_revision = (run.progress_revision or 0) + 1
            await db.commit()
        except DomainError as e:
            await db.rollback()
            outcome = {"outcome": "rejected", "error": str(e), "path": e.path}
        async with async_session() as db2:
            run2 = await db2.get(IngestionRun, run_id)
            return await run_svc.envelope(db2, run2, outcome)


# ── Reads (design S7.3, S7.4, S7.5) ──────────────────────────────────

async def read_source(cursor: Optional[str] = None, source_refs: Optional[list] = None):
    """Present ONE source page at the cursor as its rendered image (design S7.3).
    Returns (meta, jpeg_bytes): meta carries the single view's ref/kind/label/
    ordinal, next_cursor, source_end, and total_views; jpeg_bytes is that page's
    rendered image fetched from object storage (MinIO). One page per call — no
    window is ever returned, so the agent cannot read ahead. jpeg_bytes is None
    on an error or past end-of-source."""
    from app.services.products import artifacts
    from app.services.world.sources import page_key
    async with async_session() as db:
        run = await run_svc.active_run(db)
        if run is None or run.source_revision_id is None:
            return {"error": "no active external-source run"}, None
        views = (await db.execute(select(SourceView)
                 .where(SourceView.source_revision_id == run.source_revision_id)
                 .order_by(SourceView.ordinal.asc()))).scalars().all()
        total = len(views)
        start = int(cursor) if (cursor and str(cursor).isdigit()) else 0
        if start >= total:
            return {"views": [], "source_end": True, "next_cursor": None,
                    "total_views": total}, None
        v = views[start]
        end = (start + 1) >= total
        meta = {"view": {"ref": str(v.id), "kind": v.kind, "label": v.label,
                         "ordinal": v.ordinal},
                "next_cursor": (None if end else str(start + 1)),
                "source_end": end, "total_views": total}
        try:
            img, _ct = artifacts.get_object(page_key(run.source_revision_id, v.ordinal))
        except Exception as e:
            meta["image_error"] = f"no rendered page image ({e.__class__.__name__})"
            img = None
        return meta, img


async def search_world(text: Optional[str] = None, kinds: Optional[list] = None,
                       affiliation: Optional[str] = None, limit: int = 20) -> dict:
    """Candidate search over the project world model for occurrence resolution
    (design S7.4, S10): committed canonical entities matched by name / type /
    affiliation. Results are CANDIDATES, never identity decisions."""
    async with async_session() as db:
        run = await run_svc.active_run(db)
        pid = run.project_id if run else None
        limit = max(1, min(int(limit or 20), 50))
        q = select(GraphNode).where(GraphNode.project_id == pid,
                                    GraphNode.layer == "project")
        if kinds:
            q = q.where(GraphNode.entity_type.in_(list(kinds)))
        if affiliation:
            q = q.where(GraphNode.affiliation == affiliation)
        if text:
            like = f"%{text.strip()}%"
            q = q.where(or_(GraphNode.name.ilike(like),
                            GraphNode.long_name.ilike(like)))
        rows = (await db.execute(q.limit(limit))).scalars().all()
        return {"candidates": [{"ref": str(n.id), "name": n.name,
                                "entity_type": n.entity_type,
                                "affiliation": n.affiliation,
                                "echelon": n.echelon} for n in rows],
                "note": "candidates only — binding is your decision"}


async def read_world(refs: list, include_basis: bool = False) -> dict:
    """Exact, side-effect-free read of world-model records by ref (design S7.5).
    Reads canonical entities (graph_nodes) and, when requested, the assertions
    about them with their clause basis."""
    async with async_session() as db:
        out = []
        for ref in (refs or [])[:100]:
            if not _is_uuid(ref):
                out.append({"ref": ref, "error": "not a ref"})
                continue
            node = await db.get(GraphNode, UUID(str(ref)))
            if node is None:
                out.append({"ref": ref, "error": "not found"})
                continue
            rec = {"ref": ref, "name": node.name, "entity_type": node.entity_type,
                   "affiliation": node.affiliation, "echelon": node.echelon,
                   "posture": node.posture}
            if include_basis:
                a = (await db.execute(select(Assertion).where(
                    Assertion.subject_node_id == node.id,
                    Assertion.record_state == "committed"))).scalars().all()
                rec["assertions"] = [{"kind": x.kind, "attribute": x.attribute,
                                      "value": (x.value_text if x.value_num is None
                                                else x.value_num)} for x in a]
            out.append(rec)
        return {"records": out}


# ── Writes (design S7.6 – S7.11) ─────────────────────────────────────

async def assert_section(headings: list, text: str, source_refs: Optional[list] = None,
                         entities: Optional[list] = None,
                         clauses: Optional[list] = None) -> dict:
    """Assert ONE complete external-source section + its semantics (design S7.6)."""
    async def body(db, run, ctx):
        return await domain.assert_ingested_section(db, ctx, {
            "headings": headings or [], "text": text, "source_refs": source_refs or [],
            "entities": entities or [], "clauses": clauses or []})
    return await _run_mutation("external_source", body)


async def assert_section_semantics(section_id: str, entities: Optional[list] = None,
                                   clauses: Optional[list] = None) -> dict:
    """Attach semantics to the current bound system-created Section (design S7.7)."""
    async def body(db, run, ctx):
        return await domain.assert_stored_section_semantics(
            db, ctx, UUID(section_id),
            {"entities": entities or [], "clauses": clauses or []})
    return await _run_mutation("stored_section", body)


async def resolve_entity_aliases(decisions: list) -> dict:
    """Bind section-local occurrences to canonical entities (design S7.8)."""
    async def body(db, run, ctx):
        return {"decisions": await domain.resolve_entity_aliases(db, ctx, decisions)}
    return await _run_mutation(None, body)


async def supersede(items: list) -> dict:
    async def body(db, run, ctx):
        return {"items": await domain.supersede(db, ctx, items)}
    return await _run_mutation(None, body)


async def retract(items: list) -> dict:
    async def body(db, run, ctx):
        return {"items": await domain.retract(db, ctx, items)}
    return await _run_mutation(None, body)


def _is_uuid(v) -> bool:
    try:
        UUID(str(v))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

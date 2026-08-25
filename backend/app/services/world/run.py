"""Ingestion run lifecycle, run-scoped staging, and progress-tree steering —
milestone 3.

Design of record: scratch/docs/oob/tool-surface-consolidation.md — S6
(ingestion run lifecycle), S7.1 (bound session context), S7.2 (run-scoped
progress tree + focus), S8 (tool outcomes, steering, batching). Records:
app/models/world.py. Write path: services/world/domain.py.

One system-owned queue admits at most one active ingestion run across source
and generated-product ingestion (design S2 invariant 24; the schema's
ux_ingestion_runs_single_active partial unique index enforces it at the DB).
A run owns durable run-scoped staging — the section / clause / occurrence /
assertion rows carrying its id with record_state 'staged' — and a progress
tree the agent reads on every tool call.

The progress tree here is RECOMPUTED from the durable staged records and the
run phase on each call, so the navigation view can never drift from the
staging state it describes (design S7.2: "the staging state holds ... until
the run can commit; the agent never recreates either in tool arguments"). The
run's status is the phase; a monotonic progress_revision stamps each mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.world import (
    Assertion, Clause, EntityOccurrence, IngestionRun, Section, SourceRevision,
    SourceView,
)
from app.services.world.domain import BoundContext, DomainError, commit_run

# status -> agent-facing phase name (design S7.2 ingestion_context.phase).
_PHASE = {
    "assert_sections": "assert_sections",
    "extract_section_semantics": "extract_section_semantics",
    "resolve_entity_aliases": "resolve_entity_aliases",
    "review_assertion_duplicates": "review_assertion_duplicates",
    "complete": "complete",
}
_ACTIVE_STATES = ("active", "resolving", "reviewing", "committing")


def phase_of(run: IngestionRun) -> str:
    """The agent-facing phase derived from run.status + mode (design S7.2)."""
    if run.status == "active":
        return ("assert_sections" if run.mode == "external_source"
                else "extract_section_semantics")
    if run.status == "resolving":
        return "resolve_entity_aliases"
    if run.status == "reviewing":
        return "review_assertion_duplicates"
    if run.status in ("committing", "complete"):
        return "complete"
    return run.status  # queued / failed / cancelled


def bound_context(run: IngestionRun) -> BoundContext:
    """The system-bound write context for this run (design S7.1)."""
    return BoundContext(
        project_id=run.project_id, actor=(run.actor or "_ingestion"),
        commit_destination=run.commit_destination,
        product_branch_id=run.product_branch_id, run_id=run.id,
        doctrine_version=run.doctrine_version,
        source_revision_id=run.source_revision_id,
        anchors=(run.progress_tree or {}).get("anchors"),
        layer=("draft" if run.commit_destination == "product_branch" else "project"),
    )


# ---------------------------------------------------------------------------
# Admission and activation — the single queue (design S6, S9.4)
# ---------------------------------------------------------------------------

async def _next_queue_seq(db: AsyncSession) -> int:
    m = (await db.execute(select(func.max(IngestionRun.queue_seq)))).scalar()
    return (m + 1) if m is not None else 0


async def create_source_run(db: AsyncSession, *, project_id: UUID,
                            source_revision_id: UUID, actor: str,
                            doctrine_version: Optional[str] = None,
                            anchors: Optional[dict] = None) -> IngestionRun:
    """Queue an external-source ingestion run (design S6.1). It commits directly
    to the project world model; it has no product branch, FINAL, or APPROVE."""
    run = IngestionRun(
        id=uuid4(), project_id=project_id, mode="external_source",
        source_revision_id=source_revision_id, commit_destination="project",
        doctrine_version=doctrine_version, actor=actor, status="queued",
        queue_seq=await _next_queue_seq(db),
        progress_tree=({"anchors": anchors} if anchors else {}))
    db.add(run)
    await db.flush()
    return run


async def create_product_run(db: AsyncSession, *, project_id: UUID,
                             product_branch_id: UUID, actor: str,
                             pinned_project_revision: Optional[UUID] = None,
                             doctrine_version: Optional[str] = None,
                             anchors: Optional[dict] = None) -> IngestionRun:
    """Queue a generated-product semantic-extraction run bound to a product
    branch (design S6.2). It commits its staged semantics into that branch."""
    run = IngestionRun(
        id=uuid4(), project_id=project_id, mode="stored_section",
        product_branch_id=product_branch_id, commit_destination="product_branch",
        pinned_project_revision=pinned_project_revision,
        doctrine_version=doctrine_version, actor=actor, status="queued",
        queue_seq=await _next_queue_seq(db),
        progress_tree=({"anchors": anchors} if anchors else {}))
    db.add(run)
    await db.flush()
    return run


async def active_run(db: AsyncSession) -> Optional[IngestionRun]:
    return (await db.execute(select(IngestionRun).where(
        IngestionRun.status.in_(_ACTIVE_STATES)))).scalars().first()


async def activate_next(db: AsyncSession) -> Optional[IngestionRun]:
    """Admit the head of the queue when no run is active (design S6, S9.4). A
    source run pins the latest approved project revision at activation; a
    product run keeps the revision its owning execution pinned. The DB's
    single-active partial unique index is the backstop against a race."""
    if await active_run(db) is not None:
        return None
    nxt = (await db.execute(select(IngestionRun)
           .where(IngestionRun.status == "queued")
           .order_by(IngestionRun.queue_seq.asc()).limit(1))).scalar_one_or_none()
    if nxt is None:
        return None
    nxt.status = "active"
    if nxt.mode == "external_source":
        nxt.pinned_project_revision = await _latest_approved_revision(db, nxt.project_id)
    nxt.progress_revision = (nxt.progress_revision or 0) + 1
    await db.flush()
    return nxt


async def _latest_approved_revision(db, project_id) -> Optional[UUID]:
    """Pin point for a source run. The project-revision ledger lands with the
    approval-merge path (design S13); until then the run pins None and reads the
    current committed project layer, which is correct for the reconciliation
    build where source ingestion is the first writer."""
    return None


# ---------------------------------------------------------------------------
# Phase transitions (design S6, S7.2)
# ---------------------------------------------------------------------------

async def begin_resolution(db: AsyncSession, run: IngestionRun) -> None:
    """Enter entity alias resolution. An external run may only enter after the
    end of source has been read and the final held section asserted; a stored
    run only after every bound Section has semantics (design S8.1). The caller
    (the read/extract loop) asserts the precondition; here we flip the phase and
    forbid further section-level cascade."""
    if run.status != "active":
        raise DomainError(f"cannot begin resolution from status '{run.status}'")
    run.status = "resolving"
    run.progress_revision = (run.progress_revision or 0) + 1
    await db.flush()


async def begin_review(db: AsyncSession, run: IngestionRun) -> None:
    """Enter same-origin assertion duplicate review once every required
    occurrence is bound (design S7.9). Rejects if any staged assertion still has
    an unresolved endpoint."""
    if run.status != "resolving":
        raise DomainError(f"cannot begin review from status '{run.status}'")
    unresolved = await _unresolved_occurrence_count(db, run)
    if unresolved:
        raise DomainError(f"{unresolved} occurrence(s) still unresolved")
    run.status = "reviewing"
    run.progress_revision = (run.progress_revision or 0) + 1
    await db.flush()


async def complete_run(db: AsyncSession, run: IngestionRun) -> dict:
    """Commit the run's staged records to its bound destination (design S6). The
    caller owns the surrounding transaction; on success the run is complete and
    the queue is free for activate_next."""
    if run.status not in ("reviewing", "resolving", "active"):
        raise DomainError(f"cannot complete from status '{run.status}'")
    run.status = "committing"
    await db.flush()
    counts = await commit_run(db, bound_context(run), run)
    run.status = "complete"
    run.committed_at = datetime.now(timezone.utc)
    run.progress_revision = (run.progress_revision or 0) + 1
    await db.flush()
    return {"outcome": "complete", **counts}


async def fail_run(db: AsyncSession, run: IngestionRun, error: str) -> None:
    run.status = "failed"
    run.error = error
    await db.flush()


async def cancel_run(db: AsyncSession, run: IngestionRun) -> None:
    run.status = "cancelled"
    await db.flush()


# ---------------------------------------------------------------------------
# Recompute helpers — the progress tree is a VIEW of the staged records
# ---------------------------------------------------------------------------

async def _unresolved_occurrence_count(db, run) -> int:
    return (await db.execute(select(func.count()).select_from(EntityOccurrence)
            .where(EntityOccurrence.ingestion_run_id == run.id,
                   EntityOccurrence.canonical_node_id.is_(None)))).scalar() or 0


async def _last_asserted_section(db, run) -> Optional[dict]:
    row = (await db.execute(select(Section)
           .where(Section.ingestion_run_id == run.id)
           .order_by(Section.origin_sequence.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    preview = row.body_text or ""
    if len(preview) > 400:
        preview = preview[:200] + " ... " + preview[-160:]
    return {"ref": str(row.id), "headings": row.headings,
            "text_preview": preview, "source_sequence": row.origin_sequence}


async def _current_stored_section(db, run) -> Optional[dict]:
    """The first bound Section with no semantics yet (design S7.7)."""
    subq = select(Clause.section_id).where(Clause.ingestion_run_id == run.id)
    row = (await db.execute(select(Section)
           .where(Section.product_branch_id == run.product_branch_id,
                  Section.origin_kind != "external_source",
                  Section.id.not_in(subq))
           .order_by(Section.origin_sequence.asc()).limit(1))).scalar_one_or_none()
    if row is None:
        return None
    return {"ref": str(row.id), "headings": row.headings,
            "text": row.body_text, "section_sequence": row.origin_sequence}


async def _pending_alias_groups(db, run) -> list[dict]:
    """Unresolved occurrences clustered by folded designation for review
    (design S7.8). The clustering is a suggestion; the model decides identity."""
    rows = (await db.execute(select(EntityOccurrence)
            .where(EntityOccurrence.ingestion_run_id == run.id,
                   EntityOccurrence.canonical_node_id.is_(None))
            .order_by(EntityOccurrence.designation.asc()))).scalars().all()
    groups: dict[str, list[str]] = {}
    labels: dict[str, list[str]] = {}
    for o in rows:
        key = o.designation.strip().casefold()
        groups.setdefault(key, []).append(str(o.id))
        labels.setdefault(key, []).append(o.designation)
    return [{"occurrence_refs": groups[k], "designations": labels[k]}
            for k in groups]


async def _source_window(db, run) -> Optional[dict]:
    if run.source_revision_id is None:
        return None
    views = (await db.execute(select(SourceView)
             .where(SourceView.source_revision_id == run.source_revision_id)
             .order_by(SourceView.ordinal.asc()))).scalars().all()
    total = len(views)
    rev = await db.get(SourceRevision, run.source_revision_id)
    return {"source_revision": {"ref": str(run.source_revision_id),
                                "title": (rev.title if rev else None)},
            "total_views": total}


# ---------------------------------------------------------------------------
# Context + steering (design S7.2, S8.1) — recomputed after every tool result
# ---------------------------------------------------------------------------

async def build_context(db: AsyncSession, run: IngestionRun) -> dict:
    """The system-produced ingestion_context block returned by every tool call
    (design S7.2). Recomputed from the durable staged records and the phase; the
    model reads it but never emits it."""
    phase = phase_of(run)
    ctx: dict = {"progress_revision": run.progress_revision or 0, "phase": phase}

    if run.mode == "external_source":
        win = await _source_window(db, run)
        if win:
            ctx["source_revision"] = win["source_revision"]
        if phase == "assert_sections":
            last = await _last_asserted_section(db, run)
            if last:
                ctx["last_asserted_section"] = last
    else:
        if phase == "extract_section_semantics":
            cur = await _current_stored_section(db, run)
            if cur:
                ctx["current_stored_section"] = cur

    if phase == "resolve_entity_aliases":
        groups = await _pending_alias_groups(db, run)
        if groups:
            ctx["active_alias_resolution"] = groups[0]
            # Each pending group carries its (single, shared) designation too, so
            # the agent can batch-resolve every group in one call instead of one
            # round-trip per group — O(N) not O(N^2) at ORBAT scale.
            ctx["pending_alias_resolutions"] = [
                {"occurrence_refs": g["occurrence_refs"],
                 "designation": (g.get("designations") or [None])[0]}
                for g in groups[1:]]
        pend = (await db.execute(select(func.count()).select_from(Assertion)
                .where(Assertion.ingestion_run_id == run.id,
                       Assertion.record_state == "staged"))).scalar() or 0
        ctx["pending_materializations"] = pend

    if phase in ("resolve_entity_aliases", "review_assertion_duplicates"):
        ctx["unresolved"] = await _unresolved_occurrence_count(db, run)

    return ctx


def build_steering(context: dict, mode: str) -> str:
    """The three-part steering message (design S8.1): current location, the exact
    immediate call, and the resume plan. Computed from the live context, never a
    fixed per-tool string."""
    phase = context.get("phase")
    if phase == "assert_sections":
        last = context.get("last_asserted_section")
        loc = (f"You have asserted through section {last['source_sequence']}."
               if last else "No section asserted yet.")
        return (f"{loc} Read the source in order with read_source; for each section "
                "whose successor is visible, call assert_section once with its complete "
                "heading path, verbatim text, and source_refs. Hold the trailing section "
                "on the final visible view until the next view establishes its end. When "
                "the source is exhausted and the final section is asserted, resolve entity "
                "aliases.")
    if phase == "extract_section_semantics":
        cur = context.get("current_stored_section")
        if cur:
            return (f"Extract semantics for the current section (sequence "
                    f"{cur['section_sequence']}). Call assert_section_semantics with only "
                    "the entities and clauses you read from its stored text — no headings, "
                    "text, or references. When every bound section has semantics, resolve "
                    "entity aliases.")
        return "Every bound section has semantics. Resolve entity aliases next."
    if phase == "resolve_entity_aliases":
        grp = context.get("active_alias_resolution")
        if grp:
            names = ", ".join(grp.get("designations", []))
            return (f"Resolve the occurrences for [{names}]. Read candidates with "
                    "read_world, then call resolve_entity_aliases with entity_ref for an "
                    "existing entity or new_entity for a distinct identity. Continue until "
                    f"{context.get('unresolved', 0)} unresolved occurrences are bound, then "
                    "review same-origin assertion duplicates.")
        return ("Every required occurrence is bound. Review same-origin assertion "
                "duplicates, then the run can commit.")
    if phase == "review_assertion_duplicates":
        return ("Review the same-origin assertion duplicate sets. Send only the "
                "false-positive distinct overrides; unoverridden matches reuse their prior "
                "assertion. When every set is closed, the run commits.")
    if phase == "complete":
        return "The run is complete and its staged content has committed. Return control."
    return f"Run status: {phase}."


async def envelope(db: AsyncSession, run: IngestionRun, outcome: Optional[dict] = None) -> dict:
    """The full agent-facing tool response wrapper (design S7.2): the tool
    outcome plus the recomputed ingestion_context and steering."""
    context = await build_context(db, run)
    resp = {"ingestion_context": context,
            "steering": build_steering(context, run.mode)}
    if outcome is not None:
        resp["outcome"] = outcome
    return resp

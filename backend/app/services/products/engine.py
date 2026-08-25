"""The product engine — single-process asyncio, flat records, no
cascade, nothing auto-fires (fifth edition §2).

Generation is per-type and human-fired; the plan is ADVISORY and a
fire against a missing upstream approval HARD-REFUSES; dependents read
only APPROVED upstream editions. A generation's world-shaped output
lands in its PRIVATE DRAFT LAYER (layer='draft' + origin_record_id on
the world-model tables); nobody reads drafts but the record's own
rendering. APPROVE = MERGE (flip layer to 'project'); ONE approved
edition per (project, type); approving another supersedes the prior
edition's approval AND flips its merged rows to layer='superseded' —
rows are never deleted. Writes lock on FINAL, forever.
"""
import asyncio
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text, update

from app.db.session import async_session
from app.models.products import (
    ERROR_KINDS, ProductFactTouch, ProductRecord, ProductType)

log = logging.getLogger(__name__)

# The in-process task registry (single-process asyncio — §2). A died
# coroutine cannot hold the one-running index: the task-lost sweep
# fails any running record with no live task here.
_TASKS: dict[str, asyncio.Task] = {}

# Global writer semaphore — bounds concurrent writer work (edge
# default 1; the one-engine discipline). The stub holds it briefly so
# acquisition logging is exercised.
_WRITER_SEMAPHORE = asyncio.Semaphore(1)


def _now():
    return datetime.now(timezone.utc)


async def _append_log(db, record_id, line: str):
    stamp = _now().strftime("%H:%M:%S")
    await db.execute(
        update(ProductRecord).where(ProductRecord.id == record_id)
        .values(log=ProductRecord.log + f"[{stamp}] {line}\n"))


async def _touch_marks(db, project_id, classes):
    if not classes:
        return {}
    rows = (await db.execute(
        select(ProductFactTouch).where(
            ProductFactTouch.project_id == project_id,
            ProductFactTouch.fact_class.in_(classes)))).scalars().all()
    return {r.fact_class: r.touched_at.isoformat() for r in rows}


async def get_catalog(db):
    return (await db.execute(
        select(ProductType).where(ProductType.enabled.is_(True))
        .order_by(ProductType.ipoe_step.nulls_last(),
                  ProductType.type_key))).scalars().all()


async def approved_edition(db, project_id, type_key) -> Optional[ProductRecord]:
    return (await db.execute(
        select(ProductRecord).where(
            ProductRecord.project_id == project_id,
            ProductRecord.product_type == type_key,
            ProductRecord.lifecycle == "approved",
            ProductRecord.deleted.is_(False)))).scalar_one_or_none()


async def derive_state(db, project_id, ptype: ProductType) -> dict:
    """The rail's derived state for one type — computed fresh on every
    read, never stored."""
    records = (await db.execute(
        select(ProductRecord).where(
            ProductRecord.project_id == project_id,
            ProductRecord.product_type == ptype.type_key,
            ProductRecord.deleted.is_(False))
        .order_by(ProductRecord.created_at.desc()))).scalars().all()
    running = next((r for r in records
                    if r.status in ("queued", "running")), None)
    approved = next((r for r in records
                     if r.lifecycle == "approved"), None)
    newest = records[0] if records else None
    out = {"product_type": ptype.type_key, "label": ptype.label,
           "ipoe_step": ptype.ipoe_step, "dev_only": ptype.dev_only,
           "record_count": len(records)}
    blockers = []
    for dep in (ptype.depends_on or []):
        if await approved_edition(db, project_id, dep) is None:
            blockers.append(f"needs an approved {dep}")
    out["blockers"] = blockers
    if running is not None:
        out["state"] = running.status
        out["record_id"] = str(running.id)
        return out
    if newest is None:
        out["state"] = "never generated"
        return out
    out["record_id"] = str(newest.id)
    out["lifecycle"] = newest.lifecycle
    if newest.status == "failed":
        out["state"] = "failed"
        out["error_kind"] = newest.error_kind
        return out
    if approved is not None:
        marks = await _touch_marks(
            db, project_id, ptype.declared_fact_classes or [])
        merge_marks = approved.merge_touch_marks or {}
        started = (approved.started_at or approved.created_at).isoformat()
        stale_classes = [
            c for c, t in marks.items()
            if t > max(started, merge_marks.get(c, ""))]
        upstream_stale = []
        for dep, consumed_id in (approved.consumed_upstreams or {}).items():
            cur = await approved_edition(db, project_id, dep)
            if cur is None or str(cur.id) != consumed_id:
                upstream_stale.append(
                    f"{dep} has a newer approved edition")
        if stale_classes or upstream_stale:
            out["state"] = "stale"
            out["stale_reasons"] = (
                [f"newer facts in {c}" for c in stale_classes]
                + upstream_stale)
        else:
            out["state"] = "current"
        return out
    out["state"] = newest.lifecycle
    return out


def _effective_config(ptype, config: Optional[dict]) -> dict:
    """Defaults from the SPEC's config_fields overlaid with the
    analyst's choices; unknown keys and non-enum values REJECT (the
    closed-set rule applies to knobs like everything else)."""
    from app.services.products.templates import PRODUCT_SCHEMAS
    schema = PRODUCT_SCHEMAS.get(ptype.writer_spec_key) or {}
    declared = schema.get("config_fields") or {}
    if not declared:
        if config:
            raise ValueError(
                f"product type '{ptype.type_key}' declares no "
                "config_fields")
        return {}
    out = {k: spec.get("default") for k, spec in declared.items()}
    for k, v in (config or {}).items():
        spec = declared.get(k)
        if spec is None:
            raise ValueError(f"unknown config field '{k}'")
        allowed = [o.get("value") for o in (spec.get("options") or [])]
        if spec.get("type") == "multi_select":
            vals = v if isinstance(v, list) else [v]
            bad = [x for x in vals if x not in allowed]
            if bad:
                raise ValueError(
                    f"config '{k}': values {bad} not in options")
            out[k] = vals
        else:
            if allowed and v not in allowed:
                raise ValueError(
                    f"config '{k}': '{v}' not in options")
            out[k] = v
    return out


async def generate(project_id: UUID, type_key: str, created_by: str,
                   stub_behavior: Optional[str] = None,
                   config: Optional[dict] = None) -> dict:
    """THE verb. Hard-refuses on a missing upstream approval; mints
    the record QUEUED; returns immediately; execution continues in the
    task registry. stub_behavior (dev stub only): fail | slow."""
    async with async_session() as db:
        ptype = await db.get(ProductType, type_key)
        if ptype is None or not ptype.enabled:
            return {"error": f"unknown product type '{type_key}'"}
        blockers = []
        for dep in (ptype.depends_on or []):
            if await approved_edition(db, project_id, dep) is None:
                blockers.append(f"needs an approved {dep}")
        if blockers:
            return {"refused": True, "blockers": blockers}
        await sweep_task_lost(db, project_id)
        # Effective generation config: declared defaults + analyst
        # choices, validated against the SPEC's config_fields (the IBL
        # HVTL knob pattern — knobs live in the template).
        effective_config = _effective_config(ptype, config)
        record = ProductRecord(
            id=uuid_mod.uuid4(), project_id=project_id,
            product_type=type_key, status="queued",
            created_by=created_by,
            generation_config=effective_config or None,
            structured_content=(
                {"stub_behavior": stub_behavior}
                if (stub_behavior and ptype.dev_only) else None))
        db.add(record)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            running = (await db.execute(
                select(ProductRecord).where(
                    ProductRecord.project_id == project_id,
                    ProductRecord.product_type == type_key,
                    ProductRecord.status.in_(("queued", "running"))
                ))).scalar_one_or_none()
            if running is not None:
                return {"record_id": str(running.id),
                        "already_running": True}
            raise
        rid = record.id
    task = asyncio.create_task(_run(rid))
    _TASKS[str(rid)] = task
    task.add_done_callback(lambda t: _TASKS.pop(str(rid), None))
    return {"record_id": str(rid)}


async def _run(record_id: UUID):
    """One generation: the writer's internal execution, logged on the
    record. 1a ships the stub writer only."""
    try:
        async with async_session() as db:
            record = await db.get(ProductRecord, record_id)
            if record is None or record.status != "queued":
                return
            ptype = await db.get(ProductType, record.product_type)
            consumed = {}
            for dep in (ptype.depends_on or []):
                ap = await approved_edition(
                    db, record.project_id, dep)
                if ap is None:
                    record.status = "failed"
                    record.error_kind = "upstream_failed"
                    record.status_detail = (
                        f"approved {dep} vanished between refusal "
                        "check and start")
                    record.completed_at = _now()
                    await db.commit()
                    return
                consumed[dep] = str(ap.id)
            record.consumed_upstreams = consumed
            record.status = "running"
            record.started_at = _now()
            record.touch_baseline = await _touch_marks(
                db, record.project_id,
                ptype.declared_fact_classes or [])
            await db.commit()
            await _append_log(db, record_id, "record started")
            await db.commit()

        async with _WRITER_SEMAPHORE:
            async with async_session() as db:
                await _append_log(db, record_id,
                                  "writer semaphore acquired")
                record = await db.get(ProductRecord, record_id)
                ptype = await db.get(ProductType, record.product_type)
                spec_key = ptype.writer_spec_key
                await db.commit()
            if spec_key and spec_key != "stub":
                await _schema_writer(record_id, spec_key)
            else:
                await _stub_writer(record_id)

        async with async_session() as db:
            record = await db.get(ProductRecord, record_id)
            if record.status != "running":
                return
            ptype = await db.get(ProductType, record.product_type)
            end_marks = await _touch_marks(
                db, record.project_id,
                ptype.declared_fact_classes or [])
            changed = [c for c, t in end_marks.items()
                       if t > (record.touch_baseline or {}).get(c, "")]
            if changed:
                await _append_log(
                    db, record_id,
                    "picture changed during generation: "
                    + ", ".join(changed))
            record.status = "complete"
            record.completed_at = _now()
            await _append_log(db, record_id, "record complete")
            await db.commit()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("generation %s failed", record_id)
        async with async_session() as db:
            record = await db.get(ProductRecord, record_id)
            if record is not None and record.status == "running":
                record.status = "failed"
                record.error_kind = record.error_kind or "writer_invalid"
                record.status_detail = f"{type(e).__name__}: {e}"
                record.completed_at = _now()
                await _append_log(db, record_id,
                                  f"FAILED: {type(e).__name__}: {e}")
                await db.commit()


async def _stub_writer(record_id: UUID):
    """The 1a mechanism stub: writes TOKEN LAYER ROWS (one draft
    clause + one draft key_terrain entity) so approve/merge/supersede
    integrity is exercised for real, plus structured content."""
    from geoalchemy2 import WKTElement
    from app.models.graph import GraphNode
    from app.models.reference import FactClause
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        behavior = ((record.structured_content or {})
                    .get("stub_behavior"))
        if behavior == "fail":
            record.error_kind = "llm_failure"
            await _append_log(db, record_id,
                              "stub writer: requested failure")
            await db.commit()
            raise RuntimeError("stub requested failure")
        if behavior == "slow":
            await _append_log(db, record_id, "stub writer: slow mode")
            await db.commit()
            await asyncio.sleep(20)
        edition_stamp = _now().isoformat()
        db.add(FactClause(
            text=f"Stub edition marker {record_id}",
            register="episodic", kind="state",
            source_kind="engine_stub",
            source_locus=f"stub record {record_id}",
            about=["_stub"], observed_at=_now(),
            project_id=record.project_id,
            layer="draft", origin_record_id=record_id))
        db.add(GraphNode(
            id=uuid_mod.uuid4(), project_id=record.project_id,
            entity_type="key_terrain",
            name=f"Stub Terrain {str(record_id)[:8]}",
            affiliation="Neutral", created_by="_autodraft",
            layer="draft", origin_record_id=record_id,
            geom=WKTElement("POINT(21.5 53.2)", srid=4326)))
        record.structured_content = {
            **(record.structured_content or {}),
            "stub": True, "edition_stamp": edition_stamp}
        await _append_log(
            db, record_id,
            "stub writer: draft layer rows written (1 clause, "
            "1 entity)")
        await db.commit()


_CONTENT_TYPES = {
    "docx": ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document"),
    "pptx": ("application/vnd.openxmlformats-officedocument"
             ".presentationml.presentation"),
    "xlsx": ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet"),
}


async def _schema_writer(record_id: UUID, spec_key: str):
    """The generic generation (build-log cont 36v step 5): the SPEC
    keyed by the registry's writer_spec_key runs through the wave
    executor (writer.write_product), map-shape figures render at
    generation time (the current picture), and every declared output
    format walks through the ported walkers into MinIO."""
    from app.services.products import artifacts as artifact_store
    from app.services.products.templates import PRODUCT_SCHEMAS
    from app.services.products.walkers import (
        artifact_filename_base, render_docx, render_pptx, render_xlsx)
    from app.services.products.writer import write_product

    async def append(line):
        async with async_session() as db:
            await _append_log(db, record_id, line)
            await db.commit()

    schema = PRODUCT_SCHEMAS.get(spec_key)
    if schema is None:
        raise RuntimeError(
            f"writer_spec_key {spec_key!r} has no SPEC in "
            "PRODUCT_SCHEMAS — registry/templates mismatch")

    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        project_id = record.project_id
        consumed = dict(record.consumed_upstreams or {})
        ptype = await db.get(ProductType, record.product_type)
        registry_label = ptype.label if ptype else spec_key
        from app.models.map import Map as _Map
        m = await db.get(_Map, project_id)
        project_name = (m.name if m is not None else str(project_id))
        bbox = None
        if m is not None and m.bbox_west is not None:
            bbox = [m.bbox_west, m.bbox_south, m.bbox_east,
                    m.bbox_north]
        # Pre-seed upstream payloads from the consumed APPROVED
        # editions (pinned ids — never re-selected mid-run).
        upstream_payloads: dict = {}
        for dep_key, rec_id in consumed.items():
            up = await db.get(ProductRecord, UUID(rec_id))
            if up is None:
                continue
            up_type = await db.get(ProductType, up.product_type)
            up_name = ((up_type.writer_spec_key or up.product_type)
                       if up_type else up.product_type)
            upstream_payloads[up_name] = {
                "record_id": str(up.id),
                "structured_content": up.structured_content or {},
                "approved_at": (up.approved_at.isoformat()
                                if up.approved_at else None),
            }

    result = await write_product(
        project_id, record.product_type, spec_key, schema,
        upstream_payloads, append, record_id=record_id,
        generation_config=record.generation_config or {})
    content = result["structured_content"]

    # Schema-declared mechanical construction stage (2026-07-27
    # ruling: MANUAL construction — the broken terrain services are
    # never called). Runs after the writer, before the render, so the
    # record's own figure paints the constructed draft rows.
    stage_key = schema.get("construction_stage")
    if stage_key:
        from app.services.products.mcoo_stage import CONSTRUCTION_STAGES
        stage_fn = CONSTRUCTION_STAGES.get(stage_key)
        if stage_fn is None:
            raise RuntimeError(
                f"schema declares construction_stage {stage_key!r} "
                "with no registered stage")
        content = await stage_fn(record_id, project_id, content, append)

    # Map-shape figures: render the CURRENT picture once per map
    # paragraph_field (post-writer — the IBL post-merge convention).
    # The record's own figure includes ITS OWN draft layer (§2.2) —
    # the one consumer a draft layer has.
    figures: dict = {}
    map_fields = [p.get("name") for p in (schema.get("paragraph_fields")
                                          or [])
                  if isinstance(p, dict) and p.get("shape") == "map"
                  and p.get("name")]
    needs_figure = bool(map_fields) or any(
        str((f or {}).get("source", "")).startswith("map:render")
        for f in (schema.get("header_fields") or {}).values())
    if needs_figure or schema.get("output_format") == "docx":
        try:
            import httpx
            payload = {"map_uuid": str(project_id),
                       "include_draft_of": str(record_id)}
            if bbox:
                payload["bbox"] = bbox
            async with httpx.AsyncClient(timeout=240) as cx:
                r = await cx.post("http://127.0.0.1:8000/api/v1/render",
                                  json=payload)
                if r.status_code == 200 and r.headers.get(
                        "content-type", "").startswith("image/"):
                    fig = r.content
                    await append(
                        f"map figure rendered ({len(fig)} bytes)")
                    for name in (map_fields or ["_figure"]):
                        figures[name] = fig
                else:
                    await append(
                        f"map figure render failed: {r.status_code} — "
                        "figure omitted")
        except Exception as e:
            await append(f"map figure render failed: {e} — figure "
                         "omitted")

    # Output formats: plural wins over the legacy singular.
    formats = schema.get("output_formats")
    if not formats:
        formats = [schema.get("output_format") or "docx"]
    formats = [f for f in formats if f in _CONTENT_TYPES]
    base = artifact_filename_base(spec_key, schema, content,
                                  str(record_id)[:8])
    renderers = {"docx": render_docx, "pptx": render_pptx,
                 "xlsx": render_xlsx}
    artifacts_out = []
    for fmt in formats:
        blob = renderers[fmt](
            spec_key, schema, content, result["citations"],
            figures=figures, project_name=project_name,
            registry_label=registry_label)
        artifact_id = str(uuid_mod.uuid4())
        filename = f"{base}.{fmt}"
        object_key = f"{project_id}/{record_id}/{filename}"
        artifact_store.put_bytes(object_key, blob, _CONTENT_TYPES[fmt])
        artifacts_out.append({
            "artifact_id": artifact_id, "object_key": object_key,
            "filename": filename,
            "content_type": _CONTENT_TYPES[fmt]})
        await append(f"{fmt.upper()} written to MinIO "
                     f"({len(blob)} bytes)")

    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        record.structured_content = content
        record.artifacts = artifacts_out
        await _append_log(
            db, record_id,
            f"{len(artifacts_out)} artifact(s); "
            f"{len(result['citations'])} cited sources; tiers "
            f"{sorted(set(result['tiers'].values()))}")
        await db.commit()


async def sweep_task_lost(db, project_id=None):
    stmt = select(ProductRecord).where(
        ProductRecord.status == "running")
    if project_id is not None:
        stmt = stmt.where(ProductRecord.project_id == project_id)
    for r in (await db.execute(stmt)).scalars().all():
        t = _TASKS.get(str(r.id))
        if t is None or t.done():
            r.status = "failed"
            r.error_kind = "task_lost"
            r.status_detail = "task lost"
            r.completed_at = _now()
    await db.commit()


async def startup_sweep():
    async with async_session() as db:
        rows = (await db.execute(
            select(ProductRecord).where(
                ProductRecord.status.in_(("queued", "running"))
            ))).scalars().all()
        for r in rows:
            r.status = "failed"
            r.error_kind = "engine_restart"
            r.status_detail = "engine restarted mid-generation"
            r.completed_at = _now()
        if rows:
            log.warning("startup sweep failed %d in-flight product "
                        "records", len(rows))
        await db.commit()


async def cancel(record_id: UUID) -> dict:
    task = _TASKS.get(str(record_id))
    if task is not None:
        task.cancel()
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        if record is None:
            return {"error": "no such record"}
        if record.status not in ("queued", "running"):
            return {"error": f"record is {record.status}"}
        record.status = "cancelled"
        record.completed_at = _now()
        await _append_log(db, record_id, "cancelled")
        await db.commit()
    return {"cancelled": True}


async def finalize(record_id: UUID, actor: str) -> dict:
    """MARK-FINAL: the lock-and-propose act — locks further editor
    edits and presents the edition to the CO; it writes nothing
    anywhere. CO-revocable back to draft (2026-07-23 ruling); the
    FOREVER lock belongs to approval."""
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        if record is None or record.deleted:
            return {"error": "no such record"}
        if record.status != "complete":
            return {"error": f"only complete records finalize "
                             f"(record is {record.status})"}
        if record.lifecycle != "draft":
            return {"error": f"record is {record.lifecycle} — finals "
                             "never change"}
        record.lifecycle = "final"
        record.finalized_at = _now()
        record.finalized_by = actor
        await _append_log(db, record_id, f"marked FINAL by {actor}")
        await db.commit()
    return {"lifecycle": "final"}


async def approve(record_id: UUID, actor: str) -> dict:
    """APPROVE = THE MERGE, atomic: flip this record's draft rows to
    the project layer; supersede the prior approved edition (approval
    flag AND its merged world rows -> layer='superseded'); store the
    post-merge touch marks for comparator self-exclusion. Rows are
    never deleted."""
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        if record is None or record.deleted:
            return {"error": "no such record"}
        if record.lifecycle != "final":
            return {"error": f"only FINAL editions approve (record "
                             f"is {record.lifecycle})"}
        prior = await approved_edition(
            db, record.project_id, record.product_type)
        superseded = None
        if prior is not None:
            prior.lifecycle = "superseded"
            prior.superseded_by_record = record.id
            superseded = str(prior.id)
            for table in ("graph_nodes", "graph_node_positions",
                          "graph_edges", "fact_clauses",
                          "source_documents"):
                await db.execute(text(
                    f"UPDATE {table} SET layer = 'superseded' "
                    "WHERE origin_record_id = :oid "
                    "AND layer = 'project'"),
                    {"oid": str(prior.id)})
            await _append_log(
                db, prior.id,
                f"superseded by record {record.id} (approval of a "
                "newer edition)")
        merged = 0
        for table in ("graph_nodes", "graph_node_positions",
                      "graph_edges", "fact_clauses",
                      "source_documents"):
            res = await db.execute(text(
                f"UPDATE {table} SET layer = 'project' "
                "WHERE origin_record_id = :oid AND layer = 'draft'"),
                {"oid": str(record.id)})
            merged += res.rowcount or 0
        record.lifecycle = "approved"
        record.approved_at = _now()
        record.approved_by = actor
        record.ever_approved = True
        ptype = await db.get(ProductType, record.product_type)
        await db.flush()
        record.merge_touch_marks = await _touch_marks(
            db, record.project_id, ptype.declared_fact_classes or [])
        await _append_log(
            db, record_id,
            f"APPROVED by {actor}: {merged} layer rows merged"
            + (f"; superseded record {superseded}" if superseded
               else ""))
        await db.commit()
    return {"lifecycle": "approved", "merged_rows": merged,
            "superseded_record": superseded}


async def revoke(record_id: UUID, actor: str) -> dict:
    """Two revoke acts, both the CO's (2026-07-23 lifecycle ruling):
    a FINAL edition revokes BACK TO DRAFT for revisions (the same
    edition reopens for editing) — refused when the edition was ever
    approved (approved content is locked forever); an APPROVED
    edition's revoke retracts the merged rows by origin id
    (layer -> 'superseded'; never deleted) and lands on FINAL."""
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        if record is None:
            return {"error": "no such record"}
        if record.lifecycle == "final":
            if record.ever_approved:
                return {"error": "this edition was approved; approved "
                                 "content is locked forever — generate "
                                 "a new draft edition instead"}
            record.lifecycle = "draft"
            record.finalized_at = None
            record.finalized_by = None
            await _append_log(
                db, record_id,
                f"reverted to DRAFT by {actor} (revisions requested)")
            await db.commit()
            return {"lifecycle": "draft"}
        if record.lifecycle != "approved":
            return {"error": f"record is {record.lifecycle}, not "
                             "final or approved"}
        retracted = 0
        for table in ("graph_nodes", "graph_node_positions",
                      "graph_edges", "fact_clauses",
                      "source_documents"):
            res = await db.execute(text(
                f"UPDATE {table} SET layer = 'superseded' "
                "WHERE origin_record_id = :oid AND layer = 'project'"),
                {"oid": str(record.id)})
            retracted += res.rowcount or 0
        record.lifecycle = "final"
        record.approved_at = None
        record.approved_by = None
        await _append_log(
            db, record_id,
            f"approval REVOKED by {actor}: {retracted} merged rows "
            "retracted")
        await db.commit()
    return {"revoked": True, "retracted_rows": retracted}


async def soft_delete(record_id: UUID, actor: str) -> dict:
    async with async_session() as db:
        record = await db.get(ProductRecord, record_id)
        if record is None:
            return {"error": "no such record"}
        if record.lifecycle == "approved":
            return {"error": "an approved edition cannot be deleted "
                             "until revoked or superseded"}
        if record.status in ("queued", "running"):
            return {"error": "cancel the running record first"}
        record.deleted = True
        await _append_log(db, record_id, f"soft-deleted by {actor}")
        await db.commit()
    return {"deleted": True}

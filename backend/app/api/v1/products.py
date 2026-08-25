"""Product engine REST surface (fifth edition §7). REST + UI only —
NO product verbs on the MCP server (finalize/approve are HUMAN-ONLY
acts, never tools)."""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.products import ProductRecord, ProductType
from app.services.products import engine

log = logging.getLogger(__name__)
router = APIRouter()


def _serialize(r: ProductRecord, full: bool = False) -> dict:
    out = {
        "id": str(r.id), "project_id": str(r.project_id),
        "product_type": r.product_type, "status": r.status,
        "status_detail": r.status_detail, "error_kind": r.error_kind,
        "lifecycle": r.lifecycle,
        "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
        "finalized_by": r.finalized_by,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "approved_by": r.approved_by,
        "superseded_by_record": (str(r.superseded_by_record)
                                 if r.superseded_by_record else None),
        "consumed_upstreams": r.consumed_upstreams or {},
        "generation_config": r.generation_config or {},
        "artifacts": r.artifacts or [],
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": (r.completed_at.isoformat()
                         if r.completed_at else None),
    }
    lines = (r.log or "").strip().splitlines()
    out["last_log_line"] = lines[-1] if lines else ""
    if full:
        out["log"] = r.log or ""
        out["structured_content"] = r.structured_content
        out["touch_baseline"] = r.touch_baseline or {}
        out["merge_touch_marks"] = r.merge_touch_marks or {}
    return out


@router.get("/products/config")
async def products_config(project_id: Optional[UUID] = Query(None),
                          include_dev: bool = Query(False),
                          db: AsyncSession = Depends(get_db)):
    """The catalog registry + (with project_id) each type's derived
    rail state. Dev-only rows are hidden unless asked for."""
    types = [t for t in await engine.get_catalog(db)
             if include_dev or not t.dev_only]
    out = []
    for t in types:
        from app.services.products.templates import PRODUCT_SCHEMAS
        spec = PRODUCT_SCHEMAS.get(t.writer_spec_key) or {}
        row = {"type_key": t.type_key, "label": t.label,
               "category": t.category, "ipoe_step": t.ipoe_step,
               "output_formats": t.output_formats,
               "depends_on": t.depends_on,
               "declared_fact_classes": t.declared_fact_classes,
               "config_fields": spec.get("config_fields") or {},
               "dev_only": t.dev_only}
        if project_id is not None:
            row["derived"] = await engine.derive_state(
                db, project_id, t)
        out.append(row)
    return {"types": out}


@router.get("/products/records")
async def list_records(project_id: UUID,
                       product_type: Optional[str] = Query(None),
                       include_deleted: bool = Query(False),
                       limit: int = Query(100, le=500),
                       offset: int = Query(0, ge=0),
                       db: AsyncSession = Depends(get_db)):
    await engine.sweep_task_lost(db, project_id)
    stmt = select(ProductRecord).where(
        ProductRecord.project_id == project_id)
    if product_type:
        stmt = stmt.where(ProductRecord.product_type == product_type)
    if not include_deleted:
        stmt = stmt.where(ProductRecord.deleted.is_(False))
    stmt = (stmt.order_by(ProductRecord.created_at.desc())
            .limit(limit).offset(offset))
    rows = (await db.execute(stmt)).scalars().all()
    return {"records": [_serialize(r) for r in rows]}


@router.get("/products/records/{record_id}")
async def get_record(record_id: UUID,
                     db: AsyncSession = Depends(get_db)):
    r = await db.get(ProductRecord, record_id)
    if r is None:
        raise HTTPException(404, "no such record")
    return _serialize(r, full=True)


@router.post("/products/generate")
async def generate(payload: dict,
                   db: AsyncSession = Depends(get_db)):
    """THE verb: {project_id, product_type, plan_only?,
    stub_behavior?}. One type per click; hard-refuses on a missing
    upstream approval; returns the minted record id immediately."""
    try:
        project_id = UUID(str(payload.get("project_id")))
    except Exception:
        raise HTTPException(422, "project_id required")
    type_key = payload.get("product_type")
    if not type_key:
        raise HTTPException(422, "product_type required")
    ptype = await db.get(ProductType, type_key)
    if ptype is None or not ptype.enabled:
        raise HTTPException(404, f"unknown product type '{type_key}'")
    if payload.get("plan_only"):
        return {"plan": await engine.derive_state(
            db, project_id, ptype)}
    try:
        result = await engine.generate(
            project_id, type_key,
            created_by=payload.get("created_by") or "_autodraft",
            stub_behavior=payload.get("stub_behavior"),
            config=payload.get("config"))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if result.get("refused"):
        raise HTTPException(409, "; ".join(result["blockers"]))
    if result.get("error"):
        raise HTTPException(422, result["error"])
    return result


@router.post("/products/records/{record_id}/cancel")
async def cancel(record_id: UUID):
    out = await engine.cancel(record_id)
    if out.get("error"):
        raise HTTPException(409, out["error"])
    return out


@router.post("/products/records/{record_id}/finalize")
async def finalize(record_id: UUID, payload: dict = None):
    out = await engine.finalize(
        record_id, (payload or {}).get("actor") or "_autodraft")
    if out.get("error"):
        raise HTTPException(409, out["error"])
    return out


@router.post("/products/records/{record_id}/approve")
async def approve(record_id: UUID, payload: dict = None):
    out = await engine.approve(
        record_id, (payload or {}).get("actor") or "_autodraft")
    if out.get("error"):
        raise HTTPException(409, out["error"])
    return out


@router.post("/products/records/{record_id}/revoke")
async def revoke(record_id: UUID, payload: dict = None):
    out = await engine.revoke(
        record_id, (payload or {}).get("actor") or "_autodraft")
    if out.get("error"):
        raise HTTPException(409, out["error"])
    return out


@router.get("/products/records/{record_id}/artifacts/{artifact_id}")
async def download_artifact(record_id: UUID, artifact_id: str,
                            db: AsyncSession = Depends(get_db)):
    """Stream artifact bytes from MinIO through the backend (the one
    public surface fronts everything)."""
    from fastapi.responses import Response
    r = await db.get(ProductRecord, record_id)
    if r is None:
        raise HTTPException(404, "no such record")
    art = next((a for a in (r.artifacts or [])
                if a.get("artifact_id") == artifact_id), None)
    if art is None:
        raise HTTPException(404, "no such artifact")
    from app.services.products import artifacts as store
    try:
        data, ctype = store.get_object(art["object_key"])
    except Exception as e:
        raise HTTPException(502, f"artifact fetch failed: {e}")
    return Response(
        content=data, media_type=art.get("content_type") or ctype,
        headers={"Content-Disposition":
                 f"attachment; filename=\"{art['filename']}\""})


@router.delete("/products/records/{record_id}")
async def delete_record(record_id: UUID,
                        actor: str = Query("_autodraft")):
    out = await engine.soft_delete(record_id, actor)
    if out.get("error"):
        raise HTTPException(409, out["error"])
    return out

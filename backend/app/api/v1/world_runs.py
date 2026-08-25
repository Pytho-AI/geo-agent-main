"""Ingestion-run control-plane endpoints (design S6, S7.13).

Run creation, activation, the phase barriers, and commit are OPERATOR / API /
product-engine actions — not agent tools and not model decisions. They live
here as HTTP endpoints (the operator drives the pipeline through them), never on
the ingestion agent's MCP surface. The agent only reads and asserts.

Mounted at /api/v1/runs (NOT under /api/v1/world, which is the world MCP mount).
Each endpoint is a thin wrapper over services/world/tools.py, which owns the
run lifecycle + transaction boundary.
"""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.world import tools as w

router = APIRouter()


class SourceRunIn(BaseModel):
    project_id: str
    source_revision_id: str
    actor: str = "_ingestion"
    doctrine_version: Optional[str] = None
    anchors: Optional[dict] = None
    auto_activate: bool = True


class ProductRunIn(BaseModel):
    project_id: str
    product_branch_id: str
    actor: str = "_ingestion"
    anchors: Optional[dict] = None
    auto_activate: bool = True


@router.post("/source")
async def start_source_run(body: SourceRunIn):
    """Queue (and by default activate) an external-source ingestion run bound to
    a captured source revision. anchors carries the project temporal_anchors for
    relative-DTG resolution."""
    return await w.start_source_run(**body.model_dump())


@router.post("/product")
async def start_product_run(body: ProductRunIn):
    """Queue (and by default activate) a product-branch ingestion run."""
    return await w.start_product_run(**body.model_dump())


@router.post("/activate")
async def activate():
    """Admit the head of the ingestion queue when no run is active."""
    return await w.activate()


@router.post("/resolve")
async def begin_resolution():
    """Transition the active run from section assertion into entity alias
    resolution (after the source is fully read and the final section asserted)."""
    return await w.begin_resolution()


@router.post("/review")
async def begin_review():
    """Transition the active run into same-origin duplicate review (allowed only
    once every occurrence is bound)."""
    return await w.begin_review()


@router.post("/commit")
async def commit():
    """Commit the active run's staged records to its bound destination and free
    the queue for the next run."""
    return await w.commit()


@router.get("/active")
async def run_status(run_id: Optional[str] = None):
    """Status of the active run (or a named run): status, phase, mode, commit
    destination."""
    return await w.run_status(run_id=run_id)

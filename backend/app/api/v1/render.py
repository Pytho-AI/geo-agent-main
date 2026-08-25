"""POST /api/v1/render — geo-agent-hosted map render.

Drives Playwright against geo-agent's OWN frontend at /geo-app/headless
and returns the JPG bytes. pytho-app POSTs here from
`tool_render_map`; geo-agent owns Chromium wiring, URL construction,
tile-cache warmup, and the whole render surface.

Caller wire:

    POST /api/v1/render
    Content-Type: application/json
    { "product_type": "SITEMP", "map_uuid": "...", "artifact_id": "...",
      "basemap": "default", "width": 1920, "height": 1080,
      "wait_ms": 60000, "fast": false, ... }
    → 200 image/jpeg  (+ X-Render-Ms header)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID as _UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.config import get_settings
from app.services.render.headless import render_map_to_png, RenderOptions

router = APIRouter()
log = logging.getLogger("app.render")


class RenderRequest(BaseModel):
    """Every field maps 1:1 to RenderOptions so payloads round-trip
    verbatim from pytho-app's `render_map_via_geoagent`.
    """

    product_type: str | None = None
    map_uuid: str | None = None
    artifact_id: str | None = None
    basemap: str | None = None
    width: int = 1920
    height: int = 1080
    pixel_ratio: float = 1.5
    wait_ms: int = 60_000
    bbox: list[float] | None = None
    layers: list[str] | None = None
    allowed_kinds: list[str] | None = None
    basemap_layer_visibility: list[str] | None = None
    doctrinal_layer_visibility: list[str] | None = None
    show_topographic_contours: bool | None = None
    cluster_mil_units: bool | None = None
    compact_aa_labels: bool | None = None
    compact_legend_labels: bool | None = None
    fast: bool = False
    # Include one record's DRAFT layer rows in the painted picture —
    # the record's OWN artifact figure is a draft layer's only
    # consumer (fifth edition #2.2). Value = the record id.
    include_draft_of: str | None = None
    params: dict[str, Any] | None = None
    # Persist the rendered JPG server-side, keyed by map_uuid, retrievable
    # at GET /render/latest/{map_uuid}.jpg. Used by the in-map edit-session
    # "Done editing" flow: geo-agent renders ITSELF and the consumer's
    # done-hook handler only downloads + embeds — no consumer-triggered
    # re-render roundtrip.
    persist: bool = False
    # Re-render from the LAST render spec geo-agent saw for this map.
    # Every successful /render stashes its request JSON per map_uuid, so
    # the product-generation render (schema presets: layers, allowed
    # kinds, visibility, cluster flags, dimensions) becomes the base;
    # non-default fields on the replay request override it (e.g. the
    # analyst's session basemap). The edit-session Done flow POSTs
    # {map_uuid, replay: true, persist: true, ...overrides} — no caller
    # ever re-supplies the full spec.
    replay: bool = False


@router.post("/render")
async def render_map(req: RenderRequest) -> Response:
    if not req.map_uuid:
        raise HTTPException(status_code=400, detail="map_uuid required")
    try:
        map_uuid = _UUID(req.map_uuid)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"map_uuid not a UUID: {exc}",
        ) from exc

    was_replay = req.replay
    if req.replay:
        params_path = _persisted_params_path(map_uuid)
        if not params_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="replay requested but no stored render spec for this map",
            )
        base = RenderRequest.model_validate_json(params_path.read_text())
        # Overlay only what the replay caller explicitly set (model_dump
        # with exclude_unset drops every field left at its default), so
        # session overrides like basemap win without the caller having to
        # re-supply the schema presets.
        overrides = req.model_dump(exclude_unset=True)
        overrides.pop("replay", None)
        req = base.model_copy(update=overrides)

    # Finding 2: a render with no explicit bbox loads the headless page
    # at world extent. When the map carries entity-graph nodes, frame
    # the render on their extent so the force is actually visible.
    # Products still pass their own bbox and are untouched.
    if not req.bbox:
        try:
            from sqlalchemy import func, select
            from app.db.session import async_session
            from app.models.graph import GraphNode
            async with async_session() as db:
                ext = (await db.execute(
                    select(
                        func.min(func.ST_X(GraphNode.geom)),
                        func.min(func.ST_Y(GraphNode.geom)),
                        func.max(func.ST_X(GraphNode.geom)),
                        func.max(func.ST_Y(GraphNode.geom)),
                    ).where(GraphNode.project_id == map_uuid,
                            GraphNode.geom.isnot(None)))).one_or_none()
            if ext and None not in ext:
                w, s, e, n = ext
                padx = max((e - w) * 0.15, 0.05)
                pady = max((n - s) * 0.15, 0.05)
                req = req.model_copy(update={
                    "bbox": [w - padx, s - pady, e + padx, n + pady]})
        except Exception:
            log.exception("graph-extent bbox fallback failed (non-fatal)")

    opts = RenderOptions(
        width=req.width,
        height=req.height,
        bbox=req.bbox,
        layers=req.layers,
        timeout_ms=req.wait_ms,
        pixel_ratio=req.pixel_ratio,
        product_type=req.product_type,
        basemap=req.basemap,
        basemap_layer_visibility=req.basemap_layer_visibility,
        doctrinal_layer_visibility=req.doctrinal_layer_visibility,
        show_topographic_contours=req.show_topographic_contours,
        cluster_mil_units=req.cluster_mil_units,
        compact_aa_labels=req.compact_aa_labels,
        compact_legend_labels=req.compact_legend_labels,
        fast=req.fast,
        include_draft_of=req.include_draft_of,
    )
    started_ms = time.time() * 1000
    log.info(
        "render: local driver product_type=%s map_uuid=%s artifact=%s fast=%s",
        req.product_type, req.map_uuid, req.artifact_id, req.fast,
    )
    try:
        jpg = await render_map_to_png(map_uuid, opts)
    except Exception as exc:
        log.exception("render: driver raised")
        raise HTTPException(
            status_code=500,
            detail=f"render failed: {type(exc).__name__}: {exc}",
        ) from exc
    elapsed_ms = int(time.time() * 1000 - started_ms)
    log.info(
        "render: local driver OK product=%s bytes=%d ms=%d",
        req.product_type, len(jpg), elapsed_ms,
    )
    # Stash the effective render spec for this map on every successful
    # render — this is what `replay: true` re-renders from, so the
    # product-generation presets survive without any caller re-supplying
    # them. Skipped for replays themselves (the merged spec would
    # accumulate overrides as new baseline; generation renders own it).
    if not was_replay:
        try:
            ppath = _persisted_params_path(map_uuid)
            ppath.parent.mkdir(parents=True, exist_ok=True)
            ptmp = ppath.with_suffix(".json.tmp")
            ptmp.write_text(req.model_dump_json())
            ptmp.replace(ppath)
        except Exception:
            log.exception("render: params stash failed for map_uuid=%s", map_uuid)
    if req.persist:
        try:
            path = _persisted_render_path(map_uuid)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".jpg.tmp")
            tmp.write_bytes(jpg)
            tmp.replace(path)  # atomic — a concurrent GET never sees a partial file
            log.info("render: persisted %s (%d bytes)", path, len(jpg))
        except Exception:
            # The caller still gets the image; persistence is best-effort
            # but loudly logged (the done-hook consumer will 404 on GET).
            log.exception("render: persist failed for map_uuid=%s", map_uuid)
    return Response(
        content=jpg,
        media_type="image/jpeg",
        headers={"X-Render-Ms": str(elapsed_ms), "X-Render-Backend": "local"},
    )


def _persisted_render_path(map_uuid: _UUID) -> Path:
    # Under the GEO_DATA_DIR-backed data volume so persisted renders
    # survive container recreates.
    return Path(get_settings().data_dir) / "renders" / f"{map_uuid}.jpg"


def _persisted_params_path(map_uuid: _UUID) -> Path:
    # The last render spec seen for this map (replay base). Same volume
    # as the persisted renders.
    return Path(get_settings().data_dir) / "renders" / f"{map_uuid}.params.json"


@router.get("/render/spec/{map_uuid}")
async def render_spec(map_uuid: str) -> dict:
    """Last render spec stashed for a map (the replay base) — INTERNAL.

    The live/edit map surface reads this to inherit the product's
    render primitives without any consumer forwarding them: the
    product-generation render stashes its spec (basemap, layer
    visibility, show_topographic_contours, …), and the analyst-facing
    OperationsMap then paints to the same primitives the exported
    artifact will use (today: the contour overlay gate). Product-
    agnostic by construction — geo-agent never maps product_type to
    behavior client-side; the stashed spec IS the product's declared
    configuration. 404 when the map has never been product-rendered
    (e.g. a project master map) — callers treat that as "no product
    presets"."""
    try:
        uuid = _UUID(map_uuid)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"map_uuid not a UUID: {exc}") from exc
    path = _persisted_params_path(uuid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no stored render spec for this map")
    return RenderRequest.model_validate_json(path.read_text()).model_dump()


@router.get("/render/latest/{map_uuid}.jpg")
async def latest_render(map_uuid: str) -> Response:
    """Most recent persisted render for a map (written by POST /render
    with persist=true). The edit-session done hook hands consumers this
    URL; their document-refresh downloads it instead of re-rendering."""
    try:
        uuid = _UUID(map_uuid)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"map_uuid not a UUID: {exc}") from exc
    path = _persisted_render_path(uuid)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no persisted render for this map")
    return Response(
        content=path.read_bytes(),
        media_type="image/jpeg",
        # Always the latest — the analyst may re-edit seconds later.
        headers={"Cache-Control": "no-store"},
    )

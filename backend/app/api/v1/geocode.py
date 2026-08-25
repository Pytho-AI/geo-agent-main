"""GET /api/v1/geocode — resolve a place name to coordinates from the
planet `places` layer, scoped to an area of operations.

The NL agent and the document-ingest pipeline both call the underlying
service (app.services.geocode); this endpoint exposes it for the agent's
map operations and for direct callers.

    GET /api/v1/geocode?q=Grafenwohr&bbox=9,47,15,51&near=11.9,49.7&limit=5
    -> { "query": "...", "candidates": [ {name, lon, lat, kind, ...}, ... ] }
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.geocode import geocode

router = APIRouter()
log = logging.getLogger("app.geocode")


def _parse_bbox(bbox: Optional[str]):
    if not bbox:
        return None
    try:
        w, s, e, n = (float(v) for v in bbox.split(","))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"bad bbox (want w,s,e,n): {exc}") from exc
    return (w, s, e, n)


def _parse_near(near: Optional[str]):
    if not near:
        return None
    try:
        lon, lat = (float(v) for v in near.split(","))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"bad near (want lon,lat): {exc}") from exc
    return (lon, lat)


@router.get("/geocode")
async def geocode_endpoint(
    q: str = Query(..., description="place name to resolve"),
    bbox: Optional[str] = Query(None, description="AO bbox w,s,e,n — candidates are drawn only from inside it"),
    near: Optional[str] = Query(None, description="lon,lat bias point"),
    limit: int = Query(6, ge=1, le=25),
) -> dict:
    try:
        candidates = await geocode(
            q, bbox=_parse_bbox(bbox), near=_parse_near(near), limit=limit)
    except ImportError as exc:  # vector-tile decoder missing
        raise HTTPException(503, f"geocoder unavailable: {exc}") from exc
    return {"query": q, "candidates": [c.as_dict() for c in candidates]}

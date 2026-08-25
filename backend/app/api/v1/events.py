"""Analyst-action audit + forwarded client logging — INTERNAL API.

The map UI's own telemetry sink. geo-agent is standalone, so its
frontend never posts telemetry to a consumer's endpoints (a standalone
deployment has no consumer, and the earlier consumer-relative paths
404'd there); everything lands HERE and persists in the stack's own
PostGIS volume across container recreates.

Three routes:

    POST /api/v1/events              one event or {"events": [...]}
    GET  /api/v1/events              query (map_id / user_id /
                                     event_type prefix / since_ms /
                                     until_ms / limit), newest first
    POST /api/v1/events/client-log   browser-side log forwarding
                                     (frontend lib/clientLog.ts) —
                                     routed through the server logger
                                     (which persists to the data-volume
                                     log file) AND stored as an
                                     analyst_events row so browser
                                     errors are queryable next to the
                                     actions that preceded them

Ingest is deliberately tolerant: an audit sink must swallow malformed
rows (counted, logged at debug) rather than 4xx a fire-and-forget
client into silence.
"""

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.analyst_event import AnalystEvent

router = APIRouter()
log = logging.getLogger("app.events")
client_log = logging.getLogger("geo.client")

_MAX_BATCH = 500
_MAX_DETAIL_BYTES = 32_768
_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _coerce_row(raw: dict) -> Optional[AnalystEvent]:
    """One tolerant event row from a client dict, or None if hopeless."""
    if not isinstance(raw, dict):
        return None
    event_type = str(raw.get("event_type") or "").strip()
    if not event_type:
        return None
    detail = raw.get("detail")
    if detail is not None and not isinstance(detail, dict):
        detail = {"value": str(detail)[:2000]}
    occurred = raw.get("occurred_at_ms")
    try:
        occurred = int(occurred) if occurred is not None else None
    except (TypeError, ValueError):
        occurred = None
    return AnalystEvent(
        occurred_at_ms=occurred,
        received_at_ms=_now_ms(),
        user_id=(str(raw.get("user_id"))[:255] if raw.get("user_id") else None),
        map_id=(str(raw.get("map_id"))[:64] if raw.get("map_id") else None),
        surface=(str(raw.get("surface"))[:64] if raw.get("surface") else None),
        event_type=event_type[:128],
        detail=detail,
    )


@router.post("")
async def ingest_events(body: dict, db: AsyncSession = Depends(get_db)) -> dict:
    raw_list = body.get("events") if isinstance(body.get("events"), list) else [body]
    stored = 0
    skipped = 0
    for raw in raw_list[:_MAX_BATCH]:
        row = _coerce_row(raw)
        if row is None:
            skipped += 1
            continue
        db.add(row)
        stored += 1
    if stored:
        await db.commit()
    if skipped:
        log.debug("events ingest: skipped %d malformed rows", skipped)
    return {"stored": stored, "skipped": skipped}


@router.get("")
async def query_events(
    map_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(
        None, description="Exact type, or a prefix ending in '*' (e.g. client_log.*)"),
    since_ms: Optional[int] = Query(None),
    until_ms: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AnalystEvent)
    if map_id:
        stmt = stmt.where(AnalystEvent.map_id == map_id)
    if user_id:
        stmt = stmt.where(AnalystEvent.user_id == user_id)
    if event_type:
        if event_type.endswith("*"):
            stmt = stmt.where(AnalystEvent.event_type.like(event_type[:-1] + "%"))
        else:
            stmt = stmt.where(AnalystEvent.event_type == event_type)
    if since_ms is not None:
        stmt = stmt.where(AnalystEvent.received_at_ms >= since_ms)
    if until_ms is not None:
        stmt = stmt.where(AnalystEvent.received_at_ms <= until_ms)
    stmt = stmt.order_by(AnalystEvent.received_at_ms.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "events": [
            {
                "id": str(r.id),
                "occurred_at_ms": r.occurred_at_ms,
                "received_at_ms": r.received_at_ms,
                "user_id": r.user_id,
                "map_id": r.map_id,
                "surface": r.surface,
                "event_type": r.event_type,
                "detail": r.detail,
            }
            for r in rows
        ],
        "count": len(rows),
    }


class ClientLogIn(BaseModel):
    level: str = "info"
    label: str = ""
    message: str = ""
    url: Optional[str] = None
    user_agent: Optional[str] = None
    stack: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    user_id: Optional[str] = None
    map_id: Optional[str] = None


@router.post("/client-log")
async def ingest_client_log(body: ClientLogIn, db: AsyncSession = Depends(get_db)) -> dict:
    level = _LOG_LEVELS.get(body.level.lower(), logging.INFO)
    label = (body.label or "client")[:200]
    message = (body.message or "")[:4000]
    # Server logger first — this is what lands in the persistent
    # data-volume log file next to the backend's own errors.
    client_log.log(level, "[%s] %s%s", label, message,
                   f"\n{body.stack[:8000]}" if body.stack else "")
    detail = {
        "level": body.level,
        "label": label,
        "message": message,
        "url": (body.url or "")[:1000] or None,
        "user_agent": (body.user_agent or "")[:400] or None,
        "stack": (body.stack or "")[:8000] or None,
        "context": body.context,
    }
    if len(str(detail)) > _MAX_DETAIL_BYTES:
        detail["context"] = None
        detail["stack"] = (detail.get("stack") or "")[:2000] or None
    db.add(AnalystEvent(
        occurred_at_ms=None,
        received_at_ms=_now_ms(),
        user_id=body.user_id,
        map_id=body.map_id,
        surface="client",
        event_type=f"client_log.{body.level.lower()[:16]}",
        detail=detail,
    ))
    await db.commit()
    return {"stored": 1}

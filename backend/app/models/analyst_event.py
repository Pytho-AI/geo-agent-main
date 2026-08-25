from sqlalchemy import BigInteger, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from datetime import datetime
import uuid

from app.models.base import Base


class AnalystEvent(Base):
    """Persistent analyst-action + client-log audit row.

    THE durable record of what happened on the map surface: analyst
    actions (basemap switches, layer toggles, entity/overlay edits,
    route operations, natural-language commands, edit sessions,
    per-target generates) and forwarded browser-side log entries
    (event_type `client_log.*`). Lives in the stack's PostGIS volume,
    so it survives container recreates — this table exists because
    docker-logs-only telemetry evaporated on every redeploy.

    Deliberately tolerant shapes: ids and types are plain strings (an
    audit sink must never reject a row over an id format), `detail` is
    free-form JSONB, and writes are fire-and-forget from the client's
    perspective (see api/v1/events.py).
    """

    __tablename__ = "analyst_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Client-side wall clock (ms) when the action happened; server
    # receive time (ms) recorded alongside so skew is visible.
    occurred_at_ms = Column(BigInteger)
    received_at_ms = Column(BigInteger, nullable=False)
    user_id = Column(String(255))
    map_id = Column(String(64), index=True)
    # Which surface fired it: map, layer_switcher, sidebar, chat,
    # edit_session, client (forwarded browser logs), ...
    surface = Column(String(64))
    event_type = Column(String(128), nullable=False, index=True)
    detail = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_analyst_events_map_time", "map_id", "received_at_ms"),
        Index("ix_analyst_events_type_time", "event_type", "received_at_ms"),
    )

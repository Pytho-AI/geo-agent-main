from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from datetime import datetime

from app.models.base import Base


class Event(Base):
    __tablename__ = "events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), index=True)
    op_type = Column(String(50), nullable=False)  # create_entity, move_entity, etc.
    payload = Column(JSONB, nullable=False)
    actor = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

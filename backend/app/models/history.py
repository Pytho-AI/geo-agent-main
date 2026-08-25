from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.models.base import Base


class MapHistory(Base):
    """Snapshot of a map's complete state at a point in time"""
    __tablename__ = "map_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    label = Column(String(255))
    
    # Denormalized snapshot data
    map_snapshot = Column(JSONB, nullable=False)
    entities_snapshot = Column(JSONB, nullable=False, default=[])
    overlays_snapshot = Column(JSONB, nullable=False, default=[])
    artifacts_snapshot = Column(JSONB, nullable=False, default=[])
    routes_snapshot = Column(JSONB, nullable=False, default=[])
    
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(255))
    
    # Relationship
    map = relationship("Map", backref="history")
    
    # Ensure version is unique per map
    __table_args__ = (
        UniqueConstraint('map_id', 'version', name='uq_map_history_map_version'),
    )

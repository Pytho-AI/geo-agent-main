from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.models.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # shapefile, geojson, geotiff
    storage_uri = Column(String(1024), nullable=False)
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    file_meta = Column(JSONB, default={})
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    map = relationship("Map", back_populates="artifacts")

from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import uuid

from app.models.base import Base, MapMixin


class Overlay(Base, MapMixin):
    __tablename__ = "overlays"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(50), nullable=False)  # phase_line, boundary, route, etc.
    name = Column(String(255))
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=False)
    attrs = Column(JSONB, default={})
    
    # Relationship
    map = relationship("Map", back_populates="overlays")

from sqlalchemy import Column, String, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import uuid

from app.models.base import Base, MapMixin


class Entity(Base, MapMixin):
    __tablename__ = "entities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(50), nullable=False)  # unit, terrain_feature, poi, etc.
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=False)
    attrs = Column(JSONB, default={})
    confidence = Column(Float, default=1.0)
    
    # Relationship
    map = relationship("Map", back_populates="entities")

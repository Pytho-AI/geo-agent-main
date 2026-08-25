from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from app.models.base import Base


class Map(Base):
    __tablename__ = "maps"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False, index=True)
    
    # Bounding box
    bbox_west = Column(Float)
    bbox_south = Column(Float)
    bbox_east = Column(Float)
    bbox_north = Column(Float)
    
    # Center point
    center_lng = Column(Float)
    center_lat = Column(Float)
    
    # Zoom level
    zoom = Column(Float, default=8)

    # Entity graph mode: authored (the only mode built) | consumed
    # (reserved for the future ontology-like source — columns only,
    # design decision 19).
    graph_mode = Column(String(16), server_default="authored")
    
    # Additional attributes
    attrs = Column(JSONB, default={})
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    entities = relationship("Entity", back_populates="map", cascade="all, delete-orphan")
    overlays = relationship("Overlay", back_populates="map", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="map", cascade="all, delete-orphan")
    routes = relationship("Route", back_populates="map", cascade="all, delete-orphan")

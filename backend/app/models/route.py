from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import uuid

from app.models.base import Base, MapMixin


class Route(Base, MapMixin):
    """A route planning request with start/end points and multiple alternative paths."""
    __tablename__ = "routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    map_id = Column(UUID(as_uuid=True), ForeignKey("maps.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255))
    start_geom = Column(Geometry("POINT", srid=4326), nullable=False)
    end_geom = Column(Geometry("POINT", srid=4326), nullable=False)
    route_mode = Column(String(50), nullable=False, default="mixed")  # on_road, off_road, mixed
    status = Column(String(50), nullable=False, default="pending")  # pending, computing, completed, failed
    attrs = Column(JSONB, default={})

    # Relationships
    map = relationship("Map", back_populates="routes")
    paths = relationship("RoutePath", back_populates="route", cascade="all, delete-orphan", order_by="RoutePath.rank")


class RoutePath(Base):
    """A single alternative path within a route, with geometry and analysis."""
    __tablename__ = "route_paths"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id = Column(UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False, default=1)  # 1 = primary/recommended
    label = Column(String(255))  # e.g. "Alpha", "Bravo", "Charlie"
    geom = Column(Geometry("LINESTRING", srid=4326), nullable=False)
    selected = Column(Integer, default=0)  # 0 = not selected, 1 = user-selected route

    # All analysis data in one JSONB blob
    analysis = Column(JSONB, default={})

    # Relationship
    route = relationship("Route", back_populates="paths")

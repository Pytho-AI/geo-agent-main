from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, DateTime, String
from datetime import datetime


class Base(DeclarativeBase):
    pass


class MapMixin:
    """Mixin for map-scoped records with timestamps"""
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

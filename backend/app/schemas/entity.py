from pydantic import BaseModel
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.schemas.common import GeoJSON


class EntityBase(BaseModel):
    kind: str
    geom: GeoJSON
    attrs: Optional[Dict[str, Any]] = {}
    confidence: Optional[float] = 1.0


class EntityCreate(EntityBase):
    pass


class EntityUpdate(BaseModel):
    geom: Optional[GeoJSON] = None
    attrs: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None


class EntityResponse(EntityBase):
    id: UUID
    map_id: UUID
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

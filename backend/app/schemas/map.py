from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime


class MapCreate(BaseModel):
    name: str
    user_id: str
    bbox_west: Optional[float] = None
    bbox_south: Optional[float] = None
    bbox_east: Optional[float] = None
    bbox_north: Optional[float] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    zoom: Optional[float] = 8
    attrs: Optional[Dict[str, Any]] = {}


class MapUpdate(BaseModel):
    name: Optional[str] = None
    bbox_west: Optional[float] = None
    bbox_south: Optional[float] = None
    bbox_east: Optional[float] = None
    bbox_north: Optional[float] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    zoom: Optional[float] = None
    attrs: Optional[Dict[str, Any]] = None


class MapResponse(BaseModel):
    id: UUID
    name: str
    user_id: str
    bbox_west: Optional[float]
    bbox_south: Optional[float]
    bbox_east: Optional[float]
    bbox_north: Optional[float]
    center_lng: Optional[float]
    center_lat: Optional[float]
    zoom: Optional[float]
    attrs: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class MapListResponse(BaseModel):
    maps: List[MapResponse]
    total: int

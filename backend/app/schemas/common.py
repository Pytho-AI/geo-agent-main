from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID


class BBox(BaseModel):
    """Bounding box [min_lon, min_lat, max_lon, max_lat]"""
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    
    @classmethod
    def from_list(cls, bbox: List[float]) -> "BBox":
        return cls(min_lon=bbox[0], min_lat=bbox[1], max_lon=bbox[2], max_lat=bbox[3])


class GeoJSON(BaseModel):
    """GeoJSON geometry"""
    type: str
    coordinates: list


class MapRequest(BaseModel):
    """Base request with map context"""
    map_id: UUID
    user_id: str

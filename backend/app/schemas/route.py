from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from enum import Enum

from app.schemas.common import GeoJSON


# --- Enums ---

class RouteMode(str, Enum):
    ON_ROAD = "on_road"
    OFF_ROAD = "off_road"
    MIXED = "mixed"


class RouteStatus(str, Enum):
    PENDING = "pending"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"


# --- RoutePath schemas ---

class RoutePathBase(BaseModel):
    rank: int = 1
    label: Optional[str] = None
    geom: GeoJSON
    selected: Optional[int] = 0
    analysis: Optional[Dict[str, Any]] = {}


class RoutePathCreate(RoutePathBase):
    pass


class RoutePathUpdate(BaseModel):
    label: Optional[str] = None
    geom: Optional[GeoJSON] = None
    selected: Optional[int] = None
    analysis: Optional[Dict[str, Any]] = None


class RoutePathResponse(RoutePathBase):
    id: UUID
    route_id: UUID

    class Config:
        from_attributes = True


# --- Route schemas ---

class RouteBase(BaseModel):
    name: Optional[str] = None
    start_geom: GeoJSON
    end_geom: GeoJSON
    route_mode: RouteMode = RouteMode.MIXED
    attrs: Optional[Dict[str, Any]] = {}


class RouteCreate(RouteBase):
    paths: Optional[List[RoutePathCreate]] = []


class RouteUpdate(BaseModel):
    name: Optional[str] = None
    start_geom: Optional[GeoJSON] = None
    end_geom: Optional[GeoJSON] = None
    route_mode: Optional[RouteMode] = None
    status: Optional[RouteStatus] = None
    attrs: Optional[Dict[str, Any]] = None


class AnalyzeEditRequest(BaseModel):
    """Request body for analyzing user-edited route coordinates."""
    coordinates: List[List[float]]  # [[lon, lat], ...]


class RouteResponse(RouteBase):
    id: UUID
    map_id: UUID
    status: RouteStatus
    paths: List[RoutePathResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

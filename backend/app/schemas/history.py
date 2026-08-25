from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime


class SnapshotCreate(BaseModel):
    """Schema for creating a new snapshot"""
    label: Optional[str] = None
    created_by: Optional[str] = None


class MapSnapshotData(BaseModel):
    """Map data stored in snapshot"""
    id: UUID
    name: str
    user_id: str
    bbox_west: Optional[float] = None
    bbox_south: Optional[float] = None
    bbox_east: Optional[float] = None
    bbox_north: Optional[float] = None
    center_lng: Optional[float] = None
    center_lat: Optional[float] = None
    zoom: Optional[float] = None
    attrs: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class EntitySnapshotData(BaseModel):
    """Entity data stored in snapshot"""
    id: UUID
    kind: str
    geom: Dict[str, Any]  # GeoJSON geometry
    attrs: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OverlaySnapshotData(BaseModel):
    """Overlay data stored in snapshot"""
    id: UUID
    kind: str
    name: Optional[str] = None
    geom: Dict[str, Any]  # GeoJSON geometry
    attrs: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ArtifactSnapshotData(BaseModel):
    """Artifact metadata stored in snapshot"""
    id: UUID
    filename: str
    file_type: str
    storage_uri: str
    status: Optional[str] = None
    file_meta: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class SnapshotResponse(BaseModel):
    """Full snapshot response with all data"""
    id: UUID
    map_id: UUID
    version: int
    label: Optional[str] = None
    map_snapshot: Dict[str, Any]
    entities_snapshot: List[Dict[str, Any]]
    overlays_snapshot: List[Dict[str, Any]]
    artifacts_snapshot: List[Dict[str, Any]]
    routes_snapshot: List[Dict[str, Any]] = []
    created_at: datetime
    created_by: Optional[str] = None
    
    class Config:
        from_attributes = True


class SnapshotListItem(BaseModel):
    """Lightweight snapshot info for list responses"""
    id: UUID
    map_id: UUID
    version: int
    label: Optional[str] = None
    created_at: datetime
    created_by: Optional[str] = None
    
    class Config:
        from_attributes = True


class SnapshotListResponse(BaseModel):
    """List of snapshots with total count"""
    snapshots: List[SnapshotListItem]
    total: int

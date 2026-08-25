from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Literal, Union
from uuid import UUID

from app.schemas.common import GeoJSON, MapRequest


class CreateEntity(BaseModel):
    op: Literal["create_entity"] = "create_entity"
    kind: str
    geom: GeoJSON
    attrs: Optional[Dict[str, Any]] = {}


class MoveEntity(BaseModel):
    op: Literal["move_entity"] = "move_entity"
    id: UUID
    geom: GeoJSON


class UpdateEntity(BaseModel):
    op: Literal["update_entity"] = "update_entity"
    id: UUID
    attrs: Dict[str, Any]


class DeleteEntity(BaseModel):
    op: Literal["delete_entity"] = "delete_entity"
    id: UUID


class CreateOverlay(BaseModel):
    op: Literal["create_overlay"] = "create_overlay"
    kind: str
    name: Optional[str] = None
    geom: GeoJSON
    attrs: Optional[Dict[str, Any]] = {}


class DeleteOverlay(BaseModel):
    op: Literal["delete_overlay"] = "delete_overlay"
    id: UUID


class CreateRoute(BaseModel):
    op: Literal["create_route"] = "create_route"
    name: Optional[str] = None
    start_geom: GeoJSON
    end_geom: GeoJSON
    route_mode: str = "mixed"
    attrs: Optional[Dict[str, Any]] = {}


class DeleteRoute(BaseModel):
    op: Literal["delete_route"] = "delete_route"
    id: UUID


# Union of all operations
GeoOp = Union[CreateEntity, MoveEntity, UpdateEntity, DeleteEntity, CreateOverlay, DeleteOverlay, CreateRoute, DeleteRoute]


class GeoOpsRequest(MapRequest):
    ops: List[GeoOp]


class GeoOpsResult(BaseModel):
    op: str
    success: bool
    id: Optional[UUID] = None
    error: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


class GeoOpsResponse(BaseModel):
    results: List[GeoOpsResult]

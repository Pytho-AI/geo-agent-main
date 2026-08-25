"""Pydantic schemas for the entity-graph API. No SIDC anywhere in any
contract (design decision 3/11); the frontend submits picker
selections, never symbol strings."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    entity_type: str
    name: str
    long_name: Optional[str] = None
    affiliation: str = "Unknown"
    category: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    posture: Optional[str] = None
    organic_parent_id: Optional[UUID] = None
    weg_id: Optional[str] = None
    unit_type: Optional[str] = None
    echelon: Optional[str] = None
    personnel_authorized: Optional[int] = None
    personnel_current: Optional[int] = None
    significance: Optional[str] = None
    significance_note: Optional[str] = None
    current_activity: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None


class NodeUpdate(BaseModel):
    # Every field optional; only provided keys apply.
    entity_type: Optional[str] = None
    name: Optional[str] = None
    long_name: Optional[str] = None
    affiliation: Optional[str] = None
    category: Optional[str] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    posture: Optional[str] = None
    organic_parent_id: Optional[UUID] = None
    clear_organic_parent: bool = False
    weg_id: Optional[str] = None
    unit_type: Optional[str] = None
    echelon: Optional[str] = None
    personnel_authorized: Optional[int] = None
    personnel_current: Optional[int] = None
    personnel_killed: Optional[int] = None
    personnel_wounded: Optional[int] = None
    personnel_captured: Optional[int] = None
    combat_effectiveness: Optional[str] = None
    assessment_basis: Optional[str] = None
    significance: Optional[str] = None
    significance_note: Optional[str] = None
    current_activity: Optional[str] = None
    notes: Optional[str] = None
    symbol_set: Optional[str] = None
    symbol_entity_code: Optional[str] = None
    symbol_mod1: Optional[str] = None
    symbol_mod2: Optional[str] = None
    updated_by: Optional[str] = None


class EdgeCreate(BaseModel):
    from_id: UUID
    to_id: UUID
    relationship_type: str
    note: Optional[str] = None
    # Hierarchical types: one OPEN edge per from_id. True = auto-close
    # the prior open attachment (the UI confirms first); False = 409.
    close_prior: bool = False
    created_by: Optional[str] = None


class EdgeUpdate(BaseModel):
    # End-dating an edge preserves phase history (BTG dissolution).
    effective_to: Optional[datetime] = None
    note: Optional[str] = None


class HoldingCreate(BaseModel):
    weg_id: Optional[str] = None
    nomenclature_raw: Optional[str] = None
    count_authorized: Optional[int] = None
    count_current: Optional[int] = None
    created_by: Optional[str] = None


class HoldingUpdate(BaseModel):
    weg_id: Optional[str] = None
    count_authorized: Optional[int] = None
    count_current: Optional[int] = None
    count_degraded: Optional[int] = None
    count_neutralized: Optional[int] = None
    count_destroyed: Optional[int] = None
    count_captured_abandoned: Optional[int] = None
    # Set with weg_id to teach the alias table (fires the deployment-
    # wide merge-aware re-resolution sweep).
    teach_alias: bool = False
    updated_by: Optional[str] = None


class FieldValuePut(BaseModel):
    value: str
    updated_by: Optional[str] = None


class EntityTypeUpsert(BaseModel):
    type_key: str
    label: str
    color: Optional[str] = None
    is_fixed: Optional[bool] = None
    symbol_set: Optional[str] = None
    symbol_entity_code: Optional[str] = None
    default_category: Optional[str] = None
    updated_by: Optional[str] = None


class RelationshipTypeUpsert(BaseModel):
    type_key: str
    label: str
    inverse_label: str
    color: Optional[str] = None
    is_hierarchical: Optional[bool] = None
    updated_by: Optional[str] = None


class FieldDefUpsert(BaseModel):
    field_key: str
    label: str
    value_type: Optional[str] = None
    updated_by: Optional[str] = None


class EquipmentUpsert(BaseModel):
    weg_id: str
    name: str
    domain: Optional[str] = None
    equipment_class: Optional[str] = Field(None, alias="class")
    category: Optional[str] = None
    engagement_range_m: Optional[int] = None
    detection_range_m: Optional[int] = None
    road_speed_kph: Optional[int] = None
    crew: Optional[int] = None
    caliber: Optional[str] = None
    date_of_introduction: Optional[str] = None
    proliferation_note: Optional[str] = None
    symbol_entity_code: Optional[str] = None
    symbol_mod1: Optional[str] = None
    symbol_mod2: Optional[str] = None
    updated_by: Optional[str] = None

    model_config = {"populate_by_name": True}


class TemplateInstantiate(BaseModel):
    project_id: UUID
    parent_id: Optional[UUID] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    affiliation: Optional[str] = None
    created_by: Optional[str] = None


class TemplateSave(BaseModel):
    key: str
    name: str
    root_node_id: UUID
    # organic = organic tree only; task_org = organic overlaid by open
    # hierarchical attachments (the save dialog states which).
    capture: str = "organic"
    created_by: Optional[str] = None

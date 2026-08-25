from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID


class ForceEntry(BaseModel):
    """Structured friendly force entry from the COA pipeline."""
    unitName: str
    unitType: str = ""
    size: str = ""
    capability: str = ""
    currentLocation: str = ""
    availability: str = ""
    notes: str = ""


class COPGenerateRequest(BaseModel):
    """Request to generate a COP from a world state narrative."""
    world_state: str
    user_id: str = "coa-engine"
    forces: Optional[List[ForceEntry]] = None
    ipoe_products: Optional[str] = None
    mission_analysis: Optional[str] = None


class COPTerrainSummary(BaseModel):
    """Summary of terrain analysis for the area of operations."""
    elevation_range_m: Optional[List[float]] = None  # [min, max]
    dominant_land_cover: Optional[List[str]] = None
    terrain_grid: Optional[List[Dict[str, Any]]] = None


class COPGenerateResponse(BaseModel):
    """Structured COP returned after generation."""
    map_id: UUID
    bbox: List[float]  # [west, south, east, north]
    entities: Dict[str, Any]  # GeoJSON FeatureCollection
    overlays: Dict[str, Any]  # GeoJSON FeatureCollection
    routes: List[Dict[str, Any]] = []  # RouteResponse dicts
    terrain: Optional[COPTerrainSummary] = None
    meta: Dict[str, Any]
    generation_summary: str


class COPGetResponse(BaseModel):
    """Current COP state for an existing map."""
    map_id: UUID
    bbox: Optional[List[float]] = None
    entities: Dict[str, Any]
    overlays: Dict[str, Any]
    routes: List[Dict[str, Any]] = []
    meta: Dict[str, Any]


class COAMapRequest(BaseModel):
    """Request to generate a COA-specific map from a COP base map."""
    source_map_id: UUID
    coa_number: int
    coa_title: Optional[str] = None
    brief_content: str
    user_id: str = "coa-engine"
    cop_screenshot_b64: Optional[str] = None  # base64 PNG of annotated COP map


class COAMapResponse(BaseModel):
    """COA map returned after generation."""
    map_id: UUID
    bbox: List[float]
    entities: Dict[str, Any]
    overlays: Dict[str, Any]
    routes: List[Dict[str, Any]] = []
    meta: Dict[str, Any]

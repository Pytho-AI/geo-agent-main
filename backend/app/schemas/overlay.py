from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from enum import Enum

from app.schemas.common import GeoJSON
from app.constants import get_overlay_kinds


# OverlayKind is built from app.constants.overlays at import time, so the
# enum membership stays in lock-step with the constants registry. Earlier
# this class was a hardcoded subclass of (str, Enum) with ~14 obstacle/area
# values literally written into the body — the docstring claimed "dynamically
# derived" but it wasn't. The functional Enum() call below actually is.
def _build_overlay_kind_enum():
    members = {kind.upper(): kind for kind in get_overlay_kinds()}
    cls = Enum("OverlayKind", members, type=str)
    cls.__doc__ = (
        "Overlay kinds — dynamically derived from app.constants.overlays.\n"
        "Members are auto-generated from get_overlay_kinds(). Adding a new\n"
        "kind to constants/overlays.py surfaces it here without code changes."
    )

    def _is_valid(c, kind: str) -> bool:
        """Check if a kind value is valid (source of truth = constants module)."""
        return kind in get_overlay_kinds()

    cls.is_valid = classmethod(_is_valid)
    return cls


OverlayKind = _build_overlay_kind_enum()


class ObstacleEffect(str, Enum):
    """Obstacle tactical effects"""
    BLOCK = "block"
    TURN = "turn"
    FIX = "fix"
    DISRUPT = "disrupt"


class Affiliation(str, Enum):
    """Force affiliation"""
    FRIEND = "Friend"
    HOSTILE = "Hostile"
    NEUTRAL = "Neutral"
    UNKNOWN = "Unknown"


class TacticalOverlayAttrs(BaseModel):
    """Attributes for tactical overlays"""
    designation: Optional[str] = None  # e.g., "PL ALPHA", "EA DOG", "BP 22"
    affiliation: Affiliation = Affiliation.FRIEND
    echelon: Optional[str] = None  # Team, Squad, Platoon, Company, Battalion, etc.
    obstacle_effect: Optional[ObstacleEffect] = None  # For obstacle overlays
    sidc: Optional[str] = None  # MIL-STD-2525 Symbol Identification Code
    unit_id: Optional[str] = None  # Reference to owning unit
    time_from: Optional[datetime] = None  # Effective time range
    time_to: Optional[datetime] = None
    remarks: Optional[str] = None


class OverlayBase(BaseModel):
    kind: str  # Use OverlayKind values
    name: Optional[str] = None
    geom: GeoJSON
    attrs: Optional[Dict[str, Any]] = {}


class OverlayCreate(OverlayBase):
    pass


class OverlayUpdate(BaseModel):
    """Schema for updating an overlay"""
    kind: Optional[str] = None
    name: Optional[str] = None
    geom: Optional[GeoJSON] = None
    attrs: Optional[Dict[str, Any]] = None


class OverlayResponse(OverlayBase):
    id: UUID
    map_id: UUID
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

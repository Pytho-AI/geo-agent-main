"""
Entity type definitions for geo-agent.
Defines supported entity kinds and their metadata.
"""

from typing import Dict, List, Optional, Any

# Entity type definition structure
EntityTypeInfo = Dict[str, Any]

# Supported entity types
ENTITY_TYPES: List[EntityTypeInfo] = [
    {
        "value": "mil_unit",
        "label": "Military Unit",
        "desc": "Military unit with MIL-STD-2525D symbology",
        "default_sidc_unit_type": "unit",
    },
    {
        "value": "unit",
        "label": "Generic Unit",
        "desc": "Generic organizational unit",
        "default_sidc_unit_type": "unit",
    },
    {
        "value": "terrain_feature",
        "label": "Terrain Feature",
        "desc": "Natural or man-made terrain feature",
        "default_sidc_unit_type": None,
    },
    {
        "value": "poi",
        "label": "Point of Interest",
        "desc": "Named location or landmark",
        "default_sidc_unit_type": None,
    },
    {
        "value": "feature",
        "label": "Generic Feature",
        "desc": "Generic map feature",
        "default_sidc_unit_type": None,
    },
    {
        "value": "target",
        "label": "Target",
        "desc": "IMINT-identified target (priority dot; carries attrs.be_number, attrs.priority, attrs.status). Sourced from the scenario target set via pytho-app.",
        "default_sidc_unit_type": None,
    },
]


def get_entity_type_info(kind: str) -> Optional[EntityTypeInfo]:
    """Get entity type info by kind."""
    for t in ENTITY_TYPES:
        if t["value"] == kind:
            return t
    return None


def get_entity_kinds() -> List[str]:
    """Get list of all valid entity kind values."""
    return [t["value"] for t in ENTITY_TYPES]

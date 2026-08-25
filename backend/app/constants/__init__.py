"""
Constants module for geo-agent backend.
Serves as the single source of truth for entity types, overlay types, SIDC codes, and symbols.
"""

from app.constants.types import (
    SIDC_AFFILIATION,
    SIDC_ECHELON,
    SIDC_STATUS,
    SIDC_UNIT_TYPE,
    AFFILIATION_KEYWORDS,
    ECHELON_KEYWORDS,
)
from app.constants.overlays import (
    OVERLAY_TYPES,
    OVERLAY_STYLES,
    get_overlay_type_info,
    get_overlay_geometry_type,
    get_all_overlay_types,
    get_overlay_kinds,
)
from app.constants.entities import (
    ENTITY_TYPES,
    get_entity_type_info,
    get_entity_kinds,
)
from app.constants.symbols import (
    SYMBOL_SETS,
    get_all_symbols,
    get_all_symbols_cached,
    get_symbols_by_set,
    get_symbol_set_list,
    search_symbols,
)

__all__ = [
    # SIDC codes
    "SIDC_AFFILIATION",
    "SIDC_ECHELON",
    "SIDC_STATUS",
    "SIDC_UNIT_TYPE",
    # Keywords for detection
    "AFFILIATION_KEYWORDS",
    "ECHELON_KEYWORDS",
    # Overlay types
    "OVERLAY_TYPES",
    "OVERLAY_STYLES",
    "get_overlay_type_info",
    "get_overlay_geometry_type",
    "get_all_overlay_types",
    "get_overlay_kinds",
    # Entity types
    "ENTITY_TYPES",
    "get_entity_type_info",
    "get_entity_kinds",
    # Symbols
    "SYMBOL_SETS",
    "get_all_symbols",
    "get_all_symbols_cached",
    "get_symbols_by_set",
    "get_symbol_set_list",
    "search_symbols",
]

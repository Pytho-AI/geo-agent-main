"""
MIL-STD-2525E Symbol definitions loader.
Loads all symbol sets from JSON files and provides searchable symbol data.

Data source: backend/app/data/milstd/2525E *.json, generated from the
spatialillusions milstandard-e TSV tables (MIL-STD-2525E transcription)
by backend/scripts/import_milstd_2525e.py. Re-run that script to pick
up upstream table changes; never hand-edit the JSONs.
"""

import json
from typing import Dict, List, Any, Optional
from pathlib import Path

# Symbol set metadata
SYMBOL_SETS: Dict[str, Dict[str, str]] = {
    "01": {"name": "Air", "file": "2525E 01 air.json"},
    "02": {"name": "Air Missile", "file": "2525E 02 air-missile.json"},
    "05": {"name": "Space", "file": "2525E 05 space.json"},
    "06": {"name": "Space Missile", "file": "2525E 06 space-missile.json"},
    "10": {"name": "Land Unit", "file": "2525E 10 land-unit.json"},
    "11": {"name": "Land Civilian", "file": "2525E 11 land-civilian.json"},
    "15": {"name": "Land Equipment", "file": "2525E 15 land-equipment.json"},
    "20": {"name": "Land Installation", "file": "2525E 20 land-installation.json"},
    "25": {"name": "Control Measure", "file": "2525E 25 control-measures.json"},
    "27": {"name": "Dismounted Individual", "file": "2525E 27 dismounted-individual.json"},
    "30": {"name": "Sea Surface", "file": "2525E 30 sea-surface.json"},
    "35": {"name": "Sea Subsurface", "file": "2525E 35 sea-subsurface.json"},
    "36": {"name": "Mine Warfare", "file": "2525E 36 mine-warfare.json"},
    "40": {"name": "Activities", "file": "2525E 40 activities.json"},
    "50": {"name": "Signals Intelligence", "file": "2525E 50 signals-intelligence.json"},
    "60": {"name": "Cyberspace", "file": "2525E 60 cyberspace.json"},
}

# Path to milstd JSON files
DATA_DIR = Path(__file__).parent.parent / "data" / "milstd"


def _load_symbol_set(symbol_set_code: str) -> Optional[Dict[str, Any]]:
    """Load a single symbol set from its JSON file."""
    if symbol_set_code not in SYMBOL_SETS:
        return None
    
    file_path = DATA_DIR / SYMBOL_SETS[symbol_set_code]["file"]
    if not file_path.exists():
        return None
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_display_name(icon: Dict[str, Any]) -> str:
    """Build display name from entity, entity type, and entity subtype."""
    name = icon.get("entity", "Unknown")
    if icon.get("entity type"):
        name += f" - {icon['entity type']}"
    if icon.get("entity subtype"):
        name += f" - {icon['entity subtype']}"
    return name


def _build_sidc(symbol_set_code: str, entity_code: str, affiliation: str = "3") -> str:
    """
    Build a 20-character SIDC from symbol set and entity code.
    
    Format: version(2) + context(1) + affiliation(1) + symbolSet(2) + status(1) + 
            hqtfd(1) + echelon(2) + entity(6) + mod1(2) + mod2(2)

    Version 13 = MIL-STD-2525E (10 = 2525D); milsymbol 3.x renders both.
    """
    version = "13"
    context = "0"
    status = "0"
    hqtfd = "0"
    echelon = "00"
    mod1 = "00"
    mod2 = "00"
    
    return f"{version}{context}{affiliation}{symbol_set_code}{status}{hqtfd}{echelon}{entity_code}{mod1}{mod2}"


def get_all_symbols() -> List[Dict[str, Any]]:
    """
    Get all symbols from all symbol sets.
    
    Returns a list of symbol dictionaries with:
    - name: Display name (entity - entity type - entity subtype)
    - code: 6-digit entity code
    - sidc: Full 20-character SIDC (friendly affiliation)
    - symbolSet: Symbol set code
    - symbolSetName: Human-readable symbol set name
    - entity: Entity name
    - entityType: Entity type (optional)
    - entitySubtype: Entity subtype (optional)
    - geometry: Geometry type for control measures (optional)
    - keywords: Search keywords
    """
    all_symbols = []
    
    for ss_code, ss_info in SYMBOL_SETS.items():
        data = _load_symbol_set(ss_code)
        if not data:
            continue
        
        main_icons = data.get("main icon", [])
        
        for icon in main_icons:
            entity_code = icon.get("code", "000000")
            
            # Build search keywords
            keywords = [
                icon.get("entity", "").lower(),
                icon.get("entity type", "").lower(),
                icon.get("entity subtype", "").lower(),
                ss_info["name"].lower(),
            ]
            keywords = [k for k in keywords if k]  # Remove empty strings
            
            symbol = {
                "name": _build_display_name(icon),
                "code": entity_code,
                "sidc": _build_sidc(ss_code, entity_code),
                "symbolSet": ss_code,
                "symbolSetName": ss_info["name"],
                "entity": icon.get("entity", ""),
                "entityType": icon.get("entity type", ""),
                "entitySubtype": icon.get("entity subtype", ""),
                "keywords": keywords,
            }
            
            # Add geometry for control measures
            if icon.get("geometry"):
                symbol["geometry"] = icon["geometry"]
            
            all_symbols.append(symbol)
    
    return all_symbols


def get_symbols_by_set(symbol_set_code: str) -> List[Dict[str, Any]]:
    """Get all symbols for a specific symbol set."""
    if symbol_set_code not in SYMBOL_SETS:
        return []
    
    data = _load_symbol_set(symbol_set_code)
    if not data:
        return []
    
    ss_info = SYMBOL_SETS[symbol_set_code]
    main_icons = data.get("main icon", [])
    symbols = []
    
    for icon in main_icons:
        entity_code = icon.get("code", "000000")
        
        keywords = [
            icon.get("entity", "").lower(),
            icon.get("entity type", "").lower(),
            icon.get("entity subtype", "").lower(),
        ]
        keywords = [k for k in keywords if k]
        
        symbol = {
            "name": _build_display_name(icon),
            "code": entity_code,
            "sidc": _build_sidc(symbol_set_code, entity_code),
            "symbolSet": symbol_set_code,
            "symbolSetName": ss_info["name"],
            "entity": icon.get("entity", ""),
            "entityType": icon.get("entity type", ""),
            "entitySubtype": icon.get("entity subtype", ""),
            "keywords": keywords,
        }
        
        if icon.get("geometry"):
            symbol["geometry"] = icon["geometry"]
        
        symbols.append(symbol)
    
    return symbols


def get_symbol_set_list() -> List[Dict[str, str]]:
    """Get list of all available symbol sets."""
    return [
        {"code": code, "name": info["name"]}
        for code, info in SYMBOL_SETS.items()
    ]


def search_symbols(query: str, symbol_set: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Search symbols by name or keywords.
    
    Args:
        query: Search query string
        symbol_set: Optional symbol set code to filter by
        limit: Maximum number of results to return
    
    Returns:
        List of matching symbols sorted by relevance
    """
    query_lower = query.lower()
    # Filter out short words (less than 2 chars)
    query_words = [w for w in query_lower.split() if len(w) > 1]
    
    if not query_words:
        return []
    
    if symbol_set:
        symbols = get_symbols_by_set(symbol_set)
    else:
        symbols = get_all_symbols_cached()
    
    # Score and filter symbols
    scored_symbols = []
    for symbol in symbols:
        score = 0
        name_lower = symbol["name"].lower()
        name_parts = [p for p in name_lower.replace("-", " ").split() if p]
        
        # Check each query word
        for word in query_words:
            # Exact match in name gets highest score
            if word in name_lower:
                score += 10
                # Bonus for word boundary match (word starts with query)
                if any(part.startswith(word) for part in name_parts):
                    score += 5
                # Extra bonus for exact word match
                if word in name_parts:
                    score += 3
            
            # Keyword match
            if any(word in kw for kw in symbol["keywords"]):
                score += 8
            
            # Entity/type match
            entity_lower = symbol.get("entity", "").lower()
            entity_type_lower = symbol.get("entityType", "").lower()
            entity_subtype_lower = symbol.get("entitySubtype", "").lower()
            
            if word in entity_lower:
                score += 6
            if word in entity_type_lower:
                score += 4
            if word in entity_subtype_lower:
                score += 2
        
        if score > 0:
            scored_symbols.append((score, symbol))
    
    # Sort by score descending
    scored_symbols.sort(key=lambda x: x[0], reverse=True)
    
    return [s[1] for s in scored_symbols[:limit]]


# Cache for all symbols (loaded on first access)
_all_symbols_cache: Optional[List[Dict[str, Any]]] = None


def get_all_symbols_cached() -> List[Dict[str, Any]]:
    """Get all symbols with caching for performance."""
    global _all_symbols_cache
    if _all_symbols_cache is None:
        _all_symbols_cache = get_all_symbols()
    return _all_symbols_cache

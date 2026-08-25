"""
Terrain and unit-terrain compatibility constants.

Single source of truth for all terrain parameters used by both the NL terrain
tool and the route planner.
"""

from typing import Dict, List, Any

from app.services.knowledge.landcover import LAND_COVER_PROPERTIES

# ---------------------------------------------------------------------------
# Physical / grid constants
# ---------------------------------------------------------------------------
METERS_PER_MILE = 1609.344
TILE_SIZE_MI = 1.0
TILE_SIZE_DEG = TILE_SIZE_MI / 69.0          # ~1 mile in degrees
SAMPLES_PER_TILE_SIDE = 2
INTERSECTION_THRESHOLD_M = 30

# Default slope threshold for routing when no unit type is specified (% grade).
# Matches the "steep" classification upper bound — passable by tracked vehicles.
DEFAULT_MAX_SLOPE_PCT = 58

# ---------------------------------------------------------------------------
# Derived cost maps (from LAND_COVER_PROPERTIES)
# ---------------------------------------------------------------------------
_CONCEALMENT_MAP = {"full": 1.0, "partial": 0.5, "seasonal": 0.3, "none": 0.0}
CONCEALMENT_SCORE: Dict[int, float] = {
    code: _CONCEALMENT_MAP.get(props.get("concealment", "none"), 0.0)
    for code, props in LAND_COVER_PROPERTIES.items()
}

_TRAFFICABILITY_MAP = {"excellent": 1.0, "good": 1.2, "fair": 2.0, "poor": 4.0, "impassable": float("inf")}
TRAFFICABILITY_COST: Dict[int, float] = {
    code: _TRAFFICABILITY_MAP.get(props.get("trafficability_wheeled", "good"), 1.0)
    for code, props in LAND_COVER_PROPERTIES.items()
}

# ---------------------------------------------------------------------------
# Unit types and their terrain preferences/limitations
# Based on common military doctrine for unit capabilities
UNIT_TERRAIN_COMPATIBILITY: Dict[str, Dict[str, Any]] = {
    "armor": {
        "description": "Armored/Tank units",
        "preferred_terrain": ["grassland", "bare_sparse", "cropland"],
        "acceptable_terrain": ["shrubland"],
        "restricted_terrain": ["built_up", "tree_cover"],
        "impassable_terrain": ["water", "wetland", "mangroves", "snow_ice"],
        "max_slope_pct": 58,  # Modern tanks can climb ~30° / 58% grade
        "optimal_slope_pct": 27,
        "mobility_type": "tracked",
        "keywords": ["armor", "tank", "armored", "mechanized", "mech"],
    },
    "infantry": {
        "description": "Foot infantry units",
        "preferred_terrain": ["tree_cover", "built_up", "shrubland"],  # Cover/concealment
        "acceptable_terrain": ["grassland", "cropland", "bare_sparse", "wetland"],
        "restricted_terrain": ["snow_ice"],
        "impassable_terrain": ["water", "mangroves"],
        "max_slope_pct": 70,  # Infantry with gear: ~35°
        "optimal_slope_pct": 40,
        "mobility_type": "infantry",
        "keywords": ["infantry", "foot", "light infantry", "airborne", "air assault"],
    },
    "mechanized_infantry": {
        "description": "Infantry in APCs/IFVs",
        "preferred_terrain": ["grassland", "bare_sparse", "cropland"],
        "acceptable_terrain": ["shrubland", "built_up"],
        "restricted_terrain": ["tree_cover"],
        "impassable_terrain": ["water", "wetland", "mangroves", "snow_ice"],
        "max_slope_pct": 58,
        "optimal_slope_pct": 36,
        "mobility_type": "tracked",
        "keywords": ["mechanized", "mech infantry", "motorized", "stryker", "bradley"],
    },
    "artillery": {
        "description": "Field artillery units",
        "preferred_terrain": ["grassland", "bare_sparse"],  # Need open fields of fire
        "acceptable_terrain": ["cropland", "shrubland"],
        "restricted_terrain": ["built_up"],
        "impassable_terrain": ["water", "wetland", "mangroves", "tree_cover", "snow_ice"],
        "max_slope_pct": 27,  # Need relatively flat for emplacement
        "optimal_slope_pct": 9,
        "mobility_type": "tracked",  # Self-propelled, towed varies
        "keywords": ["artillery", "field artillery", "howitzer", "mlrs", "rocket"],
    },
    "cavalry": {
        "description": "Reconnaissance/Cavalry units",
        "preferred_terrain": ["grassland", "bare_sparse", "shrubland"],
        "acceptable_terrain": ["cropland", "built_up"],
        "restricted_terrain": ["tree_cover"],
        "impassable_terrain": ["water", "wetland", "mangroves"],
        "max_slope_pct": 58,
        "optimal_slope_pct": 36,
        "mobility_type": "wheeled",  # Often wheeled recon vehicles
        "keywords": ["cavalry", "recon", "reconnaissance", "scout"],
    },
    "engineer": {
        "description": "Combat engineer units",
        "preferred_terrain": ["any"],  # Engineers go where needed
        "acceptable_terrain": ["grassland", "shrubland", "cropland", "bare_sparse", "built_up", "tree_cover"],
        "restricted_terrain": ["wetland"],
        "impassable_terrain": ["water", "mangroves"],
        "max_slope_pct": 58,
        "optimal_slope_pct": 36,
        "mobility_type": "tracked",
        "keywords": ["engineer", "combat engineer", "sapper"],
    },
    "air_defense": {
        "description": "Air defense artillery units",
        "preferred_terrain": ["grassland", "bare_sparse"],  # Need clear sky view
        "acceptable_terrain": ["cropland", "shrubland"],
        "restricted_terrain": ["built_up"],
        "impassable_terrain": ["water", "wetland", "mangroves", "tree_cover", "snow_ice"],
        "max_slope_pct": 27,
        "optimal_slope_pct": 9,
        "mobility_type": "tracked",
        "keywords": ["air defense", "ada", "patriot", "stinger", "anti-air"],
    },
    "aviation": {
        "description": "Army aviation (helicopters)",
        "preferred_terrain": ["grassland", "bare_sparse"],  # Landing zones
        "acceptable_terrain": ["cropland"],
        "restricted_terrain": ["tree_cover", "built_up"],
        "impassable_terrain": ["water"],  # Can't land
        "max_slope_pct": 18,  # For landing
        "optimal_slope_pct": 9,
        "mobility_type": "air",
        "keywords": ["aviation", "helicopter", "air cav", "attack helicopter"],
    },
    "special_forces": {
        "description": "Special operations forces",
        "preferred_terrain": ["tree_cover", "built_up", "shrubland"],  # Concealment
        "acceptable_terrain": ["grassland", "cropland", "bare_sparse", "wetland", "snow_ice"],
        "restricted_terrain": [],
        "impassable_terrain": ["water"],  # Without boats
        "max_slope_pct": 84,  # Highly trained, light load: ~40°
        "optimal_slope_pct": 58,
        "mobility_type": "infantry",
        "keywords": ["special forces", "sf", "sof", "ranger", "delta", "seal"],
    },
    "logistics": {
        "description": "Supply and logistics units",
        "preferred_terrain": ["grassland", "bare_sparse", "built_up"],  # Roads
        "acceptable_terrain": ["cropland"],
        "restricted_terrain": ["shrubland", "tree_cover"],
        "impassable_terrain": ["water", "wetland", "mangroves", "snow_ice"],
        "max_slope_pct": 27,
        "optimal_slope_pct": 18,
        "mobility_type": "wheeled",
        "keywords": ["logistics", "supply", "transport", "maintenance", "support"],
    },
}

# Slope classifications (percent grade = rise/run * 100)
SLOPE_CLASSIFICATIONS: Dict[str, Dict[str, Any]] = {
    "flat": {
        "min_pct": 0,
        "max_pct": 9,
        "description": "Flat terrain, excellent for all vehicles",
    },
    "gentle": {
        "min_pct": 9,
        "max_pct": 18,
        "description": "Gentle slope, good for most vehicles",
    },
    "moderate": {
        "min_pct": 18,
        "max_pct": 36,
        "description": "Moderate slope, some vehicle restrictions",
    },
    "steep": {
        "min_pct": 36,
        "max_pct": 58,
        "description": "Steep slope, tracked vehicles only",
    },
    "very_steep": {
        "min_pct": 58,
        "max_pct": 100,
        "description": "Very steep, infantry only",
    },
    "cliff": {
        "min_pct": 100,
        "max_pct": 1000,
        "description": "Near-vertical, requires special equipment",
    },
}

# Elevation advantages
ELEVATION_TACTICAL_VALUE: Dict[str, str] = {
    "high_ground": "Provides observation, fields of fire, and defensive advantage",
    "ridge_line": "Offers cover from direct fire on reverse slope",
    "valley": "Provides concealment but limits observation",
    "depression": "Good for defensive positions, assembly areas",
}


def get_unit_compatibility(unit_type: str) -> Dict[str, Any]:
    """
    Get terrain compatibility info for a unit type.
    
    Args:
        unit_type: Unit type key (e.g., "armor", "infantry")
        
    Returns:
        Compatibility dict or empty dict if not found
    """
    return UNIT_TERRAIN_COMPATIBILITY.get(unit_type.lower(), {})


def detect_unit_type_from_name(name: str) -> str:
    """
    Detect unit type from a unit name string.
    
    Args:
        name: Unit name like "1st Armor Brigade"
        
    Returns:
        Unit type key or "infantry" as default
    """
    name_lower = name.lower()
    
    for unit_type, info in UNIT_TERRAIN_COMPATIBILITY.items():
        keywords = info.get("keywords", [])
        for keyword in keywords:
            if keyword in name_lower:
                return unit_type
    
    # Default to infantry if no match
    return "infantry"


def classify_slope(slope_pct: float) -> str:
    """
    Classify a slope into a category.

    Args:
        slope_pct: Slope as percent grade (rise/run * 100)

    Returns:
        Slope classification key
    """
    for name, info in SLOPE_CLASSIFICATIONS.items():
        if info["min_pct"] <= slope_pct < info["max_pct"]:
            return name
    return "cliff"


def is_terrain_suitable(
    unit_type: str,
    land_cover: str,
    slope_pct: float = 0,
) -> Dict[str, Any]:
    """
    Check if terrain is suitable for a unit type.

    Args:
        unit_type: Unit type key
        land_cover: Land cover type from ESA WorldCover
        slope_pct: Terrain slope as percent grade (rise/run * 100)

    Returns:
        Dict with suitable (bool), reason (str), and severity (str)
    """
    compat = get_unit_compatibility(unit_type)
    if not compat:
        return {
            "suitable": True,
            "reason": "Unknown unit type, assuming suitable",
            "severity": "info",
        }

    issues = []
    severity = "ok"

    # Check land cover
    if land_cover in compat.get("impassable_terrain", []):
        issues.append(f"{land_cover.replace('_', ' ')} is impassable for {unit_type}")
        severity = "error"
    elif land_cover in compat.get("restricted_terrain", []):
        issues.append(f"{land_cover.replace('_', ' ')} restricts {unit_type} movement")
        if severity != "error":
            severity = "warning"

    # Check slope
    max_slope = compat.get("max_slope_pct", DEFAULT_MAX_SLOPE_PCT)
    optimal_slope = compat.get("optimal_slope_pct", DEFAULT_MAX_SLOPE_PCT // 2)

    if slope_pct > max_slope:
        issues.append(f"Slope of {slope_pct:.0f}% exceeds maximum {max_slope}% for {unit_type}")
        severity = "error"
    elif slope_pct > optimal_slope:
        issues.append(f"Slope of {slope_pct:.0f}% is above optimal {optimal_slope}% for {unit_type}")
        if severity != "error":
            severity = "warning"

    return {
        "suitable": severity != "error",
        "reason": "; ".join(issues) if issues else f"Terrain suitable for {unit_type}",
        "severity": severity,
        "issues": issues,
    }

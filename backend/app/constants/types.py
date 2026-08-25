"""
MIL-STD-2525E SIDC (Symbol Identification Code) constants and keyword mappings.

Branch codes verified against backend/app/data/milstd/2525E 10 land-unit.json
(imported from MIL-STD-2525E tables). The previous table carried WRONG codes
against both D and E (infantry pointed at Aviation Fixed Wing, artillery at
Air Defense, engineer at Dog, reconnaissance at Labor) — never trust a code
here without checking the catalog JSON.
"""

from typing import Dict, List

# Symbol Set 25 = Control Measures (Tactical Graphics)
# Affiliation modifiers for tactical graphics (position 3, 0-indexed)
SIDC_AFFILIATION: Dict[str, str] = {
    "Friend": "3",      # Friendly
    "Hostile": "6",     # Hostile/Faker
    "Neutral": "4",     # Neutral
    "Unknown": "1",     # Unknown
}

# Echelon codes for SIDC positions 9-10 (amplifier + amplifierDescriptor)
# These encode the echelon/size indicator
SIDC_ECHELON: Dict[str, str] = {
    "Team": "11",
    "Squad": "12",
    "Section": "13",
    "Platoon": "14",
    "Company": "15",
    "Battalion": "16",
    "Regiment": "17",
    "Brigade": "18",
    "Division": "21",
    "Corps": "22",
    "Army": "23",
}

# Status codes for SIDC position 7 (MIL-STD-2525E)
SIDC_STATUS: Dict[str, str] = {
    "Present": "0",
    "Planned": "1",
    "Anticipated": "2",
    "Known": "3",
}

# Unit type codes for SIDC positions 11-16 (entity + entityType + entitySubType)
# Symbol Set 10 = Land Unit
# Format: entity(2) + entityType(2) + entitySubType(2)
SIDC_UNIT_TYPE: Dict[str, str] = {
    "unit": "000000",           # Unspecified — plain frame, generic unit
    "infantry": "121100",       # Movement and Maneuver > Infantry
    "armor": "120500",          # Movement and Maneuver > Armor/Mechanized
    "cavalry": "121300",        # Movement and Maneuver > Reconnaissance/Cavalry/Scout
    "artillery": "130300",      # Fires > Field Artillery
    "engineer": "140700",       # Protection > Engineer
    "signal": "111000",         # Command and Control > Signal
    "medical": "161300",        # Sustainment > Medical
    "supply": "160200",         # Sustainment > All Classes of Supply
    "maintenance": "161100",    # Sustainment > Maintenance
    "transport": "163600",      # Sustainment > Transportation
    "aviation": "120600",       # Movement and Maneuver > Army Aviation/Rotary Wing
    "airdefense": "130100",     # Fires > Air Defense
    "reconnaissance": "121300", # Movement and Maneuver > Reconnaissance/Cavalry/Scout
    "specialforces": "121700",  # Movement and Maneuver > Special Forces
    "headquarters": "110000",   # Command and Control
    "military_police": "141200", # Protection > Military Police
}

# Keywords to detect affiliation from name
AFFILIATION_KEYWORDS: Dict[str, List[str]] = {
    "Friend": ["friendly", "friend", "allied", "ally", "blue", "us ", "usa", "nato"],
    "Hostile": ["hostile", "enemy", "red", "opfor", "opposing", "adversary", "threat"],
    "Neutral": ["neutral", "green", "non-aligned", "civilian"],
    "Unknown": ["unknown", "unidentified", "pending", "suspected"],
}

# Keywords to detect echelon from name
ECHELON_KEYWORDS: Dict[str, List[str]] = {
    "Team": ["team", "fire team"],
    "Squad": ["squad"],
    "Section": ["section"],
    "Platoon": ["platoon", "plt"],
    "Company": ["company", "troop", "battery", "coy", "co "],
    "Battalion": ["battalion", "btn", "bn ", "squadron"],
    "Regiment": ["regiment", "rgt", "group"],
    "Brigade": ["brigade", "bde", "bct"],
    "Division": ["division", "div"],
    "Corps": ["corps"],
    "Army": ["army", "field army"],
}

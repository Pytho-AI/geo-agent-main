"""
Military overlay type definitions.

Each entry carries the SVG-renderer dispatch contract:

  - value: the kind string features carry on the wire
  - label, desc: UI display
  - sidc: MIL-STD-2525E entity code (20 chars), or None for non-2525E
          doctrinal extensions (ATP 2-01.3 IPB products, FM 4-0 sustainment,
          ATP 4-02 medical sustainment)
  - category: UI grouping label (Maneuver / Fire / Airspace / ...). Preserved
              as-is so the overlay picker UX stays grouped by 2525E sub-section
              rather than collapsed into one bucket
  - source_doctrine: doctrinal source — one of "MIL-STD-2525E",
                     "ATP 2-01.3", "FM 4-0", "ATP 4-02". Distinct from
                     `category` because category is for UX, source_doctrine
                     is for the renderer / writers / provenance
  - primitive: SVG renderer dispatch key — one of the 13 primitives in
               frontend/src/geo-agent/utils/tacticalGraphics.svg.js (this repo)
               PRIMITIVE_DRAWERS table (see redesign doc §3)
  - modifiers: dict of primitive-specific paint parameters

The overlay-serve endpoint copies `primitive` and `modifiers` onto each
outgoing feature's `properties` so the frontend dispatches on
`f.properties.primitive` without needing its own catalog.

SIDC format for 2525D/E: 20 characters
Format: Version(2) + SIC(1) + Affiliation(1) + SymbolSet(2) + Status(1) +
        HQ/TF/Dummy(1) + Echelon(2) + Entity(6) + Modifier1(2) + Modifier2(2)
Symbol Set 25 = Control Measures (Tactical Graphics).
"""

from typing import Dict, List, Optional, Any, Literal

# Overlay type definition structure
OverlayTypeInfo = Dict[str, Any]

# =============================================================================
# CATEGORIES — UI grouping labels for the overlay picker. Doctrinally these
# are MIL-STD-2525E Symbol Set 25 sub-sections (§11 = C2, §14 = Maneuver,
# §19 = Airspace, etc.) plus three non-2525E buckets for IPB / sustainment.
# Source doctrine is tracked separately on each entry via `source_doctrine`.
# =============================================================================
CATEGORY_COMMAND_CONTROL       = "Command & Control"
CATEGORY_MANEUVER              = "Maneuver"
CATEGORY_AIRSPACE              = "Airspace Control"
CATEGORY_MARITIME              = "Maritime"
CATEGORY_FIRE                  = "Fire Support"
CATEGORY_PROTECTION_OBSTACLES  = "Obstacles & Crossings"
CATEGORY_PROTECTION_WIRE       = "Wire & Barriers"
CATEGORY_INTELLIGENCE          = "Intelligence"
CATEGORY_SUSTAINMENT           = "Sustainment"
CATEGORY_MISSION_TASKS         = "Mission Tasks"
CATEGORY_IPB_TERRAIN           = "IPB Terrain"        # ATP 2-01.3 Step 2 terrain extensions
CATEGORY_IBL_OPERATIONAL       = "IBL Operational"    # mix bucket for non-doctrinal IBL helpers (mobility_go, hydrology_obstacle, restricted_terrain)

# =============================================================================
# SOURCE-DOCTRINE CONSTANTS — used in entries' `source_doctrine` field
# =============================================================================
DOCTRINE_MIL_STD_2525E = "MIL-STD-2525E"
DOCTRINE_ATP_2_01_3    = "ATP 2-01.3"
DOCTRINE_FM_4_0        = "FM 4-0"
DOCTRINE_ATP_4_02      = "ATP 4-02"
DOCTRINE_IBL_EXTENSION = "IBL extension"  # genuinely IBL-specific (e.g. mobility_go shading)

# =============================================================================
# PRIMITIVE CONSTANTS — must match PRIMITIVE_DRAWERS keys in
# frontend/src/geo-agent/utils/tacticalGraphics.svg.js (this repo)
# =============================================================================
P_FILLED_CORRIDOR        = "filled_corridor_with_arrowhead"
P_HOLLOW_OUTLINE_ARROW   = "hollow_outline_arrow"
P_BOWTIE_POLYLINE        = "bowtie_bounded_polyline"
P_SINGLE_SHAFT_LINE      = "single_shaft_line"
P_PHASE_LINE             = "phase_line"
# Supply/route lines — a labeled route corridor (solid MSR / dashed
# ASR, brown, no arrowhead, designation in a box). Distinct from
# single_shaft_line, which is a red direction-of-attack arrow.
P_SUPPLY_ROUTE           = "supply_route"
P_BOUNDARY               = "boundary"
P_FSCM_LINE              = "fscm_line"
P_PAIRED_AVIATION_RAILS  = "paired_aviation_rails"
P_CLOSED_POLYGON         = "closed_polygon_with_label"
P_BRACKET                = "bracket"
P_RADIAL                 = "radial"
P_CLOSED_GLYPH           = "closed_glyph"
P_MARKER_GLYPH           = "marker_glyph"
P_STRIKE_THROUGH         = "strike_through"
P_MIL_UNIT               = "mil_unit"
# Dedicated per-kind glyph primitives — each kind that has its own doctrinal
# drawer dispatches by its own primitive name; the generic closed_glyph /
# marker_glyph / radial primitives carry NO kind logic client-side.
P_DECISION_POINT_GLYPH   = "decision_point_glyph"
P_KEY_TERRAIN_GLYPH      = "key_terrain_glyph"
P_STRONG_POINT_GLYPH     = "strong_point_glyph"
P_THREAT_OBJECTIVE_GLYPH = "threat_objective_glyph"
P_CHOKE_POINT_GLYPH      = "choke_point_glyph"
P_RANGE_FAN              = "range_fan"
# Point-form primitives for kinds whose catalog primitive is polygon-class.
# A kind like `objective` is EITHER an area (polygon ring) or a point mark
# (kidney/box/label); resolve_render_attrs picks by the feature's geometry
# class at emit time, so the client dispatch stays a dumb table lookup.
P_OBJECTIVE_POINT        = "objective_point"
P_NAI_POINT              = "nai_point"
P_TAI_POINT              = "tai_point"
P_EA_POINT               = "ea_point"
P_URBAN_POINT            = "urban_point"
P_BATTLE_POSITION_POINT  = "battle_position_point"
P_ASSEMBLY_AREA_POINT    = "assembly_area_point"
P_ROZ_POINT              = "roz_point"


# =============================================================================
# COMMAND & CONTROL LINES (MIL-STD-2525E SS25 §11) — line + cap label,
# rendered via the phase_line primitive (it covers any line-with-label).
# =============================================================================
COMMAND_CONTROL_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "boundary",            "label": "Boundary",            "desc": "Unit boundary line",        "sidc": "10032500001101000000", "category": CATEGORY_COMMAND_CONTROL, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BOUNDARY,          "primitive_polygon": P_CLOSED_POLYGON, "modifiers": {"dash_pattern": "solid", "stroke_color": "#000000", "fill": "none", "stroke_pattern": "solid", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "engineer_work_line",  "label": "Engineer Work Line",  "desc": "Engineer work limit",       "sidc": "10032500001103000000", "category": CATEGORY_COMMAND_CONTROL, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,        "modifiers": {"dash_pattern": "solid", "stroke_color": "#000000"}},
    {"value": "light_line",          "label": "Light Line",          "desc": "Illumination reference",    "sidc": "10032500001102000000", "category": CATEGORY_COMMAND_CONTROL, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,        "modifiers": {"dash_pattern": "solid", "stroke_color": "#000000"}},
]

# =============================================================================
# MANEUVER LINES (MIL-STD-2525E SS25 §14) — most are line-with-cap-label
# (phase_line primitive); direction_of_attack variants are single-shaft
# arrows; ambush is a point-anchored bracket.
# =============================================================================
MANEUVER_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "airhead_line",                "label": "Airhead Line",                "desc": "Boundary of airhead",                 "sidc": "10032500001413000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "ambush",                      "label": "Ambush",                      "desc": "Ambush position",                     "sidc": "10032500001417000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,            "modifiers": {"bracket_shape": "V_apex", "tip_style": "claws", "stroke_color": "affiliation_keyed"}},
    {"value": "bridgehead_line",             "label": "Bridgehead Line",             "desc": "Boundary of bridgehead",              "sidc": "10032500001414000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    # Direction of Attack — single-shaft line with arrowhead. Per FM 1-02.2 §5
    # the supporting variant renders dashed; main/decisive renders solid.
    {"value": "direction_of_attack_aviation","label": "Direction of Attack — Aviation","desc": "Aviation attack direction",         "sidc": "10032500001406010000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE,  "modifiers": {"arrowhead": "filled", "dash_pattern": "solid",  "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "direction_of_attack_main",    "label": "Direction of Attack — Main",  "desc": "Main attack direction",               "sidc": "10032500001406020000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE,  "modifiers": {"arrowhead": "filled", "dash_pattern": "solid",  "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "direction_of_attack_supporting","label": "Direction of Attack — Supporting","desc": "Supporting attack direction",   "sidc": "10032500001406030000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE,  "modifiers": {"arrowhead": "filled", "dash_pattern": "dashed", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "final_coordination_line",     "label": "Final Coordination Line",     "desc": "Final coordination before assault",   "sidc": "10032500001407000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "forward_edge_of_battle_area", "label": "Forward Edge of Battle Area", "desc": "Forward limit of main battle area",   "sidc": "10032500001404000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "forward_line_of_troops",      "label": "Forward Line of Troops",      "desc": "Forward edge of friendly forces",     "sidc": "10032500001401000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "holding_line",                "label": "Holding Line",                "desc": "Line to be held",                     "sidc": "10032500001415000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "infiltration_lane",           "label": "Infiltration Lane",           "desc": "Route for infiltrating forces",       "sidc": "10032500001408000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE,  "modifiers": {"arrowhead": "filled", "dash_pattern": "dashed", "stroke_color": "affiliation_keyed", "annotation": "I"}},
    {"value": "limit_of_advance",            "label": "Limit of Advance",            "desc": "Maximum forward movement limit",      "sidc": "10032500001409000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "line_of_departure",           "label": "Line of Departure",           "desc": "Attack start line",                   "sidc": "10032500001410000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "line_of_departure_contact",   "label": "LD/LC",                       "desc": "LD coinciding with enemy contact",    "sidc": "10032500001411000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "phase_line",                  "label": "Phase Line",                  "desc": "Control measure for coordination",    "sidc": "10032500001403000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "#000000"}},
    {"value": "principal_direction_of_fire", "label": "Principal Direction of Fire", "desc": "Primary direction of fire",           "sidc": "10032500001405000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE,  "modifiers": {"arrowhead": "filled", "dash_pattern": "solid",  "stroke_color": "affiliation_keyed", "annotation": "PDF"}},
    {"value": "probable_line_of_deployment", "label": "Probable Line of Deployment", "desc": "Expected deployment line",            "sidc": "10032500001412000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "dashed", "stroke_color": "affiliation_keyed"}},
    {"value": "release_line",                "label": "Release Line",                "desc": "Point where attack is released",      "sidc": "10032500001416000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,         "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    # Axis of Advance (MIL-STD-2525E SS25 §15, entity 151400) — filled
    # corridor with chevron arrowhead. Moved here from CATEGORY_IBL_OPERATIONAL
    # to its proper 2525E home. Was previously excluded from the UI list because
    # the legacy 2-point line drawer couldn't render it; the new SVG primitive
    # builds the corridor from N≥2 waypoints via buildArrowOutline.
    {"value": "axis_of_advance",             "label": "Axis of Advance",             "desc": "Friendly maneuver axis (filled corridor + arrowhead, echelon-scaled width)", "sidc": "10032515151400000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FILLED_CORRIDOR, "modifiers": {"arrowhead": "chevron_filled", "fill": "affiliation_color", "rail_color": "affiliation_keyed", "width_scale": "echelon", "tail_treatment": "closed"}},
]

# =============================================================================
# AIRSPACE CONTROL LINES (MIL-STD-2525E SS25 §19)
# =============================================================================
AIRSPACE_CONTROL_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "iff_off_line", "label": "IFF Off Line", "desc": "IFF transponder off line", "sidc": "10032500001901000000", "category": CATEGORY_AIRSPACE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,            "modifiers": {"dash_pattern": "solid", "stroke_color": "#0064c8"}},
    {"value": "iff_on_line",  "label": "IFF On Line",  "desc": "IFF transponder on line",  "sidc": "10032500001902000000", "category": CATEGORY_AIRSPACE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE,            "modifiers": {"dash_pattern": "solid", "stroke_color": "#0064c8"}},
    # Air Corridor — paired rails, no arrowhead. Moved from CATEGORY_IBL_OPERATIONAL.
    {"value": "air_corridor", "label": "Air Corridor", "desc": "Aviation corridor (paired rails channel, no arrowhead)", "sidc": None, "category": CATEGORY_AIRSPACE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PAIRED_AVIATION_RAILS, "modifiers": {"rail_color": "affiliation_keyed", "fill": "none"}},
]

# =============================================================================
# MARITIME CONTROL LINES (MIL-STD-2525E SS25 §22) — bearing lines
# render as single-shaft lines without arrowhead.
# =============================================================================
MARITIME_CONTROL_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "bearing_line",                    "label": "Bearing Line",                    "desc": "General bearing line",     "sidc": "10032500002201000000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_acoustic",           "label": "Bearing — Acoustic",              "desc": "Acoustic bearing",         "sidc": "10032500002201030000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_acoustic_ambiguous", "label": "Bearing — Acoustic Ambiguous",    "desc": "Ambiguous acoustic bearing","sidc": "10032500002201040000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "dashed","stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_electro_optical",    "label": "Bearing — Electro-Optical",       "desc": "Electro-optical intercept","sidc": "10032500002201060000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_electronic",         "label": "Bearing — Electronic",            "desc": "Electronic bearing",       "sidc": "10032500002201010000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_ew",                 "label": "Bearing — EW",                    "desc": "EW bearing",               "sidc": "10032500002201020000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_jammer",             "label": "Bearing — Jammer",                "desc": "Jammer bearing",           "sidc": "10032500002201070000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_rdf",                "label": "Bearing — RDF",                   "desc": "RDF bearing",              "sidc": "10032500002201080000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "bearing_line_torpedo",            "label": "Bearing — Torpedo",               "desc": "Torpedo bearing",          "sidc": "10032500002201050000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled","dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "navigational_line",               "label": "Navigational Line",               "desc": "Navigation reference",     "sidc": "10032500002184000000", "category": CATEGORY_MARITIME, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
]

# =============================================================================
# FIRE LINES AND LINEAR TARGETS (MIL-STD-2525E SS25 §24, §26) — all are
# line-with-cap-label (phase_line primitive).
# =============================================================================
FIRE_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "battlefield_coordination_line", "label": "Battlefield Coordination Line", "desc": "BCL for air-ground coordination", "sidc": "10032500002604000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "coordinated_fire_line",         "label": "Coordinated Fire Line (CFL)",   "desc": "CFL boundary",                    "sidc": "10032500002602000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "final_protective_fire",         "label": "Final Protective Fire (FPF)",   "desc": "Final protective fires line",     "sidc": "10032500002407030000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "fire_support_coordination_line","label": "Fire Support Coord Line (FSCL)","desc": "FSCL boundary",                   "sidc": "10032500002601000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "linear_smoke_target",           "label": "Linear Smoke Target",           "desc": "Smoke screen line",               "sidc": "10032500002407020000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE, "modifiers": {"dash_pattern": "dashed","stroke_color": "affiliation_keyed"}},
    {"value": "linear_target",                 "label": "Linear Target",                 "desc": "Linear fire target",              "sidc": "10032500002407010000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_PHASE_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "munition_flight_path",          "label": "Munition Flight Path",          "desc": "Projectile flight path",          "sidc": "10032500002606000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": None}},
    {"value": "no_fire_line",                  "label": "No Fire Line (NFL)",            "desc": "No fire area boundary",           "sidc": "10032500002603000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    {"value": "restrictive_fire_line",         "label": "Restrictive Fire Line (RFL)",   "desc": "RFL boundary",                    "sidc": "10032500002605000000", "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
    # Fire Support Coordination Measure — generic subkind-discriminated wrapper.
    # Moved here from CATEGORY_IBL_OPERATIONAL.
    {"value": "fire_support_coord_measure",    "label": "Fire Support Coord Measure",    "desc": "FSCM (CFL/FSCL/RFL/NFA — subkind discriminates)", "sidc": None, "category": CATEGORY_FIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "primitive_polygon": P_CLOSED_POLYGON, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed", "fill": "none", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
]

# =============================================================================
# PROTECTION OBSTACLES (MIL-STD-2525E SS25 §27, §28) — point obstacle glyphs
# render via marker_glyph; effect arrows via bracket; bridges/fords via marker
# (subkind-keyed).
# =============================================================================
PROTECTION_OBSTACLE_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "abatis",                  "label": "Abatis",                  "desc": "Felled tree obstacle",      "sidc": "10032500002801000000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "abatis"}},
    {"value": "assault_crossing",        "label": "Assault Crossing",        "desc": "Assault crossing site",     "sidc": "10032500002713000000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "assault_crossing"}},
    {"value": "bridge_or_gap",           "label": "Bridge or Gap",           "desc": "Bridge or gap location",    "sidc": "10032500002711000000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "bridge"}},
    {"value": "ford_difficult",          "label": "Ford Difficult",          "desc": "Difficult ford crossing",   "sidc": "10032500002716000000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "ford_difficult"}},
    {"value": "ford_easy",               "label": "Ford Easy",               "desc": "Easy ford crossing",        "sidc": "10032500002715000000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "ford_easy"}},
    # Obstacle effects — paint via bracket primitive (T-cap / funnel / etc.)
    {"value": "obstacle_effect_fix",     "label": "Obstacle Effect — Fix",   "desc": "Fix obstacle effect",       "sidc": "10032500002705030000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,      "modifiers": {"bracket_shape": "T_cap",  "stroke_color": "#000000", "annotation": "F"}},
    {"value": "obstacle_effect_turn",    "label": "Obstacle Effect — Turn",  "desc": "Turn obstacle effect",      "sidc": "10032500002705040000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,      "modifiers": {"bracket_shape": "funnel", "stroke_color": "#000000", "annotation": "T"}},
    {"value": "overhead_wire",           "label": "Overhead Wire",           "desc": "Overhead wire obstruction", "sidc": "10032500002820030000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "#000000", "annotation": "W"}},
    {"value": "roadblock_armed",         "label": "Roadblock — Armed Passable","desc": "Explosives readiness 2",  "sidc": "10032500002712030000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "road_block"}},
    {"value": "roadblock_complete",      "label": "Roadblock — Complete",    "desc": "Executed roadblock",        "sidc": "10032500002712040000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "road_block"}},
    {"value": "roadblock_safe",          "label": "Roadblock — Explosives Safe","desc": "Explosives readiness 1",  "sidc": "10032500002712020000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "road_block"}},
    {"value": "roadblock_planned",       "label": "Roadblock — Planned",     "desc": "Planned roadblock",         "sidc": "10032500002712010000", "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind": "road_block"}},
    # Obstacle Belt — heavy black line + teeth chevrons. Moved from IBL_OPERATIONAL.
    {"value": "obstacle_belt",           "label": "Obstacle Belt",           "desc": "Heavy black line + teeth chevrons",  "sidc": None, "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "#000000", "tail_glyph": "teeth_chevrons", "width_px": 4}},
]

# =============================================================================
# PROTECTION WIRE & BARRIERS (MIL-STD-2525E SS25 §29)
# =============================================================================
PROTECTION_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "antitank_ditch",              "label": "Antitank Ditch",              "desc": "AT ditch (completed)",      "sidc": "10032500002902020000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "annotation": "AT", "width_px": 3}},
    {"value": "antitank_ditch_construction", "label": "Antitank Ditch — UC",         "desc": "AT ditch under construction","sidc": "10032500002902010000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "dashed", "stroke_color": "#00aa00", "annotation": "AT", "width_px": 3}},
    {"value": "antitank_wall",               "label": "Antitank Wall",               "desc": "Antitank wall",             "sidc": "10032500002902040000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "annotation": "ATW", "width_px": 3}},
    {"value": "antitank_ditch_mines",        "label": "AT Ditch + Mines",            "desc": "AT ditch with mines",       "sidc": "10032500002902030000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "annotation": "AT+M", "width_px": 3}},
    {"value": "concertina",                  "label": "Concertina Wire",             "desc": "Single concertina",         "sidc": "10032500002903070000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "triple_fence",                "label": "Double Apron Fence",          "desc": "Double apron fence wire",   "sidc": "10032500002903040000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "double_concertina",           "label": "Double Concertina",           "desc": "Double strand concertina",  "sidc": "10032500002903080000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "double_fence",                "label": "Double Fence",                "desc": "Double fence wire",         "sidc": "10032500002903030000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "ferry",                       "label": "Ferry",                       "desc": "Ferry crossing site",       "sidc": "10032500002907000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH,      "modifiers": {"glyph_table": "obstacles", "subkind": "ferry"}},
    {"value": "fighting_position",           "label": "Fighting Position",           "desc": "Fighting position line",    "sidc": "10032500002910000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "affiliation_keyed", "width_px": 3}},
    {"value": "fortified_line",              "label": "Fortified Line",              "desc": "Fortified defensive line",  "sidc": "10032500002909000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "affiliation_keyed", "width_px": 4}},
    {"value": "high_wire_fence",             "label": "High Wire Fence",             "desc": "High wire fence",           "sidc": "10032500002903060000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "lane",                        "label": "Lane",                        "desc": "Cleared lane through obstacles","sidc": "10032500002906000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "dashed", "stroke_color": "#000000", "annotation": "L", "width_px": 2}},
    {"value": "low_wire_fence",              "label": "Low Wire Fence",              "desc": "Low wire fence",            "sidc": "10032500002903050000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "mineline",                    "label": "Mineline",                    "desc": "Mine obstacle line",        "sidc": "10032500002901010000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#000000", "annotation": "M", "width_px": 3}},
    {"value": "obstacle_line",               "label": "Obstacle Line",               "desc": "General obstacle line",     "sidc": "10032500002901000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#000000", "width_px": 3}},
    {"value": "raft_site",                   "label": "Raft Site",                   "desc": "Raft crossing site",        "sidc": "10032500002908000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH,      "modifiers": {"glyph_table": "obstacles", "subkind": "raft_site"}},
    {"value": "single_fence",                "label": "Single Fence",                "desc": "Single fence wire",         "sidc": "10032500002903020000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "triple_concertina",           "label": "Triple Concertina",           "desc": "Triple strand concertina",  "sidc": "10032500002903090000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
    {"value": "trip_wire",                   "label": "Trip Wire",                   "desc": "Trip wire obstacle",        "sidc": "10032500002905000000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "dotted", "stroke_color": "#00aa00", "width_px": 2}},
    {"value": "wire_obstacle",               "label": "Wire Obstacle",               "desc": "Unspecified wire obstacle", "sidc": "10032500002903010000", "category": CATEGORY_PROTECTION_WIRE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid",  "stroke_color": "#00aa00", "width_px": 3}},
]

# =============================================================================
# INTELLIGENCE LINES (MIL-STD-2525E SS25 §30)
# =============================================================================
INTELLIGENCE_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "intelligence_coordination_line", "label": "Intelligence Coordination Line", "desc": "Intel coordination boundary", "sidc": "10032500003001000000", "category": CATEGORY_INTELLIGENCE, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_FSCM_LINE, "modifiers": {"dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
]

# =============================================================================
# SUSTAINMENT LINES (MIL-STD-2525E SS25 §33) — supply routes
# =============================================================================
SUSTAINMENT_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "alternate_supply_route", "label": "Alternate Supply Route (ASR)", "desc": "Alternate supply route", "sidc": "10032500003304000000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "ASR", "width_px": 3}},
    {"value": "asr_alternating",        "label": "ASR — Alternating",            "desc": "ASR alternating",        "sidc": "10032500003304030000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "ASR-A", "width_px": 3}},
    {"value": "asr_one_way",            "label": "ASR — One Way",                "desc": "ASR one way",            "sidc": "10032500003304010000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "ASR-1W", "width_px": 3}},
    {"value": "asr_two_way",            "label": "ASR — Two Way",                "desc": "ASR two way",            "sidc": "10032500003304020000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "ASR-2W", "width_px": 3}},
    {"value": "halted_convoy",          "label": "Halted Convoy",                "desc": "Stationary convoy",      "sidc": "10032500003302000000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "HC", "width_px": 3}},
    {"value": "main_supply_route",      "label": "Main Supply Route (MSR)",      "desc": "Primary supply route",   "sidc": "10032500003303000000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "MSR", "width_px": 4}},
    {"value": "route",                  "label": "Route",                        "desc": "Route corridor",         "sidc": "10032500003300000000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SUPPLY_ROUTE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "RTE", "width_px": 3}},
    {"value": "moving_convoy",          "label": "Moving Convoy",                "desc": "Convoy in movement",     "sidc": "10032500003301000000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "MC", "width_px": 3}},
    {"value": "msr_alternating",        "label": "MSR — Alternating",            "desc": "MSR alternating",        "sidc": "10032500003303030000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "MSR-A", "width_px": 4}},
    {"value": "msr_one_way",            "label": "MSR — One Way",                "desc": "MSR one way",            "sidc": "10032500003303010000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "MSR-1W", "width_px": 4}},
    {"value": "msr_two_way",            "label": "MSR — Two Way",                "desc": "MSR two way",            "sidc": "10032500003303020000", "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "none", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "MSR-2W", "width_px": 4}},
]

# =============================================================================
# SUSTAINMENT AREAS (FM 4-0 ch. 6; ATP 4-90; JP 4-0 Annex E) — closed polygon
# with centroid label. No 2525E polygon SIDCs exist for these in the public
# symbol set, hence sidc=None.
# =============================================================================
SUSTAINMENT_POLYGON_TYPES: List[OverlayTypeInfo] = [
    {"value": "brigade_support_area",        "label": "Brigade Support Area (BSA)",      "desc": "Brigade-level sustainment area",                       "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "division_support_area",       "label": "Division Support Area (DSA)",     "desc": "Division-level sustainment area",                      "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "logistics_support_area",      "label": "Logistics Support Area (LSA)",    "desc": "Corps/theater-level sustainment area",                 "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "combat_support_area",         "label": "Combat Support Area",             "desc": "Forward combat support area",                          "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "forward_logistics_element",   "label": "Forward Logistics Element (FLE)", "desc": "Forward-deployed sustainment element",                 "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "aerial_port_of_debarkation",  "label": "Aerial Port of Debarkation",      "desc": "APOD / airfield distribution node",                    "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "solid",  "label_position": "polygon_centroid"}},
    {"value": "seaport_of_debarkation",      "label": "Seaport of Debarkation (SPOD)",   "desc": "SPOD / port distribution node",                        "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "solid",  "label_position": "polygon_centroid"}},
    {"value": "theater_distribution_center", "label": "Theater Distribution Center",     "desc": "Strategic-to-operational distribution hub",            "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "affiliation_keyed", "stroke_pattern": "solid",  "label_position": "polygon_centroid"}},
]

# =============================================================================
# SUSTAINMENT POINTS (FM 4-0; ATP 4-90; ATP 4-02 medical) — closed-glyph with
# letter or short label inside.
# =============================================================================
SUSTAINMENT_POINT_TYPES: List[OverlayTypeInfo] = [
    {"value": "logistics_release_point",         "label": "Logistics Release Point (LRP)",        "desc": "Transfer point for forward delivery",     "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "LRP"}},
    {"value": "ammunition_transfer_point",       "label": "Ammunition Transfer Point",            "desc": "ATP / Class V transfer point",            "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "ATP"}},
    {"value": "refuel_on_the_move",              "label": "Refuel On The Move",                   "desc": "ROM site (Class III fuel forward push)",  "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "ROM"}},
    {"value": "class_i_supply_point",            "label": "Class I Supply Point",                 "desc": "Subsistence (food / water) supply point", "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "I"}},
    {"value": "class_iii_supply_point",          "label": "Class III Supply Point",               "desc": "POL (fuel / lubricants) supply point",    "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "III"}},
    {"value": "class_v_supply_point",            "label": "Class V Supply Point",                 "desc": "Ammunition supply point",                 "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "V"}},
    {"value": "class_viii_supply_point",         "label": "Class VIII Supply Point",              "desc": "Medical supply point",                    "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_ATP_4_02, "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "#a30000", "annotation": "VIII"}},
    {"value": "medical_treatment_facility",      "label": "Medical Treatment Facility",           "desc": "Role 2/3 MTF",                            "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_ATP_4_02, "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "#a30000", "annotation": "MTF"}},
    {"value": "casualty_collection_point",       "label": "Casualty Collection Point",            "desc": "Forward CCP for triage / evac staging",   "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_ATP_4_02, "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "#a30000", "annotation": "CCP"}},
    {"value": "maintenance_collection_point",    "label": "Maintenance Collection Point",         "desc": "Battle-damage / maintenance collection",  "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "MCP"}},
    {"value": "mortuary_affairs_collection_point","label": "Mortuary Affairs Collection Point",   "desc": "Human remains collection / processing",   "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "MACP"}},
    {"value": "supply_point",                    "label": "Supply Point",                         "desc": "Generic supply point",                    "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "SP"}},
    {"value": "resupply_point",                  "label": "Resupply Point",                       "desc": "Unit resupply meet point",                "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "RSP"}},
    {"value": "supply_cache",                    "label": "Supply Cache",                         "desc": "Pre-positioned supply cache",             "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "CACHE"}},
    {"value": "decontamination_point",           "label": "Decontamination Point",                "desc": "CBRN decon site (ATP 3-11.32)",           "sidc": None, "category": CATEGORY_SUSTAINMENT, "source_doctrine": DOCTRINE_FM_4_0,  "primitive": P_CLOSED_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "#000000", "annotation": "DECON"}},
]

# =============================================================================
# MISSION TASKS (MIL-STD-2525E SS25 §34) — verb graphics. Single-shaft-line
# variants for movement verbs; bracket variants for area-effect verbs;
# radial variants for security verbs.
# =============================================================================
MISSION_TASK_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "breach",                   "label": "Breach",                   "desc": "Breach mission task",       "sidc": "10032500003402000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "T_cap", "tip_style": "break_gap", "stroke_color": "affiliation_keyed"}},
    {"value": "clear",                    "label": "Clear",                    "desc": "Clear mission task",        "sidc": "10032500003405000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "C",   "shaft_count": 3}},
    {"value": "counterattack",            "label": "Counterattack",            "desc": "Counterattack mission",     "sidc": "10032500003406000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "dashed", "stroke_color": "affiliation_keyed", "annotation": "CATK"}},
    {"value": "counterattack_by_fire",    "label": "Counterattack by Fire",    "desc": "Counterattack by fire",     "sidc": "10032500003407000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "dashed", "stroke_color": "affiliation_keyed", "annotation": "CATK", "tail_glyph": "crossed_sticks"}},
    {"value": "delay",                    "label": "Delay",                    "desc": "Delay mission task",        "sidc": "10032500003408000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "D"}},
    {"value": "fix",                      "label": "Fix",                      "desc": "Fix mission task",          "sidc": "10032500003411000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "F"}},
    {"value": "follow_and_assume",        "label": "Follow and Assume",        "desc": "Follow and assume mission", "sidc": "10032500003412000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "A",   "annotation_box": True}},
    {"value": "follow_and_support",       "label": "Follow and Support",       "desc": "Follow and support mission","sidc": "10032500003413000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "S",   "annotation_box": True}},
    {"value": "retire",                   "label": "Retire / Retirement",      "desc": "Retirement movement",       "sidc": "10032500003420000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "R"}},
    {"value": "security_cover",           "label": "Security — Cover",         "desc": "Cover security mission",    "sidc": "10032500003422010000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "semicircle", "stroke_color": "affiliation_keyed", "annotation": "C"}},
    {"value": "security_guard",           "label": "Security — Guard",         "desc": "Guard security mission",    "sidc": "10032500003422020000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "semicircle", "stroke_color": "affiliation_keyed", "annotation": "G"}},
    {"value": "security_screen",          "label": "Security — Screen",        "desc": "Screen security mission",   "sidc": "10032500003422030000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "semicircle", "stroke_color": "affiliation_keyed", "annotation": "S"}},
    {"value": "seize",                    "label": "Seize",                    "desc": "Seize mission task",        "sidc": "10032500003423000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "S",   "shape_variant": "curved"}},
    {"value": "withdraw",                 "label": "Withdraw",                 "desc": "Withdraw movement",         "sidc": "10032500003424000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "W"}},
    {"value": "withdraw_under_pressure",  "label": "Withdraw Under Pressure",  "desc": "Forced withdrawal",         "sidc": "10032500003425000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "W",  "tail_glyph": "open_chevron_toward_enemy"}},
    # Missing FM 1-02.2 §6 verbs added per redesign — single-shaft-line + bracket + radial families.
    {"value": "bypass",                   "label": "Bypass",                   "desc": "Bypass mission task",       "sidc": "10032500003403000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "B"}},
    {"value": "penetrate",                "label": "Penetrate",                "desc": "Penetrate mission task",    "sidc": "10032500003409000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed", "annotation": "P",  "shaft_count": 3}},
    {"value": "block",                    "label": "Block",                    "desc": "Block mission task",        "sidc": "10032500003401000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "T_cap", "stroke_color": "affiliation_keyed"}},
    {"value": "canalize",                 "label": "Canalize",                 "desc": "Canalize mission task",     "sidc": "10032500003404000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "funnel", "stroke_color": "affiliation_keyed"}},
    {"value": "disrupt",                  "label": "Disrupt",                  "desc": "Disrupt mission task",      "sidc": "10032500003410000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "anvil", "stroke_color": "affiliation_keyed"}},
    {"value": "attack_by_fire",           "label": "Attack by Fire",           "desc": "Attack by fire mission",    "sidc": "10032500003414000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "anvil", "tip_style": "arrow_tips", "stroke_color": "affiliation_keyed"}},
    {"value": "support_by_fire",          "label": "Support by Fire",          "desc": "Support by fire mission",   "sidc": "10032500003415000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_BRACKET,           "modifiers": {"bracket_shape": "Y_splay", "tip_style": "arrow_tips", "stroke_color": "affiliation_keyed"}},
    {"value": "contain",                  "label": "Contain",                  "desc": "Contain mission task",      "sidc": "10032500003416000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "semicircle", "stroke_color": "affiliation_keyed", "annotation": "EN"}},
    {"value": "isolate",                  "label": "Isolate",                  "desc": "Isolate mission task",      "sidc": "10032500003417000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "full_circle", "stroke_color": "affiliation_keyed"}},
    {"value": "neutralize",               "label": "Neutralize",               "desc": "Neutralize mission task",   "sidc": "10032500003418000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "full_circle", "stroke_color": "affiliation_keyed", "annotation": "N"}},
    {"value": "suppress",                 "label": "Suppress",                 "desc": "Suppress mission task",     "sidc": "10032500003419000000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_RADIAL,            "modifiers": {"arc_style": "full_circle", "stroke_color": "affiliation_keyed", "annotation": "S"}},
    {"value": "occupy",                   "label": "Occupy",                   "desc": "Occupy mission task",       "sidc": "10032500003421010000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_GLYPH,      "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "O"}},
    {"value": "retain",                   "label": "Retain",                   "desc": "Retain mission task",       "sidc": "10032500003421020000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_GLYPH,      "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "R"}},
    {"value": "secure",                   "label": "Secure",                   "desc": "Secure mission task",       "sidc": "10032500003421030000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_GLYPH,      "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "S"}},
    {"value": "destroy",                  "label": "Destroy",                  "desc": "Destroy target",            "sidc": "10032500003421040000", "category": CATEGORY_MISSION_TASKS, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_STRIKE_THROUGH,    "modifiers": {"strike_style": "double_X", "stroke_color": "#dc323c"}},
]

# =============================================================================
# IPB TERRAIN EXTENSIONS (ATP 2-01.3) — IPB Step 2 terrain-analysis products.
# Have no MIL-STD-2525E entity codes by design (verified against MIL-STD-2525E
# Change 1 PDF — zero hits for "mobility corridor", three prose-only hits for
# "avenue of approach"). Render via their own SVG primitives.
# =============================================================================
IPB_TERRAIN_LINE_TYPES: List[OverlayTypeInfo] = [
    {"value": "avenue_of_approach",   "label": "Avenue of Approach",   "desc": "IPB Step 2 terrain corridor for attack (hollow open-tail outline arrow). Side-keyed color per ATP Table 4-4: friendly=blue, neutral=black, threat=red.", "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_HOLLOW_OUTLINE_ARROW, "modifiers": {"outline_color": "side_keyed", "fill": "none", "width_scale": "echelon", "tail_treatment": "open", "label_position": "arrow_body"}},
    {"value": "mobility_corridor",    "label": "Mobility Corridor",    "desc": "IPB Step 2 canalized terrain corridor (polyline + bowtie endpoints + centerline echelon tick). Always black per ATP Table 4-4.",                          "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_BOWTIE_POLYLINE,      "modifiers": {"stroke_color": "#000000", "endpoint_glyph": "bowtie", "centerline_echelon_tick": True, "width_scale": "echelon"}},
    {"value": "intervisibility_line", "label": "Intervisibility Line", "desc": "Terrain LOS sight line (dashed black)",                                                                                                                       "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_SINGLE_SHAFT_LINE,    "modifiers": {"arrowhead": "none", "dash_pattern": "dashed", "stroke_color": "#000000"}},
    # NOTE: direction_of_attack subkind-discriminated wrapper kept here for
    # back-compat with scenario data that still uses the generic value;
    # downstream resolution should prefer direction_of_attack_main / supporting /
    # aviation from CATEGORY_MANEUVER.
    {"value": "direction_of_attack",  "label": "Direction of Attack",  "desc": "Operational attack vector (subkind=main|supporting|aviation)",                                                                                              "sidc": None, "category": CATEGORY_MANEUVER,    "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "modifiers": {"arrowhead": "filled", "dash_pattern": "solid", "stroke_color": "affiliation_keyed"}},
]

# =============================================================================
# IPB TERRAIN POLYGONS (ATP 2-01.3) — terrain classification polygons +
# OPORD-derived planning polygons.
# =============================================================================
IPB_TERRAIN_POLYGON_TYPES: List[OverlayTypeInfo] = [
    {"value": "battle_position",             "label": "Battle Position",                  "desc": "Side-keyed translucent fill + bold outline",   "sidc": None, "category": CATEGORY_IPB_TERRAIN,     "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "primitive_point": P_BATTLE_POSITION_POINT, "modifiers": {"fill": "affiliation_translucent", "stroke_color": "affiliation_keyed", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "defensible_terrain",          "label": "Defensible Terrain",               "desc": "Region of natural protection on multiple flanks (FM 5-33 / ATP 2-01.3 defensible terrain). Friendly defensive position — friendly-blue dashed outline per ATP Table 4-4, no fill so the underlying terrain remains readable.", "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "fill_opacity": 0.0, "stroke_color": "#0064c8", "stroke_pattern": "dashed", "stroke_width": 2.0, "label_position": "polygon_centroid"}},
    {"value": "hydrology_obstacle",          "label": "Hydrology Obstacle",               "desc": "Water-as-obstacle polygon",                    "sidc": None, "category": CATEGORY_IBL_OPERATIONAL, "source_doctrine": DOCTRINE_IBL_EXTENSION, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "#4a90d9", "fill_opacity": 0.3, "stroke_color": "#4a90d9", "stroke_pattern": "solid"}},
    {"value": "mobility_go",                 "label": "Mobility GO",                      "desc": "GO mobility area (cross-country trafficable)", "sidc": None, "category": CATEGORY_IBL_OPERATIONAL, "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "#90ee90", "fill_opacity": 0.15, "stroke_color": "none"}},
    {"value": "named_area_of_interest",      "label": "Named Area of Interest",           "desc": "NAI collection focus polygon",                 "sidc": None, "category": CATEGORY_IPB_TERRAIN,     "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "primitive_point": P_NAI_POINT, "modifiers": {"fill": "none", "stroke_color": "#000000", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "objective",                   "label": "Objective",                        "desc": "Operational objective (kidney/area)",          "sidc": None, "category": CATEGORY_MANEUVER,        "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "primitive_point": P_OBJECTIVE_POINT, "modifiers": {"fill": "none", "stroke_color": "#dc323c", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "restricted_op_zone",          "label": "Restricted Operating Zone",        "desc": "ROZ / NFA polygon (dashed black outline)",     "sidc": None, "category": CATEGORY_AIRSPACE,        "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "primitive_point": P_ROZ_POINT, "modifiers": {"fill": "none", "stroke_color": "#000000", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "restricted_terrain",          "label": "Restricted Terrain (SLOW-GO)",     "desc": "Slow-go mobility area",                        "sidc": None, "category": CATEGORY_IBL_OPERATIONAL, "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "#daa520", "fill_opacity": 0.25, "stroke_color": "none"}},
    {"value": "severely_restricted_terrain", "label": "Severely Restricted (NO-GO)",      "desc": "No-go mobility area",                          "sidc": None, "category": CATEGORY_IBL_OPERATIONAL, "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "#8B0000", "fill_opacity": 0.30, "stroke_color": "none"}},
    {"value": "targeted_area_of_interest",   "label": "Targeted Area of Interest",        "desc": "TAI polygon",                                  "sidc": None, "category": CATEGORY_IPB_TERRAIN,     "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "primitive_point": P_TAI_POINT, "modifiers": {"fill": "none", "stroke_color": "#000000", "stroke_pattern": "dashed", "stroke_width": 2, "label_position": "polygon_centroid"}},
    {"value": "urban_area",                  "label": "Urban Area",                       "desc": "Built-up area polygon",                        "sidc": None, "category": CATEGORY_IPB_TERRAIN,     "source_doctrine": DOCTRINE_ATP_2_01_3,    "primitive": P_CLOSED_POLYGON, "primitive_point": P_URBAN_POINT, "modifiers": {"fill": "#808080", "fill_opacity": 0.4, "stroke_color": "#000000", "stroke_pattern": "solid", "label_position": "polygon_centroid"}},
]

# =============================================================================
# IPB TERRAIN POINTS (ATP 2-01.3) — point-form NAI/TAI/decision points, key
# terrain, and SITEMP additions (range fan, threat objective).
# =============================================================================
IPB_TERRAIN_POINT_TYPES: List[OverlayTypeInfo] = [
    {"value": "choke_point",      "label": "Choke Point",      "desc": "Black X glyph (movement constraint)",                                   "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_CHOKE_POINT_GLYPH, "modifiers": {"glyph": "X", "stroke_color": "#000000", "size_px": 16}},
    {"value": "decision_point",   "label": "Decision Point",   "desc": "Commander decision point (diamond)",                                    "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_DECISION_POINT_GLYPH, "modifiers": {"glyph_shape": "diamond", "fill": "none", "stroke_color": "#000000", "annotation_from_property": "id"}},
    {"value": "key_terrain",      "label": "Key Terrain",      "desc": "Purple K-in-circle (advantage-conferring terrain)",                     "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_KEY_TERRAIN_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "#fff", "stroke_color": "#8a2be2", "annotation": "K"}},
    {"value": "obstacle_point",   "label": "Obstacle Point",   "desc": "Subkind-keyed obstacle glyph",                                          "sidc": None, "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_MARKER_GLYPH, "modifiers": {"glyph_table": "obstacles", "subkind_from_property": "subkind"}},
    # THE obstacle ENTITY kind (phase-0 registry completion 2026-07-22):
    # one kind for every doctrinal obstacle form, geometry-dispatched —
    # Point resolves the subkind-keyed glyph (entity rows carry the typed
    # `subkind` column, emitted into feature properties by map_state),
    # LineString the solid obstacle line, Polygon the belt/area outline.
    {"value": "obstacle",         "label": "Obstacle",         "desc": "Doctrinal obstacle entity — point glyph by subkind, line, or belt/area by geometry", "sidc": None, "category": CATEGORY_PROTECTION_OBSTACLES, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_SINGLE_SHAFT_LINE, "primitive_point": P_MARKER_GLYPH, "primitive_polygon": P_CLOSED_POLYGON, "modifiers": {"glyph_table": "obstacles", "subkind_from_property": "subkind", "arrowhead": "none", "dash_pattern": "solid", "stroke_color": "#000000", "width_px": 3, "fill": "none", "stroke_pattern": "solid", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "strong_point",     "label": "Strong Point",     "desc": "Affiliation-keyed S-in-circle (prepared defense)",                      "sidc": None, "category": CATEGORY_MANEUVER,    "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_STRONG_POINT_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "none", "stroke_color": "affiliation_keyed", "annotation": "S"}},
    {"value": "range_fan",        "label": "Range Fan",        "desc": "Concentric red rings — enemy weapon envelope",                          "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_RANGE_FAN,    "modifiers": {"arc_style": "concentric_bands", "stroke_color": "#dc323c", "bands_from_property": "bands"}},
    {"value": "detection_ring",   "label": "Detection Ring",   "desc": "Concentric amber rings — emitter/sensor detection envelope",            "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_RANGE_FAN,    "modifiers": {"arc_style": "concentric_bands", "stroke_color": "#d97706", "bands_from_property": "bands"}},
    {"value": "threat_objective", "label": "Threat Objective", "desc": "Filled red circle — enemy seize/hold intent",                           "sidc": None, "category": CATEGORY_IPB_TERRAIN, "source_doctrine": DOCTRINE_ATP_2_01_3, "primitive": P_THREAT_OBJECTIVE_GLYPH, "modifiers": {"glyph_shape": "circle", "fill": "#dc323c", "stroke_color": "#dc323c"}},
]


# =============================================================================
# COMBINED OVERLAY TYPES
# =============================================================================
LINE_OVERLAY_TYPES: List[OverlayTypeInfo] = (
    COMMAND_CONTROL_LINE_TYPES +
    MANEUVER_LINE_TYPES +
    AIRSPACE_CONTROL_LINE_TYPES +
    MARITIME_CONTROL_LINE_TYPES +
    FIRE_LINE_TYPES +
    PROTECTION_OBSTACLE_LINE_TYPES +
    PROTECTION_LINE_TYPES +
    INTELLIGENCE_LINE_TYPES +
    SUSTAINMENT_LINE_TYPES +
    MISSION_TASK_LINE_TYPES +
    IPB_TERRAIN_LINE_TYPES
)

POLYGON_OVERLAY_TYPES: List[OverlayTypeInfo] = [
    # MIL-STD-2525E maneuver areas (sorted alphabetically)
    # Operational-area graphics — ENCLOSED SHAPES, first-class kinds
    # (never overloaded onto boundary): the overlay selector
    # autopopulates a chip per kind, so each toggles independently.
    {"value": "area_of_interest",   "label": "Area of Interest (AOI)",  "desc": "Area of interest beyond the operational area", "sidc": None, "category": CATEGORY_COMMAND_CONTROL, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "#000000", "stroke_pattern": "solid", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "area_of_operations", "label": "Area of Operations (AO)", "desc": "Assigned operational area",                    "sidc": None, "category": CATEGORY_COMMAND_CONTROL, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "none", "stroke_color": "#000000", "stroke_pattern": "solid", "stroke_width": 3, "label_position": "polygon_centroid"}},
    {"value": "assembly_area",   "label": "Assembly Area",   "desc": "Unit assembly area",   "sidc": "10032500001101000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "primitive_point": P_ASSEMBLY_AREA_POINT, "modifiers": {"fill": "affiliation_translucent", "stroke_color": "affiliation_keyed", "stroke_pattern": "dashed", "label_position": "polygon_centroid"}},
    {"value": "engagement_area", "label": "Engagement Area", "desc": "Kill zone per FM 1-02.2 / ATP 2-01.3 — red outline, no fill, labeled 'EA <name>' at centroid. Matches legend swatch (red bordered rectangle labeled 'EA').", "sidc": "10032500001102000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "primitive_point": P_EA_POINT, "modifiers": {"fill": "none", "fill_opacity": 0.0, "stroke_color": "#b91c1c", "stroke_pattern": "solid", "stroke_width": 2, "label_position": "polygon_centroid"}},
    {"value": "fortified_area",  "label": "Fortified Area",  "desc": "Defensive fortification","sidc": "10032500001103000000", "category": CATEGORY_MANEUVER, "source_doctrine": DOCTRINE_MIL_STD_2525E, "primitive": P_CLOSED_POLYGON, "modifiers": {"fill": "affiliation_translucent", "stroke_color": "affiliation_keyed", "stroke_pattern": "solid", "stroke_width": 3, "label_position": "polygon_centroid"}},
] + IPB_TERRAIN_POLYGON_TYPES + SUSTAINMENT_POLYGON_TYPES

POINT_OVERLAY_TYPES: List[OverlayTypeInfo] = (
    list(IPB_TERRAIN_POINT_TYPES)
    + SUSTAINMENT_POINT_TYPES
)

# Category order for UI display
LINE_CATEGORY_ORDER: List[str] = [
    CATEGORY_COMMAND_CONTROL,
    CATEGORY_MANEUVER,
    CATEGORY_FIRE,
    CATEGORY_AIRSPACE,
    CATEGORY_MARITIME,
    CATEGORY_PROTECTION_OBSTACLES,
    CATEGORY_PROTECTION_WIRE,
    CATEGORY_INTELLIGENCE,
    CATEGORY_SUSTAINMENT,
    CATEGORY_MISSION_TASKS,
    CATEGORY_IPB_TERRAIN,
    CATEGORY_IBL_OPERATIONAL,
]

OVERLAY_TYPES: Dict[str, Any] = {
    "line": LINE_OVERLAY_TYPES,
    "polygon": POLYGON_OVERLAY_TYPES,
    "point": POINT_OVERLAY_TYPES,
    "lineCategoryOrder": LINE_CATEGORY_ORDER,
}

# Overlay styling for UI toolbar icons (legacy; superseded by per-entry
# primitive + modifiers but kept for back-compat with older callers).
OVERLAY_STYLES: Dict[str, Dict[str, Any]] = {
    "wire_obstacle":        {"color": "#00aa00", "width": 3},
    "single_fence":         {"color": "#00aa00", "width": 3},
    "double_fence":         {"color": "#00aa00", "width": 3},
    "triple_fence":         {"color": "#00aa00", "width": 3},
    "antitank_ditch":       {"color": "#00aa00", "width": 3},
    "antitank_ditch_mines": {"color": "#00aa00", "width": 3},
    "default":              {"color": "#00aa00", "width": 2},
}


# =============================================================================
# LOOKUP HELPERS
# =============================================================================
# The catalog's kind vocabulary, public: an entity type is painted as a
# tactical graphic exactly when the catalog defines its renderer
# contract (models/graph.py GRAPHIC_TYPES derives from this — never a
# hand-mirrored list).
_KIND_INDEX: Dict[str, OverlayTypeInfo] = {
    t["value"]: t for t in (LINE_OVERLAY_TYPES + POLYGON_OVERLAY_TYPES + POINT_OVERLAY_TYPES)
}

OVERLAY_KINDS = frozenset(_KIND_INDEX)


def get_overlay_type_info(kind: str) -> Optional[OverlayTypeInfo]:
    """Get overlay type info (including primitive + modifiers) by kind."""
    return _KIND_INDEX.get(kind)


def get_overlay_geometry_type(kind: str) -> Literal["line", "polygon", "point"]:
    """Get geometry type for an overlay kind."""
    if any(t["value"] == kind for t in LINE_OVERLAY_TYPES):
        return "line"
    if any(t["value"] == kind for t in POLYGON_OVERLAY_TYPES):
        return "polygon"
    if any(t["value"] == kind for t in POINT_OVERLAY_TYPES):
        return "point"
    return "polygon"  # default


def get_all_overlay_types() -> List[OverlayTypeInfo]:
    """Get all overlay types as a flat list."""
    return LINE_OVERLAY_TYPES + POLYGON_OVERLAY_TYPES + POINT_OVERLAY_TYPES


def get_overlay_kinds() -> List[str]:
    """Get list of all valid overlay kind values."""
    return [t["value"] for t in get_all_overlay_types()]


# Geometry classes a primitive can draw. The resolution below enforces the
# contract at THE stamp site: a feature never reaches the frontend carrying a
# primitive that cannot draw its geometry class (a line drawer fed a Point
# indexes a bare number into map.project and the LngLatLike throw inside the
# render loop kills ALL map interaction — the 2026-07-19 outage).
_LINE_CLASS_PRIMITIVES = {
    P_FILLED_CORRIDOR, P_HOLLOW_OUTLINE_ARROW, P_BOWTIE_POLYLINE,
    P_SINGLE_SHAFT_LINE, P_PHASE_LINE, P_SUPPLY_ROUTE, P_BOUNDARY,
    P_FSCM_LINE, P_PAIRED_AVIATION_RAILS,
}
_POLYGON_CLASS_PRIMITIVES = {P_CLOSED_POLYGON}


def resolve_render_attrs(kind: str,
                         geometry_type: Optional[str] = None) -> Dict[str, Any]:
    """Look up a kind's renderer dispatch contract (primitive + modifiers),
    resolved for the feature's geometry class.

    Every emit site passes the feature's GeoJSON geometry type so THE
    primitive stamped on the wire is the one the frontend can draw — the
    frontend dispatch is a dumb `PRIMITIVE_DRAWERS[f.properties.primitive]`
    lookup with no kind logic and no geometry heuristics:

      - Point geometry on a polygon-class kind resolves to the row's
        `primitive_point` (OBJ kidney, NAI/TAI box, EA hex, BP/AA/ROZ/urban
        label). No point form -> no primitive -> the feature is data, not
        paint (the edit substrate still carries it).
      - Point geometry on a line-class kind resolves the row's
        `primitive_point` when the row declares one (obstacle's
        subkind glyph); otherwise no drawable form -> {}.
      - Line-class primitives draw ONLY LineString geometry (a Polygon's
        nested rings would feed ring arrays into map.project).

    Returns {} for unknown kinds — caller decides whether to drop the feature
    or pass it through with no primitive (in which case the frontend's edit
    substrate still catches it but no visible paint is emitted).
    """
    spec = _KIND_INDEX.get(kind)
    if not spec:
        return {}
    primitive = spec.get("primitive")
    if geometry_type == "Point":
        if primitive in _POLYGON_CLASS_PRIMITIVES:
            primitive = spec.get("primitive_point")
        elif primitive in _LINE_CLASS_PRIMITIVES:
            # A line-class kind MAY declare a point form (obstacle's
            # subkind glyph); without one, no drawable form.
            primitive = spec.get("primitive_point")
    elif (geometry_type is not None
          and primitive in _LINE_CLASS_PRIMITIVES
          and geometry_type != "LineString"):
        # A polygon form of a line-class kind (an NFA area on the generic
        # FSCM kind) resolves the row's polygon primitive; anything else
        # (rings into a line drawer) resolves to no paint.
        if geometry_type in ("Polygon", "MultiPolygon"):
            primitive = spec.get("primitive_polygon")
        else:
            primitive = None
    if not primitive:
        return {}
    return {
        "primitive": primitive,
        "modifiers": spec.get("modifiers", {}),
    }

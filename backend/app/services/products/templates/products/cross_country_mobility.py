"""CCM — Cross-Country Mobility Overlay — ATP 3-34.80 §B.

Tier 1 GEOINT / geospatial-engineering single-INT product. Per-vehicle-
class trafficability overlay derived from terrain primitives (slope,
soils, vegetation, hydrology) plus weather modifiers (wet-soil
trafficability degradation from the latest WEM). Distinct from MCOO's
coarse 3-class mobility shading — the standalone CCM is finer-grained
and produced by the geospatial engineer in support of movement and
maneuver, fires repositioning, and sustainment routing.

Per ATP 2-01.3: MCOO doctrinally INCORPORATES the CCM as an input layer
but is DISTINCT from it. MCOO is the combined overlay; CCM is the
trafficability primitive.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

CCM_VEHICLE_CLASS_ENUM = [
    "wheeled_light",       # HMMWV, MRAP, light tactical wheeled
    "wheeled_heavy",       # MTV, PLS, FMTV, heavy resupply
    "tracked_light",       # M2/M3 Bradley, Stryker (wheeled-tracked hybrid)
    "tracked_heavy",       # M1 Abrams, breaching vehicles
    "dismounted",          # Personnel on foot
]
CCM_VEHICLE_CLASS_LABELS = {
    "wheeled_light":  "Wheeled (Light)",
    "wheeled_heavy":  "Wheeled (Heavy)",
    "tracked_light":  "Tracked (Light)",
    "tracked_heavy":  "Tracked (Heavy)",
    "dismounted":     "Dismounted",
}

SPEC = {
    "name": "CCM",
    "output_format": "pptx",
    "shape": "paragraph",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the CCM map. Per
    # ATP 3-34.80 + ATP 2-01.3 MCOO input. CCM feeds MCOO so the basemap
    # treatment matches (omt-mcoo) — terrain hatches are the product.
    # Frontend has zero CCM-specific branches.
    # ------------------------------------------------------------------

    "map_basemap": "terrain",

    # Per-product overlay gate. CCM = cross-country mobility
    # classification only — go / slow-go / no-go per declared vehicle
    # class. Urban + hydrology obstacles are first-class mobility
    # impediments. Mobility corridors are the connective product.
    "map_overlay_kinds": [
        "restricted_terrain", "severely_restricted_terrain", "mobility_go",
        "hydrology_obstacle", "urban_area",
        "mobility_corridor",
        "boundary",
    ],

    # All road classes — CCM rates trafficability on every road, not
    # just majors. Same as MCOO.
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-secondary", "omt-road-tertiary", "omt-road-minor",
        "omt-road-path",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: terrain hatches (the entire product), hydrology
    # casing, urban, boundary, mobility corridors as the connective
    # routing. NO battle positions / NAIs / engagement areas — CCM is
    # terrain-only.
    "map_doctrinal_layer_visibility": [
        "mcoo-restricted-base", "mcoo-restricted-fill", "mcoo-restricted-line",
        "mcoo-severe-base", "mcoo-severe-fill", "mcoo-severe-line",
        "mcoo-go-line",
        "mcoo-hydro-halo", "mcoo-hydro-casing", "mcoo-hydro-body",
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-points-hit-target",
    ],

    # Topographic contours help analysts read slope which is the primary
    # mobility input. ATP 3-34.80 explicitly cites elevation gradient
    # as a CCM factor.
    "map_show_topographic_contours": True,

    # Operational-level terrain product — cluster mil units to keep
    # the mobility hatches readable.
    "map_cluster_mil_units": True,
    "map_compact_aa_labels": False,
    "map_compact_legend_labels": False,
    "doctrine": {
        "citation": "ATP 3-34.80 Cross-Country Mobility Analysis; ATP 2-01.3 (MCOO inputs)",
        "purpose": (
            "Per-vehicle-class trafficability overlay for the AO. Inputs: "
            "slope, soils, vegetation, hydrology, and weather modifiers (wet-"
            "soil degradation per WEM). Output: terrain shaded by mobility "
            "rating per the declared force vehicle class. Feeds MCOO (input "
            "layer), TEM (mobility factor of OAKOC), AGM (engagement timing "
            "windows by trafficability), and TSM (collect / deliver platform "
            "routing)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Map figure first (the CCM overlay IS the product), followed by "
            "analytical commentary describing trafficability corridors, key "
            "go / slow-go / no-go terrain, and weather-conditional degradation."
        ),
    },
    "consumes_artifacts": ["WEM"],  # WEM drives weather-conditional trafficability shifts
    "header_fields": {
        "area_of_operations": HEADER_AO,
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "vehicle_class":      {"source": "analytical", "view": "header", "required": True,
                                  "default": "tracked_heavy",
                                  "depends_on": ["entities:units:friendly"],
                                  "enum": CCM_VEHICLE_CLASS_ENUM,
                                  "enum_labels": CCM_VEHICLE_CLASS_LABELS,
                                  "render_label": "Vehicle Class",
                                  "guidance": "Force-relative — CCM is computed per-vehicle-class. Pick from the doctrinal enum based on the maneuvering element's composition."},
        "wem_artifact_id":    {"source": "upstream:WEM", "view": "internal",
                                  "required": False,
                                  "render_label": "WEM Reference",
                                  "depends_on": ["upstream:WEM"],
                                  "guidance": "Upstream WEM — when present, wet-soil rows downgrade trafficability ('cyclic nature of activity on the reduction of mobility')."},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        # Map IS the product — figure placed at top, before analytical text.
        {"name": "ccm_overlay_map",
         "view": "published", "shape": "map",
         "render_label": "Cross-Country Mobility Overlay",
         "required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — slope / soils / vegetation / hydrology
             # primitives + mobility classifications + corridors.
             "map:state",
             # Upstream products (consumes_artifacts).
             "upstream:WEM",
         ]},
        {"name": "trafficability_summary",
         "view": "published", "shape": "string",
         "render_label": "Trafficability Summary",
         "required": True, "provenance_required": True,
         "depends_on": ["map:state", "entities:mobility_corridor",
                        "entities:river", "entities:main_supply_route",
                        "documents"],
         "guidance": (
            "One-to-three sentence summary of the AO's trafficability picture "
            "for the named vehicle_class. Lead with the dominant trafficability "
            "rating across the AO; flag named GO / SLOW-GO / NO-GO terrain."
         )},
        {"name": "weather_conditional_shifts",
         "view": "published", "shape": "string",
         "render_label": "Weather-Conditional Shifts",
         "required": False, "provenance_required": True,
         "depends_on": ["upstream:WEM", "entities:mobility_corridor",
                        "documents"],
         "guidance": (
            "How the trafficability picture changes when WEM weather conditions "
            "apply. Wet-soil rows in the WEM degrade trafficability per ATP "
            "3-34.80 — call out the specific terrain polygons that shift "
            "GO → SLOW-GO under wet conditions. Cite wem_artifact_id."
         )},
        {"name": "named_corridors",
         "view": "published", "shape": "list_of_dicts",
         "render_label": "Named Mobility Corridors",
         "required": False, "provenance_required": True,
         "depends_on": ["entities:mobility_corridor", "entities:river",
                        "entities:main_supply_route", "documents"],
         "guidance": (
            "Per-corridor analytical detail. One entry per identified "
            "mobility corridor — its name, dominant terrain, trafficability "
            "rating for the declared vehicle class, weather sensitivity."
         ),
         "item_subfields": [
            {"name": "corridor_name", "render_label": "Corridor",
             "required": True,
             "guidance": "Named corridor exactly as the retrieval set carries it (a stated mobility corridor, main supply route, or axis)."},
            {"name": "trafficability_rating", "render_label": "Trafficability",
             "required": True,
             "guidance": "GO / SLOW-GO / NO-GO for the declared vehicle class."},
            {"name": "dominant_terrain", "render_label": "Dominant Terrain",
             "required": True,
             "guidance": "Slope / soils / vegetation / hydrology summary for this corridor."},
            {"name": "weather_sensitivity", "render_label": "Weather Sensitivity",
             "required": False,
             "guidance": "How wet / freeze / snow conditions shift this corridor's rating."},
         ]},
    ],
    "subtleties": [
        "CCM is per-vehicle-class — re-derive when the maneuvering element's composition changes.",
        "MCOO incorporates the CCM as one of its input layers, but MCOO's coarse 3-class shading is NOT the same product.",
        "Weather modifiers come from WEM's wet-soil trafficability rows — cite wem_artifact_id when WEM is present.",
    ],
    "hard_rules": [
        "Vehicle class must be in the enum.",
        "Trafficability ratings must be GO / SLOW-GO / NO-GO (doctrinal categorical).",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Terrain primitives: get_terrain (slope, soils, vegetation, hydrology)",
        "Weather modifiers (when WEM present): list_project_docs(filter={type:'WEM'})",
        "Force composition (vehicle class declaration): get_oob(force_type='BLUE') or analyst prose",
    ],
    "post_emit_summary": "artifact_id, vehicle_class, dominant trafficability picture, corridor count",
}

"""LOS — Line-of-Sight Analysis — ATP 3-34.80 §B.

Tier 1 GEOINT / geospatial-engineering single-INT product. Visibility
analysis between observer / sensor positions and target positions,
accounting for terrain elevation, vegetation, and urban masking. Used
to support: patrol-route observation overlays, fire-support observer /
firing-point templating, ADA radar / EW sensor coverage envelopes, NSL
protected-site LOS deconfliction.

Per ATP 3-34.80 Table 4-6, LOS analysis touches every warfighting
function — Movement and Maneuver (patrol routes, ambush positions),
Fires (observer / firing points), Protection (visibility for force
protection), Command and Control (positioning C2 nodes), Intelligence
(ISR sensor placement).

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

LOS_ANALYSIS_TYPE_ENUM = [
    "observer_to_target",     # Point-to-point analysis (sniper, observer post, sensor)
    "sensor_coverage_envelope", # Per-sensor 360-degree visibility radius
    "engagement_area_visibility", # AA / EA fields of fire
    "patrol_route_observation",   # Patrol-route observation overlays
    "protected_site_deconfliction", # NSL / RTL protected-site LOS check
]
LOS_ANALYSIS_TYPE_LABELS = {
    "observer_to_target":          "Observer-to-Target",
    "sensor_coverage_envelope":    "Sensor Coverage Envelope",
    "engagement_area_visibility":  "Engagement Area Visibility",
    "patrol_route_observation":    "Patrol Route Observation",
    "protected_site_deconfliction": "Protected-Site LOS Deconfliction",
}

SPEC = {
    "name": "LOS",
    "output_format": "pptx",
    "shape": "paragraph",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the LOS map. Per
    # ATP 3-34.80 §B. Frontend has zero LOS-specific branches.
    # ------------------------------------------------------------------

    # SITEMP-style basemap — LOS analysis needs the intervisibility
    # lines + key terrain to read first; cross-hatched water bodies
    # (the MCOO basemap treatment) would compete visually.
    "map_basemap": "default",

    # Per-product overlay gate. LOS = line-of-sight analysis only.
    # Intervisibility lines, key terrain (observer / target anchors),
    # urban cover (masking), boundary framework.
    "map_overlay_kinds": [
        "intervisibility_line", "key_terrain",
        "urban_area",
        "boundary",
    ],

    # Same density as SITEMP — major roads + labels. Observer + target
    # callouts need readable roads but not the residential spiderweb.
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: intervisibility lines (the core product), urban
    # masking, boundary, key-terrain points.
    "map_doctrinal_layer_visibility": [
        "mcoo-iv-line",
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-points-hit-target",
    ],

    # Topographic contours kept on — LOS analysis depends on elevation
    # gradient; analysts read the relief to understand why specific
    # observer-target pairs are visible or masked.
    "map_show_topographic_contours": True,

    # Individual observer / target points (each named OP shown).
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,
    "doctrine": {
        "citation": "ATP 3-34.80 §B Line of Sight Analysis; Table 4-6 (warfighting-function applications)",
        "purpose": (
            "Visibility analysis between named observer / sensor positions "
            "and target positions, accounting for terrain elevation, "
            "vegetation, and urban masking. Output: terrain overlay shaded "
            "by visibility class (visible / partially-masked / fully-masked) "
            "with named observer and target points marked. Feeds MCOO (LOS "
            "observation layer), Threat Overlay (sensor coverage envelopes), "
            "SITEMP (EA visibility), CCA (urban masking), CARVER (target "
            "Vulnerability / observability), AGM (direct-fire LOS check), "
            "TSS (sensor-quality gating), NSL (protected-site deconfliction)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Map figure first (the LOS overlay IS the product), followed by "
            "analytical commentary identifying named observer / target pairs, "
            "masking factors, and any sensor-coverage gaps."
        ),
    },
    "consumes_artifacts": [],  # Tier 1 — derives from terrain + observer/target positions
    "header_fields": {
        "area_of_operations": HEADER_AO,
        "dtg":                HEADER_DTG,
        "analysis_type":      {"source": "analytical", "view": "header", "required": True,
                                  "default": "observer_to_target",
                                  "enum": LOS_ANALYSIS_TYPE_ENUM,
                                  "enum_labels": LOS_ANALYSIS_TYPE_LABELS,
                                  "render_label": "Analysis Type",
                                  "guidance": "Doctrinal LOS analysis variant per ATP 3-34.80. Drives observer/target pairing rules."},
        "sensor_or_observer_system": {"source": "analytical", "view": "header",
                                         "required": False,
                                         "render_label": "Sensor / Observer System",
                                         "guidance": "When the analysis is sensor-specific (e.g. AN/TPQ-53 counter-fire radar, FLIR M5 night-observer), name the system. Optical / radar / EW parameters vary by system."},
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "los_overlay_map",
         "view": "published", "shape": "map",
         "render_label": "Line of Sight Overlay",
         "required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — elevation/vegetation/urban masking for LOS
             # primitives; observer + target positions for the pairs.
             "map:state",
             "entities:units",
             "entities:marked",
         ]},
        {"name": "observer_target_pairs",
         "view": "published", "shape": "list_of_dicts",
         "render_label": "Observer / Target Pairs",
         "required": False, "provenance_required": True,
         "guidance": (
            "Per-pair visibility results. One entry per analyzed observer / "
            "target pair. Required for observer_to_target and "
            "patrol_route_observation analyses; optional for envelope/"
            "engagement-area variants where the map already conveys the "
            "data."
         ),
         "item_subfields": [
            {"name": "observer_name", "render_label": "Observer",
             "required": True,
             "guidance": "Observer / sensor name + position (e.g. 'OP-1 grid 38T NM 4455 6677')."},
            {"name": "target_name", "render_label": "Target",
             "required": True,
             "guidance": "Target name + position (KG target_id when available, otherwise grid coordinate)."},
            {"name": "visibility_class", "render_label": "Visibility",
             "required": True,
             "guidance": "VISIBLE / PARTIALLY_MASKED / FULLY_MASKED — categorical per ATP 3-34.80."},
            {"name": "masking_factors", "render_label": "Masking Factors",
             "required": False,
             "guidance": "What causes partial/full masking (terrain crest, vegetation belt, urban structure). Cite the terrain layer source."},
         ]},
        {"name": "coverage_gaps",
         "view": "published", "shape": "string",
         "render_label": "Coverage Gaps",
         "required": False, "provenance_required": True,
         "guidance": (
            "Named gaps in the LOS coverage — terrain folds, urban masking "
            "corridors, dead space behind ridge lines. Drives where the "
            "next sensor / observer should be repositioned."
         )},
        {"name": "analytical_summary",
         "view": "published", "shape": "string",
         "render_label": "Analytical Summary",
         "required": True, "provenance_required": True,
         "guidance": (
            "One-to-three sentence assessment — what the LOS picture means "
            "for the named analysis_type. Tie observer placement to "
            "operational task (patrol, fire support, sensor coverage, NSL "
            "deconfliction)."
         )},
    ],
    "subtleties": [
        "LOS analysis is observer-specific — re-derive per observer / sensor system change.",
        "Engagement-area visibility analyses feed back into SITEMP and CCA; sensor-coverage envelopes feed Threat Overlay; protected-site LOS deconfliction feeds NSL.",
        "Vegetation and urban masking are first-order factors — don't fall back to bare-terrain LOS without flagging the assumption.",
    ],
    "hard_rules": [
        "Analysis type must be in the enum.",
        "Visibility classes must be VISIBLE / PARTIALLY_MASKED / FULLY_MASKED.",
        "Every analytical claim has _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Terrain primitives: get_terrain (elevation, vegetation, urban masking)",
        "Observer / target positions: get_oob (friendly), list_targets (threat)",
        "Sensor parameters (when sensor-specific): analyst prose or sensor catalog",
    ],
    "post_emit_summary": "artifact_id, analysis_type, observer/target pair count, named coverage gaps",
}

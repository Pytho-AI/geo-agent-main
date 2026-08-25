"""MCOO — Modified Combined Obstacle Overlay — ATP 2-01.3 §4.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    MOBILITY_CLASS_ENUM,
    OBSTACLE_EFFECT_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "MCOO",
    "output_format": "pptx",
    "shape": "structured",
    # MANUAL mechanical construction stage (2026-07-27 ruling: the
    # terrain-circuit services are broken and never called). The
    # engine's mcoo_stage constructs the avenue_of_approach draft-layer
    # rows from the writer's avenue items + the committed corridors /
    # anchors, and enumerates constituent corridors per avenue.
    "construction_stage": "mcoo",
    # Briefing order (issue #177): the map IS the product — it renders
    # before any text.
    "paragraph_render_order": ["combined_obstacle_overlay_map"],
    # ------------------------------------------------------------------
    # Map render configuration — doctrinally defines exactly how the MCOO
    # map should look. Every field here is read by backend tool_render_map
    # and forwarded as a URL primitive to OperationsMapHeadless; the
    # frontend has zero MCOO-specific branches. Per ATP 2-01.3 §4 / fig 4-7.
    # ------------------------------------------------------------------

    # Tileserver style id for the basemap raster. MCOO basemap renders
    # forest as diagonal-hatch green, water + wetland as cross-hatch
    # green, urban as black-X cells, ONLY motorway/trunk/primary roads
    # (no spiderweb of residential/service/minor), cream tan background.
    "map_basemap": "terrain",

    # Per-product overlay gate — only these kinds render on the MCOO map.
    # Reflects ATP 2-01.3 Step 2 terrain analysis scope: mobility,
    # avenues of approach, key terrain, obstacles, urban areas.
    # Scheme-of-maneuver kinds (axis_of_advance, objective) are
    # intentionally OFF — MCOO is terrain analysis, not OPORD overlay.
    "map_overlay_kinds": [
        "avenue_of_approach", "mobility_corridor", "intervisibility_line",
        "key_terrain", "choke_point",
        "restricted_terrain", "severely_restricted_terrain", "mobility_go",
        "hydrology_obstacle", "urban_area",
        "obstacle_point", "obstacle_belt",
        # The world model's extracted obstacle instances + natural
        # river obstacles paint on the MCOO (issue #177: the MCOO map
        # was missing obstacles — a core MCOO element).
        "obstacle", "river",
        "boundary", "phase_line",
        # New: synthesized by the terrain-circuit MCOO pipeline. Both
        # are doctrinal step-2 outputs per ATP 2-01.3 (engagement areas
        # selected from GVD-vertex convergences; defensible terrain
        # from flanked regions in the circuit analysis).
        "engagement_area", "defensible_terrain",
    ],

    # MapLibre layer ids on the OMT vector basemap that should be
    # VISIBLE for this product. Anything not in this list is hidden via
    # setLayoutProperty. With the new omt-mcoo raster basemap, road
    # polylines + water polygons come from the raster — so the vector
    # layers here are mostly TEXT labels + supplemental polygons that
    # may be redundant. MCOO doctrine wants every road class for
    # mobility analysis (and the labels), so we keep all road + place
    # label vector layers on top.
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-secondary", "omt-road-tertiary", "omt-road-minor",
        "omt-road-path",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # MapLibre layer ids in the doctrinal-MCOO layer set (created by
    # applyDoctrinalControlMeasures from the overlay/entity features
    # whose `kind` is in map_overlay_kinds above) that should be
    # VISIBLE for this product. Anything not in this list is hidden.
    # MCOO shows terrain analysis + boundaries; no targets, no enemy
    # disposition, no fire-support measures.
    "map_doctrinal_layer_visibility": [
        "mcoo-restricted-base", "mcoo-restricted-fill", "mcoo-restricted-line",
        "mcoo-severe-base", "mcoo-severe-fill", "mcoo-severe-line",
        "mcoo-go-line",
        "mcoo-hydro-halo", "mcoo-hydro-casing", "mcoo-hydro-body",
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-obs-belt-line", "mcoo-iv-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-pl-line",
        "mcoo-points-hit-target",
    ],

    # SITEMP-style zoom-tiered topographic contour overlays. MCOO uses
    # the doctrinal terrain hatches as its primary terrain readout; the
    # contour overlay would compete visually. False per ATP 2-01.3 §4.
    "map_show_topographic_contours": False,

    # Cluster individual mil_unit features into echelon icons (bn/bde).
    # MCOO is an operational-level terrain product — clustering keeps
    # the map readable when many unit symbols would otherwise fight
    # the terrain hatches. SITEMP/Threat Overlay show individual units instead.
    "map_cluster_mil_units": True,

    # Compact AA labels along the chevron (SITEMP/Threat Overlay style). MCOO's
    # avenues of approach are full doctrinal labels with width band +
    # echelon, not the compact one-letter form used on a busy SITEMP.
    "map_compact_aa_labels": False,

    # Compact legend (SITEMP/Threat Overlay pack the legend tight to leave room
    # for many enemy unit symbols). MCOO has fewer point symbols and
    # uses the full doctrinal legend per fig 4-7.
    "map_compact_legend_labels": False,
    "doctrine": {
        "purpose": (
            "Step-2 IPOE landscape map graphic depicting terrain mobility classifications, "
            "AAs, mobility corridors, key terrain, obstacles. Tailored to mission, "
            "collaborative across staff." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Map-layer stack: base → hydrology → mobility classes → urban → obstacles → minefields → mobility corridors → AAs → key terrain → labels → legend.",
    },
    # Combined overlay. Incorporates WEM (weather modifies trafficability),
    # TEM (terrain effects), CCM (per-vehicle-class trafficability), LOS
    # (observation overlay), and IIR (GEOINT) (imagery-confirmed terrain).
    "consumes_artifacts": ["WEM", "TEM", "CCM", "LOS"],
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "scale":              {"source": "session", "view": "header", "required": False,
                                "render_label": "Scale"},
        "force_type":         {"source": "session", "view": "header", "required": True,
                                "default": "Division",
                                "render_label": "Force Type Assumption",
                                "guidance": (
                                    "mobility classes are force-relative; declares the "
                                    "force-type assumption. Default 'Division' when the "
                                    "threat main body maneuvers at division echelon; "
                                    "analyst can override (e.g. 'BCT' for a "
                                    "brigade-level overlay)."
                                )},
        "weather_modifier_wem_ref": {"source": "upstream:WEM", "view": "header",
                                      "required": False,
                                      "render_label": "WEM Reference",
                                      "depends_on": ["upstream:WEM"],
                                      "guidance": "WEM artifact_id for trafficability modifiers"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed fields — populated by handlers/intel_agent.py:_build_skeleton
        # from render_map() output. Hidden from the header k/v table; surface as
        # the <figure> map embed below the header.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # ---- LEAF DATA PARAGRAPHS ----
        # Each data paragraph reads ONE slice of get_terrain (its own layer +
        # tightly-coupled siblings). data_source_filter narrows the payload
        # BEFORE the writer sees it so the prompt never inhales the full
        # ~250k-token merged terrain dict. Without this MCOO.avenues_of_approach
        # hit 400 (prompt overran the 262144-token Gemma context).
        {"name": "mobility_classifications",
         "view": "published",
         "shape": "list_of_dicts",
         # Writer-involvement law: the engine builds the rows from the
         # terrain entities (grids pass through — the model never
         # transcribes or invents geometry); the model only selects
         # rows and fills class + rationale.
         "item_rows": {
             "reads": ["entities:mobility_corridor", "entities:river",
                       "entities:named_area"],
             "mechanical": {"polygon": "location_mgrs",
                            "name": "name"},
             "analytical": ["class", "rationale"],
         },
         "render_label": "Terrain Mobility Classifications",
         "required": True,
         "provenance_required": True,
         # World-model reads: the mobility-classification polygons +
         # the project map config (AO bbox). Raw feature geometry is for
         # the MAP RENDER, not the prose writer.
         "depends_on": ["entities:mobility_corridor",
                         "entities:key_terrain", "entities:river",
                         "entities:named_area", "map:config",
                         "documents"],
         "guidance": (
             "Polygon-by-polygon mobility classification. Classes are force-relative — "
             "cite force_type in header. Cross-hatched green = severely-restricted, "
             "single-hatched green = restricted, unmarked = unrestricted. Urban areas "
             "overlay as black X-pattern."
         ),
         "item_subfields": [
             {"name": "polygon", "render_label": "Polygon (MGRS / GeoJSON)",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": (
                  "Polygon GEOMETRY — NEVER a friendly descriptive name. "
                  "Emit either:\n"
                  "  (a) a closed MGRS ring as a comma-separated sequence "
                  "of grid coords, e.g. "
                  "'35VLF42500580, 35VLF45200580, 35VLF48700605, 35VLF42500580', "
                  "OR\n"
                  "  (b) a GeoJSON Polygon dict, e.g. "
                  '{"type":"Polygon","coordinates":[[[26.05,57.78],[26.30,58.05],'
                  '[26.55,58.12],[26.05,57.78]]]}\n'
                  "Names like 'Northern open ground area' belong in `rationale`, "
                  "not here. Cite the terrain layer source that supplied the "
                  "geometry."
              )},
             {"name": "class", "render_label": "Class",
              "enum": MOBILITY_CLASS_ENUM,
              "guidance": "enum — unrestricted / restricted / severely_restricted"},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": "what made this polygon this class (slope / soils / vegetation / hydrology / built-up). Begin with the area's friendly descriptive name so the analyst-readable label lives here; _provenance lists the ref marks used"}]},
        {"name": "avenues_of_approach",
         "view": "published",
         "shape": "list_of_dicts",
         "max_tokens": 6000,
         "render_label": "Avenues of Approach",
         "required": True,
         "provenance_required": True,
         # AAs nest mobility corridors — depend on the mobility_classifications
         # rollup rather than re-reading raw mobility layer.
         # AAs derive from the sibling mobility rollup + the anchor
         # kinds (corridors route around obstacles; endpoints anchor on
         # key terrain). Raw geometry is map-render input, not prose input.
         "depends_on": ["mobility_classifications",
                         "entities:mobility_corridor",
                         "entities:key_terrain", "entities:river",
                         "entities:bridge", "map:config",
                         "documents"],
         "guidance": (
             "Per ATP 2-01.3 ¶4-21 an avenue of approach is a path used "
             "by a maneuvering force converging on its objective or on "
             "key terrain. Per ¶4-22 each AA aggregates a SERIES of "
             "mobility corridors reaching the same objective. Per ¶4-21 "
             "during offensive operations the MCOO evaluates both:\n"
             "  - Best friendly AAs to the command's objective.\n"
             "  - AAs available to the threat for counterattack, "
             "withdrawal, or movement of reinforcements/reserves.\n"
             "\n"
             "Field-practice convention (CALL, SAMS, ArcGIS MAOT): ONE "
             "chevron per AA, owned by one side, with the opposing "
             "side's bidirectional use of the same terrain captured in "
             "the AA's rationale text NOT as a paired opposing chevron. "
             "Threat AAs are therefore GEOGRAPHICALLY DISTINCT corridors "
             "the threat uses (lateral inter-divisional shifts, "
             "reinforcement from outside the AO, withdrawal vectors, "
             "reserve commitment from rear) — NOT reciprocal mirrors of "
             "friendly attack AAs.\n"
             "\n"
             "The output MUST include rows for ALL of the following:\n"
             "  - One FRIENDLY AA per decisive THREAT objective or "
             "key-terrain feature in the retrieval set (side='friendly', "
             "objective_mgrs from a threat-side key_terrain/objective "
             "entity). Rationale notes the threat formation that could "
             "counterattack via this same corridor.\n"
             "  - One THREAT attack AA from the threat's assembly areas "
             "toward the friendly main defensive objective: "
             "side='threat', objective_mgrs from the friendly-side "
             "objective/key_terrain entity.\n"
             "  - Optional THREAT lateral or reinforcement AAs between "
             "threat formations or from the threat-side AO boundary, "
             "where the stated corridors support them: side='threat', "
             "objective_mgrs = the receiving formation's location.\n"
             "  - Optional NEUTRAL AAs through unaligned terrain "
             "corridors (rare; only when terrain creates a corridor no "
             "formation specifically uses).\n"
             "\n"
             "Do not generate threat AAs whose corridor mirrors a "
             "friendly AA's corridor — capture that bidirectional use "
             "in the friendly AA's rationale instead. Each AA row drives "
             "ONE chevron on the rendered MCOO; the runner enumerates "
             "constituent mobility corridors per AA from same-side "
             "key_terrain origins and computes per-corridor width / "
             "class / AA echelon per ATP 2-01.3 Table 4-2."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "Avenue ID",
              "guidance": "label per avenue of approach — typically a short token that captures side and objective"},
             {"name": "side", "render_label": "Side",
              "enum": ["friendly", "threat", "neutral"],
              "guidance": (
                  "The maneuvering force's side. Friendly AAs converge "
                  "on threat key terrain. Threat AAs converge on friendly "
                  "key terrain. Neutral AAs are corridors usable by either "
                  "side that don't anchor on a specific formation's objective."
              )},
             {"name": "objective_name", "render_label": "Objective",
              "guidance": "name of the convergence point — what the maneuvering force is trying to reach"},
             {"name": "objective_mgrs", "render_label": "Objective (MGRS)",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": (
                  "MGRS of the convergence point. Pull from a key_terrain "
                  "entry whose side is the OPPOSITE of this AA's side "
                  "(friendly key_terrain for threat AAs; threat key_terrain "
                  "for friendly AAs)."
              )},
             {"name": "mobility_corridors", "render_label": "Mobility Corridors",
              "shape": "list_of_dicts",
              "source": "derived:terrain_corridor_enumeration",
              "required": False,
              "guidance": (
                  "Pipeline-derived list of mobility corridors converging "
                  "on this AA's objective. The runner enumerates one "
                  "corridor per opposite-side key_terrain origin, plans "
                  "the centerline via the geo-agent terrain planner, and "
                  "samples per-corridor width + class per ATP 2-01.3 "
                  "Table 4-2. Not emitted by the writer."
              ),
              "item_subfields": [
                  {"name": "corridor_id", "render_label": "Corridor ID", "required": False},
                  {"name": "from_name", "render_label": "From", "required": False},
                  {"name": "from_mgrs", "render_label": "From (MGRS)", "required": False},
                  {"name": "width_km", "render_label": "Off-Road Width (km)", "required": False},
                  {"name": "off_road_class", "render_label": "Off-Road Class", "required": False,
                   "enum": ["division", "brigade", "regiment", "battalion", "company", "sub-company", "unknown"]},
                  {"name": "road_class", "render_label": "Road-Supported Class", "required": False,
                   "enum": ["division", "brigade", "regiment", "battalion", "company", "sub-company", "unknown"]},
                  {"name": "class", "render_label": "Corridor Class", "required": False,
                   "enum": ["division", "brigade", "regiment", "battalion", "company", "sub-company", "unknown"]},
              ]},
             {"name": "echelon", "render_label": "Echelon",
              "enum": ["division", "brigade", "regiment", "battalion", "company", "sub-company", "unknown"],
              "source": "derived:atp_2_01_3_table_4_2",
              "required": False,
              "guidance": (
                  "AA's accommodating echelon — derived post-emit from "
                  "the constituent mobility_corridors per ATP 2-01.3 "
                  "Table 4-2 nesting (Division AA contains Brigade-class "
                  "corridors, Brigade AA contains Battalion-class, etc.). "
                  "Not emitted by the writer."
              )},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": "why this AA matters in the operational context — the doctrinal significance of the convergence and the terrain that shapes it"}]},
        {"name": "key_terrain",
         "view": "published",
         "shape": "list_of_dicts",
         # Writer-involvement law: candidates come from the committed
         # terrain-ish entities; the model SELECTS which are key and
         # classifies them — names and grids pass through the engine.
         "item_rows": {
             "reads": ["entities:key_terrain", "entities:bridge",
                       "entities:garrison", "entities:rail_hub"],
             "mechanical": {"name": "name", "mgrs": "location_mgrs"},
             "analytical": ["type", "decisive", "rationale"],
             "ordinal_id_prefix": "K",
         },
         "render_label": "Key Terrain",
         "required": True,
         "provenance_required": True,
         "depends_on": ["entities:key_terrain", "entities:bridge",
                        "entities:garrison", "entities:rail_hub",
                        "map:state", "documents"],
         "guidance": (
             "Terrain whose seizure / retention affords a marked advantage to either "
             "combatant. Depicted as purple 'K' in a circle/curve enclosing the terrain."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "K-ID",
              "guidance": "key-terrain label (e.g., 'K1')"},
             {"name": "name", "render_label": "Name",
              "guidance": "common name (e.g., 'Hill 425', 'I-95 / Route 7 interchange')"},
             {"name": "type", "render_label": "Type",
              "enum": ["high_ground", "bridge", "intersection", "airfield",
                        "dam", "port", "government_complex", "social_institution"]},
             {"name": "mgrs", "render_label": "MGRS",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": (
                  "Single MGRS string locating the key-terrain feature "
                  "centroid. Pull DIRECTLY from a key_terrain / bridge / "
                  "garrison / rail hub entity in the retrieval set; do "
                  "not fabricate a grid. The renderer paints the purple "
                  "'K' glyph at that point. Cite the entity's ref mark "
                  "in _provenance."
              )},
             {"name": "decisive", "render_label": "Decisive Terrain",
              "required": False,
              "guidance": "true when the terrain is DECISIVE (its seizure essential to mission success), not just key. Rare — most key terrain is not decisive"},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": "specific advantage afforded (observation / fields of fire / control of LOC / etc.); _provenance lists the ref marks used"}]},
        {"name": "obstacles",
         "view": "published",
         "shape": "list_of_dicts",
         # Writer-involvement law: obstacle candidates are the
         # committed river / obstacle / bridge entities; grids pass
         # through (an entity with no stated grid renders without one
         # — never an invented grid); the model classifies effect.
         "item_rows": {
             "reads": ["entities:river", "entities:obstacle",
                       "entities:bridge"],
             "mechanical": {"mgrs": "location_mgrs",
                            "name": "name"},
             "analytical": ["type", "tactical_effect",
                            "mobility_class_imposed", "rationale"],
         },
         "render_label": "Obstacles",
         "required": True,
         "provenance_required": True,
         "depends_on": ["entities:river", "entities:obstacle",
                        "entities:bridge", "map:config", "documents"],
         "guidance": (
             "Both natural (rivers, marshes, cliffs) and man-made (minefields, "
             "wire, AT ditches). Depicted in black. Effective only when covered "
             "by observation and fields of fire."
         ),
         "item_subfields": [
             {"name": "type", "render_label": "Type",
              "enum": ["natural", "man_made"]},
             {"name": "mgrs", "render_label": "Location",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents"],
              "guidance": (
                  "Single MGRS string locating the obstacle centroid "
                  "(point obstacles like a bridge demolition or minefield "
                  "centerpoint). For linear obstacles (river segments, "
                  "AT ditches) emit the dominant chokepoint MGRS; the "
                  "renderer paints a point symbol either way. Pull from "
                  "the river / bridge / obstacle entities in the "
                  "retrieval set — do not invent grids. Cite the "
                  "entity's ref mark in _provenance."
              )},
             {"name": "tactical_effect", "render_label": "Tactical Effect",
              "enum": OBSTACLE_EFFECT_ENUM,
              "guidance": "disrupt / turn / fix / block"},
             {"name": "mobility_class_imposed", "render_label": "Mobility Class Imposed",
              "enum": MOBILITY_CLASS_ENUM,
              "required": False,
              "guidance": (
                  "the mobility-class the obstacle imposes on the terrain it "
                  "lies in. Optional — only when the obstacle dominates the "
                  "polygon. ALLOWED VALUES (exactly these three strings, "
                  "lowercase, underscored):\n"
                  "  - 'severely_restricted' — terrain rendered impassable "
                  "to wheeled / most tracked movement without engineering "
                  "effort (e.g. an unfordable river segment, a dense "
                  "minefield, a destroyed bridge with no bypass).\n"
                  "  - 'restricted' — terrain that slows movement, channels "
                  "formations, or forces deviation but is still trafficable "
                  "(e.g. an AT ditch with bypass, a marsh edge, a wire belt).\n"
                  "  - 'unrestricted' — obstacle's effect on bulk mobility "
                  "is negligible (rare for this field; usually leave blank "
                  "instead).\n"
                  "DO NOT EMIT M1 / M2 / M3 / M4 or any other NATO "
                  "mobility-class taxonomy — those violate the schema enum "
                  "(MOBILITY_CLASS_ENUM in templates/common.py) and will "
                  "be rejected at validation. Use the three doctrinal "
                  "trafficability classes above, matching the same enum "
                  "used by mobility_classifications.class."
              )},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "depends_on": ["entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents", "entities:civil"],
              "guidance": "why this obstacle imposes its tactical effect; what covers it with observation/fires; _provenance lists the ref marks used"}]},
        # ---- ROLLUP PARAGRAPHS ----
        # Map + legend + map_artifact_id consume the sibling data paragraphs
        # (NOT raw cougaar tool returns). data_source_filter explicitly drops
        # raw cougaar deps that the parser would auto-add from artifact
        # mentions, so the rollup writer only sees the structured rollup
        # outputs of its siblings.
        {"name": "combined_obstacle_overlay_map",
         "view": "published",
         "shape": "map",
         "render_label": "Combined Obstacle Overlay",
         "required": True,
         "provenance_required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Sibling data paragraphs (rollup: the LLM-classified slices
             # are the canonical source of polygon labels / mobility class).
             "mobility_classifications", "avenues_of_approach",
             "key_terrain", "obstacles",
             # Live cougaar data the map render consumes directly so it
             # can fire in parallel with the sibling writer LLM calls.
             "entities:mobility_corridor", "entities:key_terrain", "entities:river", "entities:bridge", "entities:obstacle", "map:config", "documents",
             "entities:civil",
             "map:state",
             # Upstream products contributing map overlays (per
             # consumes_artifacts: WEM trafficability modifiers,
             # TEM terrain effects, CCM per-vehicle class, LOS observation).
             "upstream:WEM", "upstream:TEM",
             "upstream:CCM", "upstream:LOS",
         ]},
        # map_artifact_id paragraph removed — combined_obstacle_overlay_map
        # (shape:"map") already carries the rendered PNG + map_overlays
        # metadata. A separate string field was redundant and unfillable by
        # the writer (the LLM has no way to know the geo-agent M-#### id),
        # which produced "Not reported" + a stranded RENDERED MAP heading
        # below the figure.
        # Text `legend` paragraph removed — the rendered map JPG carries
        # the doctrinal legend (mobility hatches / AA chevron / key-terrain
        # K-glyph / obstacle symbols / phase line / boundary) in-frame via
        # MapCartographicChrome. A prose paragraph after the figure
        # duplicated information already on the map.
        ],
    "subtleties": [
        "Integrates ALL impediments: built-up areas, slope, soils, vegetation, hydrology + obstacles. Distinct from cross-country mobility overlay.",
        "Collaborative effort across the staff: G-2/GEOINT lead + S-6 LOS comms input + CBRN officer chemical-agent terrain effects.",
        "Mobility classifications are RELATIVE, not absolute. Force-size + formation matter — `force_type` in the header is the declared assumption.",
        "Obstacles are only effective if covered by observation and fields of fire.",
        "Weather is a TIME-VARYING modifier. Cite WEM artifact_id; MCOO valid for a specific time window.",
        "Graphic conventions: AA arrows = friendly/blue, threat/red, neutral/black; key terrain = purple 'K' in circle/curve; hydrology = blue; restricted terrain = green single-hatched diagonals; severely-restricted terrain = green cross-hatched diagonals; urban = black X-pattern; obstacles = black symbols. Red is reserved for THREAT (AAs), NEVER for terrain.",
        "MCOO carries TERRAIN, OBSTACLES, AAs, KEY TERRAIN — and nothing else. Unit positions live on the Threat Overlay (current) and SITEMP (templated). Engagement areas and templated unit graphics belong on SITEMP, not MCOO."],
    "hard_rules": [
        "Never invent terrain features — cite the retrieval set's terrain entities and stated passages.",
        "Mobility classifications must be force-type-declared in header.",
        "Obstacle tactical_effect must be from OBSTACLE_EFFECT_ENUM.",
        "Mobility class must be from MOBILITY_CLASS_ENUM.",
        "Cite WEM artifact_id when trafficability has been weather-modified.",
        "No unit positions on the MCOO. If the analyst asks for 'where the enemy is' on this product, the correct product is Threat Overlay (current) or SITEMP (templated).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Terrain primitives: get_terrain()",
        "Weather modifier: list_project_docs(filter={type:'WEM'}) then get_project_doc",
        "Map render: render_map(layers=['terrain','units','spatial_overlay'], format='both')",
        "Civil infrastructure (urban variant — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NOGO/SLOWGO — civil annotations and obstacle integration): get_spatial_overlay()",
        "OPORD AO: get_project_doc(tag='OPORD')"],
    "post_emit_summary": "artifact_id, AAs prioritized, key terrain enumerated, mobility classifications summary",
}

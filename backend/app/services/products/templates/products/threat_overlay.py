"""Threat Overlay — Step-3 / §B-18 doctrinal Threat Template (DOCTEMP).

Per ATP 2-01.3 §4 + §B-18 the Threat Overlay is the doctrinal threat
template for the operation: formation-relative depiction of how the
threat force is doctrinally arrayed, generic-terrain (no MGRS), no
friendly C2, no scenario-specific catalog pickups. The Step-4 SITEMP
downstream adjusts this template onto OE-specific terrain (MGRS-
positioned, per-COA).

This artifact OWNS the forward BP belt centerline AS DATA — published
as a generic-terrain LineString in the forward_bp_belt paragraph_field,
consumed by the SITEMP at per-COA template time (the SITEMP picks BP
catalog ids from scenario.TERRAIN.battle_positions and reads geometry
from the catalog; this threat-template artifact authors the doctrinal
centerline that the catalog entries are arrayed against).

DESIGN FOLLOWUP — do NOT silently add LLM-emitted polygon overlays.
Hard constraint: no LLM-emitted spatial coordinates anywhere. If real
Threat Overlay overlay layers are desired on the master map, schema-
migrate as follows:

  - forward_bp_belt rows as LineString overlay features (centerline
    polyline + named occupant) BUT ONLY by referencing scenario / catalog
    geometry by id — never writer-emit coordinates.
  - weapon-range rings tied to row_fields[].weapon_range_kilometers as
    range_fan overlays at the unit's MGRS (read from scenario.KG_OOB
    unit catalog by row_fields[].id).
  - collection_nais polygons as named_area_of_interest overlays with
    attrs.source='Threat Overlay' BY REFERENCE to scenario NAI
    catalog.

writer_overlays will then flow through the existing
_push_overlays_to_master_map path under source='Threat Overlay'. The
writer LLM does NOT emit ad-hoc polygon coordinates under any
circumstance.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    ECHELON_ENUM,
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    POSTURE_ENUM,
    POSTURE_LABELS,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Threat Overlay",
    "output_format": "pptx",
    "shape": "row",
    # ------------------------------------------------------------------
    # Map render configuration — doctrinally defines exactly how the
    # Threat Overlay map should look. Every field read by backend
    # tool_render_map → URL primitive to OperationsMapHeadless; frontend
    # has zero Threat-Overlay-specific branches. Per ATP 2-01.3 §4 /
    # §B-18.
    # ------------------------------------------------------------------

    # omt-sitemp basemap: clean cream backdrop, major roads only, so the
    # threat template (battle positions, range fans, NAIs) reads first.
    "map_basemap": "default",

    # Per-product overlay gate. Threat Overlay = doctrinal threat
    # template per ATP 2-01.3 §4 / §B-18 — formation-relative threat
    # disposition WITHOUT terrain/weather adjustment (that's SITEMP,
    # Step 4) and WITHOUT friendly C2 overlays (those belong on
    # friendly products).
    #
    # mil_unit is the FOCAL POINT — identity / size / location /
    # strength PER threat formation per the doctrinal rule.
    "map_overlay_kinds": [
        "mil_unit",
        "key_terrain", "urban_area",
        "threat_objective", "range_fan",
        "battle_position",
    ],

    # Same density as SITEMP — water, light landcover, major roads,
    # labels. NO secondary/tertiary/minor (would clutter the threat
    # template).
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban context + battle positions only. No
    # friendly C2 (boundary/phase line). No NAI/TAI (Step 4 product).
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bp-fill", "mcoo-bp-line",
        "mcoo-points-hit-target",
    ],

    # No topographic contour overlay — Threat Overlay is threat
    # disposition, not terrain analysis. Contours would compete with
    # the range fans and battle position polygons.
    "map_show_topographic_contours": False,

    # Individual threat unit symbols (each formation shown). Per the
    # ATP 2-01.3 rule: identity / size / location / strength annotated
    # PER threat formation, not rolled up.
    "map_cluster_mil_units": False,

    # Compact AA labels — Threat Overlay often shows the threat-side
    # AAs that match the template; compact form keeps the AAs from
    # obscuring the templated battle positions.
    "map_compact_aa_labels": True,

    # Compact legend — Threat Overlay's legend has many weapon-system
    # symbols (range_fan classes, BP types); compact packing leaves
    # more map area.
    "map_compact_legend_labels": True,

    # Engagement-area perspective. The Threat Overlay (IPB Step 3
    # threat template) depicts the threat's doctrinal array including
    # the threat's planned fires plan — so only side=threat EAs from
    # scenario.TERRAIN.engagement_areas_catalog paint here. Blue
    # prospective EAs (US fires plan) do NOT belong on a threat-
    # perspective product.
    "map_engagement_area_perspective": "threat",
    "doctrine": {
        "purpose": (
            "Step-3 / §B-18 doctrinal Threat Template (DOCTEMP) — depicts "
            "how the threat force is doctrinally arrayed for the "
            "operation's defense posture (or offense, depending on the "
            "operation). Formation-relative, generic-terrain, NO MGRS, "
            "NO friendly C2 overlays. Identity / size / doctrinal-"
            "posture / weapon reach annotated PER known threat "
            "formation. Owns the forward BP belt centerline as data, "
            "published in the forward_bp_belt paragraph_field and "
            "consumed by the Step-4 SITEMP at per-COA template time "
            "(the SITEMP picks BP catalog ids from "
            "scenario.TERRAIN.battle_positions and reads geometry from "
            "the catalog; this template authors the doctrinal "
            "centerline the catalog entries are arrayed against). The "
            "Step-4 SITEMP downstream adjusts this template onto "
            "OE-specific terrain (MGRS-positioned, per-COA)."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows ordered by weapon_range_kilometers descending (longest reach first).",
    },
    "order_by": {"field": "weapon_range_kilometers", "direction": "desc"},
    "row_source": "entities:units:hostile",
    "consumes_artifacts": ["MCOO", "DonovianDoctrine"],
    "published_section_title": "Threat Template",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "area_of_interest":   {"source": "session", "view": "header",
                                "required": True,
                                "render_label": "Area of Interest",
                                "default": "{area_of_operations}"},
        "mcoo_artifact_id":   {"source": "upstream:MCOO", "view": "internal",
                                "required": False,
                                "render_label": "MCOO Reference",
                                "depends_on": ["upstream:MCOO"],
                                "guidance": "MCOO this template is drawn over. Soft-required — Threat Template can render standalone, but the analyst-level expectation is MCOO is present"},
        "threat_doctrine_artifact_id": {"source": "document:DonovianDoctrine", "view": "internal",
                                "required": True,
                                "render_label": "Threat Doctrine Reference",
                                "depends_on": ["document:DonovianDoctrine"],
                                "guidance": "Concrete threat-doctrine reference cited via this artifact's depends_on. Non-IDX-26 scenarios rebind the concrete reference at scenario load."},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed fields — populated by handlers/intel_agent.py:_build_skeleton
        # from render_map() output. Hidden from the header k/v table; surface as
        # the <figure> map embed below the header.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "row_fields": {
        "id":                {"source": "entity:id", "view": "internal",
                               "required": True, "provenance_required": True,
                               "render_label": "Unit ID"},
        "identity":          {"source": "entity:name", "view": "published",
                               "required": True, "provenance_required": True,
                               "render_label": "Unit Identity"},
        "size":              {"source": "entity:echelon", "view": "published",
                               "required": True, "provenance_required": True,
                               "render_label": "Echelon", "enum": ECHELON_ENUM},
        "location_mgrs":     {"source": "entity:location_mgrs", "view": "published",
                               "required": True, "provenance_required": True,
                               "render_label": "Location (MGRS)"},
        "strength":          {"source": "entity:strength", "view": "published",
                               "required": False,
                               "render_label": "Strength",
                               "guidance": "Combat-effectiveness assessment from OOB. MECHANICAL — runner short-circuits to the cougaar payload."},
        "posture":           {"source": "entity:size_posture_activity", "view": "published",
                               "required": False,
                               "render_label": "Posture",
                               "enum": POSTURE_ENUM,
                               "enum_labels": POSTURE_LABELS,
                               "guidance": (
                                   "CATEGORICAL BUCKET — value MUST be exactly one of the enum tokens. "
                                   "Map the observed activity to the enum (e.g. 'dug in' -> defending, "
                                   "'displacing rear' -> withdrawing). Posture is the bucket; "
                                   "activity_description is the prose. NEVER copy activity prose verbatim "
                                   "into posture; default to 'operational' only when no more specific bucket applies."
                               )},
        "activity_description": {"source": "entity:size_posture_activity", "view": "published",
                                   "required": True, "provenance_required": True,
                                   "render_label": "Activity",
                                   "guidance": (
                                       "Prose detail of the doctrinal activity for this formation — full sentence "
                                       "with specifics (what / where / when / how). MUST NOT be identical to "
                                       "posture; posture is the one-word categorical bucket, this field is the "
                                       "narrative description."
                                   )},
        "area_of_operations_radius_meters": {"source": "derive:aor_radius_m", "view": "published",
                                               "required": False,
                                               "render_label": "AOR Radius (m)",
                                               "guidance": "MECHANICAL — runner derives from echelon per the runner's echelon-to-AOR lookup. Writer never authors."},
        "weapon_range_kilometers": {"source": "derive:weapon_range_km", "view": "published",
                                      "required": False,
                                      "render_label": "Weapon Range (km)",
                                      "guidance": "MECHANICAL — runner derives from unit class per the runner's class-to-range lookup. Writer never authors."},
        "observation_dtg":   {"source": "entity:doi", "view": "published",
                               "required": True,
                               "render_label": "Observation DTG"},
        "observation_source": {"source": "derive:observation_source", "view": "published",
                                "required": True,
                                "render_label": "Source",
                                "guidance": "MECHANICAL — runner emits the canonical OOB-derived source token. Writer never authors."},
        "parent_unit":       {"source": "entity:parent", "view": "workpaper",
                               "required": False,
                               "render_label": "Parent Unit"},
    },
    "paragraph_fields": [
        # forward BP belt centerline as DATA. Threat Overlay (Step-3
        # DOCTEMP) is the doctrinal authoring surface for the BP belt
        # concept. SITEMP downstream consumes catalog entries from
        # scenario.TERRAIN.battle_positions for per-COA MGRS templating.
        {"name": "forward_bp_belt",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Forward Battle Position Belt",
         "required": True,
         "depends_on": [
             "document:DonovianDoctrine",
             "upstream:MCOO",
         ],
         "guidance": (
             "Per ATP 2-01.3 §B-18 (DOCTEMP doctrinal control measures) and "
             "the scenario's threat-doctrine reference cited via this artifact's "
             "depends_on, the forward BP belt is the doctrinal forward-edge "
             "defensive belt occupied by the threat force's first-echelon "
             "formations. Generic-terrain, formation-relative — describe the "
             "belt's doctrinal centerline (E-W along the forward edge of the "
             "threat-defended sector, oriented per the operation's defended "
             "direction) and list the doctrinal occupants by formation "
             "echelon and BP type (per TC 7-100.2 §3.f simple vs complex BP).\n\n"
             "The Step-4 SITEMP downstream picks per-COA occupants by catalog "
             "id from scenario.TERRAIN.battle_positions and reads MGRS "
             "geometry from the catalog. This template AUTHORS the doctrinal "
             "centerline; the SITEMP CONSUMES it per-COA. No prescriptive "
             "unit lists — describe doctrinal occupant TYPE (e.g. "
             "'first-echelon mechanized / motorized infantry BDE BPs ~10-15 "
             "km forward of the DIV HQ along the forward edge of battle area, "
             "complex BP per TC 7-100.2 §3.f'), and bind to the OOB at "
             "runtime via the catalog-by-id pattern downstream."
         ),
         "item_subfields": [
             {"name": "occupant_formation_echelon", "render_label": "Occupant Formation Echelon",
              "enum": ECHELON_ENUM,
              "provenance_required": True,
              "guidance": "Doctrinal echelon of the formation occupying this belt segment (e.g. BDE for first-echelon BDEs in the forward belt). Cite the threat-doctrine reference section that anchors this echelon assignment."},
             {"name": "occupant_formation_type", "render_label": "Occupant Formation Type",
              "provenance_required": True,
              "guidance": "Doctrinal formation type (e.g. 'mechanized infantry brigade', 'motorized infantry brigade'). Generic — NO scenario-specific designators. The SITEMP downstream binds to the actual OOB unit by catalog id."},
             {"name": "bp_type", "render_label": "BP Type",
              "enum": ["simple", "complex"],
              "provenance_required": True,
              "guidance": "Per TC 7-100.2 §3.f — simple BP (single sector of fire, no internal subdivision) or complex BP (multiple mutually-supporting positions, internal disengagement options). Cite the threat-doctrine reference section."},
             {"name": "default_occupancy", "render_label": "Default Occupancy",
              "enum": ["occupied", "prepared_unoccupied", "deception"],
              "provenance_required": True,
              "guidance": "Doctrinal default occupancy for this belt segment. The Step-4 SITEMP may override per-COA (e.g. a pre-emptive offensive COA -> 'prepared_unoccupied' override on the catalog entry)."},
             {"name": "doctrinal_depth_from_div_hq_kilometers", "render_label": "Doctrinal Depth (km, formation-relative)",
              "provenance_required": True,
              "guidance": "Formation-relative depth of the belt centerline behind the threat-defended forward line, expressed as kilometers forward of the DIV HQ (or rearward of the FLOT, depending on the threat-doctrine reference's framing). Generic-terrain — NO MGRS. The Step-4 SITEMP downstream binds to the OE-specific MGRS via scenario.TERRAIN.battle_positions catalog ids."},
             {"name": "orientation_compass_degrees", "render_label": "Orientation (compass degrees)",
              "provenance_required": True,
              "guidance": "Primary engagement-direction compass bearing of the belt segment (e.g. 180° for a threat defending NORTH of LD facing SOUTH). Doctrinal — derived from the operation's defended direction per the threat-doctrine reference."},
             {"name": "scenario_catalog_id_hint", "render_label": "Scenario Catalog ID (hint, optional)",
              "required": False,
              "guidance": "OPTIONAL hint to the downstream SITEMP — the scenario.TERRAIN.battle_positions catalog id this doctrinal belt entry corresponds to. EMITTED ONLY when the scenario fixture has been authored and the catalog id is known at template-authoring time. The SITEMP downstream may also pick catalog ids directly without this hint — both paths converge on the same scenario.TERRAIN.battle_positions geometry."},
             {"name": "rationale", "render_label": "Doctrinal Rationale",
              "provenance_required": True,
              "guidance": "Short doctrinal rationale citing the threat-doctrine reference section that anchors this belt segment (e.g. 'first-echelon BDE positioned forward to canalize attacker into the prepared kill zone covered by the second-echelon counter-attack reserve in depth')."},
         ]},
        # Map paragraph_field — renderer auto-renders + auto-captions.
        {"name": "threat_template_map",
         "view": "published",
         "shape": "map",
         "render_label": "Threat Template",
         "required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             "entities:units",
             "map:state",
             "anchors",
             "upstream:MCOO",
             "document:DonovianDoctrine",
         ]},
        {"name": "collection_nais",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Collection NAIs / TAIs",
         "required": False,
         "guidance": (
             "Optional NAI/TAI overlay tied to the doctrinal threat template — "
             "collection focused on confirming/denying the doctrinal occupancy of "
             "the forward BP belt or on maintaining custody of high-value formations. "
             "Richer per-COA NAI/DP/event-template plans live on the Step-4 SITEMP "
             "/ Event Template."
         ),
         "item_subfields": [
             # The LLM has zero business emitting spatial coordinates.
             # NAIs/TAIs reference scenario.TERRAIN.named_areas_of_interest
             # by id; the backend reads polygon from the catalog row at
             # render time. Same catalog-reference pattern as SITEMP
             # engagement_areas + battle_positions (situation_template.py
             # line 751 "PICK FROM THE SEEDED CATALOG — NEVER INVENT
             # POLYGONS"). Polygon subfield removed.
             {"name": "id", "render_label": "NAI/TAI ID",
              "depends_on": ["map:state"],
              "guidance": (
                  "MUST be an existing id from "
                  "scenario.TERRAIN.named_areas_of_interest (NAIs) or "
                  "scenario.TERRAIN.target_areas_of_interest (TAIs) — "
                  "the catalog enumerates every NAI/TAI the scenario "
                  "defines. NEVER invent a label like 'NAI 1'; if a "
                  "needed area isn't in the catalog, that's a "
                  "scenario-catalog gap to escalate, not a writer-time "
                  "fabrication."
              )},
             {"name": "kind", "render_label": "Kind",
              "enum": ["NAI", "TAI"]},
             {"name": "tied_to_unit_id", "render_label": "Tied to Threat Formation",
              "required": False,
              "guidance": "row_fields[].id of the threat formation this NAI/TAI is focused on; blank if AOI-wide"},
             {"name": "watching_for", "render_label": "Watching For",
              "provenance_required": True,
              "guidance": "indicator collected against (movement / signature / change in posture)"}]},
    ],
    "subtleties": [
        "Threat Overlay is the Step-3 / §B-18 doctrinal Threat Template (DOCTEMP). The Step-4 SITEMP downstream adjusts this template onto OE-specific terrain (MGRS-positioned, per-COA).",
        "Identity + size + doctrinal posture + weapon reach annotated per known threat formation.",
        "Drawn ON the MCOO base — the two are tied.",
        "forward_bp_belt is the doctrinal AUTHORING surface for the BP belt concept. The SITEMP consumes scenario.TERRAIN.battle_positions catalog entries (per the catalog-by-id pattern already proven for NAIs / threat_objectives) and reads MGRS from the catalog. This artifact authors the doctrinal centerline; the catalog entries are arrayed against it.",
        "Row source `kg_units_active` filters to currently-active threat formations; DESTROYED / DEFEATED entities excluded at row-source level (renderer strikes through retained entries).",
        "Priority weighting: rows ordered by `weapon_range_kilometers desc` (longest-reach first) per order_by, surfacing highest-priority formations at the top.",
        "Weapon range rings are a visual element; cite the threat-OOB source.",
        "Optional collection_nais paragraph carries NAI/TAI graphics focused on confirming or maintaining custody of the doctrinal threat template. Per-COA NAI/DP plans belong on SITEMP."],
    "hard_rules": [
        "Never invent unit identities — kg-sourced.",
        "Never claim observation_dtg without KG basis.",
        "Every analytical field carries _provenance.",
        "DEFEATED / DESTROYED entities are filtered by row_source; if intentionally retained, the renderer strikes them through — do not invent a separate `status` field at the schema level.",
        "forward_bp_belt is FORMATION-RELATIVE — describe the belt's doctrinal centerline and occupant TYPE (echelon + formation type), NOT scenario-specific unit designators. The Step-4 SITEMP downstream binds to scenario.TERRAIN.battle_positions catalog ids for MGRS geometry.",
        "Threat doctrine binding is via this artifact's depends_on — concrete tag-named ref. Non-IDX-26 scenarios rebind the concrete reference at scenario load.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Threat structure (OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Recent activity: get_recent_intel(window_hours=24, types=['report','engagement','imagery'])",
        "Threat OOB reference: get_project_doc(tag='OOB')",
        "Threat doctrine (anchors the doctrinal belt centerline and occupant types — concrete tag-named ref): get_project_doc(tag='DonovianDoctrine')",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ): get_spatial_overlay()",
        "Phased concept of operations: get_phases() — current phase + decisive point + phase objectives",
        "Latest FRAGO: list_project_docs(filter={type:'FRAGO'})",
        "MCOO base: list_project_docs(filter={type:'MCOO'})",
        "Map render: render_map(layers=['terrain','units','spatial_overlay'], format='both')"],
    "post_emit_summary": "artifact_id, threat formation count, top 3 by weapon_range_kilometers, forward_bp_belt segment count",
}

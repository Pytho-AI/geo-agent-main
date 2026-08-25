"""Decision Support Template (DST) + matrix — ATP 2-01.3 Step 4 para 6-72 + Fig 6-14.

Per para 6-72: "The DST provides the commander with a structured basis for
deploying fires, maneuver, and jamming assets and for reducing the enemy's
defensive capability with these assets. Simply stated, it provides commanders
with the specific points on the battlefield where they will be required to
make decisions regarding the employment of assets. These decisions can be
keyed to phase lines, events on the ground, or to specific enemy actions."

Per para 6-71 the DST is built from the completed Event Template + Event
Matrix (this product's upstream). Together with the Information Collection
Matrix it forms the Step-4 IPOE consolidation layer between SITEMP/Threat COA Statement and
the OPORD's collection tasking (Annex L).

The DST is a graphic + a matrix per Fig 6-14 — both render together on this
product (template = graphic overlay, matrix = paragraph_field).

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Decision Support Template",
    "output_format": "pptx",
    "shape": "structured",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines exactly how the
    # Decision Support Template map should look. Per ATP 5-0 / ATP
    # 2-01.3 fig 6-14. Frontend has zero DST-specific branches.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. DST = friendly axes + DPs + NAIs +
    # key time-phase lines.
    "map_overlay_kinds": [
        "axis_of_advance", "decision_point",
        "named_area_of_interest", "objective",
        "phase_line", "boundary",
        "engagement_area",
        "key_terrain",
    ],

    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban + boundary framework, phase lines, NAI/TAI
    # (decision points sit on / next to NAIs). Same set as Event
    # Template — DST is the decision-side companion to TEM's NAI/DP grid.
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-pl-line",
        "mcoo-nai-line", "mcoo-tai-line",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,
    "doctrine": {
        "purpose": (
            "Step-4 IPOE: structured basis the commander uses to deploy fires, "
            "maneuver, and jamming assets and to reduce the enemy's defensive "
            "capability with those assets. Provides the commander with the "
            "specific points on the battlefield where they will be required to "
            "make decisions regarding the employment of assets. Decisions can be "
            "keyed to phase lines, events on the ground, or to specific enemy "
            "actions. Built off the Event Template + Matrix." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Decision points ordered by trigger time (earliest first), then "
            "by NAI ID within the same time-phase line."
        ),
    },
    "consumes_artifacts": ["Event Template", "SITEMP", "Threat COA Statement", "MCOO"],
    "header_fields": {
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "event_template_artifact_id": {"source": "upstream:Event Template", "view": "internal",
                                         "required": False,
                                         "render_label": "Event Template Reference",
                                         "depends_on": ["upstream:Event Template"],
                                         "guidance": (
                                             "Upstream Event Template + Matrix — the DST "
                                             "is built from its NAIs and indicators."
                                         )},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal",
                                "required": False,
                                "render_label": "Threat COA Statement Reference",
                                "depends_on": ["upstream:Threat COA Statement"],
                                "guidance": "Parent Threat COA Statement the DST is keyed to."},
        "sitemp_artifact_ids": {"source": "upstream:SITEMP", "view": "internal",
                                  "required": False,
                                  "render_label": "SITEMP References",
                                  "depends_on": ["upstream:SITEMP"],
                                  "guidance": (
                                      "Comma-separated SITEMP artifact_ids the DST DPs "
                                      "anchor to. Each DP's trigger_NAI typically traces "
                                      "back to a SITEMP NAI."
                                  )},
        "mcoo_artifact_id":   {"source": "upstream:MCOO", "view": "internal",
                                "required": False,
                                "render_label": "MCOO Reference",
                                "depends_on": ["upstream:MCOO"],
                                "guidance": "Terrain basis the DST graphic is drawn over."},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed — DST is map-bearing (Fig 6-14 left panel = graphic).
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # ATP 5-0 / ATP 2-01.3: DST is the graphic plot of decision points +
        # NAIs + TAIs + phase lines overlaid on terrain. The matrix companion
        # (DSM) tabulates the same DPs textually; this is the graphic.
        {"name": "decision_support_map",
         "view": "published",
         "shape": "map",
         "render_label": "Decision Support Template",
         "required": True,
         "provenance_required": True,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — DPs/NAIs/TAIs/phase lines/boundaries/axes,
             # phased timeline, OOB for friendly axis context.
             "map:state",
             "anchors",
             "entities:units",
             # Upstream products (consumes_artifacts) — the DPs/TAIs the
             # analyst chose live in Event Template + SITEMP + Threat COA Statement;
             # MCOO provides terrain backdrop.
             "upstream:Event Template", "upstream:SITEMP",
             "upstream:Threat COA Statement", "upstream:MCOO",
         ]},
        {"name": "decision_points",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Decision Points",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Commander decision points — derive ONE row per entry in the "
             "scenario fixture DP catalog (DP-1 through DP-5). DPs are "
             "FRIENDLY commander decisions triggered BY enemy activity — "
             "NEVER write an enemy decision into decision_text "
             "(e.g. 'Commit 604 TANK BDE from armored reserve' is the "
             "enemy's decision, not the friendly commander's). The "
             "friendly_decision field in the DP catalog is the canonical "
             "source for decision_text."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "DP ID",
              "guidance": "Copy verbatim from DP catalog: DP-1, DP-2, DP-3, DP-4, DP-5."},
             {"name": "location_mgrs", "render_label": "Location (MGRS)",
              "provenance_required": True,
              "guidance": (
                  "MGRS of the linked NAI (look up DP catalog's "
                  "linked_nais → NAI catalog mgrs)."
              )},
             {"name": "trigger_NAI", "render_label": "Trigger NAI",
              "provenance_required": True,
              "guidance": (
                 "Copy verbatim from DP catalog `linked_nais` (e.g. "
                 "'NAI-VALGA, NAI-PIKASILLA'). Comma-separated string, "
                 "NOT a JSON list literal."
              )},
             {"name": "trigger_event", "render_label": "Trigger Event",
              "provenance_required": True,
              "guidance": (
                 "Copy verbatim from DP catalog `triggering_indicator`. "
                 "Describes the ENEMY activity at the linked NAI(s) that "
                 "fires the friendly commander decision."
              )},
             {"name": "decision_text", "render_label": "Decision",
              "guidance": (
                 "Copy verbatim from DP catalog `friendly_decision`. "
                 "MUST be a FRIENDLY commander decision (V Corps / "
                 "1st ID / 1st AD / 1st CAV / etc.) — NEVER an enemy "
                 "decision. If the DP catalog says 'Commit 1st ID main "
                 "effort to Valga penetration', write that verbatim."
              )},
             {"name": "options", "render_label": "Options",
              "guidance": (
                 "Copy verbatim from DP catalog `options` (pipe-separated). "
                 "Typically 2-3 friendly options per ATP 5-0."
              )},
             {"name": "effect_on_friendly_COA", "render_label": "Effect on Friendly COA",
              "provenance_required": True,
              "depends_on": ["upstream:Threat COA Statement"],
              "guidance": (
                 "Per-option effect on friendly COA success/risk. Derive "
                 "from DP catalog options + Threat COA Statement's distinguishing "
                 "characteristics. Example: 'Option A reinforces Valga "
                 "main effort but exposes AA2 flank | Option B preserves "
                 "1st AD for branch sequel'."
              )},
             {"name": "latest_time", "render_label": "Latest Time",
              "guidance": (
                 "Copy verbatim from DP catalog `ltiov` (e.g. 'H+24', "
                 "'D+3 0600Z', 'D+20')."
              )},
             {"name": "assets_employed", "render_label": "Assets Employed",
              "guidance": (
                 "Friendly units the DP commits — extract from the DP "
                 "catalog `friendly_decision` (e.g. '1st Infantry Division', "
                 "'1st Armored Division', 'Corps reserve / 1st CAV'). "
                 "Comma-separated."
              )},
         ]},
        {"name": "associated_indicators",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Associated Indicators",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Indicators (from the upstream Event Matrix) that trigger the "
             "DST decision points. Decisions can be keyed to specific enemy "
             "actions — those actions are the indicators."
         ),
         "item_subfields": [
             {"name": "indicator", "render_label": "Indicator",
              "provenance_required": True,
              "guidance": (
                 "Indicator phrasing (analyst-named OE-specific). Same "
                 "phrasing as the upstream Event Matrix indicator column."
              )},
             {"name": "nai_id", "render_label": "NAI",
              "guidance": "NAI where the indicator is observed."},
             {"name": "fires_dp_id", "render_label": "Fires DP",
              "guidance": "DP ID this indicator triggers (cross-reference to decision_points[].id)."},
         ]},
        {"name": "time_phase_markers",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Time-Phase Markers",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Time-phase lines / markers the DST is keyed to. Aligns with "
             "the upstream Event Template's TPLs."
         ),
         "item_subfields": [
             {"name": "label", "render_label": "Label",
              "guidance": "H-hour-relative label, e.g. 'H-24', 'H+0', 'H+6'."},
             {"name": "geometry", "render_label": "Geometry",
              "provenance_required": True,
              "guidance": "Phase-line geometry (MGRS line or GeoJSON)."},
             {"name": "associated_dps", "render_label": "Associated DPs",
              "guidance": "DP IDs keyed to this TPL (comma-separated)."},
         ]},
        # Map IS the `decision_support_map` shape:"map" field above; the
        # exporter auto-renders + auto-captions it from map_overlays[].
        # A separate string field asking the writer to type the M-#### was
        # redundant noise — the writer had no handle on the runner-assigned
        # map UUID and would emit apology prose into the slot.
    ],
    "subtleties": [
        "The DST provides commanders with the specific points on the battlefield where they will be required to make decisions regarding the employment of assets. DST is decision-centric, NOT NAI-centric — NAIs are the trigger, the DP is the product.",
        "Decisions can be keyed to three trigger types: (a) phase lines, (b) events on the ground, (c) specific enemy actions. Each DP's trigger_event names which of these (and the trigger_NAI may be empty when the trigger is a pure phase-line crossing).",
        "The DST and the Information Collection Matrix are SIBLING products downstream of the Event Template + Matrix — both build off the event template's NAI + indicator set.",
        "DST is a commander's product, NOT an intelligence product per se — built by the staff (G-2/S-2 + G-3/S-3 collaboration) but the OUTPUT is the commander's decision aid.",
        "The artifact is two-part: the DST graphic (left panel — map with DPs / TPLs) + the DST matrix (right panel — DP × trigger × decision × options × effect). This product renders both.",
        "Options per DP are typically 2-3 (rarely more) — the commander chooses between options, so the option set must be manageable in the decision moment.",
        "effect_on_friendly_COA is the commander's decision criterion — it's what makes the DP an actual decision point and not a status report.",
        "Every DP cites the trigger NAI / event from the upstream Event Template + Matrix in _provenance.",
    ],
    "hard_rules": [
        "Every DP MUST cite an upstream NAI or event in _provenance — DPs are not invented; they are derived from the Event Template's NAI / indicator set.",
        "Every DP's trigger_event MUST name one of the three: phase_line_crossing / ground_event / enemy_action (or use this verbatim phrasing in the trigger description).",
        "Every DP MUST have ≥ 2 options — a 'decision' with one option is not a decision.",
        "Every DP MUST have effect_on_friendly_COA populated — without it the DP carries no decision criterion.",
        "associated_indicators rows MUST reference both an NAI ID and a DP ID present in the same artifact (cross-reference integrity).",
        "Time-phase markers MUST align with the upstream Event Template's TPLs (labels and geometries match).",
        "Every analytical claim cites source in _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream Event Template + Matrix: list_project_docs(filter={type:'Event Template'}) then get_project_doc(tag=<latest>)",
        "Per-COA SITEMPs (NAI source): list_project_docs(filter={type:'SITEMP'})",
        "Parent Threat COA Statement: list_project_docs(filter={type:'Threat COA Statement'}) then get_project_doc(tag=<latest>)",
        "MCOO base terrain: list_project_docs(filter={type:'MCOO'})",
        "OPORD context (friendly COA, commander's intent): get_project_doc(tag='OPORD')",
        "Phased concept of operations (PRIMARY — decision points anchored to phase windows): get_phases() — current phase + decisive point + phase objectives",
        "Operations overlay control measures (DPs anchored to NAIs/TAIs/EAs/OBJ/phase lines from the overlay): get_spatial_overlay()",
        "Map render: render_map(layers=['terrain','decision_points','time_phase_lines','spatial_overlay'], format='both')",
    ],
    "post_emit_summary": "artifact_id, DP count, decision-asset coverage (fires / maneuver / jamming), latest trigger time",
}

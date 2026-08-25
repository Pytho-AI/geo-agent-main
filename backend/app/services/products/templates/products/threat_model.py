"""Threat Model — ATP 2-01.3 Step 3 (Evaluate the Threat) paras 5-45 – 5-46.

The doctrinal Step-3 threat description. Per para 5-45 the threat model
consists of three activities: (1) convert threat doctrine / patterns of
operations to graphics — the threat template (DOCTEMP); (2) describe the
threat's preferred tactics, options, and peculiarities; (3) identify HVTs.
This schema renders all three as one product per Fig 5-4.

Per the 2026-05-13 product audit, the Threat Template graphic (formerly a
standalone product) is folded into the Threat Model as the
threat_template_graphic section — it is sub-component (1) of the three
activities per para 5-45, not a separate deliverable. The HVT list remains
standalone (HVTL — Fig 5-7) since it is also referenced by the targeting
chain downstream of the Threat Model.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    ECHELON_ENUM,
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    HEADER_SPATIAL_OVERLAY_BBOX,
    HEADER_SPATIAL_OVERLAY_MAP_ID,
    HEADER_SPATIAL_OVERLAY_URL,
    OBSTACLE_EFFECT_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "Threat Model",
    "output_format": "docx",
    "shape": "structured",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines exactly how the
    # Threat Model (doctrinal enemy template) map should look. Per ATP
    # 2-01.3 §5-45 / fig 5-2. Frontend has zero THREAT_MODEL-specific
    # branches; every behavior here flows through URL primitives.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. Threat Model = threat template (graphic +
    # tactics + HVT-ID), idealized doctrinal placement (NOT current
    # locations — that's Threat Overlay). THREAT-SIDE ONLY: axis_of_advance,
    # direction_of_attack, route, and friendly command-post markers are
    # explicitly EXCLUDED (those are friendly-maneuver concepts and would
    # be a doctrinal violation on the Threat Model template). avenue_of_
    # approach is permitted because per IPB Step 2 it is side-neutral
    # terrain analysis. mil_unit IS included so doctrinal templated units
    # render as symbols (see Threat Overlay / SITEMP for the same pattern).
    "map_overlay_kinds": [
        "avenue_of_approach", "key_terrain",
        "threat_objective", "range_fan",
        "battle_position", "engagement_area",
        "named_area_of_interest",
        "phase_line", "boundary",
        "mil_unit",
    ],

    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban context, battle positions (the template's
    # core graphic), boundary framework. No NAI/TAI (Event Template
    # concept).
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bp-fill", "mcoo-bp-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-points-hit-target",
    ],

    # No contour overlay; Threat Model is doctrinal placement, terrain
    # is implicit context only.
    "map_show_topographic_contours": False,

    # Individual enemy unit symbols — the template shows each templated
    # echelon (BTG / Mtzd Coy / etc.) at its doctrinal position.
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": True,
    "map_compact_legend_labels": True,
    # Landscape: the threat-model product carries the Fig 5-2 / 5-3
    # organizational charts and the capabilities reference table alongside
    # the tactics/options/peculiarities narrative. Org charts read poorly in
    # portrait DOCX; landscape gives the tables and graphics room to breathe
    # without truncating echelon labels.
    "doctrine": {
        "purpose": (
            "Step-3 IPOE doctrinal threat description. The threat model is "
            "the analytical tool that feeds Step-4 situation templates "
            "(SITEMP) — it captures how the threat conducts operations in "
            "ideal conditions, with no terrain constraints. Three components: "
            "(1) threat template / DOCTEMP (separate artifact, referenced "
            "here); (2) preferred tactics, options, and peculiarities "
            "narrative; (3) HVT identification (separate HVTL artifact, "
            "referenced here). Feeds the downstream Threat Template, Threat "
            "Capability Statement, SITEMP, Threat COA Statement, and HVTL products." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Sections in order: threat overview → organizational structure → "
            "preferred tactics → options (branches/sequels) → peculiarities → "
            "threat-template + HVT cross-references. No row priority."
        ),
    },
    # Step-3 threat description (multi-day cumulative). Tier 1 BOTH
    # rollups (SIGSUM / HUMINTSUM / OSIR — trend baseline) AND atomics
    # (TACELINT / HUMINT IIR — current-window tactics signals), plus BIIR
    # per-person for key-personality identification.
    "consumes_artifacts": ["SIGSUM", "HUMINTSUM", "OSIR", "DonovianDoctrine"],
    # SLA narrowing — Threat Model authors org structure + tactics +
    # peculiarities from the OOB + doctrine. Narrow each upstream to
    # its analytical body.
    "default_data_source_filter": {
        "upstream:SIGSUM":              ["rows", "header"],
        "upstream:HUMINTSUM":           ["rows", "header"],
        "upstream:OSIR":                ["rows", "header"],
        "document:DonovianDoctrine":    ["sections"],
    },
    "header_fields": {
        "threat_actor":       {"source": "session", "view": "header",
                                 "required": True,
                                 "render_label": "Threat Actor",
                                 "default": "Donovian Armed Forces",
                                 "guidance": (
                                    "Named threat the model describes "
                                    "(e.g., 'Donovian 25th Motor Rifle "
                                    "Division', 'Free Pavlovian Resistance "
                                    "Front'). Drives which OOB / doctrine "
                                    "reference the intel agent pulls. "
                                    "Writer derives the specific echelon "
                                    "from get_oob() / OPORD threat "
                                    "characterization when available; "
                                    "default keeps the field populated "
                                    "until that resolution occurs."
                                 )},
        "threat_type":        {"source": "analytical", "view": "header",
                                 "required": True,
                                 "render_label": "Threat Type",
                                 "enum": ["regular", "irregular", "hybrid"],
                                 "default": "regular",
                                 "guidance": (
                                    "Regular = state-organized force similar "
                                    "to friendly; irregular = non-state / "
                                    "guerrilla / criminal; hybrid = "
                                    "combination employed in concert. Drives "
                                    "which organizational-chart variant "
                                    "applies (regular vs irregular). Writer "
                                    "MUST override the 'regular' default "
                                    "when the threat actor is non-state or "
                                    "hybrid per OOB / sociocultural context."
                                 )},
        "phase":              HEADER_PHASE,
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "area_of_interest":   {"source": "session", "view": "header",
                                 "required": True,
                                 "render_label": "Area of Interest",
                                 "default": "{area_of_operations}"},
        # operation_type drives which threat_template_graphic variant is
        # rendered. Per ATP 2-01.3 para 5-67: templates are scaled per type of
        # operation (offense / defense / ambush / etc.). One Threat Model per
        # operation_type; analysts produce multiple Threat Models when the
        # threat is expected to employ multiple operation types.
        "operation_type":     {"source": "session", "view": "header",
                                 "required": True,
                                 "render_label": "Operation Type",
                                 "enum": ["offense", "defense", "ambush",
                                           "raid", "movement", "kidnapping",
                                           "clandestine_sustainment",
                                           "insurgent_attack", "other"],
                                 "default": "offense",
                                 "guidance": (
                                    "Threat templates are scaled per type of "
                                    "operation. Drives which template variant "
                                    "is rendered in threat_template_graphic. "
                                    "Writer MUST override the 'offense' "
                                    "default when get_phases() / OPORD "
                                    "anticipates the threat in a defensive, "
                                    "ambush, raid, or movement posture in "
                                    "the current phase."
                                 )},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Map embed fields for the threat_template_graphic — generic-terrain
        # render (no OE overlay) per ATP 2-01.3 para 5-46. Same pipeline as
        # SITEMP / Threat Overlay / MCOO; product_type='Threat Model' hint
        # selects the generic-terrain layers in render_map dispatch.
        "spatial_overlay_url":    HEADER_SPATIAL_OVERLAY_URL,
        "spatial_overlay_map_id": HEADER_SPATIAL_OVERLAY_MAP_ID,
        "spatial_overlay_bbox":   HEADER_SPATIAL_OVERLAY_BBOX,
    },
    "paragraph_fields": [
        # BLUF — commander-readable bottom line, rendered FIRST so the
        # Threat Model (and its folded Threat Template graphic) leads with
        # the analytical judgment before the doctrinal-template map, the org
        # chart, and the tactics drilldown. Per ATP 2-01.3 para 5-45 this
        # product describes how the threat fights in ideal conditions; the
        # BLUF states who the threat is, the decisive way they fight in this
        # operation_type, and the one peculiarity / capability the friendly
        # commander must plan against — not a re-narration of the sections
        # below.
        {"name": "bluf",
         "view": "published",
         "shape": "string",
         "render_label": "Bottom Line Up Front (BLUF)",
         "required": True,
         "provenance_required": True,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "Commander-readable bottom line of this Threat Model, stated UP "
            "FRONT before the doctrinal-template map and the "
            "tactics/options/peculiarities detail. Two to four sentences. "
            "Lead with the threat identity (header.threat_actor / "
            "threat_type) and the operation_type this model covers, then the "
            "decisive way the threat fights it per its doctrine (the "
            "signature tactic and doctrinal objective), and close with the "
            "single peculiarity or capability the friendly commander must "
            "plan against. Synthesize from threat_overview / preferred_tactics "
            "/ peculiarities / capabilities_summary — do NOT re-narrate them "
            "row-by-row. This is the commander's bottom-line judgment, not a "
            "staff product. Cite OOB / DonovianDoctrine basis in _provenance."
         )},
        # ATP 2-01.3 §B-18: the threat model includes a doctrinal template
        # plot showing the threat's standard scheme of maneuver. Map comes
        # after the narrative overview but before the tactics drilldown.
        {"name": "doctrinal_template_map",
         "view": "published",
         "shape": "map",
         "render_label": "Doctrinal Template",
         "required": False,
         "layers": ["terrain", "units", "spatial_overlay"],
         "depends_on": [
             # Live data — threat unit positions, terrain anchors (key
             # terrain / AAs the doctrinal template plots over), control
             # measures (boundaries / phase lines).
             "entities:units",
             "map:state",
             "map:state",
             # Upstream SIGINT/HUMINT/OSINT roll-ups inform doctrinal
             # template positioning (consumes_artifacts subset).
             "upstream:SIGSUM", "upstream:HUMINTSUM", "upstream:OSIR",
         ]},
        {"name": "threat_overview",
         "view": "published",
         "shape": "string",
         "render_label": "Threat Overview",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "Two-to-four sentence overview of the threat: who they are, "
            "their strategic objective in the AO, regular/irregular/hybrid "
            "classification rationale. Cite OOB / sociocultural DB / OPORD "
            "intel annex."
         )},
        {"name": "organizational_structure",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Organizational Structure",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "Composition + command relationships (regular threat org vs "
            "irregular threat org). Two-levels-down resolution. One row per "
            "echelon node — the renderer composes the hierarchy graphically "
            "when the parent_id chain is intact."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "Unit ID",
              "guidance": "stable id (e.g., U-001 or kg_id from the order of battle data)"},
             {"name": "designation", "render_label": "Designation",
              "provenance_required": True,
              "guidance": "name/designation per OOB (e.g., '25th Motor Rifle Division')"},
             {"name": "echelon", "render_label": "Echelon",
              "enum": ECHELON_ENUM,
              "guidance": "doctrinal echelon ordinal — drives the two-levels-down rule"},
             {"name": "parent_id", "render_label": "Parent Unit ID",
              "required": False,
              "guidance": "id of the parent node — wires the org chart hierarchy"},
             {"name": "primary_systems", "render_label": "Primary Systems",
              "required": False,
              "guidance": "key equipment / weapon systems (e.g., 'T-72B MBT, BMP-3 IFV'). Cite NGIC / OOB."},
             {"name": "role", "render_label": "Doctrinal Role",
              "required": False,
              "guidance": "doctrinal task (e.g., 'main effort maneuver', 'fire support', 'security force')"}]},
        {"name": "preferred_tactics",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Preferred Tactics",
         "required": True,
         "provenance_required": True,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "Description of the threat's preferred tactics (attack / defend / "
            "reinforce / retrograde / ambush / raid / etc.). One row per "
            "tactic the threat is known to favor. The description is required "
            "even when the tactics are graphically depicted in the threat "
            "template — it lets the model become more than 'a snapshot in "
            "time' and supports mental war gaming. Donovian Armed Forces follow "
            "the OPFOR / TC 7-100 doctrinal model — express tactics in those "
            "terms (zone construct disruption/battle/support, defeat by fires, "
            "antitank dominance, integrated air defense, counter-attack from "
            "depth, reconnaissance-fires complex, maskirovka) per the "
            "DonovianDoctrine reference."
         ),
         "item_subfields": [
             {"name": "tactic", "render_label": "Tactic",
              "provenance_required": True,
              "guidance": "doctrinal name (e.g., 'meeting engagement', 'baited ambush', 'hasty defense')"},
             {"name": "trigger_conditions", "render_label": "Trigger Conditions",
              "provenance_required": True,
              "guidance": "when the threat prefers this tactic (terrain / tempo / force ratio / phase). Cite threat-OOB source."},
             {"name": "execution_pattern", "render_label": "Execution Pattern",
              "provenance_required": True,
              "guidance": "how the threat executes the tactic — formations, spacing, sequencing. Pulls from observed patterns + doctrinal references."}]},
        {"name": "options",
         "view": "published",
         "shape": "dict",
         "render_label": "Options — Branches and Sequels",
         "required": True,
         "provenance_required": True,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "Branches and sequels available to the threat. Branches = "
            "alternatives built into the basic plan (used primarily for "
            "changing deployments or accepting/declining combat). Sequels = "
            "follow-on operations contingent on victory, defeat, or "
            "stalemate. List both. Branches and sequels for Donovian forces "
            "MUST match the doctrinal decision triggers in section 4 of the "
            "DonovianDoctrine reference (lateral TANK BDE reinforcement on "
            "breach, delay to Voru wetland, retrograde to Tartu with "
            "destruction of bridges/LOCs)."
         ),
         "subfields": [
             "branches_if_succeeding",
             "branches_if_failing",
             "sequels_on_victory",
             "sequels_on_defeat",
             "sequels_on_stalemate"]},
        {"name": "peculiarities",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Peculiarities",
         "required": False,
         "depends_on": ["document:DonovianDoctrine"],
         "guidance": (
            "Threat-specific peculiarities — strengths and vulnerabilities "
            "the friendly commander should know. Examples: 'threat fuel "
            "shortages', 'recently completed defensive training', 'lacks "
            "armor-piercing 120mm rounds', 'heavy reliance on information "
            "warfare to control populace', 'SPF well-trained in hasty "
            "ambushes'. List actual observed items, not generic examples. "
            "For Donovian forces, derive at least 3 entries from the "
            "DonovianDoctrine reference section 8 signature OPFOR behaviors "
            "(massed counter-preparation fires, reconnaissance-fires complex "
            "closure inside friendly OODA loop, 4-6h lateral TANK BDE "
            "reinforcement timing, decoy positions, centralized C2)."
         ),
         "item_subfields": [
             {"name": "category", "render_label": "Category",
              "enum": ["strength", "vulnerability", "cultural", "logistical", "doctrinal_constraint"],
              "guidance": "classification of the peculiarity"},
             {"name": "description", "render_label": "Description",
              "provenance_required": True,
              "guidance": "one-sentence description of the peculiarity — cite OOB / SITREP / recent intel basis"},
             {"name": "friendly_implication", "render_label": "Friendly Implication",
              "required": False,
              "guidance": "how the friendly commander exploits or mitigates this peculiarity. Optional."}]},
        # Threat Template graphic — folded from former standalone "Threat
        # Template" product per 2026-05-13 audit. Per ATP 2-01.3 para 5-45 it
        # is one of the three Threat Model activities (graphic + tactics +
        # HVT-ID). Depicts how the threat deploys on GENERIC terrain per its
        # doctrine, BEFORE OE-specific terrain adjustment. SITEMP downstream
        # adjusts the same units to actual OE-adjusted MCOO basemap.
        {"name": "threat_template_graphic",
         "view": "published",
         "shape": "dict",
         "render_label": "Threat Template Graphic (DOCTEMP — Generic Terrain)",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "ATP 2-01.3 para 5-46 + 5-67: graphical depiction of how the "
            "threat would deploy on GENERIC terrain per its doctrine, before "
            "OE-specific terrain adjustment. Components per para 5-46: (1) "
            "location of all threat units two levels down, (2) distance / "
            "time between threat forces conducting the operation, (3) "
            "graphic control measures (unit frontages, unit depths, "
            "boundaries, engagement areas, obstacles). The operation_type "
            "header field discriminates the variant (offense / defense / "
            "ambush / etc.). Two-levels-down rule: a BDE-scope template "
            "depicts CO/PLT; a BN-scope template depicts PLT/specialty team."
         ),
         "subfields": ["templated_units",
                        "doctrinal_control_measures",
                        "distances_and_timings",
                        "doctrinal_objective",
                        "scale_note",
                        "map_artifact_id"],
         "subfield_guidance": {
             "templated_units": (
                 "Threat units arrayed per doctrine on GENERIC terrain "
                 "(two-levels-down resolution). Each: id, designation, "
                 "echelon, doctrinal_position (formation-relative — NOT "
                 "MGRS; SITEMP downstream adjusts to actual coordinates), "
                 "doctrinal frontage_km + depth_km (the BASIS the SITEMP "
                 "deviation calc downstream measures against), primary_systems. "
                 "Cite OOB / NGIC source for doctrinal frontages/depths."
             ),
             "doctrinal_control_measures": (
                 "Boundaries, engagement areas, obstacles, phase lines, "
                 "objectives, axes of advance, battle positions, NAIs — "
                 "positioned RELATIVE TO THE FORMATION, not OE-specific "
                 "MGRS. Each: id, kind, doctrinal_position, tactical_effect "
                 f"(for obstacles: one of {OBSTACLE_EFFECT_ENUM})."
             ),
             "distances_and_timings": (
                 "REQUIRED, NEVER 'Not reported' / 'N/A' / empty. Spacing "
                 "between threat forces — security zone forward of main "
                 "body by X km / Y hours; reserve at Z km depth ready to "
                 "commit in H+N; march-column vehicle intervals. Each: "
                 "relationship, distance_km, time_h, doctrinal_source "
                 "(NGIC / OOB threat-doctrine document + paragraph). For "
                 "Donovian forces use the DonovianDoctrine reference "
                 "defaults: security zone 15 km / 1-2 h forward of main "
                 "body; division reserve 10-15 km depth ready in H+2; "
                 "lateral TANK BDE reinforcement 4-6 h; corps support "
                 "zone 30-40 km depth. Emit at least three rows so the "
                 "doctrinal-template plot has timing anchors to label."
             ),
             "doctrinal_objective": (
                 "What the threat seeks per its doctrine in this operation_type "
                 "(e.g., 'destroy lead friendly battalion forward of FEBA to "
                 "deny operational reach'; 'fix friendly mounted force in "
                 "defile to enable second-echelon flanking attack'). Cite "
                 "threat-OOB source."
             ),
             "scale_note": (
                 "Scope (BDE-scope / BN-scope / etc.) and resolution (two "
                 "levels down). Required so downstream SITEMP knows the "
                 "echelon basis when deriving the OE-adjusted variant."
             ),
             "map_artifact_id": (
                 "geo-agent render_map(layers=['terrain_generic',"
                 "'doctrinal_units','doctrinal_control_measures'], "
                 "format='both') output id; landscape PNG on GENERIC "
                 "(stylized or muted-OE) basemap so the doctrinal "
                 "disposition is isolated from terrain effects."
             ),
         }},
        {"name": "threat_capability_statement_artifact_id",
         "view": "published",
         "shape": "string",
         "render_label": "Threat Capability Statement Reference",
         "required": False,
         "guidance": (
            "artifact_id of the downstream Threat Capability Statement that "
            "enumerates the threat's capabilities by warfighting function. "
            "Optional — referenced when the capability statement has been "
            "drafted; otherwise the writer surfaces a capability summary "
            "inline below."
         )},
        {"name": "hvtl_artifact_id",
         "view": "published",
         "shape": "string",
         "render_label": "HVT List Reference",
         "required": False,
         "guidance": (
            "artifact_id of the Step-3 HVT list — separate HVTL artifact. "
            "Soft-required: HVT identification is the third component of the "
            "threat model, but the HVTL is often produced after the threat "
            "model and referenced back."
         )},
        {"name": "capabilities_summary",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Capability Summary by Warfighting Function",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "One-row-per-warfighting-function summary of what the threat is "
            "capable of doing — C2, Movement and Maneuver, Intelligence, "
            "Fires, Sustainment, Protection, Information / Cyber-EW. Brief; "
            "the full per-WfF detail lives in the separate Threat Capability "
            "Statement product. This summary is what makes the threat model "
            "standalone-readable."
         ),
         "item_subfields": [
             {"name": "warfighting_function", "render_label": "Warfighting Function",
              "enum": ["command_and_control", "movement_and_maneuver",
                        "intelligence", "fires", "sustainment", "protection",
                        "information_cyber_electromagnetic"],
              "guidance": "warfighting function categories"},
             {"name": "capability_summary", "render_label": "Capability Summary",
              "provenance_required": True,
              "guidance": (
                "one-to-two sentence summary of the threat's strength + "
                "posture for this WfF. Cite OOB / NGIC source. The full "
                "per-capability detail (strength × posture × effects-on-"
                "friendly × indicators) is in the Threat Capability Statement."
              )}]}],
    "subtleties": [
        "The threat model has three components per ATP 2-01.3 para 5-45: threat template graphic, tactics/options/peculiarities narrative, HVT identification. The template graphic is rendered HERE as threat_template_graphic (folded from former standalone product); the HVT list is still standalone (HVTL) since it feeds the downstream targeting chain.",
        "Threat model is BEFORE OE-specific terrain adjustment. The template depicts how the threat operates when not constrained by OE effects. SITEMP (Step 4) is the OE-adjusted product downstream — it re-renders the same templated_units on the actual OE-adjusted MCOO basemap.",
        "Two-levels-down rule carries into both the org chart AND the threat_template_graphic.templated_units: a BDE-scope threat model depicts companies/platoons.",
        "Templates are scaled per operation type per para 5-67 (offense / defense / ambush / personnel movement / clandestine sustainment / kidnapping). header.operation_type drives the variant; multiple threat models per threat are expected when the threat is anticipated to employ multiple operation types.",
        "Hybrid threats employ regular and irregular capabilities in concert — the threat_type=hybrid case still requires a classification of WHICH components are regular vs irregular.",
        "Peculiarities are observed-specific, not generic. Example: 'threat forces lack sufficient armor-piercing 120-millimeter tank rounds' — that level of specificity. Generic 'has insufficient logistics' is not useful.",
        "Sequencing: Threat Model (incl. graphic) → Threat Capability Statement → SITEMP → Threat COA Statement.",
        "Doctrinal control measures in threat_template_graphic are POSITIONED RELATIVE TO THE FORMATION — formation-relative descriptions, NOT MGRS. MGRS coordinates are SITEMP-level.",
        "Every analytical claim (capability summary, peculiarity, tactic execution pattern, templated unit frontage/depth, doctrinal control measure position) cites source in _provenance."],
    "hard_rules": [
        "Never invent threat doctrine. Preferred tactics, options, peculiarities, templated_units (frontage/depth/doctrinal_position), doctrinal_control_measures, and distances_and_timings cite OOB / NGIC / DonovianDoctrine / observed-pattern intel basis in _provenance.",
        "Donovian threat actor uses the OPFOR / TC 7-100 doctrinal model — preferred_tactics, options, and peculiarities are framed in those terms (zone construct, defeat by fires, antitank dominance, integrated air defense, counter-attack from depth, reconnaissance-fires complex, maskirovka). Generic enemy-action language ('economy-of-force defense', 'armored counterattack', 'massed indirect fires' alone) is insufficient — the doctrinal substance comes from get_project_doc(tag='DonovianDoctrine'). Doctrinal frontages, depths, and distances for templated_units MUST match the doctrinal values in that reference (BDE ~10-15 km frontage; division reserve ~10-15 km depth; corps support zone ~30-40 km depth; counter-attack timing 4-6 hours).",
        "threat_type ∈ {regular, irregular, hybrid} — no other values.",
        "operation_type drives threat_template_graphic variant — must be one of the enum values.",
        "organizational_structure AND threat_template_graphic.templated_units depict two-levels-down (BDE model → CO/PLT; DIV model → BN/CO).",
        "Generic-terrain only in threat_template_graphic: doctrinal_position fields are formation-relative descriptions, NOT MGRS. OE-specific MGRS positions belong on SITEMP downstream.",
        "threat_template_graphic must include all three doctrinal components: (1) templated_units, (2) distances_and_timings, (3) doctrinal_control_measures. Schema enforces via required-true on the subfields.",
        "Capabilities summary covers the warfighting functions; the full per-capability detail lives in the Threat Capability Statement artifact.",
        "Every analytical field carries _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Threat structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Threat OOB reference: get_project_doc(tag='OOB')",
        "Threat doctrine (REQUIRED — anchors preferred_tactics, options, peculiarities, threat_template_graphic, and capabilities_summary): get_project_doc(tag='DonovianDoctrine'). Donovian Armed Forces follow the OPFOR / TC 7-100 doctrinal model. preferred_tactics MUST express the zone construct (disruption / battle / support), defeat by fires, antitank dominance, integrated air defense, counter-attack from depth, reconnaissance-fires complex, maskirovka. options MUST follow the doctrinal decision triggers in section 4. peculiarities MUST reflect the signature OPFOR behaviors in section 8 (centralized C2, decoy positions, lateral reinforcement timing).",
        "Sociocultural / political context (irregular + hybrid — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Recent threat activity (patterns of operations): get_recent_intel(window_hours=72, types=['report','engagement','imagery'])",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ — threat-model geometry references): get_spatial_overlay()",
        "Phased concept of operations (phased enemy adaptation): get_phases() — current phase + decisive point + phase objectives",
        "OPORD intel annex / Annex L for adversary characterization: get_project_doc(tag='OPORD'), list_project_docs(filter={type:'ANNEX_L_INTEL'})",
        "Prior threat-model artifact (regen): list_project_docs(filter={type:'Threat Model'})"],
    "post_emit_summary": "artifact_id, threat_actor, threat_type, peculiarity count, capability-summary WfF coverage",
}

"""Collateral Damage Estimate (CDE) — JP 3-60 Ch. III §C para 3.c(6); FM 3-60 paras 2-59 – 2-61.

CDE is the joint-force methodology for estimating unintentional or incidental
injury or damage to persons or objects that would not be lawful military
targets in the circumstances ruling at the time (JP 3-60 GL-5 'collateral
damage' definition). It assists the commander in weighing collateral risk
against military necessity and is a required input to the Phase 3 Capabilities
Analysis step of the joint targeting cycle (JP 3-60 Ch. III §C para 3.c(6)),
required for ALL TARGETS that have a weaponeering solution per JP 3-60 Ch. III
§D para 3.d(6)(a)(3): 'A CDE for lethal effects and a CEE for lethal and
nonlethal effects are required for all targets that have a weaponeering
solution.'

Doctrinal acronym: CDE appears verbatim in JP 3-60 (acronym list at JP 3-60
glossary GL-1 'CDE — collateral damage estimation'), in FM 3-60 (acronym list
at FM 3-60 glossary 'CDE — collateral damage estimation'), and throughout
both pubs.

The CDE-1 → CDE-5 progression (informally 'CDE levels' or 'CDE phases') is
defined in CJCSI 3160.01D, (U) No-Strike and the Collateral Damage Estimation
Methodology — a CUI publication not consumed by this agent. Per JP 3-60 Ch. II
para 4.d and Ch. III §C para 3.c(6), CDE is normally performed by trained and
certified personnel. The agent's role here is to PRE-FILL the inputs the
certified CDE analyst needs — target identity, aimpoint, weapon proposal,
collateral-environment characterization, NSL proximity — and to capture the
CDE OUTPUTS (recommended CDE level, mitigation measures, approval-authority
routing) after the certified analyst completes the methodology. Per JP 3-60
Ch. III §C para 3.c(6), 'The commander assumes additional risk if trained and
certified personnel are not used.'

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

# CDE level enum — CDE-1 through CDE-5 progression per CJCSI 3160.01D
# methodology (referenced by JP 3-60 III-13 §(e) note and FM 3-60 para 2-59
# note). Token form matches doctrinal display ('CDE-1', 'CDE-2', etc.) as a
# canonical string. The pub itself is CUI; only the level identifier and the
# fact-of-progression are doctrinally citeable here.
CDE_LEVEL_ENUM = [
    "cde_1",
    "cde_2",
    "cde_3",
    "cde_4",
    "cde_5",
]

CDE_LEVEL_LABELS = {
    "cde_1": "CDE-1",
    "cde_2": "CDE-2",
    "cde_3": "CDE-3",
    "cde_4": "CDE-4",
    "cde_5": "CDE-5",
}

# Doctrinal collateral-risk concern categories per JP 3-60 Ch. II para 4.d and
# Ch. III §C para 3.c(6): 'characterize the level and extent of collateral
# risk to the commander (e.g., the adverse consequences to diplomatic and
# public relations or the effects on civilian infrastructure [including
# electronic networks]).' Plus JP 3-60 App. A §5.b and Ch. I para 8.a(11):
# civilian casualties, civilian property, civil infrastructure, environmental
# harm. CBRN per JP 3-60 Ch. III §C para 3.c(2) and the WMD note at I-16.
COLLATERAL_CONCERN_ENUM = [
    "civilian_casualties",
    "civilian_injury",
    "civilian_property_damage",
    "civilian_infrastructure_damage",
    "electronic_network_effects",
    "environmental_harm",
    "cbrn_release_or_residue",
    "diplomatic_consequences",
    "public_relations_consequences",
    "host_nation_relations",
    "humanitarian_access_disruption",
    "other_collateral_concern",
]

COLLATERAL_CONCERN_LABELS = {
    "civilian_casualties":           "Civilian Casualties",
    "civilian_injury":               "Civilian Injury",
    "civilian_property_damage":      "Civilian Property Damage",
    "civilian_infrastructure_damage": "Civilian Infrastructure Damage",
    "electronic_network_effects":    "Electronic Network Effects",
    "environmental_harm":            "Environmental Harm",
    "cbrn_release_or_residue":       "CBRN Release / Residue",
    "diplomatic_consequences":       "Diplomatic Consequences",
    "public_relations_consequences": "Public Relations Consequences",
    "host_nation_relations":         "Host-Nation Relations",
    "humanitarian_access_disruption": "Humanitarian Access Disruption",
    "other_collateral_concern":      "Other Collateral Concern",
}

# Approval-authority routing — collateral concern severity drives the approval
# echelon per JP 3-60 Ch. I §B para 9.b (Sensitive Targets warrant Presidential
# or SecDef approval) and Ch. III §C para 3.c(6) (sensitive target criteria
# referred to appropriate authority via the sensitive target approval and
# review process).
APPROVAL_AUTHORITY_ENUM = [
    "tactical_commander",
    "component_commander",
    "joint_force_commander",
    "combatant_commander",
    "secdef_under_star",
    "presidential_under_star",
]

APPROVAL_AUTHORITY_LABELS = {
    "tactical_commander":      "Tactical Commander",
    "component_commander":     "Component Commander",
    "joint_force_commander":   "JFC",
    "combatant_commander":     "CCDR",
    "secdef_under_star":       "Secretary of Defense (STAR)",
    "presidential_under_star": "Presidential (STAR)",
}

SPEC = {
    "name": "CDE",
    "output_format": "docx",
    "shape": "header_only",
    # ------------------------------------------------------------------
    # Map render configuration. Doctrinally defines the CDE map. CDE is
    # a per-target product — map shows the aimpoint + collateral context
    # (urban areas, restricted zones, no-strike list polygons). Frontend
    # has zero CDE-specific branches.
    # ------------------------------------------------------------------

    "map_basemap": "default",

    # Per-product overlay gate. CDE = collateral damage estimate.
    # Target + collateral context (urban areas, restricted zones).
    "map_overlay_kinds": [
        "threat_objective", "objective",
        "engagement_area",
        "urban_area",  # collateral context
        "restricted_op_zone",
        "boundary",
    ],

    # Full road density at target scale — analyst needs to read roads
    # around the aimpoint to evaluate evacuation routes, secondary
    # damage from blast on adjacent infrastructure.
    "map_basemap_layer_visibility": [
        "omt-water", "omt-waterway",
        "omt-landcover-wood", "omt-landcover-grass", "omt-landuse-urban",
        "omt-road-motorway", "omt-road-trunk", "omt-road-primary",
        "omt-road-secondary", "omt-road-tertiary",
        "omt-road-name", "omt-place-label",
        "place-label-maaamet", "place-label-english",
    ],

    # Doctrinal layers: urban (collateral risk), boundary, points.
    "map_doctrinal_layer_visibility": [
        "mcoo-urban-fill", "mcoo-urban-line",
        "mcoo-bnd-halo", "mcoo-bnd-line", "mcoo-bnd-line-flot",
        "mcoo-points-hit-target",
    ],

    "map_show_topographic_contours": False,
    # CDE is single-target. No mil-units typically; cluster=False so
    # if one is rendered (e.g. assigned weaponeering platform) it
    # shows individually.
    "map_cluster_mil_units": False,
    "map_compact_aa_labels": False,
    # Single-target product — full doctrinal legend (target ID,
    # CDE level callouts, no-strike-list reasons) needs the room.
    "map_compact_legend_labels": False,
    "doctrine": {
        "purpose": (
            "Per-target collateral damage estimate. Captures the inputs a certified "
            "CDE analyst needs to apply the CDE-1 → CDE-5 progression, the resulting "
            "CDE level recommendation, the mitigation measures (weaponeering, fuzing, "
            "time-of-day, attack azimuth, etc.) that bring the estimate within the "
            "commander's risk tolerance, and the approval-authority routing that the "
            "resulting level requires. Targets with associated collateral damage "
            "concerns expected to exceed CCDR- or JFC-approved sensitive target "
            "criteria are referred to the appropriate authority using the sensitive "
            "target approval and review process.\n\n"
            "Pytho's role is to PRE-FILL the estimate-input structure — target "
            "identity, aimpoint, NSL proximity, collateral environment "
            "characterization, civilian-activity pattern-of-life, proposed weapon — "
            "BEFORE the certified analyst completes the CDE-1 → CDE-5 progression. "
            "The final CDE level, casualty estimates, and approval routing are the "
            "OUTPUTS of the certified workflow. The agent does NOT synthesize "
            "numeric casualty estimates." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Single-target product (header_only shape). One CDE per asset-target interaction (each feasible interaction should have first-, second-, and higher-order effects identified).",
    },
    "consumes_artifacts": ["HPTL", "TMP", "NSL", "RTL"],
    # Per-field upstream dep filter — narrow each artifact dep payload
    # to the single-target slice CDE actually consumes. Mirrors HVTL
    # default_data_source_filter pattern. NSL/RTL are filtered by geo
    # radius from the target MGRS (not a full-list dump).
    "default_data_source_filter": {
        "HPTL": {"target_id_filter": "header.target_id"},
        "TMP": {"target_id_filter": "header.target_id"},
        "NSL": {
            "geo_radius_from_mgrs": "header.target_location_mgrs",
            "radius_m": 5000,
        },
        "RTL": {
            "geo_radius_from_mgrs": "header.target_location_mgrs",
            "radius_m": 5000,
        },
    },
    # Map-overlay feeders for the renderer — drive the threat_objective /
    # objective / urban_area / restricted_op_zone / boundary overlays
    # from the bound target identifiers + NSL/RTL/OPORD payloads.
    "map_overlay_feeders": {
        "threat_objective": "header.target_location_mgrs",
        "objective": "header.target_location_mgrs",
        "urban_area": "geo_radius_from_target",
        "restricted_op_zone": "dep.NSL.entities + dep.RTL.entities",
        "boundary": "opord.boundaries",
    },
    # Collateral-environment radius parameter — quantifies the "civilian
    # structures within radius" + NSL/RTL proximity gates above. Default
    # 5km per JP 3-60 Ch. III §C para 3.c(6) Phase-3 capabilities-analysis
    # collateral envelope. Overridable per-engagement.
    "collateral_radius_m": 5000,
    "header_fields": {
        # Session-bound identifiers — the row-derivation dispatcher threads
        # bound target_id / description / MGRS into session args at CDE
        # creation. These NEVER hit the writer LLM — the dispatcher pre-fills
        # them via header_field_defaults_from_bound_target (see SPEC below).
        "target_id":         {"source": "session", "view": "header", "required": True,
                                "render_label": "Target ID",
                                "default_from_bound_target": "kbID",
                                "guidance": "BE / CTID / UID format — the target the CDE is scoped to. Threaded from the bound target via session args; the writer never authors this field."},
        "target_description": {"source": "session", "view": "header", "required": True,
                                 "render_label": "Target Description",
                                 "default_from_bound_target": "name"},
        "target_location_mgrs": {"source": "session", "view": "header", "required": True,
                                   "render_label": "Target Location (MGRS)",
                                   "default_from_bound_target": "location_mgrs"},
        "jdpi_id":           {"source": "upstream:TMP", "view": "header", "required": False,
                                "render_label": "JDPI Reference (TMP)",
                                "depends_on": ["upstream:TMP"],
                                "guidance": "JDPI ID from the upstream TMP when mensuration has been performed. Leaves blank for the IDX 26 TMP-stub case."},
        "dtg":               {**HEADER_DTG, "render_label": "Estimate DTG"},
        "engagement_window_start_dtg": {"source": "session", "view": "header",
                                          "required": False,
                                          "render_label": "Engagement Window Start"},
        "engagement_window_end_dtg":   {"source": "session", "view": "header",
                                          "required": False,
                                          "render_label": "Engagement Window End",
                                          "guidance": (
                                            "When the engagement is scheduled — drives "
                                            "the time-of-day / pattern-of-life inputs "
                                            "('cyclic "
                                            "nature of activity on the reduction of "
                                            "collateral damage — the periods when "
                                            "there may be fewer civilians and other "
                                            "noncombatants in and around the target "
                                            "area')."
                                          )},
        "prepared_by":    HEADER_PREPARED_BY,
        "hptl_artifact_id":  {"source": "upstream:HPTL", "view": "internal", "required": False,
                                "depends_on": ["upstream:HPTL"],
                                "render_label": "HPTL Reference"},
        "tmp_artifact_id":   {"source": "upstream:TMP", "view": "internal", "required": False,
                                "depends_on": ["upstream:TMP"],
                                "render_label": "TMP Reference"},
        "nsl_artifact_id":   {"source": "upstream:NSL", "view": "internal", "required": False,
                                "depends_on": ["upstream:NSL"],
                                "render_label": "NSL Reference"},
        "rtl_artifact_id":   {"source": "upstream:RTL", "view": "internal", "required": False,
                                "depends_on": ["upstream:RTL"],
                                "render_label": "RTL Reference"},
        # IDX 26 stub flag — same pattern as TMP. Numeric collateral thresholds
        # (casualty counts, blast radii, weaponeering tables) are CUI under
        # CJCSI 3160.01D; the agent renders the structure, certified analysts
        # complete the estimate.
        "stub_flag":         {"source": "constant", "view": "header", "required": True,
                                "default": True,
                                "render_label": "IDX 26 STUB",
                                "guidance": (
                                    "IDX 26 STUB per data-provision-requirements §1.B "
                                    "— certified CDE analyst"
                                    "weaponeering tables, and population-density "
                                    "products are not provided. The agent pre-fills "
                                    "the input structure; the certified analyst "
                                    "completes the CDE-1 → CDE-5 progression and "
                                    "records the level + mitigation measures."
                                )},
        "stub_reason":       {"source": "constant", "view": "header", "required": True,
                                "default": (
                                    "CDE methodology workflow (CDE-1 →"
                                    "CDE-5 progression + numeric casualty thresholds) "
                                    "is CUI and requires a trained-and-certified "
                                    "analyst.The agent emits the input-side "
                                    "data sheet for downstream certified completion."
                                )},
        "classification":    HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "target_and_aimpoint",
         "view": "published",
         "shape": "dict",
         "render_label": "Target and Aimpoint",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:TMP",
         ],
         "guidance": (
            "Target identity + aimpoint description. When a TMP exists, copy "
            "target_identity and aimpoint_description forward from the TMP. "
            "function_primary feeds the proportionality analysis ("
            "§4 para (6): 'the concrete and direct military advantage expected to "
            "be gained')."
         ),
         "subfields": ["target_name", "target_type_five_o", "target_function",
                        "aimpoint_description", "structure_type",
                        "structure_hardening", "mobility_class"]},
        {"name": "weapon_proposal",
         "view": "published",
         "shape": "dict",
         "render_label": "Proposed Weapon / Delivery",
         "required": True,
         "provenance_required": True,
         "depends_on": ["upstream:HPTL"],
         "guidance": (
            "Weapon and delivery profile being CDE'd — the asset-target "
            "interaction. The CDE is "
            "weapon-specific; a different weapon = a different CDE. "
            "Copy weapon_system / munition_type / munition_quantity / "
            "fuzing forward from the parent HPTL row weaponeering "
            "recommendation when populated. Only mark "
            "[ANALYST INPUT REQUIRED] when the HPTL row has no "
            "weaponeering data."
         ),
         "subfields": ["weapon_system", "munition_type", "munition_quantity",
                        "fuzing", "attack_azimuth", "release_altitude",
                        "delivery_method", "expected_circular_error_probable"]},
        {"name": "collateral_environment",
         "view": "published",
         "shape": "dict",
         "render_label": "Collateral Environment",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:NSL",
         ],
         "guidance": (
            "Characterization of the collateral environment surrounding the "
            "aimpoint — the inputs to the CDE-1 → CDE-5 progression. "
            "civilian_structures_within_radius lists the nearby civilian / "
            "protected structures by type + standoff distance; "
            "nsl_entities_within_radius lists overlap with the NSL by entity "
            "id (cite nsl_artifact_id parent). population_density / "
            "pattern_of_life / civilian_activity_indicators support the "
            "Cyclic-activity timing analysis."
         ),
         "subfields": ["civilian_structures_within_radius",
                        "nsl_entities_within_radius",
                        "rtl_entities_within_radius",
                        "population_density_estimate",
                        "pattern_of_life_summary",
                        "civilian_activity_indicators",
                        "time_of_day_pattern",
                        "weather_at_engagement_window",
                        "terrain_and_built_environment"]},
        {"name": "estimated_collateral_concerns",
         "view": "published",
         "shape": "dict",
         "render_label": "Estimated Collateral Concerns",
         "required": True,
         "provenance_required": True,
         "guidance": (
            "The categorical concerns the analyst expects to materialize per JP "
            "('characterize the"
            "level and extent of collateral risk to the commander'). "
            "concerns_present is a list of COLLATERAL_CONCERN_ENUM values. "
            "DO NOT synthesize numeric casualty counts — those come from the "
            "certified CDE workflow."
         ),
         "subfields": ["concerns_present",
                        "qualitative_severity_summary",
                        "second_and_higher_order_effects",
                        "infrastructure_dependencies_at_risk",
                        "cbrn_release_risk_note",
                        "environmental_consequence_note"],
         "subfield_specs": {
             "concerns_present": {"enum": COLLATERAL_CONCERN_ENUM,
                                    "enum_labels": COLLATERAL_CONCERN_LABELS,
                                    "shape": "list",
                                    "guidance": (
                                        "concerns_present values MUST be "
                                        "drawn from the COLLATERAL_CONCERN_"
                                        "ENUM tokens verbatim (lowercase "
                                        "snake_case): civilian_casualties, "
                                        "civilian_injury, civilian_property_"
                                        "damage, civilian_infrastructure_"
                                        "damage, electronic_network_effects, "
                                        "environmental_harm, cbrn_release_"
                                        "or_residue, diplomatic_consequences, "
                                        "public_relations_consequences, host_"
                                        "nation_relations, humanitarian_"
                                        "access_disruption, other_collateral_"
                                        "concern. Reject any other token."
                                    )},
             "cbrn_release_risk_note": {
                 "stub_when_no_data": True,
                 "default": "[ANALYST INPUT REQUIRED]",
                 "guidance": (
                     "Emit [ANALYST INPUT REQUIRED] if no CBRN-release "
                     "data is available; do NOT emit generic placeholder "
                     "text like 'No significant activity reported'."
                 ),
             },
         }},
        {"name": "cde_level_recommendation",
         "view": "published",
         "shape": "dict",
         "render_label": "CDE Level Recommendation",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "paragraph.collateral_environment",
             "paragraph.estimated_collateral_concerns",
         ],
         "guidance": (
            "OUTPUT of the certified CDE workflow.cde_level "
            "is one of CDE-1 through CDE-5 (CDE_LEVEL_ENUM). When stub_flag = "
            "True, leave cde_level blank — the certified analyst sets it. "
            "rationale references the specific collateral-environment factors "
            "that drove the level. iterative_progression_notes captures the "
            "stepwise CDE-1 → CDE-N reasoning per the methodology."
         ),
         "subfields": ["cde_level",
                        "rationale",
                        "iterative_progression_notes",
                        "analyst_assumptions",
                        "analyst_uncertainties"],
         "subfield_specs": {
             "cde_level": {"enum": CDE_LEVEL_ENUM, "enum_labels": CDE_LEVEL_LABELS},
         }},
        {"name": "mitigation_measures",
         "view": "published",
         "shape": "dict",
         "render_label": "Mitigation Measures",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "paragraph.estimated_collateral_concerns",
             "paragraph.weapon_proposal",
             "upstream:RTL",
         ],
         "guidance": (
            "Concrete measures the targeting team applies to bring the estimate "
            "within the commander's risk tolerance ("
            "CDE/CEE provide mitigation techniques). Weapon downgrade, fuzing "
            "change, attack azimuth, time-of-day shift, warning/leaflet, "
            "evacuation coordination, nonlethal alternative (RTL "
            "'nonlethal_only' branch). Each measure should reduce a named "
            "concern from estimated_collateral_concerns."
         ),
         "subfields": ["weapon_downgrade_or_change",
                        "fuzing_change",
                        "attack_azimuth_change",
                        "engagement_window_shift",
                        "warning_or_evacuation_coordination",
                        "standoff_distance_increase",
                        "nonlethal_alternative_considered",
                        "residual_risk_after_mitigation"],
         "subfield_specs": {
             "nonlethal_alternative_considered": {
                 "stub_when_no_data": True,
                 "default": "[ANALYST INPUT REQUIRED]",
                 "guidance": (
                     "Emit [ANALYST INPUT REQUIRED] if no nonlethal "
                     "alternative was evaluated; do NOT emit generic "
                     "placeholder text."
                 ),
             },
         }},
        {"name": "proportionality_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "Proportionality Assessment",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "paragraph.weapon_proposal",
             "paragraph.estimated_collateral_concerns",
         ],
         "guidance": (
            "Commander's proportionality determination"
            "(proportionality principle: 'the anticipated incidental loss of "
            "life and damage to civilian/protected property resulting from an "
            "attack cannot be excessive in relation to the concrete and direct "
            "military advantage expected to be gained'). expected_military_"
            "advantage is the affirmative side; expected_incidental_harm is the "
            "estimated collateral consequence. proportionality_judgment is the "
            "commander's call (acceptable / unacceptable / referred-up)."
         ),
         "subfields": ["expected_military_advantage",
                        "expected_incidental_harm",
                        "proportionality_judgment",
                        "loac_review_complete",
                        "sja_concurrence",
                        "sja_reviewer_name"]},
        {"name": "approval_routing",
         "view": "published",
         "shape": "dict",
         "render_label": "Approval Routing",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "paragraph.cde_level_recommendation",
             "paragraph.proportionality_assessment",
         ],
         "guidance": (
            "Required approval authority for engagement given the CDE level + "
            "sensitive-target status (targets"
            "exceeding CCDR- or JFC-approved sensitive target criteria are "
            "referred via the STAR process). approval_authority is one of "
            "APPROVAL_AUTHORITY_ENUM. When the target is a sensitive target "
            "or the CDE level triggers the STAR "
            "criterion per the establishing directive, set "
            "star_routing_required = True and route to SecDef / Presidential "
            "."
         ),
         "subfields": ["approval_authority",
                        "star_routing_required",
                        "star_reference_id",
                        "current_status",
                        "approval_dtg",
                        "approving_official_name"],
         "subfield_specs": {
             "approval_authority": {"enum": APPROVAL_AUTHORITY_ENUM,
                                      "enum_labels": APPROVAL_AUTHORITY_LABELS},
         }},
        {"name": "analyst_certification",
         "view": "published",
         "shape": "dict",
         "render_label": "Analyst Certification",
         "required": True,
         # analyst_certification is operator-input, not data-derived,
         # but we keep provenance_required:True for consistency with
         # every other published paragraph_field. The certified analyst
         # fills these downstream; the IDX-26 stub default leaves them
         # marked [ANALYST INPUT REQUIRED].
         "provenance_required": True,
         "guidance": (
            "'CDE/CEE are processes "
            "normally performed by trained and certified personnel. The "
            "commander assumes additional risk if trained and certified "
            "personnel are not used.' Capture the certifying authority and "
            "certification reference. When stub_flag = True, the certified "
            "analyst completes this block downstream."
         ),
         "subfields": ["analyst_name", "analyst_org",
                        "certification_authority",
                        "certification_reference",
                        "certification_expiry",
                        "qc_reviewer_name"]},
        {"name": "post_engagement_reference",
         "view": "workpaper",
         "shape": "dict",
         "render_label": "Post-Engagement CDA Reference",
         "required": False,
         "guidance": (
            "'CDA compares "
            "the CDE conducted in phase 3 (capabilities analysis) to the "
            "actual collateral damage assessment.' Capture the downstream BDA "
            "/ CDA artifact_id once available."
         ),
         "subfields": ["cda_artifact_id", "bda_artifact_id",
                        "actual_collateral_outcome_summary"],
         "subfield_specs": {
             "actual_collateral_outcome_summary": {
                 "stub_when_no_data": True,
                 "default": "[ANALYST INPUT REQUIRED]",
                 "guidance": (
                     "Emit [ANALYST INPUT REQUIRED] if no downstream BDA/"
                     "CDA outcome is available; do NOT emit generic "
                     "placeholder text."
                 ),
             },
         }},
    ],
    "subtleties": [
        "'A CDE for lethal effects and a CEE for lethal and nonlethal effects are required for all targets that have a weaponeering solution.' CDE is a UNIVERSAL gate at Phase 3, not a sensitive-target-only product. This is why CDE is a standalone per-target product and NOT a field on TMP or HPTL — every weaponeered target gets one.",
        "CDE is performed by 'trained and certified personnel. The commander assumes additional risk if trained and certified personnel are not used.' The agent's pre-fill is NOT a substitute for the certified workflow — it is the input-side data sheet.",
        "CDE-1 → CDE-5 progression: the iterative methodology applies a stepwise refinement (initial coarse estimate at CDE-1; progressively more detailed weaponeering / structure / population analysis through CDE-5). The CUI nature of the numeric thresholds means the agent cannot generate the level itself — it captures the level output by the certified analyst.",
        "CDA (Collateral Damage Assessment) ↔ CDE relationship: CDAin Phase 6 (Assess) compares the CDE conducted in Phase 3 to the actual observed collateral outcome. post_engagement_reference holds the back-pointer.",
        "Engagement-phase reaffirmation: 'As changes to the OE may affect an engagement decision, the CID and CDE/CEE processes are conducted prior to target engagement and continue throughout the engagement.' The CDE is not 'done' at Phase 3 — it is re-checked at Phase 5 Engage when conditions change.",
        "NSL / RTL proximity is a primary collateral-environment input. NSL entities within the collateral_environment.civilian_structures_within_radius computed by the geo agent drive the CDE level upward and may trigger the STAR routing. RTL entities introduce restriction-source constraints into the proposed weapon profile.",
        "Thedoctrinal protected-class list is broader than 'civilian humans' — it includes civilian property, civil infrastructure, livestock, environment, civil air, and 'anything that could have a negative effect on military operations.' The COLLATERAL_CONCERN_ENUM covers all these.",
        "Proportionality is the commander's call, not the analyst's.The CDE produces the FACTS (estimated harm + military advantage); the commander makes the JUDGMENT. proportionality_judgment is the named commander's decision per the established target engagement authority.",
        "CDE for nonlethal effects (cyber / EW) uses the parallel CEE (Collateral Effects Estimation) methodology — same general structure, different specific outputs. The term 'collateral effect' includes the broader nonlethal sphere. This product schema focuses on lethal-effects CDE; CEE-only engagements should use the same product with weapon_proposal carrying the nonlethal capability.",
        "Per IDX 26 organizer requirement: every analytical claim cites source. The CDE-level output remains blank under stub_flag = True; the certified analyst sets it downstream.",
    ],
    "hard_rules": [
        "Never synthesize a numeric casualty estimate or population-density count — the casualty / probability thresholds underlying CDE-1 → CDE-5 are CUI. Emit the structural inputs + the certified-analyst output; never fabricate the numbers in between.",
        "cde_level is OUTPUT of the certified workflow. When stub_flag = True, leave cde_level blank (do not invent placeholder levels — the field encodes whether the certified CDE has actually run).",
        "Every weaponeered target requires a CDE. The HPTL row-derivation step that emits a weaponeering solution MUST trigger a CDE artifact production.",
        "When an NSL entity is within the collateral radius, the CDE MUST cite the NSL artifact_id and the specific NSL entity id in nsl_entities_within_radius. NSL deconfliction is a Phase 3 / Phase 5 hard gate ('8. Conflicts with NSL').",
        "When sensitive-target criteria are exceeded, star_routing_required MUST be True and approval_authority MUST be secdef_under_star or presidential_under_star.",
        "Proportionality_judgment is the named-commander's decision, not the analyst's. Capture the approving official_name in approval_routing.",
        "Re-check CDE prior to engagement and continuously throughout. The product is a LIVING artifact — re-emit when collateral environment changes.",
        "Per IDX 26: every analytical claim cites source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Target details + aimpoint: get_target(target_id=<id>); upstream TMP via list_project_docs(filter={type:'TMP'})",
        "Parent HPTL row: list_project_docs(filter={type:'HPTL'}) then get_project_doc(tag=<latest>)",
        "NSL proximity check: list_project_docs(filter={type:'NSL'}) then get_project_doc(tag=<latest>) — query by target_location_mgrs radius",
        "RTL proximity / constraints: list_project_docs(filter={type:'RTL'}) then get_project_doc(tag=<latest>)",
        "Collateral environment (civilian structures, pattern-of-life): get_project_doc(tag='OE Definition') civil-considerations section + render_map(layers=['civilian_structures','population_density'])",
        "Civil considerations (collateral environment — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Sustainment overlay (collateral environment near MTF / Class III/V/VIII / CCP / MCP — sustainment-node proximity drives collateral concern): get_spatial_overlay()",
        "Weather at engagement window: get_environmental(date=<engagement_dtg>) or upstream WEM artifact",
        "OPORD ROE annex + sensitive-target criteria: get_project_doc(tag='OPORD')",
        "Latest FRAGO with collateral-mitigation guidance: list_project_docs(filter={type:'FRAGO'}) then get_project_doc",
        "Prior CDE for the same target (regen / re-check): list_project_docs(filter={type:'CDE'}) then get_project_doc",
        "SJA legal review: get_project_doc(tag='SJA_review') when available",
    ],
    "post_emit_summary": "artifact_id, target_id, recommended cde_level or stub status, count of NSL entities in radius, star_routing_required y/n",
}

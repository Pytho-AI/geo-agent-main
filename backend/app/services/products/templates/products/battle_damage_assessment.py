"""BDA — Battle Damage Assessment — JP 3-60 App. C 3-phase.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    DAMAGE_MECHANISM_ENUM,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    PDA_ARMORED_DAMAGE,
    PDA_BUILDING_DAMAGE,
    PDA_CONFIDENCE,
    PDA_RUNWAY_DAMAGE,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

# Title-case labels for BDA enums. Auto-humanize handles most, but capturing
# them here makes the doctrinal spelling explicit. PDA_CONFIDENCE values are
# rendered in Title Case; building damage uses light/moderate/severe.
_PDA_CONFIDENCE_LABELS = {
    "confirmed": "Confirmed",
    "probable":  "Probable",
    "possible":  "Possible",
}
_PDA_BUILDING_LABELS = {
    "light":    "Light",
    "moderate": "Moderate",
    "severe":   "Severe",
}
_PDA_ARMORED_LABELS = {
    "damaged":  "Damaged",
}
_PDA_RUNWAY_LABELS = {
    "cratered":    "Cratered",
    "cut":         "Cut",
    "interdicted": "Interdicted",
}
_DAMAGE_MECHANISM_LABELS = {
    "blast":         "Blast",
    "fragmentation": "Fragmentation",
    "fire":          "Fire",
}

SPEC = {
    "name": "BDA",
    "output_format": "pptx",
    "shape": "header_only",
    "doctrine": {
        "purpose": (
            "Three-phase battle damage assessment: PDA (physical) → FDA (functional) → "
            "TSDA (target system damage). Plus MEA (munitions effectiveness), CDA "
            "(collateral — required for joint, optional for Army), reattack "
            "recommendation. Per-target / per-engagement-event." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Phases in order: 1 PDA → 2 FDA → 3 TSDA, plus MEA + CDA + reattack. Phases 1 and 2 may be reported concurrently.",
    },
    # BDA is shape=header_only — HVTL row_id_selection_field /
    # selected_<scope>_kg_ids pattern is NOT applicable here (no 214-row
    # pool problem; one BDA artifact per right-clicked target). Document
    # explicitly so the next refactor does not graft HVTL selection
    # knob onto BDA by mistake.
    #
    # Targeting + Tier 1 post-strike imagery exploits. BDA Phase 1
    # (physical damage) pulls IIR (GEOINT) and RECCEXREP imagery.
    "consumes_artifacts": [
        "HPTL", "TMP", "AGM", "TSS",
        "Threat Model", "Threat COA Statement", "Threat Overlay",
        "NSL", "RTL",
    ],
    # Per-field upstream dep filter — narrow every BDA writer prompt to
    # the writer-relevant subsection of each artifact dep payload.
    # Mirrors HVTL pattern.
    "default_data_source_filter": {
        "upstream:HPTL": ["rows"],
        "upstream:TMP": ["header", "jdpi", "desired_effects"],
        "upstream:AGM": ["rows"],
        "upstream:TSS": ["rows"],
        "upstream:Threat Model": ["organizational_structure", "threat_overview"],
        "upstream:NSL": ["rows"],
        "upstream:RTL": ["rows"],
        "document:OPORD": ["desired_effects", "annex_e_roe"],
    },
    # Bound-target session field defaults — the row-derivation dispatcher
    # threads bound target identifiers into session args at BDA creation.
    # These NEVER hit the writer LLM — the dispatcher pre-fills via this
    # block so gaps[] never surfaces them on right-click.
    "header_field_defaults_from_bound_target": {
        "target_number": "kbID",
        "target_description": "name",
        "target_location_mgrs": "location_mgrs",
        "engagement_dtg": "engagement_dtg",
    },
    "header_fields": {
        # Operation type — drives whether CDA paragraph is required.
        # Joint: 4-element CA (BDA + MEA + reattack + CDA) — CDA is mandatory.
        # Army-only: 3-element CA — CDA is optional.
        "operation_type":   {"source": "session", "view": "header", "required": True,
                               "default": "army",
                               "enum": ["joint", "army"],
                               "enum_labels": {"joint": "Joint", "army": "Army"},
                               "render_label": "Operation Type",
                               "guidance": (
                                   "Joint (4-element combat assessment = BDA + "
                                   "MEA + reattack + CDA) or Army-only "
                                   "(3-element, CDA optional). Drives whether "
                                   "collateral_damage_assessment is required."
                               )},
        # Bound-target session identifiers — threaded into session args
        # at BDA creation via header_field_defaults_from_bound_target
        # (see SPEC above). NEVER author by writer LLM.
        "target_number":    {"source": "session", "view": "header", "required": True,
                               "render_label": "Target Number",
                               "default_from_bound_target": "kbID",
                               "guidance": "BE / CTID / UID format. Threaded from the bound target via session args."},
        "target_description": {"source": "session", "view": "header", "required": True,
                                 "render_label": "Target Description",
                                 "default_from_bound_target": "name"},
        "target_location_mgrs": {"source": "session", "view": "header", "required": True,
                                   "render_label": "Target Location (MGRS)",
                                   "default_from_bound_target": "location_mgrs"},
        "engagement_dtg":   {"source": "session", "view": "header", "required": True,
                               "render_label": "Engagement DTG (when struck)",
                               "default_from_bound_target": "engagement_dtg"},
        "acquisition_dtg":  {"source": "session", "view": "header", "required": False,
                               "render_label": "Acquisition DTG"},
        "reporting_dtg":    {**HEADER_DTG, "render_label": "Reporting DTG"},
        "reporting_agency": {"source": "session", "view": "header", "required": True,
                               "render_label": "Reporting Agency"},
        "assessing_analyst": {"source": "session", "view": "header", "required": True,
                                "default": "V Corps G-2 analyst",
                                "render_label": "Assessing Analyst"},
        # Upstream artifact references — full ref-style block matching
        # HVTL lines 149-157. Each entry depends_on its source artifact
        # so the DAG ordering preserves the read-after-write semantics.
        "hptl_artifact_id": {"source": "upstream:HPTL", "view": "internal", "required": False,
                                "render_label": "HPTL Reference",
                                "depends_on": ["upstream:HPTL"]},
        "tmp_artifact_id": {"source": "upstream:TMP", "view": "internal", "required": False,
                               "depends_on": ["upstream:TMP"],
                               "render_label": "Pre-strike JDPI Reference (TMP)"},
        "agm_artifact_id": {"source": "upstream:AGM", "view": "internal", "required": False,
                              "render_label": "AGM Reference",
                              "depends_on": ["upstream:AGM"]},
        "tss_artifact_id": {"source": "upstream:TSS", "view": "internal", "required": False,
                              "render_label": "TSS Reference",
                              "depends_on": ["upstream:TSS"]},
        "threat_model_artifact_id": {"source": "upstream:Threat Model", "view": "internal", "required": False,
                                       "render_label": "Threat Model Reference",
                                       "depends_on": ["upstream:Threat Model"]},
        "threat_coa_statement_artifact_id": {"source": "upstream:Threat COA Statement", "view": "internal", "required": False,
                                              "render_label": "Threat COA Statement Reference",
                                              "depends_on": ["upstream:Threat COA Statement"]},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                         "render_label": "Threat Overlay Reference",
                                         "depends_on": ["upstream:Threat Overlay"]},
        "nsl_artifact_id": {"source": "upstream:NSL", "view": "internal", "required": False,
                              "render_label": "NSL Reference",
                              "depends_on": ["upstream:NSL"]},
        "rtl_artifact_id": {"source": "upstream:RTL", "view": "internal", "required": False,
                              "render_label": "RTL Reference",
                              "depends_on": ["upstream:RTL"]},
        # GRVTY-supplied RECCEXREP fields, threaded in by bda_autofire's
        # _build_autofire_context (the autofire stamps these into the
        # writer's ANALYST CONTEXT block, the writer cites them verbatim
        # in the engagement record + PDA paragraphs). The reccexrep_*
        # fields skip the LLM (source=session, threaded by autofire) so
        # the doctrinal grade + narrative + sensor context never get
        # paraphrased by the writer.
        "reccexrep_target_status": {"source": "session", "view": "header", "required": False,
                                       "render_label": "RECCEXREP Target Status (GRVTY)",
                                       "guidance": "Doctrinal BDA grade from RECCEXREP — DESTROYED / DEGRADED / NO_EFFECT etc. Threaded from the autofire context; never paraphrased."},
        "reccexrep_gentext": {"source": "session", "view": "header", "required": False,
                                 "render_label": "RECCEXREP Narrative (GRVTY)",
                                 "guidance": "Free-text narrative from RECCEXREP. Threaded from the autofire context."},
        "reccexrep_ben": {"source": "session", "view": "header", "required": False,
                              "render_label": "Target BEN (Basic Encyclopedia Number)",
                              "guidance": "RECCEXREP target reference — Basic Encyclopedia Number."},
        "reccexrep_item_name": {"source": "session", "view": "header", "required": False,
                                   "render_label": "RECCEXREP Item Name",
                                   "guidance": "Item nomenclature engaged per RECCEXREP."},
        "reccexrep_mission_platform": {"source": "session", "view": "header", "required": False,
                                          "render_label": "Sensor Platform (RECCEXREP)",
                                          "guidance": "Platform that observed the engagement (RECCEXREP mission_platform_or_type)."},
        "reccexrep_time_on_target": {"source": "session", "view": "header", "required": False,
                                         "render_label": "Time on Target (RECCEXREP)",
                                         "guidance": "Engagement window per RECCEXREP."},
        # GRVTY-supplied imagery analysis from IDXImageIirObservation
        # (verified live 2026-06-11 — GRVTY ships analysis text like
        # 'ENEMY RECON BN STATIONARY WITH DESTROYED EQUIPMENT' here).
        # Threaded inline by bda_autofire via the OBSERVED_ON edge from
        # IDXImageIirItem; never authored by the writer LLM.
        "iir_observation_text": {"source": "session", "view": "header", "required": False,
                                    "render_label": "Imagery Analysis (GRVTY)",
                                    "guidance": "Free-text analyst narrative from IDXImageIirObservation.additionalInfo."},
        "iir_change_significance": {"source": "session", "view": "header", "required": False,
                                       "render_label": "Imagery Change Significance",
                                       "guidance": "NAC (no change) / UNK (unknown) / SC (significant change) per IDXImageIirObservation.imageryChangeSignificance."},
        "iir_oob_type": {"source": "session", "view": "header", "required": False,
                             "render_label": "Imagery OOB Type",
                             "guidance": "OOB classification (e.g. AOB = Aerial Order of Battle) per IIR observation."},
        "iir_ben": {"source": "session", "view": "header", "required": False,
                        "render_label": "IIR Target BEN",
                        "guidance": "Basic Encyclopedia Number from the IIR Item."},
        "iir_target_name": {"source": "session", "view": "header", "required": False,
                                 "render_label": "IIR Target Name"},
        "iir_image_weather": {"source": "session", "view": "header", "required": False,
                                   "render_label": "Image Weather Condition"},
        "iir_image_quality_code": {"source": "session", "view": "header", "required": False,
                                        "render_label": "Image Quality Code"},
        # Imagery URL from IDXImageryReport joined to this RECCEXREP. The
        # exporter's image-embed hook fetches the file via
        # utils.url_fetcher (protocol-agnostic — http/https/file/ftp/s3)
        # and embeds it in the PDA imagery section.
        "imagery_url": {"source": "session", "view": "header", "required": False,
                          "render_label": "Post-strike Imagery URL",
                          "guidance": "IDXImageryReport.imagery_url for the engagement. Exporter fetches + embeds the file in the artifact."},
        "imagery_mission_number": {"source": "session", "view": "header", "required": False,
                                       "render_label": "Imagery Mission Number"},
        "imagery_sensor_position": {"source": "session", "view": "header", "required": False,
                                        "render_label": "Imagery Sensor Position"},
        "prepared_by":   HEADER_PREPARED_BY,
        "classification":   HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "engagement_record",
         "view": "published",
         "shape": "dict",
         "render_label": "Engagement Record",
         "required": True,
         "provenance_required": True,
         "batch_group": "bda_post_strike",
         "depends_on": [
             "upstream:HPTL", "upstream:AGM", "upstream:TMP",
             "entities:marked", "clauses:episodic",
         ],
         "subfields": ["delivery_unit", "delivery_means_weapon_system",
                        "munitions_payload_action", "desired_effect_per_agm"]},
        {"name": "phase_1_physical_damage_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "Phase 1 — PDA (Physical Damage and Change Assessment)",
         "required": True,
         "provenance_required": True,
         "batch_group": "bda_post_strike",
         "depends_on": [
             "upstream:HPTL", "upstream:TMP",
             "clauses:episodic", "map:state",
         ],
         "guidance": (
             "Physical damage quantification. damage_mechanism MUST be exactly one "
             "of the DAMAGE_MECHANISM_ENUM values: 'blast', 'fragmentation', or "
             "'fire' (single lowercase token; no free text like 'Blast/fragmentation.' "
             "— pick the dominant one). Confidence enum: confirmed (≥95%) / probable "
             "(50–94%) / possible (<50%). Use the target-type-specific damage "
             "category and leave the others blank — do NOT cross-mix "
             "building/armored/runway categories on the same row."
         ),
         "subfields": ["observed_or_interpreted_damage",
                        "quantitative_damage_extent",
                        "damage_mechanism",
                        "damage_category_for_buildings",
                        "damage_category_for_armored_vehicles",
                        "damage_category_for_runways",
                        "confidence",
                        "imagery_and_sensor_evidence",
                        "casualty_equipment_destroyed_counts"],
         "subfield_specs": {
             "damage_mechanism":                       {"enum": DAMAGE_MECHANISM_ENUM,
                                                          "enum_labels": _DAMAGE_MECHANISM_LABELS},
             "damage_category_for_buildings":          {"enum": PDA_BUILDING_DAMAGE,
                                                          "enum_labels": _PDA_BUILDING_LABELS},
             "damage_category_for_armored_vehicles":   {"enum": PDA_ARMORED_DAMAGE,
                                                          "enum_labels": _PDA_ARMORED_LABELS},
             "damage_category_for_runways":            {"enum": PDA_RUNWAY_DAMAGE,
                                                          "enum_labels": _PDA_RUNWAY_LABELS},
             "confidence":                              {"enum": PDA_CONFIDENCE,
                                                          "enum_labels": _PDA_CONFIDENCE_LABELS},
         }},
        {"name": "phase_2_functional_damage_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "Phase 2 — FDA (Functional Damage and Change Assessment)",
         "required": True,
         "provenance_required": True,
         "batch_group": "bda_functional",
         "depends_on": [
             "phase_1_physical_damage_assessment",
             "upstream:HPTL", "upstream:Threat Model",
             "clauses:episodic", "entities:units",
         ],
         "guidance": (
             "Effect on target's mission capability. Includes a recovery-time "
             "estimate. Tag temporary vs durable assessments via "
             "temporary_assessment_caveat — confidence is lower the sooner after "
             "the strike."
         ),
         "subfields": ["effect_on_target_mission_capability",
                        "all_source_intelligence_basis",
                        "estimated_recovery_time",
                        "temporary_assessment_caveat"]},
        {"name": "phase_3_target_system_damage_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "Phase 3 — TSDA (Target System Damage Assessment)",
         "required": True,
         "provenance_required": True,
         "batch_group": "bda_functional",
         "depends_on": [
             "phase_1_physical_damage_assessment",
             "upstream:HPTL",
             "upstream:Threat Model",
             "upstream:Threat COA Statement",
             "upstream:Threat Overlay",
             "entities:units",
             "document:OPORD",
         ],
         "guidance": (
             "Aggregate FDAs across the target system plus 2nd/3rd-order effects. "
             "Map to commander's objectives. relatively_permanent_flag marks whether "
             "the system damage persists across the operation."
         ),
         "subfields": ["target_system_scope",
                        "overall_impact_assessment",
                        "subdivision_assessments",
                        "enemy_unit_combat_effectiveness",
                        "relatively_permanent_flag",
                        "mapping_to_commanders_objectives"]},
        {"name": "munitions_effectiveness_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "MEA — Munitions Effectiveness Assessment",
         "required": True,
         "provenance_required": True,
         "batch_group": "bda_post_strike",
         "depends_on": [
             "upstream:AGM", "upstream:TMP", "clauses:episodic",
         ],
         "guidance": (
             "Weapon system + munition effectiveness vs predicted. Recommendations "
             "feed weaponeering / re-attack planning."
         ),
         "subfields": ["weapon_system_effectiveness",
                        "munition_effectiveness",
                        "methodology",
                        "tactics_used",
                        "weapon_delivery_parameters",
                        "recommendations"]},
        {"name": "collateral_damage_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "CDA — Collateral Damage Assessment",
         # Required when operation_type=joint (4-element CA); optional
         # when operation_type=army (3-element CA). Runtime gating
         # honors operation_type header field.
         "required": False,
         "provenance_required": True,
         "depends_on": [
             "upstream:NSL", "upstream:RTL",
             "entities:civil", "map:state",
             "document:OPORD",
         ],
         "guidance": (
             "Required for JOINT combat assessment (4-element CA), optional for "
             "ARMY-only (3-element CA). Always fill in joint context; for Army-only "
             "the writer may emit {'applicability': 'army_only_n_a'} or leave the "
             "dict empty. Drive scope from operation_type header field."
         ),
         "subfields": ["applicability",
                        "effect_on_surrounding_environment",
                        "loac_review",
                        "nsl_rtl_deconfliction"]},
        {"name": "reattack_recommendation",
         "view": "published",
         "shape": "dict",
         "render_label": "Reattack Recommendation",
         "required": False,
         "provenance_required": True,
         "batch_group": "bda_functional",
         "depends_on": [
             "phase_1_physical_damage_assessment",
             "upstream:HPTL", "upstream:TSS", "upstream:AGM",
             "entities:units",
         ],
         "guidance": (
             "Required when PDA confidence is below confirmed OR FDA shows mission "
             "capability not defeated as desired. recommended is boolean; rationale "
             "explains the call. joint_recommendation captures coordinating-component "
             "input when applicable. Drive operation_type gating from header."
         ),
         "subfields": ["recommended", "rationale",
                        "operational_risk_assessment",
                        "risk_mitigation_options",
                        "joint_recommendation"]},
        {"name": "beyond_counts_indicators",
         "view": "workpaper",
         "shape": "dict",
         "render_label": "Beyond-counts Indicators",
         "required": False,
         "batch_group": "bda_post_strike",
         "depends_on": [
             "clauses:episodic", "entities:units",
         ],
         "guidance": (
             "Indirect signals that the strike achieved (or failed) the desired "
             "effect — enemy behavior changes, comms spikes, target hardening / "
             "displacement. Supports the FDA narrative."
         ),
         "subfields": ["targets_moving_or_hardening_response",
                        "enemy_behavior_technique_changes",
                        "comm_efforts_increased",
                        "damage_affecting_combat_effectiveness_as_expected"]}],
    "subtleties": [
        "Three-phase BDA: PDA → FDA → TSDA. Recent joint usage renames to '+Change' semantics — same content, broader definition (damage OR change-of-state).",
        "Combat assessment is Army 3-element = BDA + MEA + reattack; or Joint 4-element = + CDA. The collateral_damage_assessment paragraph applies the joint rule when the operation is joint; for Army-only operations it can carry applicability='army_only_n_a' or remain empty.",
        "PDA confidence: confirmed (≥95%) / probable (50–94%) / possible (<50%). Always exactly one of those three values — not a free-text confidence.",
        "PDA damage categories are TARGET-TYPE-SPECIFIC: buildings (light/moderate/severe), armored vehicles (damaged), runways (cratered/cut/interdicted). Pick the category matching the target_description; leave the others blank.",
        "FDA includes a recovery-time estimate. The temporary_assessment_caveat field flags the inherent uncertainty of an FDA done within hours of the strike.",
        "TSDA aggregates FDAs across the target system plus 2nd/3rd-order effects, and is 'relatively permanent' — judgments that persist across the operation.",
        "Federated BDA — pre-established cross-command partnerships; reporting_agency captures the federated partner when applicable.",
        "Phases 1 and 2 may be reported concurrently in a single BDA product when both are ready.",
        "Every claim cites imagery_id + report_id + sensor_geometry."],
    "hard_rules": [
        "Phase 1 PDA confidence must be confirmed / probable / possible — no other strings.",
        "Damage category per target type (no cross-mixing). Pick the category that matches the bound target class/sidc — armored vehicles -> damage_category_for_armored_vehicles; buildings -> damage_category_for_buildings; runways -> damage_category_for_runways. Leave the other categories blank. Derivation comes from the bound target kg record + the enum definitions in subfield_specs — never enumerate specific platform names.",
        "Cite tmp_artifact_id (pre-strike JDPI from TMP) when available for miss-distance baseline; required when the strike used a coordinate-seeking munition.",
        "CDA is REQUIRED when the operation is joint. It is OPTIONAL for Army-only operations. The runner does not enforce this — the analyst flags applicability.",
        "Never declare a target DEFEATED at PDA alone — that judgment is the FDA/TSDA call.",
        "Every assessment cites source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Engagement record + sensor evidence: get_recent_intel(types=['engagement','imagery'])",
        "Target details: get_target(target_id=<id>)",
        "HPTL parent: list_project_docs(filter={type:'HPTL'}) then get_project_doc",
        "Pre-strike JDPI: list_project_docs(filter={type:'TMP'}) then get_project_doc",
        "Threat OOB (combat effectiveness baseline — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Civil considerations (collateral context — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures + sustainment overlay (target unit context via AO / boundaries / OBJ / EA / axis; sustainment proximity for PDA/FDA/CDA collateral paragraphs — MTF/CCP/Class III/V/VIII): get_spatial_overlay()",
        "OPORD desired effects: get_project_doc(tag='OPORD')"],
    "post_emit_summary": "artifact_id, target_id, PDA confidence + damage category, recovery_time, reattack recommended y/n",
}

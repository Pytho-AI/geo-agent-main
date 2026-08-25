"""CA — Combat Assessment — FM 3-60 paras 2-70 – 2-82; JP 3-60 App. C; CJCSI 3162.02.

Doctrine: 'Combat assessment is the determination of the overall effectiveness of
force employment during military operations' (JP 3-60 + FM 3-60 glossary, 'Also
called CA'). Per FM 3-60 para 2-70, CA elements are BDA + MEA + Reattack
Recommendation (Army 3-element) or those three + CDA (Joint 4-element). Per
the 2026-05-13 product audit, MEA and Reattack Recommendation are CA SECTIONS,
not standalone products: 'The operations officer ... CONDUCTS munitions
effectiveness assessment' (para 2-80) is an activity that gets written up
into CA; the Reattack Recommendation (para 2-82) 'requires a decision' that
is captured as a CA section.

BDA remains a standalone product (per-target / per-engagement; can fire on its
own cycle). CA references BDA artifacts; MEA and RR live INSIDE CA as
per-engagement paragraph_fields plus aggregate rollups.

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

# Army vs Joint framing.
COMBAT_ASSESSMENT_FRAMING_ENUM = ["army_three_element", "joint_four_element"]
_COMBAT_ASSESSMENT_FRAMING_LABELS = {
    "army_three_element":  "Army 3-Element (BDA + MEA + Reattack Recommendation)",
    "joint_four_element":  "Joint 4-Element (BDA + MEA + CDA + Reattack Recommendation)",
}

SPEC = {
    "name": "CA",
    # output_formats matches HVTL's format-resolver iteration contract
    # (line 33-34). The singular output_format field caused HVTL
    # finalize handler to 404 — switching to output_formats list +
    # legacy_formats avoids that.
    "output_formats": ["pptx"],
    "legacy_formats": [],
    "shape": "header_only",
    # Targeting-cycle cadence — V Corps battle rhythm runs the targeting
    # working group on a 24h cycle; CA aggregates one cycle's outcomes.
    "cadence_hours": 24,
    "doctrine": {
        "purpose": (
            "Combat Assessment — the umbrella product that determines the "
            "overall effectiveness of force employment during military "
            "operations. Aggregates the three (Army) or four (Joint) "
            "constituent CA elements — BDA, MEA, Reattack Recommendation "
            "(+ CDA for joint) — against the commander's predetermined "
            "Measures of Effectiveness. Produced at the strategic, "
            "operational, or tactical level. BDA Phase 2 reports may include "
            "CA elements when appropriate; this schema is the formal CA "
            "rollup, distinct from a single BDA report." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Continuous process across the operation. Schema produces a CA "
            "rollup keyed to a reporting period (per targeting cycle, per "
            "ATO/ITO period, or per phase). One CA per reporting period; the "
            "same target may appear across multiple CAs as additional BDA / "
            "MEA refines the assessment."
        ),
    },
    "consumes_artifacts": ["BDA", "AGM", "HPTL"],
    # Per-field upstream dep filter — narrows every CA writer prompt to
    # the writer-relevant subsection of each artifact dep payload.
    # Mirrors HVTL pattern (lines 101-129).
    "default_data_source_filter": {
        "upstream:BDA": [
            "header",
            "engagement_record",
            "phase_1_physical_damage_assessment",
            "phase_2_functional_damage_assessment",
            "phase_3_target_system_damage_assessment",
            "munitions_effectiveness_assessment",
            "collateral_damage_assessment",
            "reattack_recommendation",
        ],
        "upstream:AGM": [
            "measures_of_effectiveness",
            "engagement_records",
            "desired_effects",
        ],
        "upstream:HPTL": ["rows"],
    },
    # Writer-controlled BDA-window selection — list of BDA artifact_ids
    # the CA reporting period covers. Every BDA inside [reporting_period_
    # start, reporting_period_end] is one engagement event. Singleton
    # wave — lands BEFORE per-engagement batched fields. Mirrors HVTL
    # selected_hvt_kg_ids singleton (lines 167-213).
    "row_id_selection_field": "selected_bda_artifact_ids",
    "header_fields": {
        "dtg": {**HEADER_DTG, "render_label": "Reporting DTG"},
        "area_of_operations": {**HEADER_AO},
        # Phase default = Phase I (Penetration) — matches HVTL line 136.
        "phase": {**HEADER_PHASE, "default": "Phase I (Penetration)",
                    "render_label": "Operation Phase"},
        "reporting_period_start": {"source": "computed", "view": "header", "required": True,
                                       "render_label": "Reporting Period Start"},
        "reporting_period_end":   {"source": "computed", "view": "header", "required": True,
                                       "render_label": "Reporting Period End"},
        "framing": {"source": "session", "view": "header", "required": True,
                       "default": "army_three_element",
                       "enum": COMBAT_ASSESSMENT_FRAMING_ENUM,
                       "enum_labels": _COMBAT_ASSESSMENT_FRAMING_LABELS,
                       "render_label": "CA Framing",
                       "depends_on": ["upstream:BDA"],
                       "guidance": (
                           "Army 3-element (BDA + MEA + Reattack Recommendation) "
                           "for Army-only operations; Joint 4-element (+ CDA) "
                           "when the operation is joint. Drives whether the "
                           "collateral_damage_summary paragraph is required."
                       )},
        "prepared_by":   HEADER_PREPARED_BY,
        "classification":   HEADER_CLASSIFICATION,
        # Writer's analytical BDA-window selection — list of BDA
        # artifact_id strings inside [reporting_period_start,
        # reporting_period_end]. The DAG runner uses this list as the
        # per-engagement iteration pool (see row_id_selection_field
        # above). Singleton wave — lands BEFORE the mea_per_engagement
        # + rr_per_engagement batched waves so iteration knows how many
        # entries.
        "selected_bda_artifact_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            "render_label": "Selected BDA Artifact IDs (Reporting Window)",
            "depends_on": [
                "upstream:BDA",
                "upstream:AGM",
                "upstream:HPTL",
            ],
            "guidance": (
                "JSON array of BDA artifact_id strings — every BDA "
                "inside [reporting_period_start, reporting_period_end] "
                "is one engagement event. Read the BDA pool dep, "
                "filter by header.engagement_dtg in window, return the "
                "artifact_id list verbatim. NEVER invent ids; every "
                "entry must verbatim-match a pool entry."
            ),
        },
    },
    "paragraph_fields": [
        {"name": "executive_summary",
         "view": "published",
         "shape": "string",
         "render_label": "Executive Summary",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:OPORD",
             "entities:units",
         ],
         "guidance": (
             "Commander-readable bottom line of the CA. States the overall "
             "effectiveness of force employment during the reporting period, "
             "in terms the commander can act on. Three to five sentences. "
             "Anchored to the targeting objectives + commander's intent."
         )},
        {"name": "engagements_assessed",
         "view": "published",
         # list_of_dicts with item_subfields — matches mea_findings shape
         # so the renderer treats engagements_assessed identically. Each
         # row pairs to its constituent BDA artifact and carries the
         # rollup outcomes (paired-BDA, paired-MEA, RR disposition,
         # MOE status).
         "shape": "list_of_dicts",
         "render_label": "Engagements Assessed",
         "required": True,
         "provenance_required": True,
         "row_count_source": "header.selected_bda_artifact_ids",
         "depends_on": [
             "selected_bda_artifact_ids",
             "upstream:BDA", "upstream:AGM", "upstream:HPTL",
         ],
         "guidance": (
             "One row per engagement event aggregated in this CA. Each row "
             "points to its constituent BDA artifact and carries brief MEA / "
             "RR outcomes. The full per-engagement MEA findings and Reattack "
             "Recommendation detail live in the mea_findings and "
             "reattack_recommendation paragraphs below."
         ),
         "item_subfields": [
             {"name": "target_number", "render_label": "Target Number",
              "guidance": "BE / CTID / UID — verbatim from paired BDA header.target_number"},
             {"name": "target_description", "render_label": "Target Description"},
             {"name": "engagement_dtg", "render_label": "Engagement DTG",
              "source": "kg"},
             {"name": "bda_artifact_id", "render_label": "BDA Artifact ID",
              "source": "upstream:BDA"},
             {"name": "bda_outcome_summary", "render_label": "BDA Outcome Summary",
              "guidance": "1-sentence rollup of paired BDA phase_3_target_system_damage_assessment.overall_impact_assessment"},
             {"name": "mea_outcome_summary", "render_label": "MEA Outcome Summary"},
             {"name": "reattack_disposition", "render_label": "Reattack Disposition",
              "enum": ["reattack", "restrike_modified", "no_reattack", "move_to_new_task"]},
             {"name": "moe_status", "render_label": "MOE Status",
              "guidance": "pulls from paired AGM measures_of_effectiveness"},
         ]},
        # Per-engagement MEA findings (folded from former standalone MEA product
        # per 2026-05-13 audit). FM 3-60 para 2-80: 'The operations officer ...
        # conducts munitions effectiveness assessment.' Six recommendation
        # categories per FM 3-60: methodology, tactics, weapon system, munitions,
        # fuzing, weapon delivery parameters.
        {"name": "mea_findings",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "MEA Findings (Per Engagement)",
         "required": True,
         "provenance_required": True,
         "row_count_source": "header.selected_bda_artifact_ids",
         "depends_on": [
             "selected_bda_artifact_ids",
             "upstream:BDA",
             "upstream:AGM",
         ],
         "guidance": (
             "One row per engagement assessed. Evaluates weapon-system + "
             "munitions effectiveness against the engaged target, comparing "
             "observed effectiveness (drawn from the paired BDA) to "
             "weaponeering-predicted effectiveness from JTC phase 3 "
             "capabilities analysis. Conducted concurrently and interactively "
             "with BDA — not sequentially after it. The six FM 3-60 "
             "recommendation categories (methodology / tactics / weapon system "
             "/ munitions / fuzing / weapon delivery parameters) each get an "
             "explicit field so the targeting working group can act on them. "
             "Primary responsibility splits between staff: operations officer "
             "in coordination with FSE + targeting working group on Army "
             "ops; J-3 / JFE on joint."
         ),
         "item_subfields": [
             {"name": "target_number", "render_label": "Target Number",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "BE / CTID / UID — matches the engagements_assessed row"},
             {"name": "engagement_record", "render_label": "Engagement Record",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Authoritative record of what was delivered (delivery_unit / delivery_means / munition / fuzing / rounds / desired_effect_per_agm). Mirrors paired BDA."},
             {"name": "weaponeering_baseline", "render_label": "Weaponeering Baseline (Predicted)",
              "provenance_required": True,
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Anticipated effectiveness from JTC phase 3 capabilities analysis. Cite the weaponeering tool documented in the paired AGM engagement_record — synthesizing 'predicted' effectiveness without a documented run is not acceptable."},
             {"name": "observed_effectiveness", "render_label": "Observed Effectiveness (Actual)",
              "provenance_required": True,
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Actual effectiveness from the paired BDA (physical + functional damage). Cite BDA artifact_id; MEA does not re-derive damage assessments."},
             {"name": "weapon_system_effectiveness", "render_label": "Weapon System Effectiveness",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Effectiveness of delivery system (platform / fire control / guidance). Distinct from the munition: successful delivery of an ineffective munition vs errant delivery of a normally-effective munition produce different recommendations."},
             {"name": "munition_effectiveness", "render_label": "Munition Effectiveness",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Effectiveness of munition + fuzing against this target type. Separates weapon-vs-target matching from delivery accuracy."},
             {"name": "methodology_and_tactics_assessment", "render_label": "Methodology / Tactics Assessment",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Targeting methodology and tactics used to engage. Planned-vs-executed engagement sequence, deconfliction, tactical-level decisions."},
             {"name": "weapon_delivery_parameters_assessment", "render_label": "Weapon Delivery Parameters Assessment",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Delivery parameters as planned vs actual (release altitude / speed / dive angle / range / time-of-flight / guidance-mode handoff). Envelope-compliance check."},
             {"name": "recommendations", "render_label": "Recommendations",
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "The six FM 3-60 categories — methodology / tactics / weapon system / munitions / fuzing / weapon delivery parameters — each addressed (may be empty when no change is warranted). Plus commander's-guidance recommendations on UBL / RSR / CSR."},
             {"name": "reattack_disposition_input", "render_label": "Input to Reattack Decision",
              "required": False,
              "batch_group": "mea_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "MEA's contribution to the reattack call: whether weapon/munition/tactics/delivery changes alone are likely to achieve the desired effect on reengagement. Feeds the reattack_recommendation paragraph below."},
         ]},
        # Per-engagement Reattack Recommendation (folded from former standalone
        # RR product per 2026-05-13 audit). FM 3-60 para 2-82: RR 'requires a
        # decision' that merges BDA + MEA against predetermined MOEs. Signed by
        # intel officer + FSCOORD + ops officer per the Army split.
        {"name": "reattack_recommendation",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Reattack Recommendation (Per Engagement)",
         "required": False,
         "row_count_source": "header.selected_bda_artifact_ids",
         "depends_on": [
             "selected_bda_artifact_ids",
             "upstream:BDA",
         ],
         "guidance": (
             "One row per engagement where a reattack decision is being "
             "captured. Merges the paired BDA (what was achieved) with the "
             "paired mea_findings (how the engagement performed) against the "
             "predetermined MOEs developed at JTC start. Per FM 3-60 para "
             "2-82, generally NOT made on BDA Phase 1 alone — exception is a "
             "confirmed miss, where reattack may be authorized based on target "
             "priority + weapon availability + law of war + ROE. Decision is "
             "signed by the intelligence officer in conjunction with the "
             "FSCOORD or deputy FSCOORD and the operations officer."
         ),
         "item_subfields": [
             {"name": "target_number", "render_label": "Target Number",
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "BE / CTID / UID — matches the engagements_assessed row"},
             {"name": "decision_inputs", "render_label": "Decision Inputs (BDA + MEA Summary)",
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Bottom-line claims from paired BDA + MEA + desired_effect_per_agm + measures_of_effectiveness. Not a re-derivation — pulls the bottom lines out so the recommendation stands on its own."},
             {"name": "effect_against_moe_comparison", "render_label": "Effect vs Predetermined MOE",
              "provenance_required": True,
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Core analytical step: compare merged BDA + MEA picture against predetermined MOEs developed at JTC start. moe_status_per_metric + degree_of_success + shortfall_summary."},
             {"name": "operational_risk_assessment", "render_label": "Operational Risk Assessment",
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Risk of NOT reattacking (HPT remains functional) vs risk of reattacking (asset diversion, friendly maneuver impact, ROE / LOAC, collateral). Targeting team + current ops responsibility."},
             {"name": "objectives_relative_impact", "render_label": "Objectives-Relative Impact",
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Must address all five axes by name: targets, target_critical_elements, target_systems, enemy_combat_force_strengths, friendly_maneuver. Empty fields OK when axis unaffected; structure must be present."},
             {"name": "recommended_disposition", "render_label": "Recommended Disposition",
              "enum": ["reattack", "restrike_modified", "no_reattack", "move_to_new_task"],
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "reattack = reengage same params; restrike_modified = reengage with MEA-driven changes; no_reattack = desired effect achieved; move_to_new_task = ready for new task toward JFC objectives."},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Why this disposition. Cite paired BDA + MEA artifact_ids."},
             {"name": "engagement_changes", "render_label": "Engagement Changes (if restrike_modified)",
              "required": False,
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "Specific weapon / munition / fuzing / tactics / delivery-parameter changes drawn from paired MEA recommendations. Required when recommended_disposition is 'restrike_modified'."},
             {"name": "confirmed_miss_authorization", "render_label": "Confirmed-Miss Authorization (if applicable)",
              "required": False,
              "batch_group": "rr_per_engagement",
              "depends_on": ["selected_bda_artifact_ids"],
              "guidance": "When RR is issued on BDA Phase 1 confirmed-miss basis prior to full BDA Phase 2 / 3: confirmed_miss_flag + target_priority_basis + weapon_availability_basis + law_of_war_review + roe_review."},
         ]},
        {"name": "bda_rollup",
         "view": "published",
         "shape": "dict",
         # Strip doctrine citation from render_label — doctrine refs
         # belong in code comments + LLM guidance, never analyst-facing
         # render labels. Per "no doctrine citations in user-visible UI".
         "render_label": "BDA Rollup (Target-System Damage Assessment Across Engagements)",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "selected_bda_artifact_ids",
             "upstream:BDA",
             "clauses:episodic",
             "entities:units",
         ],
         "guidance": (
             "Aggregate BDA picture — the effect on "
             "the target across the engagements assessed. Specifically rolls up "
             "Phase 3 TSDA judgments across the reporting period: target-system-"
             "level impact, enemy unit combat effectiveness, second- and "
             "third-order effects. Cites the constituent BDA artifacts."
         ),
         "subfields": ["target_systems_addressed",
                        "aggregate_pda_summary",
                        "aggregate_fda_summary",
                        "aggregate_tsda_summary",
                        "enemy_unit_combat_effectiveness_changes",
                        "second_and_third_order_effects"]},
        {"name": "mea_rollup",
         "view": "published",
         "shape": "dict",
         "render_label": "MEA Rollup (Force Effectiveness)",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "selected_bda_artifact_ids",
             "upstream:AGM",
             "upstream:BDA",
         ],
         "guidance": (
             "Aggregate MEA picture — the performance "
             "of the capability across the engagements assessed. Identifies "
             "patterns across the doctrinal recommendation categories "
             "(methodology / tactics / weapon system / munitions / fuzing / "
             "weapon delivery parameters) so the targeting working group can "
             "act on systemic issues, not just per-target ones. May surface "
             "commander's-guidance recommendations on unit "
             "basic load / required supply rate / controlled supply rate."
         ),
         "subfields": ["systemic_weapon_system_findings",
                        "systemic_munitions_findings",
                        "systemic_tactics_and_methodology_findings",
                        "systemic_delivery_parameter_findings",
                        "commanders_guidance_recommendations"]},
        {"name": "collateral_damage_summary",
         "view": "published",
         "shape": "dict",
         "render_label": "CDA Summary (Joint 4-Element Only)",
         "required": False,
         "depends_on": [
             "upstream:BDA",
         ],
         "guidance": (
             "Required when framing is 'joint_four_element'"
             "— the joint force commander's responsibility to account for "
             "unintentional or incidental injury or damage to civilians, "
             "noncombatants, or their property. Compares the CDE conducted in JTC "
             "phase 3 (capabilities analysis) with observed / inferred / reported "
             "damage. Not required for the Army 3-element framing; the existing "
             "BDA schema's collateral_damage_assessment paragraph carries the "
             "per-target CDA contribution either way."
         ),
         "subfields": ["applicability",
                        "engagements_with_collateral_effects",
                        "predicted_vs_observed_collateral_delta",
                        "loac_review_summary",
                        "civilian_harm_mitigation_actions"]},
        {"name": "moe_and_objectives_status",
         "view": "published",
         "shape": "dict",
         "render_label": "MOE and Objectives Status",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:AGM",
         ],
         "guidance": (
             "The"
             "MOEs / MOPs developed at JTC start, evaluated against what was "
             "actually achieved. Maps engagement-level outcomes to the "
             "commander's objectives and to the larger hierarchy of operational "
             "and national objectives. Usesboth MOEs "
             "(effects creation) and MOPs (task accomplishment)."
         ),
         "subfields": ["moe_status_by_objective",
                        "mop_status_by_task",
                        "progress_against_commanders_intent",
                        "shortfalls_and_gaps"]},
        {"name": "reattack_and_future_targeting",
         "view": "published",
         "shape": "dict",
         "render_label": "Reattack Recommendations and Future Targeting",
         "required": True,
         "provenance_required": True,
         "depends_on": [
             "upstream:BDA",
             "upstream:HPTL",
             "entities:units",
         ],
         "guidance": (
             "'Future target nominations and "
             "reattack recommendations merge the picture of what was done (BDA) "
             "with how it was done (MEA) and compares the result with "
             "predetermined MOEs.' Aggregates the standalone Reattack "
             "Recommendation products issued in this reporting period plus any "
             "new target nominations the CA generates. Feeds back into D3A "
             "Decide via the targeting working group."
         ),
         "subfields": ["reattack_recommendations_summary",
                        "new_target_nominations",
                        "targets_recommended_for_removal_from_hptl",
                        "d3a_decide_feedback"]},
        {"name": "operational_risk_and_recommendations_to_commander",
         "view": "published",
         "shape": "dict",
         "render_label": "Operational Risk and Recommendations to Commander",
         "required": True,
         "depends_on": [
             "entities:civil",
             "map:state",
         ],
         "guidance": (
             "The purpose of CA is to inform the commander "
             "of effects, enemy ability to make and sustain war, and recommended "
             "next actions. Captures the targeting team's recommendations to the "
             "commander on whether to continue the current targeting plan, "
             "modify it, reallocate assets, or change phase."
         ),
         "subfields": ["overall_risk_assessment",
                        "asset_reallocation_recommendations",
                        "phase_transition_recommendations",
                        "decisions_requested_of_commander"]},
        {"name": "post_combat_assessment_planning",
         "view": "workpaper",
         "shape": "dict",
         "render_label": "Post-Combat Assessment Planning",
         "required": False,
         "depends_on": [
             "upstream:BDA",
         ],
         "guidance": (
             "Planning for "
             "post-operations data collection — operations-related data, "
             "intelligence-related data, MEA exploitation (on-site analysis by "
             "MEA exploitation teams of engineers, tacticians, and intelligence "
             "analysts). Captures the federated-BDA partnerships and the planned MEA exploitation deployments. "
             "Workpaper view — not pushed to commander's briefing."
         ),
         "subfields": ["federated_bda_partnerships",
                        "mea_exploitation_team_deployments",
                        "post_operations_data_collection_plan",
                        "lessons_learned"]},
    ],
    "subtleties": [
        "Army 3-element CA =BDA + MEA + Reattack Recommendation. Joint 4-element CA =+ CDA. framing header field drives whether collateral_damage_summary is required.",
        "CA is the UMBRELLA — the per-target analytical work lives in the standalone BDA / MEA / RR products. Each engagements_assessed row points to its constituent artifacts; the rollup paragraphs (bda_rollup, mea_rollup) aggregate across them.",
        "CA is a command responsibility and a subcomponent of operation assessment. Not all operations require CA: 'some joint operations (e.g., defense support of civil authorities, foreign humanitarian assistance) require no targeting. In these cases, assessment is still required, but CA is not.'",
        "A BDA Phase 2 report may include CA elements when appropriate (MEA comments, reattack recommendation). The standalone CA product is the formal rollup, separate from the per-target BDA report.",
        "Future targeting and reattack recommendations 'merge the picture of what was done (BDA) with how it was done (MEA) and compares the result with predetermined MOEs.' moe_and_objectives_status + reattack_and_future_targeting carry this comparison.",
        "Post-CA data collection (operations-related, intelligence-related, MEA exploitation) is essential to evaluate full target damage, determine true effectiveness, and improve the assessment process. post_combat_assessment_planning captures this in workpaper form.",
        "Every claim cites source — the constituent BDA / MEA / RR artifact_ids carry the underlying provenance.",
    ],
    "hard_rules": [
        f"framing must be one of {COMBAT_ASSESSMENT_FRAMING_ENUM} — drives the CDA requirement.",
        "When framing is 'joint_four_element', collateral_damage_summary.applicability must be set and the paragraph must be populated. When framing is 'army_three_element', it is optional.",
        "engagements_assessed must list every engagement event aggregated in the reporting period with its bda_artifact_id. The per-engagement mea_findings row for that target_number is required; reattack_recommendation row is required when a reattack decision is being captured.",
        "mea_findings.weaponeering_baseline must cite the weaponeering tool documented in the paired AGM engagement_record. Synthesizing predicted effectiveness without a documented run is not acceptable.",
        "mea_findings.observed_effectiveness must cite the paired BDA artifact_id when available — MEA does not re-derive damage assessments.",
        "mea_findings.recommendations must address the six FM 3-60 categories (methodology / tactics / weapon system / munitions / fuzing / weapon delivery parameters); each may be empty when no change is warranted but the categories must be present.",
        "reattack_recommendation.recommended_disposition must be one of {reattack, restrike_modified, no_reattack, move_to_new_task}.",
        "reattack_recommendation.engagement_changes must be populated when recommended_disposition is 'restrike_modified', drawn from the paired mea_findings.recommendations.",
        "reattack_recommendation.objectives_relative_impact must address all five axes by name (targets / target_critical_elements / target_systems / enemy_combat_force_strengths / friendly_maneuver).",
        "Reattack recommendations are generally NOT made on BDA Phase 1 alone. The confirmed_miss_authorization sub-field is the exception path when reattack must be authorized before BDA Phase 2/3 completes.",
        "moe_and_objectives_status must reference the predetermined MOEs / MOPs developed at JTC start (typically captured on the AGM and the operation order). Synthesizing new MOEs at CA time is a process violation.",
        "Every assessment cites source.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Constituent BDAs: list_project_docs(filter={type:'BDA', dtg_range:[reporting_period_start, reporting_period_end]}) then get_project_doc per row",
        "AGM (MOE / desired-effect baseline + engagement record): list_project_docs(filter={type:'AGM'}) then get_project_doc",
        "TMP (pre-strike JDPI for miss-distance baseline in MEA findings): list_project_docs(filter={type:'TMP'}) then get_project_doc",
        "HPTL (priority context): list_project_docs(filter={type:'HPTL'}) then get_project_doc",
        "OPORD desired effects: get_project_doc(tag='OPORD')",
        "Engagement record + sensor evidence: get_recent_intel(types=['engagement','imagery'])",
        "Threat OOB (enemy-combat-effectiveness baseline — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Civil considerations (target environment civil context — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures + sustainment overlay (target environment via AO / boundaries / OBJ / EA / axis; sustainment proximity in PDA/FDA/CDA paragraphs — MTF/CCP/Class III/V/VIII): get_spatial_overlay()",
    ],
    "post_emit_summary": "artifact_id, reporting period, # engagements assessed, MOE status, framing, decisions requested",
}

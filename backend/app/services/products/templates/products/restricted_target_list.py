"""Restricted Target List (RTL) — ; FM 3-60 paras 1-11 / 1-13.

The RTL is a list of VALID targets that have specific restrictions placed on
the actions authorized against them (JP 3-60 GL-6 'restricted target',
'restricted target list'). Actions exceeding the documented restrictions are
prohibited until coordinated and approved by the establishing HQ. Engaging
restricted targets without due regard for the specified restriction(s) may be
a violation of the law of war ().

Doctrinal acronym: RTL appears verbatim in JP 3-60 (GL-2 + GL-6 + III-13) and
in FM 3-60 (acronym list + paras 1-11 / 1-13).

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_AO,
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PREPARED_BY,
    TARGET_CATEGORY_ENUM,
    TARGET_CATEGORY_LABELS,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

# Doctrinal restriction-type enum —  enumerates the canonical
# restriction families ("Limit collateral damage / Do not strike during
# daytime / Strike only with a certain weapon / Proximity to protected
# facilities and locations");  adds 'coordinate
# with a specific national agency / do not use cluster munitions'.
RESTRICTION_TYPE_ENUM = [
    "munition_type_restriction",
    "time_of_day_restriction",
    "weather_restriction",
    "collateral_damage_limit",
    "proximity_protected_facility",
    "coordination_required",
    "approval_authority_elevated",
    "method_of_engagement_restriction",
    "duration_or_phase_restriction",
    "national_agency_coordination",
    "nonlethal_only",
    "other_restriction"]

RESTRICTION_TYPE_LABELS = {
    "munition_type_restriction":         "Munition Type Restriction",
    "time_of_day_restriction":           "Time-of-Day Restriction",
    "weather_restriction":               "Weather Restriction",
    "collateral_damage_limit":           "Collateral Damage Limit",
    "proximity_protected_facility":      "Proximity to Protected Facility",
    "coordination_required":             "Coordination Required",
    "approval_authority_elevated":       "Elevated Approval Authority",
    "method_of_engagement_restriction":  "Method of Engagement Restriction",
    "duration_or_phase_restriction":     "Duration or Phase Restriction",
    "national_agency_coordination":      "National Agency Coordination",
    "nonlethal_only":                    "Nonlethal Effects Only",
    "other_restriction":                 "Other Restriction",
}

# Source of restriction — same legal/policy family as NSL plus the operational
# authorities that can impose engagement constraints.
RESTRICTION_SOURCE_ENUM = [
    "law_of_war",
    "international_law",
    "rules_of_engagement",
    "joint_force_commander_guidance",
    "component_commander_guidance",
    "host_nation_agreement",
    "intelligence_gain_loss_concern",
    "sensitive_target_designation",
    "other_authority"]

RESTRICTION_SOURCE_LABELS = {
    "law_of_war":                     "Law of War",
    "international_law":              "International Law",
    "rules_of_engagement":            "ROE",
    "joint_force_commander_guidance": "JFC Guidance",
    "component_commander_guidance":   "Component Commander Guidance",
    "host_nation_agreement":          "Host-Nation Agreement",
    "intelligence_gain_loss_concern": "Intelligence Gain/Loss",
    "sensitive_target_designation":   "Sensitive Target ()",
    "other_authority":                "Other Authority",
}

SPEC = {
    "name": "RTL",
    "output_format": "pptx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. JP 3-60 GL-6:
    # per-target restriction list filtered by restriction type and
    # sensitive-target flag.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "row",
    "doctrine": {
        "purpose": (
            "Restriction-list product. Enumerates VALID targets that have specific "
            "restrictions placed on the actions authorized against them. The RTL "
            "applies to all subordinate echelons. RTL entries CAN be engaged — within "
            "the documented restriction envelope — and CAN appear on the HPTL / JIPTL "
            "carrying their restriction tags (this is the distinction from the NSL, "
            "which is categorically off-limits and is not a target list). Sensitive "
            "targets are typically on the RTL and require Presidential or SecDef "
            "approval under the STAR process." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows grouped by target category. Within a category, ordered by "
            "restriction severity — sensitive targets (sensitive_target_flag = True, "
            "requiring Presidential / SecDef approval) first, then targets with "
            "multiple restrictions, then single-restriction targets. RTL is NOT "
            "priority-ordered as a fires payoff list — that is the HPTL's job."
        ),
    },
    "row_source": "entities:marked",
    "group_by": "category",
    # OE Definition + NSL gate + Tier 1 BOTH rollups AND atomics:
    # mid-cycle restriction triggers (emitter-specific gate from a fresh
    # TACELINT, sensitive-target flag from a fresh HUMINT IIR) bypass
    # the rollup latency.
    "consumes_artifacts": ["Operational Environment Definition", "NSL",
                            "SIGSUM", "HUMINTSUM"],
    "published_section_title": "Restricted Targets",
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "approving_authority": {"source": "session", "view": "header", "required": True,
                                  "default": "TBD — JFC approval pending",
                                  "render_label": "Approving Authority",
                                  "guidance": (
                                    "Authority that approved this RTL. 'A list of restricted targets nominated by "
                                    "elements of the joint force and approved by the "
                                    "joint force commander or directed by higher "
                                    "authorities.' Pull from OPORD §3.d / FRAGO header."
                                  )},
        "establishing_directive": {"source": "session", "view": "header", "required": False,
                                     "render_label": "Establishing Directive",
                                     "guidance": (
                                        "Order or directive that promulgates this RTL "
                                        "for the AOR (OPORD §3.d, FRAGO, standalone "
                                        "RTL message). Cite by reference number when "
                                        "available."
                                     )},
        "applies_to_echelons": {"source": "session", "view": "header", "required": False,
                                   "default": "All subordinate echelons",
                                   "render_label": "Applies to Echelons",
                                   "guidance": (
                                    "'RTLs apply to all "
                                    "subordinate echelons.' Customize only when the "
                                    "establishing directive scopes a subset (rare)."
                                   )},
        "nsl_artifact_id":    {"source": "upstream:NSL", "view": "internal", "required": False,
                                 "render_label": "NSL Reference",
                                 "depends_on": ["upstream:NSL"],
                                 "guidance": "Companion NSL artifact_id when available — for cross-deconfliction (an RTL entry CANNOT also be on the NSL)."},
        "oe_definition_artifact_id": {"source": "upstream:OE Definition", "view": "internal",
                                        "required": False,
                                        "render_label": "OE Definition Reference"},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
    },
    "row_fields": {
        # Identity block — published
        "id":                {"source": "entity:id", "view": "internal",
                                "required": True, "provenance_required": True,
                                "render_label": "ID"},
        "name":              {"source": "entity:name", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Restricted Target"},
        "category":          {"source": "entity:category", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Category",
                                "enum": TARGET_CATEGORY_ENUM,
                                "enum_labels": TARGET_CATEGORY_LABELS},
        "location_mgrs":     {"source": "entity:location_mgrs", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Location (MGRS)"},
        "restriction_summary": {"source": "analytical", "view": "published",
                                   "required": True, "provenance_required": True,
                                   "render_label": "Restriction",
                                   "guidance": (
                                    "ONE short imperative sentence — exactly what the "
                                    "restriction prohibits or requires. Cite the "
                                    "controlling instrument (ROE serial nr. / FRAGO "
                                    "paragraph / treaty article) in _provenance per "
                                    "('clearly documented "
                                    "in the ETF'). Examples per  / "
                                    ": 'Do not strike "
                                    "during daytime', 'Coordinate with [agency] before "
                                    "engagement', 'Do not use cluster munitions', "
                                    "'Engage only with PGM ≤ 500 lb', 'Engage only when "
                                    "no civilian activity observed within 200 m'."
                                   )},
        "restriction_type":  {"source": "analytical", "view": "published",
                                "required": True, "provenance_required": True,
                                "render_label": "Restriction Type",
                                "enum": RESTRICTION_TYPE_ENUM,
                                "enum_labels": RESTRICTION_TYPE_LABELS,
                                "guidance": (
                                    "Doctrinal restriction-type tag — pick the most "
                                    "binding category. When multiple types apply, the "
                                    "additional types go in additional_restrictions "
                                    "(workpaper)."
                                )},
        "restriction_source": {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "Restriction Basis",
                                  "enum": RESTRICTION_SOURCE_ENUM,
                                  "enum_labels": RESTRICTION_SOURCE_LABELS,
                                  "guidance": (
                                    "Authority under which the restriction is imposed. "
                                    "When the entity is a sensitive target (Presidential / SecDef "
                                    "approval), use 'sensitive_target_designation' and "
                                    "set sensitive_target_flag = True."
                                  )},
        "sensitive_target_flag": {"source": "analytical", "view": "published",
                                     "required": False, "default": False,
                                     "render_label": "Sensitive Target",
                                     "guidance": (
                                        "True when the target is a sensitive target per "
                                        " — 'Sensitive targets "
                                        "are those targets for which planned actions "
                                        "warrant Presidential or SecDef approval... "
                                        "Sensitive targets, which are typically on the "
                                        "RTL.' Triggers the  STAR "
                                        "(Sensitive Target Approval and Review) process. "
                                        "When True, override_authority MUST name the "
                                        "Presidential / SecDef approval path."
                                     )},
        "override_authority": {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "render_label": "Approval Authority",
                                  "guidance": (
                                    "Authority that must approve action exceeding the "
                                    "restriction (: "
                                    "'prohibited until coordinated and approved by the "
                                    "establishing HQ'). For sensitive targets "
                                    "(sensitive_target_flag = True): Presidential or "
                                    "SecDef per  STAR process. For "
                                    "ROE-only restrictions: whoever owns the ROE. "
                                    "Default to JFC."
                                  )},
        # Workpaper — supports SJA / targeting working group analysis
        "additional_restrictions": {"source": "analytical", "view": "workpaper",
                                       "required": False, "provenance_required": True,
                                       "render_label": "Additional Restrictions",
                                       "guidance": (
                                        "Other RESTRICTION_TYPE_ENUM tags that apply "
                                        "beyond the primary restriction_type. List as "
                                        "comma-separated enum values."
                                       )},
        "restriction_rationale": {"source": "analytical", "view": "workpaper",
                                     "required": True, "provenance_required": True,
                                     "render_label": "Rationale",
                                     "depends_on": ["upstream:NSL"],
                                     "guidance": (
                                        "Why this restriction is imposed. The rationale should be "
                                        "'clearly documented in the ETF.' Cite the "
                                        "controlling intelligence-gain/loss concern, "
                                        "proximity to NSL entity, treaty / ROE article, "
                                        "diplomatic concern, etc. in _provenance."
                                     )},
        "engagement_envelope": {"source": "analytical", "view": "workpaper",
                                   "required": False, "provenance_required": True,
                                   "render_label": "Engagement Envelope",
                                   "guidance": (
                                    "Concrete parameters within which engagement IS "
                                    "authorized — the inverse of the restriction. e.g. "
                                    "'JDAM-1000 only; weather VFR; no civilian activity "
                                    "within 200m last 4h.' Used downstream by "
                                    "weaponeering and TSS gating."
                                   )},
        "coordination_pocs":  {"source": "analytical", "view": "workpaper",
                                  "required": False, "provenance_required": True,
                                  "render_label": "Coordination POCs",
                                  "guidance": (
                                    "Specific agencies / staff cells that must be "
                                    "coordinated with prior to engagement ('coordinate with a specific "
                                    "national agency'). Used by current operations / "
                                    "JTCB."
                                  )},
        "nsl_proximity_note": {"source": "analytical", "view": "workpaper",
                                  "required": False,
                                  "render_label": "NSL Proximity",
                                  "depends_on": ["upstream:NSL"],
                                  "guidance": (
                                    "When restriction_type is 'proximity_protected_facility', "
                                    "cite the nearest NSL entity id and standoff "
                                    "distance. Triggers CDE for any engagement of this "
                                    "target."
                                  )},
        "established_dtg":   {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Date Added to RTL"},
        "last_reviewed_dtg": {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Last Reviewed DTG"},
        "review_authority":  {"source": "analytical", "view": "workpaper",
                                "required": False,
                                "render_label": "Review Authority"},
        "nominating_source": {"source": "analytical", "view": "workpaper",
                                "required": False, "provenance_required": True,
                                "render_label": "Nominating Source",
                                "guidance": (
                                    "Element that nominated the target for the RTL "
                                    "— 'nominated by elements of the "
                                    "joint force and approved by the joint force "
                                    "commander or directed by higher authorities.' "
                                    "The G-2 is the Army nominator."
                                )},
    },
    "subtleties": [
        "RTL entries are VALID targets (per the 'restricted target' definition) — they can be engaged within the restriction envelope. This is the key distinction from NSL (which is categorically protected and NOT a target list).",
        "RTL ↔ HPTL relationship: RTL entries CAN appear on the HPTL / JIPTL, but they carry their restriction tags forward into AGM remarks and TSS gating. The targeting working group sees both the priority and the restriction.",
        "'RTLs apply to all subordinate echelons.' V Corps RTL inherits the higher-echelon (JFC / CCMD) RTL plus any V Corps-imposed restrictions.",
        "Sensitive-target subset (): 'Sensitive targets are those targets for which planned actions warrant Presidential or SecDef approval... Sensitive targets, which are typically on the RTL...' — flag with sensitive_target_flag = True and route the override through  STAR.",
        "NSL ↔ RTL deconfliction: an entity CANNOT appear on both lists. NSL = protected and off-limits; RTL = valid but constrained. When the same physical entity is nominated to both, the more-restrictive (NSL) status wins until the override authority documents removal.",
        "Engagement-without-due-regard is a legal hazard (: 'Engaging restricted targets without due regard for the specified restriction(s) may be a violation of the law of war'). The schema enforces an explicit override_authority + restriction_source pairing so the legal posture is documentable.",
        "'When targets are restricted from lethal effects, commanders may consider nonlethal capabilities to achieve or support their objectives.' restriction_type='nonlethal_only' supports this branch.",
        "Disclaimer: 'A specific weaponeering solution does not imply a target restriction.' Do not promote a weaponeering preference to an RTL restriction.",
        "Per IDX 26 organizer requirement: every restriction cites the controlling ROE serial nr. / treaty article / OPORD paragraph in _provenance."],
    "hard_rules": [
        "An RTL entry CANNOT also be on the NSL (cross-deconfliction enforced at row-derivation time using nsl_artifact_id).",
        "Every entry must cite at least one RESTRICTION_SOURCE_ENUM authority AND name a concrete override_authority who can approve action beyond the restriction ().",
        "When sensitive_target_flag = True, override_authority MUST name the Presidential or SecDef approval path per  +  STAR.",
        "Restriction_type restricted to the RESTRICTION_TYPE_ENUM ( +  exemplars). Use 'other_restriction' only with explicit rationale and override_authority cited.",
        "Target category restricted to TARGET_CATEGORY_ENUM — same category space as HVTL / HPTL for cross-list consistency.",
        "Per IDX 26: every restriction has _provenance for the controlling instrument.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Candidate targets in AO: list_targets()",
        "NSL (cross-deconfliction): list_project_docs(filter={type:'NSL'}) then get_project_doc(tag=<latest>)",
        "Civil considerations ROE-restricted context (now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Sustainment overlay (restricted strikes near MTF/CCP/Class III/V/VIII/MSR/ASR; LRP/ATP/ROM/MCP proximity): get_spatial_overlay()",
        "OPORD §3.d targeting guidance + ROE annex: get_project_doc(tag='OPORD')",
        "Latest FRAGO with RTL updates: list_project_docs(filter={type:'FRAGO'}) then get_project_doc",
        "Prior RTL (regen / continuity): list_project_docs(filter={type:'RTL'}) then get_project_doc(tag=<latest>)",
        "SJA / legal review notes: get_project_doc(tag='SJA_review') when available",
        "Sensitive-target nominations / STAR routing: get_project_doc(tag='STAR_nominations') when available"],
    "post_emit_summary": "artifact_id, row count, top restriction types, count of sensitive-target flagged entries, any NSL deconfliction conflicts found",
}

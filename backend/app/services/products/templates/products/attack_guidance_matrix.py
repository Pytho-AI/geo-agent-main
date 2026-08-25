"""AGM — Attack Guidance Matrix — paras 2-22 – 2-26 + App. D Table D-3.

D3A Decide-phase product. Commander-approved matrix that prescribes WHEN
(planned / as-acquired / immediate), HOW (engagement means), EFFECTS
(suppress / neutralize / destroy), and REMARKS for every HPT. The AGM
synthesizes the HPTL + TSS gates with commander's targeting guidance into
the executable Decide artifact (paras 2-22 – 2-26).

paras 1-65 + 2-149 + Ch. 3 corroborate AGM as a DIVARTY-level
S-2 targeting section product issued by the commander; this schema is
echelon-agnostic and the preparing_unit / approving_commander header fields
carry the actual owners.

See templates/products/__init__.py for the assembled PRODUCT_SCHEMAS map.
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

# Doctrinal AGM column axis. Table D-3 columns: HPT, When, How,
# Effect, Remarks. The HPT name IS the row key (matrix row label), so the
# four data columns are: when_engage, how_engage, effects,
# restrictions_or_special_instructions.
AGM_COL_AXIS = [
    "when_engage",
    "how_engage",
    "effects",
    "restrictions_or_special_instructions",
]

# WHEN values per App. D para D-7 second bullet group:
#   P = Planned (engaged on the planned timeline)
#   A = As Acquired (engaged as detected; HPTL ordering breaks ties)
#   I = Immediate (precedes all other engagements except TST; reserved
#                  for CBRN-capable systems, HQ, long-range fires, etc.)
AGM_WHEN_ENUM = ["P", "A", "I"]
AGM_WHEN_LABELS = {
    "P": "P — Planned",
    "A": "A — As Acquired",
    "I": "I — Immediate",
}

# EFFECTS per App. C Section I (desired effects) + App. D Table D-3
# legend. Suppress / Neutralize / Destroy is the doctrinal triad for kinetic
# fires; App. C also defines Disrupt, Delay, Divert, Limit, Damage,
# Deny, Degrade, Influence, Inform, Manipulate, Negate. The AGM cell uses
# the doctrinal verb directly (e.g., 'Neutralize'); for nonlethal effects
# the writer picks the App. C verb that matches the engagement means.
AGM_EFFECTS_ENUM = [
    "destroy",
    "neutralize",
    "suppress",
    "disrupt",
    "delay",
    "deny",
    "degrade",
    "divert",
    "limit",
    "damage",
    "influence",
    "inform",
    "manipulate",
    "negate",
]
AGM_EFFECTS_LABELS = {
    "destroy":    "Destroy",
    "neutralize": "Neutralize",
    "suppress":   "Suppress",
    "disrupt":    "Disrupt",
    "delay":      "Delay",
    "deny":       "Deny",
    "degrade":    "Degrade",
    "divert":     "Divert",
    "limit":      "Limit",
    "damage":     "Damage",
    "influence":  "Influence",
    "inform":     "Inform",
    "manipulate": "Manipulate",
    "negate":     "Negate",
}

SPEC = {
    "name": "AGM",
    "output_format": "pptx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. D
    # Table D-3: commander-approved HPT × {When, How, Effect, Remarks};
    # FM calls it "a living tool" updated by FRAGO.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "matrix",
    # Landscape: the AGM has narrative-heavy Remarks cells (collateral damage
    # constraints, coordination requirements, ammunition limits) that need
    # horizontal real-estate. Landscape gives ~14" usable width — enough for
    # WHEN (narrow) + HOW (medium) + EFFECTS (narrow) + Remarks (wide) plus
    # the HPT row label. Portrait truncated Remarks cells in early prototypes.
    "doctrine": {
        "purpose": (
            "Commander-approved matrix that prescribes WHEN, HOW, EFFECTS, "
            "and REMARKS for each HPT. One AGM may cover execution at any "
            "point, per cycle, or per phase. The targeting working group "
            "drafts; the commander approves. Drives executable engagement "
            "orders + feeds the TSM (which synchronizes detect / deliver / "
            "assess agencies around the AGM's engagement plan)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows = HPTs from the consumed HPTL, in HPTL priority order. "
            "Columns: when_engage (P/A/I), how_engage (weapon/munition pair), "
            "effects (suppress / neutralize / destroy / etc.), "
            "restrictions_or_special_instructions (collateral damage, "
            "coordination, ammunition limits, BDA requirements)."
        ),
    },
    "consumes_artifacts": ["HPTL", "TSS"],
    # Per-field upstream dep filter — drops per-cell HPTL workpaper
    # provenance maps from the writer prompt. AGM only needs rows
    # + header from the upstream HPTL + TSS payloads. Mirrors HVTL's
    # default_data_source_filter pattern (lines 101-129).
    "default_data_source_filter": {
        "upstream:HPTL": ["rows", "header"],
        "upstream:TSS": ["rows", "header"],
    },
    # Writer-controlled row-id selection. The HPTL is the candidate pool;
    # AGM is the commander-approved subset for THIS phase + commander's
    # targeting guidance. NSL/RTL/civilian entries from HPTL MUST be
    # dropped (LOAC-protected facilities never engaged). Singleton wave
    # — lands before the agm_published paragraph_field batch.
    "row_id_selection_field": "selected_agm_hpt_kg_ids",
    "published_section_title": "Attack Guidance",
    "matrix_spec": {
        "field": "agm_matrix",
        # Row axis is dynamic — the HPTs from the consumed HPTL. The renderer
        # treats matrix keys as rows when row_axis is missing.
        "col_axis": AGM_COL_AXIS,
        "row_label": "High-Payoff Target",
        "col_label": "Attack Guidance",
    },
    "header_fields": {
        "area_of_operations":   HEADER_AO,
        "dtg":                  HEADER_DTG,
        # Phase defaults to Phase I (Penetration) via skeleton-fill — see
        # HVTL line 136 fix. AGM must never publish blank phase.
        "phase":                {**HEADER_PHASE, "default": "Phase I (Penetration)"},
        # Writer's analytical AGM row selection — list of HPT kg_ids
        # scoped to THIS phase + commander's targeting guidance. NSL /
        # RTL / civilian entries dropped at selection. Singleton wave —
        # lands BEFORE the agm_published paragraph_field batch so the
        # paragraph writer sees the curated row pool, not every HPTL row.
        "selected_agm_hpt_kg_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            "render_label": "Selected AGM HPT kg_ids",
            "depends_on": ["upstream:HPTL"],
            "guidance": (
                "JSON array of HPT kg_id strings the AGM engages this "
                "phase. Each kg_id MUST verbatim-match a row id on the "
                "consumed HPTL. NSL / RTL / civilian / LOAC-protected "
                "entries from HPTL MUST be dropped — those are never "
                "engaged. Order matches HPTL priority. NEVER invent "
                "kg_ids."
            ),
        },
        "preparing_unit":       {**HEADER_PREPARED_BY,
                                   "default": "G-3 Targeting / Targeting Working Group",
                                   "render_label": "Preparing Unit",
                                   "guidance": (
                                      "Targeting working group drafts ("
                                      "); at DIVARTY the targeting "
                                      "officer in the S-2 section prepares."
                                   )},
        "approving_commander":  {"source": "session", "view": "header",
                                   "required": True,
                                   "default": "TBD — commander approval pending",
                                   "render_label": "Approving Commander",
                                   "guidance": (
                                      "The commander, with "
                                      "recommendations from the targeting "
                                      "working group, MUST approve the attack "
                                      "guidance. Pull from OPORD §3.d or "
                                      "FRAGO header. Leave default when "
                                      "drafting before approval."
                                   )},
        "classification":       HEADER_CLASSIFICATION,
        "hptl_artifact_id":     {"source": "upstream:HPTL", "view": "internal",
                                   "required": True,
                                   "render_label": "HPTL Reference",
                                   "depends_on": ["upstream:HPTL"],
                                   "guidance": (
                                      "Upstream HPTL — AGM rows ARE the HPTs "
                                      "listed on the HPTL in HPTL priority "
                                      "order ('A prioritized HPTL')."
                                   )},
        "tss_artifact_id":      {"source": "upstream:TSS", "view": "internal",
                                   "required": False,
                                   "render_label": "TSS Reference",
                                   "depends_on": ["upstream:HPTL", "upstream:TSS"],
                                   "guidance": (
                                      "Upstream TSS — when present, the AGM "
                                      "how_engage column SHOULD align with the "
                                      "weapon system the TSS gates the HPT "
                                      "for. When TSS hasn't been produced "
                                      "yet, the writer derives weapon-system "
                                      "selection from the HPTL workpaper + "
                                      "commander's targeting guidance."
                                   )},
    },
    "paragraph_fields": [
        {"name": "agm_matrix",
         "view": "published",
         "shape": "grid_table",
         "render_label": "Attack Guidance Matrix",
         "required": True,
         # Co-fire agm_matrix + agm_rows + general_attack_guidance +
         # tst_handling_note in a single batched LLM pass. Without this,
         # the writer makes 4 serial ~17K-token prompts; the agm_published
         # batch_group consolidates them into one call (commits 08f4dad /
         # d3259a3 introduced this pattern for HVTL).
         "batch_group": "agm_published",
         "depends_on": [
             "selected_agm_hpt_kg_ids",
             "upstream:HPTL",
             "upstream:TSS",
         ],
         "guidance": (
            "Per-HPT × 4-column matrix . Rows = HPTs "
            "from the consumed HPTL in HPTL priority order. Columns:\n"
            "  - when_engage = WHEN. "
            "group. ENUM: 'P' (Planned — engage on planned timeline; track or "
            "re-confirm if past the planned time), 'A' (As Acquired — engage "
            "as detected; multi-target ties broken by HPTL priority), 'I' "
            "(Immediate — precedes all other engagements except TST; reserved "
            "for CBRN-capable systems, division/IFC HQ, integrated air "
            "defense systems, long-range missiles/rockets).\n"
            "  - how_engage = HOW third bullet. The engagement "
            "means — primary AND alternate where possible ("
            "sentence). Format: '<system> / <munition>' (e.g., 'M270A2 MLRS "
            "/ GMLRS-ER UA', 'AH-64E / Hellfire AGM-114R', 'F-35A / GBU-31 "
            "JDAM', 'Electromagnetic Attack / EA-18G Growler', 'AI / Cyber'). "
            "Use TSS variants where they apply.\n"
            "  - effects = EFFECTS. Use the standard "
            "I desired-effect verbs. Quantifiable terms preferred ('Destroy "
            "≥50% of battery vehicles', 'Suppress for 8 minutes during gap "
            "crossing'). Use the verbthat matches the commander's "
            "guidance: typically Suppress / Neutralize / Destroy for kinetic; "
            "Deny / Degrade / Disrupt / Influence / Inform / Manipulate / "
            "Negate for non-kinetic / CEMA.\n"
            "  - restrictions_or_special_instructions = REMARKS "
            "fifth bullet. Collateral damage estimation limitations, accuracy "
            "or time constraints, required coordination (airspace control, "
            "CEMA deconfliction, ICRC notification), ammunition limits, BDA "
            "requirements, exceptions (e.g., 'do not engage if the enemy is "
            "withdrawing'), and combat-assessment specifics. Cite OPORD or "
            "FRAGO source for every constraint.\n"
            "The AGM minimum content is: phase or time "
            "period, specific HPT, timing of engagement, how engaged, desired "
            "effects, and remarks (including restrictions) — every column "
            "must be filled."
         )},
        {"name": "agm_rows",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Attack Guidance Rows (Structured)",
         "required": True,
         # agm_rows MUST be populated — downstream TIDAT method_of_engagement
         # / method_of_fire_and_control lookup depends on this structure.
         # Empty agm_rows = TIDAT echoes blank no matter what TIDAT's
         # schema declares. Co-fired with agm_matrix in the same batch
         # so the writer emits both in one pass; doctrinal hard_rule
         # 'agm_rows MUST mirror agm_matrix one-to-one' is therefore
         # naturally enforced.
         "batch_group": "agm_published",
         "depends_on": [
             "selected_agm_hpt_kg_ids",
             "upstream:HPTL",
             "upstream:TSS",
         ],
         "guidance": (
            "Structured-row mirror of agm_matrix for downstream consumers "
            "(TSM, BDA, Combat Assessment, TIDAT) that need to look up "
            "engagement guidance by target_id without parsing the rendered "
            "matrix. One entry per HPT row in agm_matrix, SAME ORDER, SAME "
            "CONTENT — emit both in the same writer pass. If agm_matrix "
            "lists 12 HPTs, agm_rows lists 12 dicts. agm_rows MUST be "
            "populated — downstream TIDAT engagement-echo lookup depends "
            "on it; an empty list breaks the per-target message echo."
         ),
         "item_subfields": [
             {"name": "target_id",
              "render_label": "HPT kg_id",
              "provenance_required": True,
              "guidance": "HPT entity id (kg_id) for the row — matches the HPT row label in agm_matrix. Sourced from the consumed HPTL."},
             {"name": "hpt_name",
              "render_label": "HPT Name",
              # Anti-enumeration rule (matches HVTL) — do not name a
              # specific doctrinal platform inline; pull from the kg
              # entity's name. Hardcoded examples in guidance bias the
              # writer toward the example platform.
              "guidance": "Doctrinal HPT name as shown in the matrix row label (the kg:name value for the kg_id). Mirrors the agm_matrix outer key without the kg_id parenthetical."},
             {"name": "when_engage",
              "render_label": "WHEN",
              "enum": AGM_WHEN_ENUM,
              "provenance_required": True,
              "guidance": "P / A / I per AGM_WHEN_ENUM. Identical to the agm_matrix row's when_engage cell."},
             {"name": "how_engage",
              "render_label": "HOW",
              "provenance_required": True,
              "guidance": "Weapon system / munition pair (e.g., 'M270A2 MLRS / GMLRS-ER UA'). Identical to the agm_matrix row's how_engage cell."},
             {"name": "effects",
              "render_label": "EFFECTS",
              "provenance_required": True,
              "guidance": "Effects verb (destroy/neutralize/suppress/...). Identical to the agm_matrix row's effects cell."},
             {"name": "restrictions_or_special_instructions",
              "render_label": "REMARKS",
              "provenance_required": True,
              "guidance": "Collateral / coordination / BDA-required / exceptions text. Identical to the agm_matrix row's REMARKS cell."},
         ]},
        {"name": "general_attack_guidance",
         "view": "published",
         "shape": "dict",
         "render_label": "General Attack Guidance",
         "required": True,
         "batch_group": "agm_published",
         "depends_on": [
             "selected_agm_hpt_kg_ids",
             "upstream:HPTL",
         ],
         "guidance": (
            "'Attack guidance may address specific or "
            "general target descriptions and is provided to weapons systems "
            "managers via the AGM.' Capture the commander's general guidance "
            "that conditions every row of the matrix — desired-effects "
            "weighting, lethal vs nonlethal preference, dynamic-targeting "
            "thresholds, default coordination requirements."
         ),
         "subfields": [
            "commanders_desired_effects_weighting",
            "lethal_nonlethal_preference",
            "dynamic_targeting_authority",
            "default_coordination_requirements",
            "bda_default_requirement",
         ],
         "subfield_guidance": {
            "commanders_desired_effects_weighting": "Commander's relative weighting of Destroy / Neutralize / Suppress / other Section-I verbs for this phase (e.g., 'Phase 2 prioritizes Neutralize on enemy fires to enable gap crossing; Destroy reserved for CBRN-capable systems').",
            "lethal_nonlethal_preference": "Phase-level preference between lethal fires and non-lethal effects (CEMA, IO, deception). Drives how_engage column defaults for HPTs where both options exist.",
            "dynamic_targeting_authority": "Authority and process for engaging As-Acquired (A) and Immediate (I) targets — who in the main CP approves, what coordination is required ('Theoperations officer, FSCOORD, and FSO must establish procedures within the main CP').",
            "default_coordination_requirements": "Standing coordination requirements that apply to every row unless explicitly waived in remarks (airspace control, fires-cell deconfliction, CEMA deconfliction).",
            "bda_default_requirement": "Default BDA expectation per HPT — typically driven from the consumed HPTL `bda_required` flag and `bda_time_window` workpaper field. The remarks column carries per-HPT overrides.",
         }},
        {"name": "synchronization_with_decision_support",
         "view": "published",
         "shape": "string",
         "render_label": "Synchronization with Decision Support Template",
         "required": False,
         "provenance_required": True,
         "guidance": (
            "'The AGM should be synchronized with the "
            "decision support template and ensure the selection of HPTs is "
            "supported by targeting intelligence requirements and the "
            "information collection plan.' One short paragraph describing the "
            "decision-point linkage — which decision points trigger updates "
            "to this AGM, which named areas of interest feed which rows. Cite "
            "the DST artifact_id or OPORD Tab when present."
         )},
        {"name": "tst_handling_note",
         "view": "published",
         "shape": "string",
         "render_label": "TST and Component-Critical Target Handling",
         "required": False,
         "batch_group": "agm_published",
         "depends_on": [
             "selected_agm_hpt_kg_ids",
             "upstream:HPTL",
         ],
         "guidance": (
            "'TSTs and "
            "Component-Critical Targets are sub-classes of HPTs handled via "
            "dynamic targeting'. Brief note on how this AGM treats TSTs — "
            "which categories on the HPTL are flagged TST, what the standing "
            "engagement criteria are (per JFC-approved TST list), and the "
            "delegation chain when the dynamic-targeting window opens."
         )},
    ],
    "subtleties": [
        "AGM row scope = the writer-selected commander-prioritized HPTs for this phase, NOT every HPTL row. The HPTL is the candidate pool; AGM is the commander-approved subset. selected_agm_hpt_kg_ids drives the cut.",
        "AGM is COMMANDER-APPROVED.The targeting working group recommends; the commander approves. The approving_commander header field captures the approval authority; pre-approval drafts run with the default TBD value.",
        "One AGM may be produced per cycle, per phase, or for execution at any point . The phase header field disambiguates which AGM applies; FRAGO updates can issue a new AGM mid-phase.",
        "AGM lethal + nonlethal effects coexist on the same matrix. The how_engage column carries CEMA / cyber / IO entries alongside kinetic fires; the effects column uses the verb that matches.",
        "WHEN enum {P, A, I} maps directly to 'Planned', 'As Acquired', 'Immediate'. 'I' is reserved for the most critical targets (CBRN, HQ, IADS, long-range fires) and PRECEDES all other engagements except TST .",
        "HOW column should identify a PRIMARY AND ALTERNATE engagement means where possible . 'Each engagement system may require different TSS criteria' — variants in the TSS artifact map to HOW choices here.",
        "EFFECTS in QUANTIFIABLE TERMS preferred. Number of systems to be destroyed, length of time to suppress, percentage of capability denied.",
        "REMARKS column carries restrictions fifth bullet sub-list: collateral damage estimation limits, accuracy / time constraints, required coordination, ammunition limits, combat-assessment specifics. Withdrawing-enemy exceptions are noted here.",
        "AGM is a LIVING tool — updatedbased on changing enemy situation, discussed during routine staff planning meetings. A separate AGM may exist per phase of the concept of operations.",
        "'Data from these documents should be integrated into mission command systems to facilitate digital execution, coordination, and assessments.' The AGM artifact is the digital-execution source for AFATDS / JADOCS workflows.",
        "AGM execution lives in the DIVARTY fire-control workflow.",
        "Per IDX 26: every row + every general guidance subfield cites source in _provenance.",
    ],
    "hard_rules": [
        "AGM row scope = the writer-selected commander-prioritized HPTs for this phase via selected_agm_hpt_kg_ids — the HPTL is the candidate pool, AGM is the commander-approved subset. Order matches HPTL priority.",
        "NSL / RTL / civilian / LOAC-protected entries from HPTL MUST be dropped at AGM row selection — never engage LOAC-protected facilities.",
        "agm_rows MUST mirror agm_matrix one-to-one in the same order. Same HPT count, same target_id ordering, same when/how/effects/remarks values per row. Emit both in the same pass.",
        "when_engage MUST be one of {P, A, I} — no free text. The enum maps to 'Planned / As Acquired / Immediate'.",
        "effects column uses the standard desired-effect verbs —no neologisms. Preferred form: quantified ('Destroy ≥50% of battery vehicles'); minimum acceptable form: the verb alone ('Neutralize').",
        "how_engage column must name the weapon system AND the munition or means (e.g., 'M270A2 MLRS / GMLRS-ER UA', not just 'MLRS'). Pair primary + alternate where the engagement plan permits.",
        "Every row's restrictions_or_special_instructions cell is populated. If no specific restriction applies, the cell carries the default coordination requirements (airspace, fires-cell, CEMA) — never blank.",
        "commander approval status is reflected in approving_commander header — TBD when drafting, named officer when approved. Never claim 'approved' without a named commander.",
        "Per IDX 26: every analytical field carries _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream HPTL: list_project_docs(filter={type:'HPTL'}) then get_project_doc(tag=<latest>)",
        "Upstream TSS: list_project_docs(filter={type:'TSS'}) then get_project_doc(tag=<latest>)",
        "Threat structure (HPT unit context — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "OPORD targeting guidance: get_project_doc(tag='OPORD') §3.d + Annex D (Fires)",
        "FRAGO updates: list_project_docs(filter={type:'FRAGO'})",
        "Decision Support Template / DST: get_project_doc(tag='DST') when present",
        "Standing TST list: get_project_doc(tag='TST_LIST') when present",
        "Operations overlay control measures (engagement geometry — axis / OBJ / EA / NAI / TAI proximity drives when_engage timing): get_spatial_overlay()",
        "Phased concept of operations (attack guidance shifts by phase per commander's targeting guidance): get_phases() — current phase + decisive point + phase objectives",
        "Weapon-system availability: get_project_doc(tag='OPORD') Annex D (Fires) — friendly fires order of battle",
        "ROE / collateral damage estimation thresholds: get_project_doc(tag='OPORD') Annex E (Rules of Engagement)",
    ],
    "post_emit_summary": "artifact_id, HPT row count, count by when_engage enum (P/A/I), count of Immediate-class HPTs, approval status",
}

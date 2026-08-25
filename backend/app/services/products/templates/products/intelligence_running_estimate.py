"""Intelligence Running Estimate — ATP 2-33.4 App. E paras E-7 – E-9, Figure E-3.

Doctrine source: ATP 2-33.4 (INCL C1) Appendix E (Intelligence Production),
paragraphs E-7, E-8, E-9 and the published format example in Figure E-3
(page E-5). Per ADP 5-0 (cited in E-7), a running estimate is "the
continuous assessment of the current situation used to determine if the
current operation is proceeding according to the commander's intent and
if the planned future operations are supportable." The intelligence
running estimate is the intelligence-staff portion of that continuous
assessment.

Per E-8: "Unlike other intelligence products, the intelligence running
estimate combines both the analysis of friendly and allied forces'
intelligence activities to support current operations."

Per E-9: "The analysis focuses on current threat activities, strengths,
and assessed intent/objectives to provide the commander and associated
reporting requirements with a consistent summary of the threat. As the
operation progresses, the collaborative effort may involve further
analysis of the terrain and weather, monitoring the flow of displaced
persons on the battlefield as inhibitors to friendly force maneuverability,
and, when necessary, additional security requirements."

Doctrinal note in E-9: "In the highly volatile large-scale ground combat
environment, the intelligence operational officer along with the
all-source intelligence analyst are likely to maintain the running
estimate."

ATP 2-33.4 publishes NO acronym for this product type. The registry key
is "Intelligence Running Estimate" (full doctrinal name) and the class
identifier in this module is `IntelligenceRunningEstimate` — the schema
must not invent an acronym (e.g. IRE) that doctrine does not use.

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

SPEC = {
    "name": "Intelligence Running Estimate",
    "output_format": "docx",
    "shape": "paragraph",
    "doctrine": {
        "purpose": (
            "Continuously-updated intelligence assessment used to determine if "
            "the current operation is proceeding according to the commander's "
            "intent and if planned future operations are supportable. Enables "
            "the intelligence operational officer/NCO to continually update "
            "the commander on mission execution from the intelligence "
            "perspective. This is the only intelligence product that COMBINES "
            "analysis of friendly and allied-forces intelligence activities "
            "with the threat analysis. Focus is current threat activities, "
            "strengths, and assessed intent/objectives — providing a "
            "consistent summary of the threat. Distinct from the Intelligence "
            "Estimate (MDMP-time formal estimate) and from the INTSUM "
            "(periodic situation summary). In LSCO the running estimate is "
            "typically maintained by the intelligence operational officer + "
            "all-source intelligence analyst." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "5-paragraph format: 1. Mission → 2. Area of Operations (with "
            "a. Terrain / b. Civil Considerations / c. Weather subparagraphs) "
            "→ 3. Enemy Situation (with a–i: Composition / Disposition / "
            "Strength / Tactics and Training / Sustainment / Operational "
            "Effectiveness / Intelligence / Communications / Other "
            "subparagraphs) → 4. Enemy Capabilities (with a. State Enemy's "
            "Capabilities / b. State Enemy's Limitations / c. Analysis and "
            "Discussion subparagraphs) → 5. Conclusions. Closes with "
            "ACKNOWLEDGE: [Designated Staff Officer] / OFFICIAL: "
            "[Authenticator]. Never re-order or merge."
        ),
    },
    # Running estimate is updated continuously during execution — it draws
    # on the same upstream IPOE chain as the Intelligence Estimate but
    # also folds in current operations reporting and the prior running
    # estimate revision.
    # Tier 2 fused inputs + Tier 1 BOTH rollups AND atomics (see INTSUM
    # comment for the same-day-event rationale).
    "consumes_artifacts": ["Intelligence Estimate", "MCOO", "TEM", "WEM",
                            "CCA", "Threat Overlay", "SITEMP", "Threat COA Statement", "INTSUM",
                            "BDA", "SITREP", "PIR",
                            "SIGSUM", "HUMINTSUM", "OSIR", "KLIEGLIGHT"],
    # SLA narrowing — see intelligence_summary.py.
    "default_data_source_filter": {
        "upstream:Intelligence Estimate": ["paragraph_2", "paragraph_3",
                                            "paragraph_4", "header"],
        "upstream:MCOO":                ["obstacles", "key_terrain",
                                          "avenues_of_approach",
                                          "cover_and_concealment_overlay", "header"],
        "upstream:TEM":                 ["rows", "header"],
        "upstream:WEM":                 ["rows", "header"],
        "upstream:CCA":                 ["rows", "header"],
        "upstream:Threat Overlay":      [],
        "upstream:SITEMP":              ["coas", "named_areas_of_interest", "header"],
        "upstream:Threat COA Statement":["coas", "header"],
        "upstream:INTSUM":              ["rows", "structured_data", "header"],
        "upstream:BDA":                 ["rows", "header"],
        "upstream:SITREP":              ["rows", "structured_data", "header"],
        "upstream:PIR":                 ["rows", "header"],
        "upstream:SIGSUM":              ["rows", "header"],
        "upstream:HUMINTSUM":           ["rows", "header"],
        "upstream:OSIR":                ["rows", "header"],
        "upstream:KLIEGLIGHT":          ["rows", "header"],
    },
    "header_fields": {
        # Header lines: [CLASSIFICATION], 'INTELLIGENCE RUNNING ESTIMATE
        # NUMBER___', '(U) DATE-TIME GROUP:', '(U) REFERENCES: Maps, charts,
        # or other documents.'
        "intelligence_running_estimate_number": {
            "source": "session", "view": "header",
            "required": True,
            "render_label": "Intelligence Running Estimate Number",
            "guidance": (
                "Header line 'INTELLIGENCE RUNNING ESTIMATE NUMBER___'. "
                "Sequential per unit SOP (e.g. '001', '002', "
                "'V-Corps-G2-RE-014'). Never leave blank — this is the "
                "version handle for the continuously-updated estimate."
            )},
        "dtg":                    HEADER_DTG,
        "references":             {"source": "session", "view": "header",
                                     "required": True,
                                     "default": "Maps, charts, or other documents per base OPORD.",
                                     "render_label": "References",
                                     "guidance": (
                                         "Header line '(U) REFERENCES: Maps, "
                                         "charts, or other documents.' Default "
                                         "mirrors that literal text; override "
                                         "to list specific charts / overlays / "
                                         "prior estimate revisions when "
                                         "appropriate."
                                     )},
        "area_of_operations":     HEADER_AO,
        # Upstream artifact links — the running estimate is the OPERATIONS-
        # phase update of the planning-phase Intelligence Estimate, so it
        # cites that estimate plus the standing IPOE chain plus current
        # operations reporting (INTSUM, BDA, SITREP).
        "intelligence_estimate_artifact_id": {"source": "upstream:Intelligence Estimate", "view": "internal", "required": False,
                                                "render_label": "Parent Intelligence Estimate",
                                                "depends_on": ["upstream:Intelligence Estimate"],
                                                "guidance": (
                                                    "Artifact id of the parent "
                                                    "Intelligence Estimate this "
                                                    "running estimate revises. "
                                                    "Not strictly required — the "
                                                    "running estimate may stand "
                                                    "alone — but populated when "
                                                    "an Intelligence Estimate "
                                                    "exists in the cycle."
                                                )},
        "mcoo_artifact_id":               {"source": "upstream:MCOO", "view": "internal", "required": False,
                                             "depends_on": ["upstream:MCOO"]},
        "tem_artifact_id":                {"source": "upstream:TEM", "view": "internal", "required": False,
                                             "depends_on": ["upstream:TEM"]},
        "wem_artifact_id":                {"source": "upstream:WEM", "view": "internal", "required": False,
                                             "depends_on": ["upstream:WEM"]},
        "cca_artifact_id":                {"source": "upstream:CCA", "view": "internal", "required": False,
                                             "depends_on": ["upstream:CCA"]},
        "threat_overlay_artifact_id":     {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                             "depends_on": ["upstream:Threat Overlay"]},
        "sitemp_artifact_id":             {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                             "depends_on": ["upstream:SITEMP"]},
        "threat_coa_statement_artifact_id":               {"source": "upstream:Threat COA Statement", "view": "internal", "required": False,
                                             "depends_on": ["upstream:Threat COA Statement"]},
        "intsum_artifact_id":             {"source": "upstream:INTSUM", "view": "internal", "required": False,
                                             "depends_on": ["upstream:INTSUM"],
                                             "render_label": "Latest INTSUM"},
        "bda_artifact_id":                {"source": "upstream:BDA", "view": "internal", "required": False,
                                             "depends_on": ["upstream:BDA"],
                                             "render_label": "Latest BDA"},
        "pir_artifact_id":                {"source": "upstream:PIR", "view": "internal", "required": False,
                                             "render_label": "Current PIR Set",
                                             "depends_on": ["upstream:PIR"],
                                             "guidance": (
                                                 "PIR artifact whose questions Para 2.a's running PIR "
                                                 "estimate is reporting against. Each running-estimate "
                                                 "PIR status update (open / partial / answered / closed) "
                                                 "traces back to a row in this PIR artifact. Without "
                                                 "this ref, Para 2.a has no commander-approved baseline."
                                             )},
        "designated_staff_officer_name_and_designation": {
            "source": "session", "view": "header",
            "required": True,
            "render_label": "ACKNOWLEDGE — Designated Staff Officer (Name and Designation)",
            "guidance": (
                "Footer 'ACKNOWLEDGE: [Designated Staff Officer's Name and "
                "Designation]'. Example: 'LTC SMITH / G-2'. BOTH name AND "
                "designation — never abbreviate to one or the other."
            )},
        "authenticator_name_and_position": {
            "source": "session", "view": "header",
            "required": True,
            "render_label": "OFFICIAL — Authenticator (Name and Position)",
            "guidance": (
                "Footer 'OFFICIAL: [Authenticator's Name and Position]'. "
                "Example: 'CW3 JONES / Senior All-Source Intelligence "
                "Analyst'. BOTH name AND position."
            )},
        "prepared_by":         HEADER_PREPARED_BY,
        "classification":         HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        # ===================== PARAGRAPH 1 — MISSION =====================
        {"name": "paragraph_1_mission",
         "view": "published",
         "shape": "string",
         "render_label": "1. Mission",
         "required": True,
         "guidance": (
             "Para 1 — 'MISSION: The commander determines the unit's mission.' "
             "Restated mission VERBATIM from the base OPORD. Never paraphrase. "
             "Pull from the OPORD Para 2 Mission."
         ),
         "depends_on": [
             "documents",
         ]},
        # ===================== PARAGRAPH 2 — AREA OF OPERATIONS =====================
        {"name": "paragraph_2_area_of_operations",
         "view": "published",
         "shape": "dict",
         "render_label": "2. Area of Operations (AO)",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 2 — 'AREA OF OPERATIONS (AO): Describe the existing "
             "situation in the AO based on:'. Three MANDATORY subparagraphs, "
             "in this verbatim order: a. Terrain ('How terrain affects a "
             "functional area's capabilities.'), b. Civil Considerations "
             "('Description of areas, structures, capabilities, organizations, "
             "people, and events.' — this is ASCOPE verbatim), c. Weather "
             "('How weather affects friendly and threat warfighting function "
             "capabilities.'). Note the ordering Terrain → Civil → Weather "
             "(Civil Considerations interposed) — preserved exactly here. "
             "Cite the tem / cca / wem artifact id under each subfield."
         ),
         "subfields": ["a_terrain",
                        "b_civil_considerations",
                        "c_weather"]},
        # ===================== PARAGRAPH 3 — ENEMY SITUATION =====================
        {"name": "paragraph_3_enemy_situation",
         "view": "published",
         "shape": "dict",
         "render_label": "3. Enemy Situation",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 3 — 'ENEMY SITUATION: Summary of each threat "
             "characteristic that can influence mission accomplishment:'. NINE "
             "MANDATORY subparagraphs a–i, in this verbatim order: "
             "a. Composition; b. Disposition ('Geographic location of threat "
             "elements and how they are deployed or employed.'); c. Strength "
             "('Committed forces, reinforcements, air, and chemical, biological, "
             "radiological, nuclear, and high-yield explosive weapons.'); "
             "d. Tactics and Training ('Strategy, methods of operations, "
             "tactics, and training.'); e. Sustainment ('Procurement, "
             "maintenance, distribution, and materiel replacement.'); "
             "f. Operational Effectiveness ('Threat morale, weapons "
             "effectiveness, equipment readiness, leadership, and personnel.'); "
             "g. Intelligence ('Estimate of the threat's intelligence "
             "collection capability.'); h. Communications ('The threat's "
             "communications modes.'); i. Other. Subparagraphs with no new "
             "information this cycle get 'No change since [prior running "
             "estimate number].' — never delete a subparagraph. Cite "
             "threat_overlay_artifact_id / sitemp_artifact_id / intsum_artifact_id / "
             "bda_artifact_id under the matching subfield in _provenance."
         ),
         "subfields": ["a_composition",
                        "b_disposition",
                        "c_strength",
                        "d_tactics_and_training",
                        "e_sustainment",
                        "f_operational_effectiveness",
                        "g_intelligence",
                        "h_communications",
                        "i_other"]},
        # ===================== PARAGRAPH 4 — ENEMY CAPABILITIES =====================
        {"name": "paragraph_4_enemy_capabilities",
         "view": "published",
         "shape": "dict",
         "render_label": "4. Enemy Capabilities",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 4 — 'ENEMY CAPABILITIES: In conventional operations:'. "
             "THREE MANDATORY subparagraphs, in this verbatim order: "
             "a. State Enemy's Capabilities ('What, where, when, and in what "
             "strength for each capability.'); b. State Enemy's Limitations "
             "('Cause and effect of each limitation.'); c. Analysis and "
             "Discussion ('Effect of capabilities on terrain, civil "
             "considerations, weather.'). a_state_enemys_capabilities is a "
             "list-of-dicts (one row per capability with What/Where/When/"
             "Strength columns) so the exporter renders it as a faithful "
             "table. b and c are narrative strings. Cite threat_coa_statement_artifact_id / "
             "threat_capability_statement source in _provenance."
         ),
         "subfields": ["a_state_enemys_capabilities",
                        "b_state_enemys_limitations",
                        "c_analysis_and_discussion"]},
        # ===================== PARAGRAPH 5 — CONCLUSIONS =====================
        {"name": "paragraph_5_conclusions",
         "view": "published",
         "shape": "string",
         "render_label": "5. Conclusions",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 5 — 'CONCLUSIONS: Conclusions based on information and "
             "analysis about the total effects of the AO on threat "
             "operations.' Synthesizes Paragraphs 2–4 into a commander-facing "
             "assessment: what the total AO (terrain + civil + weather) does "
             "to threat operations, and what that implies for friendly "
             "mission accomplishment. 3-6 sentences. Cite the upstream IPOE "
             "artifacts (TEM/WEM/CCA/SITEMP/Threat COA Statement) in _provenance — this "
             "paragraph is a synthesis and every claim traces back to a "
             "named source."
         ),
         "depends_on": [
             "entities:civil",
             "upstream:CCA",
             "upstream:Threat COA Statement",
             "upstream:SITEMP",
             "upstream:TEM",
             "upstream:WEM",
         ]}],
    "subtleties": [
        "The Intelligence Running Estimate is the CONTINUOUSLY UPDATED intelligence-staff portion of the unit's running estimate. Distinct from the Intelligence Estimate (one-shot MDMP-time formal estimate) and from the INTSUM (periodic situation summary).",
        "This is the ONLY intelligence product that combines analysis of friendly AND allied-forces intelligence activities with the threat analysis. Other intel products are threat-side only.",
        "Focus is current threat activities, strengths, and assessed intent/objectives. As operations progress, terrain/weather analysis and DP-flow monitoring may be folded in.",
        "Para 2 subparagraph order is Terrain → Civil Considerations → Weather (not Terrain → Weather → Civil). Preserved verbatim.",
        "Para 3 carries NINE subparagraphs a–i (Composition / Disposition / Strength / Tactics-and-Training / Sustainment / Operational-Effectiveness / Intelligence / Communications / Other). Every cycle must emit all nine, even if a subparagraph reads 'No change since prior estimate.'",
        "Para 4 'State Enemy's Capabilities' is the only subparagraph that renders as a table — four columns: What / Where / When / Strength. The schema models it as list_of_dicts so the exporter generates the table.",
        "ACKNOWLEDGE/OFFICIAL footer requires BOTH name and designation/position for each — never abbreviate.",
        "In LSCO the intelligence operational officer + all-source intelligence analyst typically maintain the running estimate. The preparing_unit default 'V Corps G-2' captures the staff section; the ACKNOWLEDGE/OFFICIAL block captures the individuals.",
        "Every analytical subparagraph in Paras 2/3/4/5 carries _provenance citing the upstream IPOE / INTSUM / BDA artifact it draws from."],
    "hard_rules": [
        "5-paragraph order — Mission (1) → AO (2) → Enemy Situation (3) → Enemy Capabilities (4) → Conclusions (5). Never re-order or merge.",
        "Paragraph 2 MUST carry three subparagraphs in order: a. Terrain, b. Civil Considerations, c. Weather (Civil Considerations between Terrain and Weather).",
        "Paragraph 3 MUST carry all nine subparagraphs a–i in order: Composition / Disposition / Strength / Tactics-and-Training / Sustainment / Operational-Effectiveness / Intelligence / Communications / Other. No-change subparagraphs get an explicit 'No change since prior estimate.' — never delete a subparagraph.",
        "Paragraph 4 MUST carry three subparagraphs a/b/c: a. State Enemy's Capabilities (list_of_dicts: What / Where / When / Strength), b. State Enemy's Limitations, c. Analysis and Discussion.",
        "Paragraph 1 (Mission) MUST be the restated mission verbatim from the parent OPORD — never paraphrase.",
        "ACKNOWLEDGE and OFFICIAL footer fields each require BOTH name and designation/position — never one or the other.",
        "Every analytical subparagraph cites _provenance (Para 2.a ↔ TEM, 2.b ↔ CCA, 2.c ↔ WEM, Para 3 ↔ Threat Overlay/SITEMP/INTSUM/BDA, Para 4 ↔ Threat COA Statement/Threat Capability Statement, Para 5 ↔ synthesis of all of the above).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Parent estimate / prior running estimate: list_project_docs(filter={type:'Intelligence Estimate'}), list_project_docs(filter={type:'Intelligence Running Estimate'}) then get_project_doc",
        "Upstream IPOE chain: list_project_docs filtered by MCOO / TEM / WEM / CCA / Threat Overlay / SITEMP / Threat COA Statement then get_project_doc",
        "Current operations reporting: list_project_docs(filter={type:'INTSUM'}), {type:'BDA'}, {type:'SITREP'} then get_project_doc",
        "Threat picture (Para 3 Composition/Disposition/Strength — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob(), list_targets()",
        "Recent activity (Para 3 Operational Effectiveness): get_recent_intel(window_hours=24)",
        "Civil considerations (Para 2.b, Para 5 — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures + sustainment kinds (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ + BSA/DSA/LSA/FLE/APOD/SPOD + MSR/ASR + LRP/ATP/ROM/MTF/CCP/MCP/Class III/V/VIII — Para 2.a / 2.b / Para 5 sustainment paragraph): get_spatial_overlay()",
        "Phased concept of operations (PRIMARY — IRE is THE phase-aware product; phase-keyed running narrative): get_phases() — current phase + decisive point + phase objectives",
        "Terrain context (Para 2.a, Para 5): get_terrain()",
        "Weather context (Para 2.c, Para 5): get_environmental()",
        "Parent OPORD (Para 1 Mission verbatim): get_project_doc(tag='OPORD'), get_project_doc(tag='ANNEX_B_INTEL')"],
    "post_emit_summary": "artifact_id, running estimate number, deltas vs prior estimate, top-line conclusion",
}

"""Intelligence Estimate — ATP 2-33.4 App. E paras E-5 – E-6, Figure E-2.

Doctrine source: ATP 2-33.4 (INCL C1) Appendix E (Intelligence Production),
paragraphs E-5 and E-6, with the published format example in Figure E-2
(page E-4). This product is Appendix 1 to Annex B (Intelligence) of the
operation order — it is the MDMP-time formal estimate that supports COA
development, distinct from the periodic INTSUM (Fig E-4) and from the
continuously-updated Intelligence Running Estimate (Fig E-3).

Per E-5: "An intelligence estimate is the appraisal, expressed in writing
or orally, of available intelligence relating to a specific situation or
condition with a view of determining the courses of action open to the
enemy or adversary and the order of probability of their adoption (JP 2-0).
Since intelligence analysts will have performed IPB to support the
commander's MDMP effort and likely participated in a thorough staff
war-gaming effort to validate friendly and threat COAs, the intelligence
estimate is a version of the staff planning effort and part of the larger
OPORD."

ATP 2-33.4 publishes NO acronym for this product type. The registry key
is "Intelligence Estimate" (full doctrinal name) and the class identifier
in this module is `IntelligenceEstimate` — the schema must not invent
an acronym (e.g. IE / IEST) that doctrine does not use.

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
    "name": "Intelligence Estimate",
    "output_format": "docx",
    "shape": "paragraph",
    "doctrine": {
        "purpose": (
            "MDMP-time formal intelligence estimate published as Appendix 1 to "
            "Annex B (Intelligence) of the OPORD. The appraisal of available "
            "intelligence relating to the situation with a view to determining "
            "the courses of action open to the enemy and the order of "
            "probability of their adoption. Develops and disseminates the "
            "threat COA analysis along with the requirements to determine the "
            "adoption of a COA; the assessments — threat strengths, "
            "compositions, dispositions, and vulnerabilities — form the basis "
            "for future intelligence analytical requirements. Distinct from "
            "the Intelligence Running Estimate (continuously updated during "
            "execution) and from the INTSUM (periodic situation summary)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "5-paragraph OPORD-appendix format: 1. Situation (Area of "
            "Interest, Area of Operations with Terrain + Weather "
            "subparagraphs, Enemy Forces with Composition + Disposition + "
            "Capability + Enemy Courses of Action subparagraphs, Friendly "
            "Forces, IGO/NGO, Civil Considerations, Attachments and "
            "Detachments, Assumptions) → 2. Mission → 3. Execution → "
            "4. Sustainment → 5. Command and Signal. Followed by ACKNOWLEDGE "
            "/ OFFICIAL signature block and Tab A (Terrain) / Tab B "
            "(Weather) / Tab C (Civil Considerations) / Tab D (IPB Products) "
            "attachments. Never re-order or merge paragraphs."
        ),
    },
    # The intelligence estimate is the MDMP-time formal write-up of the
    # IPOE chain — it cites every upstream IPOE product. Per E-6, the
    # threat-COA assessment is the COA-development driver; per Fig E-2
    # Para 1.c.(4), it explicitly references the Threat COA Statement sketch (Tab D
    # Exhibit 3). Tab A / Tab B / Tab C correspond to the standing IPOE
    # products TEM (terrain) / WEM (weather) / CCA (civil considerations).
    # Tier 2 fused IPOE inputs + Tier 1 BOTH rollups AND atomics — same
    # mid-cycle rationale as INTSUM.
    "consumes_artifacts": ["Operational Environment Definition", "MCOO", "TEM", "WEM", "CCA",
                            "Threat Overlay", "SITEMP", "Threat COA Statement", "HVTL", "HPTL",
                            "Threat Model", "Threat Capability Statement",
                            "SIGSUM", "HUMINTSUM", "OSIR", "KLIEGLIGHT"],
    # SLA narrowing — see intelligence_summary.py for the rationale. The
    # Intelligence Estimate consumes everything from IPOE plus targeting
    # outputs; narrow each upstream to its analytical body.
    "default_data_source_filter": {
        "upstream:Operational Environment Definition": ["paragraph_2",
                                                          "paragraph_3", "header"],
        "upstream:MCOO":                ["obstacles", "key_terrain",
                                          "avenues_of_approach",
                                          "cover_and_concealment_overlay", "header"],
        "upstream:TEM":                 ["rows", "header"],
        "upstream:WEM":                 ["rows", "header"],
        "upstream:CCA":                 ["rows", "header"],
        "upstream:Threat Overlay":      [],
        "upstream:SITEMP":              ["coas", "named_areas_of_interest", "header"],
        "upstream:Threat COA Statement":["coas", "header"],
        "upstream:HVTL":                ["rows", "header"],
        "upstream:HPTL":                ["rows", "header"],
        "upstream:Threat Model":        ["organizational_structure",
                                          "threat_overview",
                                          "preferred_tactics", "peculiarities",
                                          "options", "header"],
        "upstream:Threat Capability Statement": ["rows", "header"],
        "upstream:SIGSUM":              ["rows", "header"],
        "upstream:HUMINTSUM":           ["rows", "header"],
        "upstream:OSIR":                ["rows", "header"],
        "upstream:KLIEGLIGHT":          ["rows", "header"],
    },
    "header_fields": {
        # Fig E-2 explicit header lines: [CLASSIFICATION], appendix title with
        # OPORD number, References (Maps + doctrinal refs), Time Zone Used
        # Throughout the Order. Plus the standard preparing-unit / DTG fields
        # the wider IBL convention applies.
        "operation_order_number": {"source": "session", "view": "header",
                                     "required": True,
                                     "render_label": "OPORD Number",
                                     "guidance": (
                                         "OPORD identifier this appendix is part "
                                         "of (header line — 'APPENDIX 1 "
                                         "(INTELLIGENCE ESTIMATE) to ANNEX B "
                                         "(INTELLIGENCE) OPERATION ORDER 001'). "
                                         "Pull from the parent OPORD; never invent."
                                     )},
        "references_maps":        {"source": "session", "view": "header",
                                     "required": True,
                                     "default": "See base order.",
                                     "render_label": "References — Maps",
                                     "guidance": (
                                         "References (a): map list — by "
                                         "convention 'See base order.' when "
                                         "the OPORD's References paragraph "
                                         "already enumerates them."
                                     )},
        "references_doctrinal":   {"source": "session", "view": "header",
                                     "required": True,
                                     "default": "See base order.",
                                     "render_label": "References — Doctrinal",
                                     "guidance": (
                                         "References (b): underpinning "
                                         "publications. Default 'See base "
                                         "order.' when the OPORD already "
                                         "enumerates them."
                                     )},
        # time_zone_used_throughout_the_order dropped — every DTG in this
        # estimate carries an explicit Z suffix; a separate header field
        # repeating "ZULU" is redundant chrome.
        "dtg":                    HEADER_DTG,
        "area_of_operations":     HEADER_AO,
        # Upstream IPOE artifact links — every paragraph below should
        # cite back to one of these in _provenance.
        "oe_definition_artifact_id":      {"source": "upstream:OE Definition", "view": "internal", "required": False},
        "mcoo_artifact_id":               {"source": "upstream:MCOO", "view": "internal", "required": False,
                                             "depends_on": ["upstream:MCOO"]},
        "tem_artifact_id":                {"source": "upstream:TEM", "view": "internal", "required": False,
                                             "depends_on": ["upstream:TEM"],
                                             "render_label": "TEM (Tab A — Terrain)"},
        "wem_artifact_id":                {"source": "upstream:WEM", "view": "internal", "required": False,
                                             "depends_on": ["upstream:WEM"],
                                             "render_label": "WEM (Tab B — Weather)"},
        "cca_artifact_id":                {"source": "upstream:CCA", "view": "internal", "required": False,
                                             "depends_on": ["upstream:CCA"],
                                             "render_label": "CCA (Tab C — Civil Considerations)"},
        "threat_overlay_artifact_id":     {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                             "depends_on": ["upstream:Threat Overlay"]},
        "sitemp_artifact_id":             {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                             "depends_on": ["upstream:SITEMP"]},
        "threat_coa_statement_artifact_id":               {"source": "upstream:Threat COA Statement", "view": "internal", "required": True,
                                             "render_label": "Threat COA Statement (Tab D — Threat COA Statement Sketch)",
                                             "depends_on": ["upstream:Threat COA Statement"],
                                             "guidance": (
                                                 "Required: Para 1.c.(4) "
                                                 "explicitly references the Threat COA Statement "
                                                 "sketch (Exhibit 3 to Tab D). "
                                                 "Cannot publish an Intelligence "
                                                 "Estimate without an upstream "
                                                 "Threat COA Statement artifact."
                                             )},
        "hvtl_artifact_id":               {"source": "upstream:HVTL", "view": "internal", "required": False,
                                             "depends_on": ["upstream:HVTL"]},
        "hptl_artifact_id":               {"source": "upstream:HPTL", "view": "internal", "required": False,
                                             "depends_on": ["upstream:HPTL"]},
        "commander_signature_grade":      {"source": "session", "view": "header",
                                             "required": True,
                                             "default": "BG",
                                             "render_label": "Commander Grade",
                                             "guidance": (
                                                 "Signature-block grade "
                                                 "(e.g. BG, MG, COL). "
                                                 "ACKNOWLEDGE / COMMANDER line."
                                             )},
        "g2_authenticator_name":          {"source": "session", "view": "header",
                                             "required": True,
                                             "render_label": "G-2 Authenticator",
                                             "guidance": (
                                                 "OFFICIAL / G-2 signature "
                                                 "block name (e.g. DEBORD / G-2)."
                                             )},
        "prepared_by":         HEADER_PREPARED_BY,
        "classification":         HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        # ===================== PARAGRAPH 1 — SITUATION =====================
        # Para1 — Situation. Decomposed into a, b, c, d, e, f, g
        # subparagraphs. Para 1.b.(1)(2) Terrain/Weather → Tab A/B references.
        # Para 1.c is the Enemy Forces analytical core: composition, disposition,
        # capability, Threat COA Statement. Para 1.e is Civil Considerations → Tab C reference.
        {"name": "paragraph_1a_area_of_interest",
         "view": "published",
         "shape": "string",
         "render_label": "1.a. Area of Interest",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 1.a — Area of Interest. The IBL implementation embeds "
             "the AOI definition inline AND cites the OE Definition artifact "
             "id in _provenance (the AOI was set in Step-1 IPOE). One "
             "paragraph: AOI boundary description + the rationale linking it "
             "to the mission."
         )},
        {"name": "paragraph_1b_area_of_operations",
         "view": "published",
         "shape": "dict",
         "render_label": "1.b. Area of Operations",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 1.b — Area of Operations, with mandatory (1) Terrain and "
             "(2) Weather subparagraphs. 'See Tab A / Tab B' is acceptable IF "
             "the corresponding TEM (terrain) / WEM (weather) artifact id is "
             "populated in the header and a 1-sentence summary sits in the "
             "subfield. Cite tem_artifact_id / wem_artifact_id / "
             "mcoo_artifact_id in _provenance for the matching subfield."
         ),
         "subfields": ["area_of_operations_description",
                        "terrain_summary_tab_a",
                        "weather_summary_tab_b"],
         "depends_on": [
             "upstream:TEM",
             "upstream:WEM",
         ]},
        {"name": "paragraph_1c_enemy_forces",
         "view": "published",
         "shape": "dict",
         "render_label": "1.c. Enemy Forces",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 1.c — Enemy Forces, the analytical core of the "
             "Intelligence Estimate. MANDATORY subparagraphs: (1) Composition, "
             "(2) Disposition, (3) Capability, (4) ECOAs. Composition = "
             "identification + organization of the threat force (echelon, "
             "formation type). Disposition = current geographic deployment "
             "and posture. Capability = combat readiness, force ratios, and "
             "key system holdings (e.g. '80% operational-readiness'). "
             "enemy_courses_of_action MUST cite the Threat COA Statement artifact in "
             "_provenance and use the COA labels verbatim from that Threat COA Statement — "
             "Para 1.c.(4) explicitly references the Threat COA Statement Sketch under Tab D."
         ),
         "subfields": ["composition",
                        "disposition",
                        "capability",
                        "enemy_courses_of_action"],
         "depends_on": [
             "upstream:Threat COA Statement",
         ]},
        {"name": "paragraph_1c_prime_friendly_forces",
         "view": "published",
         "shape": "string",
         "render_label": "1.c (cont). Friendly Forces",
         "required": True,
         "guidance": (
             "Second 1.c paragraph — the published template has TWO sibling "
             "1.c paragraphs (Enemy Forces and Friendly Forces); both are "
             "preserved here. 'See Annex A (Task Organization).' is the "
             "default. Override only if the estimate has its own "
             "friendly-forces analytical content."
         )},
        {"name": "paragraph_1d_interagency_intergovernmental_and_nongovernmental_organizations",
         "view": "published",
         "shape": "string",
         "render_label": "1.d. Interagency, Intergovernmental, and Nongovernmental Organizations",
         "required": True,
         "guidance": (
             "Para 1.d. Default cross-reference 'See Annex V (Interagency "
             "Coordination).' acceptable when Annex V exists. Otherwise: "
             "short summary of in-AO IGO/NGO presence relevant to the "
             "threat picture (refugee corridors, medical NGOs, OSCE observer "
             "teams, etc.)."
         )},
        {"name": "paragraph_1e_civil_considerations",
         "view": "published",
         "shape": "string",
         "render_label": "1.e. Civil Considerations",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 1.e — cross-reference 'See Tab C (Civil Considerations) "
             "to this appendix.' acceptable when cca_artifact_id is "
             "populated. Inline: 1-3 sentences naming the ASCOPE "
             "characteristics (areas / structures / capabilities / "
             "organizations / people / events) that materially shape the "
             "threat picture. Cite cca_artifact_id in _provenance."
         )},
        {"name": "paragraph_1f_attachments_and_detachments",
         "view": "published",
         "shape": "string",
         "render_label": "1.f. Attachments and Detachments",
         "required": True,
         "guidance": (
             "Para 1.f — default 'See Annex B (Intelligence).' Most cycles "
             "delegate this to the parent annex; populate inline only when "
             "intel-specific attachments (e.g. attached HUMINT Collection "
             "Team, attached MI battalion DS slice) belong here."
         )},
        {"name": "paragraph_1g_assumptions",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "1.g. Assumptions",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Para 1.g — intelligence assumptions made during MDMP that bear "
             "on the threat picture. Each assumption is one row: short "
             "statement + the OPORD / IPOE artifact that drove it. Cite "
             "source in _provenance. 'See Annex B (Intelligence).' is "
             "acceptable when the parent annex's assumptions paragraph is "
             "the canonical list; otherwise enumerate here."
         ),
         "item_subfields": [
             {"name": "assumption_text", "render_label": "Assumption",
              "required": True,
              "guidance": "Statement of the assumption. One sentence."},
             {"name": "basis", "render_label": "Basis",
              "required": True,
              "guidance": (
                  "Why this assumption is being made — the upstream OPORD "
                  "paragraph or IPOE artifact that drove it."
              )}]},
        # ===================== PARAGRAPH 2 — MISSION =====================
        # Fig E-2 has Para 2 as a one-liner 'See Annex B (Intelligence).'
        # which is the parent annex's restated mission. We preserve that
        # convention.
        {"name": "paragraph_2_mission",
         "view": "published",
         "shape": "string",
         "render_label": "2. Mission",
         "required": True,
         "guidance": (
             "Para2 — restated mission. 'See Annex B "
             "(Intelligence).' is the doctrinal default (the parent annex "
             "carries the mission statement). Override only if the estimate "
             "is published as a stand-alone product disconnected from the "
             "parent OPORD."
         )},
        # ===================== PARAGRAPH 3 — EXECUTION =====================
        {"name": "paragraph_3_execution",
         "view": "published",
         "shape": "string",
         "render_label": "3. Execution",
         "required": True,
         "guidance": (
             "Para3 — 'See Annex B (Intelligence).' default. "
             "The execution scheme of intelligence support lives in the "
             "parent annex (Para 3.a Scheme of Intelligence Support)."
         )},
        # ===================== PARAGRAPH 4 — SUSTAINMENT =====================
        {"name": "paragraph_4_sustainment",
         "view": "published",
         "shape": "string",
         "render_label": "4. Sustainment",
         "required": True,
         "guidance": (
             "Para4 — 'See Annex B (Intelligence).' default."
         )},
        # ===================== PARAGRAPH 5 — COMMAND AND SIGNAL =====================
        {"name": "paragraph_5_command_and_signal",
         "view": "published",
         "shape": "string",
         "render_label": "5. Command and Signal",
         "required": True,
         "guidance": (
             "Para5 — 'See Annex B (Intelligence).' default. "
             "Command and Signal lives in Annex B Para 4 and is "
             "cross-referenced from here."
         )},
        # ===================== ATTACHMENTS LIST =====================
        # Fig E-2 publishes the Tab A–D list. This is a static convention
        # field rather than an analytical one — the runner emits the four
        # tab pointers regardless.
        {"name": "attachments_list",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Attachments",
         "required": True,
         "guidance": (
             "ATTACHMENTS block — Tab A (Terrain) / Tab B (Weather) / Tab C "
             "(Civil Considerations) / Tab D (Intelligence Preparation of "
             "the Battlefield-Products). Each row carries the tab name and "
             "the corresponding IPOE artifact id (TEM / WEM / CCA / "
             "SITEMP + Threat Overlay bundle). The IBL exporter does NOT generate "
             "separate tab pages — it surfaces them as artifact-id "
             "references in the rendered appendix."
         ),
         "depends_on": [
             "map:state",
             "upstream:CCA",
             "upstream:SITEMP",
             "upstream:TEM",
             "upstream:WEM",
         ],
         "item_subfields": [
             {"name": "tab_id", "render_label": "Tab",
              "required": True,
              "guidance": "Tab A / Tab B / Tab C / Tab D."},
             {"name": "tab_title", "render_label": "Title",
              "required": True,
              "guidance": (
                  "Terrain / Weather / Civil Considerations / Intelligence "
                  "Preparation of the Battlefield-Products."
              )},
             {"name": "source_artifact_id", "render_label": "Source Artifact",
              "required": False,
              "guidance": (
                  "Upstream artifact id this tab points to (TEM / WEM / CCA "
                  "/ SITEMP + Threat Overlay). May be blank if the tab is not yet "
                  "produced this MDMP cycle."
              )}]}],
    "subtleties": [
        "The Intelligence Estimate is the MDMP-time FORMAL estimate — it is published as Appendix 1 to Annex B (Intelligence) of the OPORD. Distinct from the Intelligence Running Estimate (continuously updated during execution) and from the INTSUM (periodic situation summary).",
        "The estimate's COA-development assessment (threat strengths, compositions, dispositions, vulnerabilities) is the COA-development driver for friendly MDMP and seeds future intelligence analytical requirements.",
        "Para 1.c carries the analytical CORE: Composition / Disposition / Capability / ECOAs. Everything in Para 2–5 is by convention 'See Annex B (Intelligence).' — the parent annex carries the operational text.",
        "Two sibling 1.c paragraphs (Enemy Forces and Friendly Forces) — the schema preserves both via paragraph_1c_enemy_forces and paragraph_1c_prime_friendly_forces.",
        "Para 1.c.(4) explicitly cites the Threat COA Statement Sketch under Tab D — Threat COA Statement is the only upstream IPOE artifact the estimate REQUIRES.",
        "Tab A (Terrain) maps to TEM, Tab B (Weather) maps to WEM, Tab C (Civil Considerations) maps to CCA, Tab D (IPB Products) bundles SITEMP / Threat Overlay / Threat COA Statement. The exporter cross-references the artifact ids; it does NOT regenerate tab pages.",
        "Every analytical paragraph carries _provenance citing the upstream IPOE artifact it draws from."],
    "hard_rules": [
        "5-paragraph OPORD-appendix order — Situation (1.a–g) → Mission (2) → Execution (3) → Sustainment (4) → Command and Signal (5). Never re-order or merge.",
        "Paragraph 1.c REQUIRES four subparagraphs verbatim: Composition / Disposition / Capability / Enemy Courses of Action.",
        "threat_coa_statement_artifact_id is REQUIRED in the header — Para 1.c.(4) explicitly cites the Threat COA Statement Sketch under Tab D. Cannot publish an Intelligence Estimate without an upstream Threat COA Statement.",
        "Threat COA Statement labels inside paragraph_1c_enemy_forces.enemy_courses_of_action MUST match the upstream Threat COA Statement product verbatim.",
        "Attachments list MUST carry all four tabs (A Terrain / B Weather / C Civil Considerations / D IPB-Products) — never elide a tab even when the source_artifact_id is blank.",
        "Every analytical paragraph cites _provenance (Para 1.a ↔ OE Definition, 1.b ↔ TEM/WEM/MCOO, 1.c ↔ Threat Overlay/SITEMP/Threat COA Statement, 1.e ↔ CCA, 1.g ↔ OPORD).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream IPOE chain: list_project_docs(filter={type:'OE Definition'}), {type:'MCOO'}, {type:'TEM'}, {type:'WEM'}, {type:'CCA'}, {type:'Threat Overlay'}, {type:'SITEMP'}, {type:'Threat COA Statement'}, {type:'HVTL'}, {type:'HPTL'} then get_project_doc",
        "Threat picture (Para 1.c Composition/Disposition — now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "Civil considerations (Para 1.e — now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures + sustainment kinds (Para 1.b spatial framing + sustainment annex — AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ + BSA/DSA/LSA/FLE/APOD/SPOD + MSR/ASR + LRP/ATP/ROM/MTF/CCP/MCP/Class III/V/VIII): get_spatial_overlay()",
        "Phased concept of operations (Estimate phase framing): get_phases() — current phase + decisive point + phase objectives",
        "Terrain context (Para 1.b.(1)): get_terrain()",
        "Weather context (Para 1.b.(2)): get_environmental()",
        "Parent OPORD (Mission, Execution, Sustainment, C2 cross-refs and Assumptions): get_project_doc(tag='OPORD'), get_project_doc(tag='ANNEX_B_INTEL')"],
    "post_emit_summary": "artifact_id, Threat COA Statement artifact cited, key composition/disposition/capability findings, threat COA list",
}

"""CCA — Civil Considerations Assessment — ATP 2-01.3 §4-96 ASCOPE×PMESII-PT.

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
    "name": "CCA",
    "output_format": "pptx",
    "shape": "matrix",
    # Landscape (pptx) — the ASCOPE × PMESII-PT matrix is 6-col × 8-row of
    # bullet-heavy civil-entity cells. Portrait gives ~0.8" per data column
    # which truncates entity names like "Tartu municipality (C-0101)";
    # landscape gives ~1.4" which fits. output_format implies orientation:
    # pptx → landscape 16:9 slide.
    "doctrine": {
        "purpose": (
            "Step-2 IPOE 3-part product family (data file + overlays + assessment) "
            "describing how civil considerations affect friendly + threat operations. "
            "ASCOPE × PMESII-PT 8-row × 6-col matrix (8 PMESII-PT lenses × 6 ASCOPE "
            "characteristics). Physical Environment + Time are the two lenses that "
            "extend PMESII to PMESII-PT; the unit defines what those rows contain."
            + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Matrix axes fixed: rows = PMESII-PT (8 — political, military, economic, social, information, infrastructure, physical_environment, time); columns = ASCOPE (6 — areas, structures, capabilities, organizations, people, events).",
    },
    # ASCOPE × PMESII-PT. Rollups (HUMINTSUM / OSIR) carry the cumulative
    # civic baseline; atomic HUMINT IIRs + Tactical OSINT Tippers carry
    # current-cycle civic events the rollup doesn't have yet.
    "consumes_artifacts": ["MCOO",
                            "HUMINTSUM", "OSIR"],
    "matrix_spec": {
        "field": "ascope_pmesii_pt_matrix",
        "row_axis": ["political", "military", "economic", "social",
                      "information", "infrastructure",
                      "physical_environment", "time"],
        "col_axis": ["areas", "structures", "capabilities",
                      "organizations", "people", "events"],
        "row_label": "PMESII-PT Lens",
        "col_label": "ASCOPE Characteristic",
    },
    "header_fields": {
        "dtg":                HEADER_DTG,
        "area_of_operations": HEADER_AO,
        "area_of_interest":   {"source": "session", "view": "header",
                                "required": True,
                                "render_label": "Area of Interest",
                                "default": "{area_of_operations}"},
        "prepared_by":        HEADER_PREPARED_BY,
        "mcoo_artifact_id":   {"source": "upstream:MCOO", "view": "internal",
                                "required": False,
                                "render_label": "MCOO Reference",
                                "depends_on": ["upstream:MCOO"],
                                "guidance": "for urban infrastructure overlap"},
        "classification":     HEADER_CLASSIFICATION,
    },
    # BLUF (issue #177): the two-minute commander summary renders first.
    "paragraph_render_order": ["commanders_summary"],
    "paragraph_fields": [
        {"name": "commanders_summary",
         "view": "published",
         "shape": "string",
         "render_label": "Analyst Note - Two-Minute Summary",
         "required": True,
         "provenance_required": True,
         "max_tokens": 1200,
         "depends_on": ["entities:civil", "entities:organization",
                        "entities:person", "documents"],
         "guidance": (
             "The two-minute brief: exactly what the analyst would say "
             "standing in front of the commander with two minutes on the "
             "clock — the overall civil impact on the operation, the two "
             "or three considerations that change decisions, and the one "
             "thing that must not be struck. Short declarative sentences; "
             "lead with the single most consequential impact."
         )},
        {"name": "civil_rfis",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Civil Considerations RFIs",
         "required": False,
         "provenance_required": True,
         "max_tokens": 3000,
         "depends_on": ["entities:civil", "documents",
                        "clauses:episodic"],
         "guidance": (
             "Requests for information covering the civil-considerations "
             "GAPS this assessment exposed — what the staff does not know "
             "about the civil environment that materially affects the "
             "operation. One row per gap; drive collection, never restate "
             "known facts."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "RFI",
              "guidance": "stable id (e.g., 'RFI-C-01')"},
             {"name": "question", "render_label": "Question",
              "provenance_required": True,
              "guidance": "the answerable question, PIR-style"},
             {"name": "gap", "render_label": "Gap",
              "guidance": "which civil consideration the answer closes"},
             {"name": "priority", "render_label": "Priority",
              "enum": ["high", "medium", "low"]}]},
        {"name": "ascope_pmesii_pt_matrix",
         "view": "published",
         "shape": "grid_table",
         "render_label": "ASCOPE × PMESII-PT Matrix",
         "required": True,
         "engine_join": "ascope_pmesii",
         "depends_on": [
             "matrix:ascope_pmesii",
         ],
         "guidance": (
             "ENGINE-CONSTRUCTED (2026-07-27 ruling) — no writer involvement. "
             "Each of the 48 cells is the mechanical tag join: entities whose "
             "ascope tags carry the COLUMN category, joined through clause_about "
             "to clauses whose pmesii tags carry the ROW facet. Cell display = "
             "entity names; per-cell _provenance = the entity's mark plus its "
             "supporting clauses' marks. Empty intersections stay honestly "
             "empty; all 8 rows x 6 columns always render. Tags are stamped at "
             "ingestion (assert_section clause pmesii / entity ascope) and "
             "corrected through the repair surface — a wrong cell is a wrong "
             "TAG, never a writer-prompt problem."
         )},
        {"name": "displaced_persons_overlay",
         "view": "published",
         "shape": "dict",
         "render_label": "Displaced Persons Overlay",
         "required": False,
         "depends_on": [
             "entities:civil",
         ],
         "guidance": (
             "Civil-considerations overlay highlighting refugee / IDP flows that "
             "could affect operations. Populate when the AO has active or anticipated "
             "displacement; leave empty otherwise. Identifying flows permits "
             "prepositioning of capabilities, materials, and humanitarian assistance. "
             "Pull displacement entities directly from the retrieval set. Cite "
             "their ref marks in _provenance."
         ),
         "subfields": ["camps", "movement_vectors", "expected_volume"],
         "subfield_guidance": {
             "camps": "Locations of refugee / IDP camps and temporary settlements (MGRS or named place; cite civil-affairs source).",
             "movement_vectors": "Anticipated displacement routes — origin → destination axes, road networks used, choke points.",
             "expected_volume": "Order-of-magnitude estimate (hundreds / thousands / tens-of-thousands) with the basis (e.g., 'population of affected districts ~50k per UN OCHA report').",
         }},
        {"name": "protected_targets_list",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Protected Targets List",
         "required": False,
         "depends_on": [
             "entities:civil",
         ],
         "guidance": (
             "G-9/S-9 (civil affairs) + chief of fires identify protected entities so "
             "they can be DECONFLICTED out of the HPTL during targeting. Examples "
             "include hospitals, religious sites, UNESCO World Heritage sites, ICRC "
             "facilities, water and food infrastructure. Cultural sites are generally "
             "protected by international law. Pull protected-entity records from the "
             "civil-considerations payload's relevant layers (structures / "
             "organizations / people). "
             "IDENTIFIER DISCIPLINE: PT-### row ids may be locally minted by the "
             "writer (one per row, monotonic), but the underlying entity MUST be "
             "a real entity from the retrieval set — cite its ref mark in "
             "_provenance. Leave empty if the AO genuinely has no such "
             "entities; do not fabricate."
         ),
         "item_subfields": [
             {"name": "id", "render_label": "ID",
              "guidance": "Stable identifier (e.g., 'PT-001')."},
             {"name": "name", "render_label": "Name",
              "guidance": "Specific named entity — 'Tartu University Hospital', 'St. Mary's Cathedral', 'Voru UNESCO archeological site'."},
             {"name": "type", "render_label": "Type",
              "enum": ["hospital", "religious-site", "cultural-heritage", "school",
                        "water-treatment", "NGO-facility", "ICRC-facility",
                        "UN-facility"],
              "enum_labels": {
                  "hospital":          "Hospital",
                  "religious-site":    "Religious Site",
                  "cultural-heritage": "Cultural Heritage",
                  "school":            "School",
                  "water-treatment":   "Water Treatment",
                  "NGO-facility":      "NGO Facility",
                  "ICRC-facility":     "ICRC Facility",
                  "UN-facility":       "UN Facility",
              },
              "guidance": "Category — hospital / religious-site / cultural-heritage / school / water-treatment / NGO-facility / ICRC-facility / UN-facility."},
             {"name": "protection_basis", "render_label": "Protection Basis",
              "enum": ["IHL_LOAC", "UNESCO", "religious", "ICRC"],
              "guidance": "IHL_LOAC for general LOAC-protected categories (medical / cultural / religious); UNESCO for designated World Heritage; religious for site protected by religious significance only; ICRC for International Committee of the Red Cross facilities."},
             {"name": "mgrs", "render_label": "Location",
              "guidance": "MGRS to 6- or 8-digit precision."}]},
        {"name": "narrative_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "Civil Considerations Assessment (Narrative)",
         "required": True,
         "max_tokens": 6000,
         "provenance_required": True,
         "depends_on": [
             "entities:civil", "entities:organization",
             "entities:person", "entities:nation",
             "documents", "clauses:episodic",
             "upstream:HUMINTSUM",
             "upstream:OSIR",
         ],
         "guidance": (
             "Civil-considerations ASSESSMENT proper. Draws on the ASCOPE × PMESII-PT "
             "matrix + overlays to synthesize: (1) social and political pattern map, "
             "(2) formal + informal leadership, (3) key societal friction points, "
             "(4) effects of friendly operations on the population (and expected "
             "population reactions), and (5) influence strategies (non-lethal "
             "engagement). For stability tasks, weight civil considerations heavily "
             "— a greater emphasis may need to be placed on civil considerations "
             "than on the enemy during stability tasks. Draw on the "
             "civil-considerations payload for the civil baseline + the project "
             "doc catalog (HUMINTSUM / OSIR) for cumulative civic context. "
             "When naming leaders, friction points, or specific entities, cite "
             "their ref marks in _provenance — narrative claims about named "
             "entities require a retrieval-set source.\n\n"
             "EMIT FORMAT — CRITICAL: Emit a dict with EXACTLY these five keys, "
             "EACH ON ITS OWN LINE in the JSON object, EACH carrying one paragraph:\n"
             "  - social_political_pattern_map\n"
             "  - formal_informal_leadership\n"
             "  - key_societal_friction_points\n"
             "  - friendly_operations_effects_on_population\n"
             "  - influence_strategies\n"
             "All five subfields are REQUIRED. Do NOT concatenate two subfield "
             "values into a single oversized key (e.g., never emit a key like "
             "`\"...prose-text-here,influence_strategies\"` which fuses the "
             "formal_informal_leadership value with the influence_strategies key "
             "name — that is a known writer-side JSON-emission bug). Keep each "
             "key on its own line; close every value string with `\"` BEFORE "
             "starting the next key."
         ),
         "subfields": ["social_political_pattern_map", "formal_informal_leadership",
                        "key_societal_friction_points", "friendly_operations_effects_on_population",
                        "influence_strategies"],
         "subfield_guidance": {
             "social_political_pattern_map": "Mapping of social + political patterns across the AO — ethnic/sectarian distribution, party-affiliation areas, shadow-government zones, tribal/clan dominance. Tie to the matrix POLITICAL + SOCIAL rows.",
             "formal_informal_leadership": "Both formal (elected officials, judges, military commanders) AND informal (elders, religious leaders, criminal-network leaders) authority figures — name them where possible.",
             "key_societal_friction_points": "Inter-ethnic / inter-sectarian / economic / generational fault lines and their flashpoints (markets, holidays, anniversaries).",
             "friendly_operations_effects_on_population": "Anticipated population reactions to planned friendly operations — both negative (displacement, infrastructure damage, civilian casualties risk) and positive (security, economic stimulus, governance restoration).",
             "influence_strategies": "Non-lethal engagement opportunities — key communicators, MISO themes, civil-affairs project priorities, partnered local leadership.",
         }}],
    "subtleties": [
        "CCA is a 3-part product family: (1) civil considerations DATA FILE organizing raw entities by ASCOPE; (2) OVERLAYS that depict the data file graphically (incl. displaced-persons overlay); (3) ASSESSMENT narrative synthesizing patterns and influence opportunities. This schema renders the matrix (which surfaces the data file), the displaced-persons overlay, the protected-targets list, and the narrative_assessment.",
        "ASCOPE × PMESII crosswalk is the analytical frame (6-row variant). PMESII-PT extension to 8 lenses adds Physical Environment + Time; the unit defines what goes in those two extension rows.",
        "G-9/S-9 leads CCA; G-2/S-2 collaborates — especially on threat-enabling civil networks (insurgent inform-and-influence, criminal organizations, shadow-government influence areas).",
        "Stability tasks weight civil considerations heavily — a greater emphasis may need to be placed on civil considerations than on the enemy during stability tasks.",
        "Protected-targets sub-list feeds HPTL deconfliction — G-9/S-9 + chief of fires identify protected; cultural sites are protected by international law.",
        "Displaced-persons overlay is CONDITIONAL — populate only when AO has active or anticipated refugee/IDP flows.",
        "Narrative_assessment is the synthesis layer covering: (a) social + political pattern mapping, (b) formal + informal leadership, (c) key societal friction points, (d) effects of friendly operations on the population, (e) influence strategies. Matrix supports it; assessment is the operationally useful output.",
        "Every matrix cell entry + every protected-target row + every narrative_assessment claim cites its retrieval-set marks in _provenance."],
    "hard_rules": [
        "Never invent civil entities. Every matrix cell entry, every protected-target row, every overlay element cites real retrieval-set members by ref mark in _provenance.",
        "Matrix axes are fixed and complete: 8 PMESII-PT rows × 6 ASCOPE columns = 48 cells. A cell may be empty if the AO has nothing in that intersection (e.g., MILITARY × Events may be empty during pure stability) — but every row and every column must appear in the rendered matrix.",
        "Matrix cells contain AO-specific real entries, NOT paraphrased generic boilerplate. 'enclaves; municipalities; provinces' is example text — replace with named municipalities/enclaves observed in this AO.",
        "Protected entities MUST set protection_basis (IHL_LOAC / UNESCO / religious / ICRC). A protected target without protection_basis is invalid output.",
        "Narrative_assessment must cover ALL FIVE investigation areas (social_political_pattern_map, formal_informal_leadership, key_societal_friction_points, friendly_operations_effects_on_population, influence_strategies). Emitting only 1–2 subfields is incomplete.",
        "Every analytical record carries _provenance.",
        PROVENANCE_HARD_RULE],
    "data_sources": [
        "Civil baseline (now merges OPORD-derived ASCOPE/PMESII rows extracted from scenario_ingest with the static fixture): get_civil()",
        "Per ASCOPE category: get_civil(layer='areas'), get_civil(layer='structures'), etc.",
        "Operations overlay control measures + sustainment kinds (civil annotations cross-ref — AO / boundaries / NAIs / NOGO/SLOWGO + MTF/CCP/Class VIII sustainment proximity): get_spatial_overlay()",
        "OPORD context: get_project_doc(tag='OPORD')",
        "MCOO upstream urban content: list_project_docs(filter={type:'MCOO'})"],
    "post_emit_summary": "artifact_id, populated cell count, key civil leaders / protected targets identified",
}

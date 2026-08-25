"""INTSUM — Intelligence Summary — ATP 2-33.4.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION,
    HEADER_PREPARED_BY,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "INTSUM",
    "output_format": "docx",
    "shape": "paragraph",
    # The INTSUM identifier IS the document title — exporter replaces the
    # doctrinal long-name "INTELLIGENCE SUMMARY" with the resolved
    # intsum_number ("INTSUM-<start>-<end>") and drops the row from the
    # header table so it doesn't duplicate.
    "title_field": "intsum_number",
    # V Corps OPORD reporting standard: forward INTSUMs every 12h, corps
    # every 24h. Default to the forward cadence; analyst can override per
    # cycle once that path is wired.
    "cadence_hours": 12,
    "doctrine": {
        "purpose": (
            "G-2/S-2 periodic publication of threat-situation assessment for the commander. "
            "Default = analytical narrative in 7 paragraphs; an 18-line transmission form is "
            "the alternate." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Paragraphs 1–7 in fixed order.",
    },
    # Tier 2 fused inputs + Tier 1 single-INT inputs (BOTH rollups AND
    # atomics). The discipline rollups (SIGSUM, HUMINTSUM, OSIR) carry
    # PRIOR-cycle baseline and trend assessment; atomic single-INT
    # products (TACELINT, KLIEGLIGHT, HUMINT IIR, IIR (GEOINT), RECCEXREP,
    # Tactical OSINT Tipper, INTREP) carry CURRENT-cycle collection that
    # hasn't been rolled up yet. Both matter: the rollup model works for
    # next-day reporting but fails the moment something significant
    # happens mid-cycle — the analyst pulls current-window atomics
    # directly to brief developing situations, then folds them with
    # yesterday's rollups for context.
    "consumes_artifacts": ["WEM", "TEM", "MCOO", "CCA", "Threat Overlay",
                            "SITEMP", "Threat COA Statement", "BDA",
                            "SIGSUM", "HUMINTSUM", "OSIR", "KLIEGLIGHT"],
    # SLA narrowing per the user's "use the field and row filtering
    # mechanisms like in SITEMP" directive. Every upstream artifact and
    # cougaar tool is narrowed to the keep-list a doctrinal INTSUM
    # actually needs. Renderer scaffolding (_provenance, _audit,
    # schema_state metadata, full map_overlays bbox dumps) are dropped
    # by omission. Per-field data_source_filter overrides this default
    # via dag_executor._apply_field_filters.
    "default_data_source_filter": {
        # Upstream artifact section-narrowing — keep the analytical
        # body, drop renderer scaffolding.
        "upstream:WEM":                 ["rows", "header"],
        "upstream:TEM":                 ["rows", "header"],
        "upstream:MCOO":                ["obstacles", "key_terrain",
                                          "avenues_of_approach",
                                          "cover_and_concealment_overlay", "header"],
        "upstream:CCA":                 ["rows", "header"],
        "upstream:Threat Overlay":      [],   # dep-edge only; no payload
        "upstream:SITEMP":              ["coas", "named_areas_of_interest", "header"],
        "upstream:Threat COA Statement":["coas", "header"],
        "upstream:BDA":                 ["rows", "header"],
        "upstream:SIGSUM":              ["rows", "header"],
        "upstream:HUMINTSUM":           ["rows", "header"],
        "upstream:OSIR":                ["rows", "header"],
        "upstream:KLIEGLIGHT":          ["rows", "header"],
        # cougaar.get_oob: bucketed RED + § 12 fusion extensions.
        # cougaar.get_recent_intel: only the fused observations array.
        # The per-observation raw_records explosion gets stripped by
        # dag_executor._slim_recent_intel before reaching the writer.
        # cougaar.list_targets: keep target rows + the no-geometry flag
        # so writer knows when to fall back to scenario MGRS.
        # cougaar.get_civil: civil considerations sites/events only.
        # cougaar project doc lookups: keep tag + body, drop the doc-
        # metadata wrapper.
    },
    "header_fields": {
        # Period-bracketed identifier. Two source-of-truth fields (period
        # start + period end); intsum_number is a computed string derived
        # from them. Multi-operator safe by construction — two INTSUMs
        # covering different periods naturally have different IDs; two
        # covering the same period are duplicate work, surfaced by a
        # uniqueness check on (preparing unit, period_start, period_end).
        # period_end_dtg = scenario canonical-now (full DDHHMMZmonYY anchor).
        # period_start_dtg = period_end_dtg - cadence_hours (12h forward INTSUM
        # per V Corps OPORD reporting standard). Both are computed by the
        # runner in _build_skeleton — the writer NEVER fills these.
        "period_start_dtg": {"source": "computed", "view": "header", "required": True,
                              "render_label": "Period Start"},
        "period_end_dtg":   {"source": "computed", "view": "header", "required": True,
                              "render_label": "Period End"},
        # Derived from period DTGs via _build_skeleton's template substitution
        # — empty if either period DTG is missing at skeleton time. The
        # exporter re-derives at render time so DocEditor edits to the
        # periods recompute the number live.
        "intsum_number":    {"source": "computed", "view": "header", "required": True,
                              "default": "INTSUM-{period_start_dtg}-{period_end_dtg}",
                              "render_label": "INTSUM Number",
                              "guidance": "Auto-derived from the period DTGs. Re-issued / corrected INTSUMs append -R<n>."},
        "prepared_by":      HEADER_PREPARED_BY,
        "wem_artifact_id":    {"source": "upstream:WEM", "view": "internal", "required": False,
                                 "depends_on": ["upstream:WEM"]},
        "sitemp_artifact_id": {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                 "depends_on": ["upstream:SITEMP"]},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal",
                                          "required": False,
                                          "depends_on": ["upstream:Threat Overlay"],
                                          "render_label": "Threat Overlay Reference"},
        "threat_coa_statement_artifact_id":   {"source": "upstream:Threat COA Statement", "view": "internal", "required": False,
                                 "depends_on": ["upstream:Threat COA Statement"]},
        "bda_artifact_id":    {"source": "upstream:BDA", "view": "internal", "required": False,
                                 "depends_on": ["upstream:BDA"]},
        "classification":     HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "paragraph_1_weather",
         "view": "published",
         "shape": "string",
         "render_label": "1. WEATHER",
         "required": True,
         "provenance_required": True,
         "guidance": "SWO + G-2 analysis on weather effects, current and 5-day forecast"},
        {"name": "paragraph_2_situation_highlights",
         "view": "published",
         "shape": "dict",
         "render_label": "2. SITUATION HIGHLIGHTS",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Operational-environment rollup across all 8 OE domains. One short paragraph "
             "per subfield summarizing what changed during the reporting period in THAT "
             "domain (not in general). Pull from recent intel + civil + CCA + cyber/EW "
             "reporting. Subfields not exercised this period get 'No significant activity "
             "reported.' — never delete a subfield.\n\n"

             "ELECTROMAGNETIC_SPECTRUM subfield specifically: read "
             "cougaar.get_recent_intel._ems_volume_summary (a per-INT raw-vertex + "
             "fused-observation rollup of SIGINT + ELINT + COMINT) BEFORE writing this "
             "subfield. Each fused observation in reports_by_source_int.SIGINT / .ELINT / "
             ".COMINT carries an evidence_text like '400 SIGINT detection(s) of signal X' — "
             "the integer in that string IS the raw-detection count; do NOT mistake the "
             "3-25 rows for the EMS volume. Whenever _ems_volume_summary.raw_vertices_total "
             "is > 100, characterize EMS activity by enumerating the per-INT counts and "
             "naming the signals/emitters where evidence_text identifies them. 'No "
             "significant activity reported' is correct ONLY when raw_vertices_total is 0. "
             "Same rule applies to CYBERSPACE / INFORMATION_ENVIRONMENT subfields when "
             "ELINT/COMINT evidence_text references cyber/EW emitters.\n\n"

             "AIR / MARITIME / SPACE / LAND subfields: pull from reports_by_source_int + "
             "imagery + the OOB current-disposition data (Tier-2 fused). Volume rollups in "
             "_per_vertex_counts are advisory — narrative comes from evidence_text + "
             "entity_name + observed_time. 'No significant activity reported' is correct "
             "only when no rows in any source_int bucket reference that domain.\n\n"

             "CIVIL_OR_OTHER_CONSIDERATIONS subfield: pull from cougaar.get_civil "
             "(displacement, infrastructure status, NGO presence) + artifact.CCA "
             "(critical infrastructure threat assessment)."
         ),
         "subfields": ["air", "land", "maritime", "space", "cyberspace",
                        "information_environment", "electromagnetic_spectrum",
                        "civil_or_other_considerations"],
         "depends_on": [
             "entities:civil",
             "clauses:episodic",
             "upstream:CCA",
         ]},
        {"name": "paragraph_3_summary_of_enemy_situation",
         "view": "published",
         "shape": "dict",
         "render_label": "3. SUMMARY OF THE ENEMY SITUATION",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "Threat-side rollup, by-domain. Distinct from Para 2 (which is OE-wide). "
             "Each subfield = current threat disposition and recent activity in that "
             "domain. 'other_domains' covers space/cyberspace/EMS/info if not addressed "
             "elsewhere; 'other' is the catch-all for civil, irregular, or proxy actors. "
             "Pull from the order of battle data + target catalog + recent Threat Overlay/SITEMP. Cite source artifacts."
         ),
         "subfields": ["land", "air", "maritime", "other_domains", "other"],
         "depends_on": [
             "entities:units",
             "entities:marked",
             "upstream:SITEMP",
         ]},
        {"name": "paragraph_4_unit_assessment",
         "view": "published",
         "shape": "dict",
         "render_label": "4. UNIT ASSESSMENT",
         "required": True,
         "provenance_required": True,
         "guidance": (
             "G-2 unit assessment of enemy COAs. BOTH most-likely AND most-dangerous are "
             "mandatory — distinct from the 18-line transmission form which only carries ML. "
             "Pull from the latest Threat COA Statement artifact (cite threat_coa_statement_artifact_id in _provenance). "
             "COA labels MUST match the Threat COA Statement product verbatim — this paragraph is the MDMP "
             "coupling. 'other' is for emerging / alternate COAs the analyst wants to surface."
         ),
         "subfields": ["most_likely_course_of_action",
                        "most_dangerous_course_of_action",
                        "other"],
         "depends_on": [
             "upstream:Threat COA Statement",
         ]},
        {"name": "paragraph_5_enemy_movement_during_reporting_period",
         "view": "published",
         "shape": "string",
         "render_label": "5. ENEMY MOVEMENT DURING THE REPORTING PERIOD",
         "required": True,
         "provenance_required": True,
         "guidance": "Major threat units, last-known positions (two levels below reporting command), DCGS-A pointer mandatory"},
        {"name": "paragraph_6_priority_intelligence_requirements",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "6. PIRs",
         "required": True,
         "guidance": (
             "All current PIRs from the OPORD / latest FRAGO, each tagged Answered or "
             "Unanswered for the reporting period. Pull PIR list from the OPORD "
             "or latest FRAGO via the project doc catalog. Use the SAME "
             "wording as the source — never paraphrase the PIR."
         ),
         "depends_on": [
             "documents",
             "documents",
         ],
         "item_subfields": [
             {"name": "requirement_text", "render_label": "PIR",
              "required": True,
              "guidance": "PIR text VERBATIM from OPORD / FRAGO — do not paraphrase."},
             {"name": "answered", "render_label": "Answered",
              "required": True,
              "guidance": "Yes / No / Partially. Computed against intel collected this reporting period."},
             {"name": "explanation_if_unanswered", "render_label": "Explanation if Unanswered",
              "required": False,
              "guidance": (
                  "Conditional. Populate only when `answered` is No or Partially. "
                  "Short note explaining the gap (e.g. 'collection asset weather-degraded', "
                  "'no observation opportunity this period'). For an Unanswered PIR with "
                  "no new context, 'No update this period' is acceptable. Leave blank "
                  "when `answered`==Yes."
              )}]},
        {"name": "paragraph_7_reports_and_distribution",
         "view": "published",
         "shape": "string",
         "render_label": "7. REPORTS AND DISTRIBUTION",
         "required": True,
         "guidance": "Distribution + subordinate reporting + DCGS-A procedures + authentication INSIDE Para 7"}],
    "subtleties": [
        "8 domain subparagraphs in Para 2 (exhaustive OE coverage).",
        "5-day weather window in Para 1.",
        "Both ML AND MD COAs in Para 4 — distinct from the 18-line transmission form which only has ML.",
        "COA labels in Para 4 must align with the MDMP wargame outputs.",
        "DCGS-A pointer in Para 5 — mandatory.",
        "Report authentication INSIDE Para 7, not separate line.",
        "Cadence: 24h higher echelons, 12h forward BCT/BN."],
    "hard_rules": [
        "All 7 paragraphs required, in fixed order — never re-order or merge.",
        "Para 4 must have BOTH most-likely AND most-dangerous COAs; COA labels must match the upstream Threat COA Statement artifact verbatim.",
        "Para 5 must include DCGS-A pointer.",
        "Para 6: requirement_text and answered are required for every PIR; explanation_if_unanswered is conditional (populate only when answered == No / Partially).",
        "Every paragraph cites upstream artifact (Para 1 ↔ SWO/get_environmental, Para 4 ↔ Threat COA Statement, Para 5 ↔ Threat Overlay/SITEMP/BDA, etc.).",
        PROVENANCE_HARD_RULE],
    "data_sources": [
        "Threat picture (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob(), list_targets()",
        "Recent activity in window: get_recent_intel(window_hours=12, types=['report','engagement','imagery'])",
        "Weather + astronomical for period end: get_environmental(date=<period_end_dtg>)",
        "Civil considerations (now merges OPORD-derived ASCOPE/PMESII rows with the static fixture): get_civil()",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ — situation overview): get_spatial_overlay()",
        "Phased concept of operations (current-phase situation framing): get_phases() — current phase + decisive point + phase objectives",
        "Terrain context: get_terrain()",
        "Scenario static: get_project_doc(tag='OPORD'), get_project_doc(tag='ANNEX_L_INTEL')",
        "Latest FRAGO: list_project_docs(filter={type:'FRAGO'}) then get_project_doc",
        "Prior INTSUM: list_project_docs(filter={type:'INTSUM'}) then get_project_doc",
        "Recent Threat COA Statement: list_project_docs(filter={type:'Threat COA Statement'}) then get_project_doc",
        "Latest WEM/TEM/MCOO/CCA/Threat Overlay/SITEMP/BDA: list_project_docs + get_project_doc"],
    "post_emit_summary": "artifact_id, salient finding (key threat development / PIR shift / doctrinal-next recommendation)",
}

"""SITREP — Situation Report — FM 6-99 18-line.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION, HEADER_DTG, HEADER_PREPARED_BY, PRECEDENCE_ENUM,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "SITREP",
    "output_format": "docx",
    "shape": "lines",
    "doctrine": {
        "purpose": (
            "Commander's integrated situation report to higher HQ — own forces / intel / "
            "logistics / comms / personnel / political-military-diplomatic events / "
            "commander's evaluation. 18 lines, event-triggered." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Lines 1–18 in the fixed 18-line order.",
    },
    # INTSUM + BDA + Tier 1 time-perishable tippers (Tactical OSINT Tipper
    # and KLIEGLIGHT feed SITREP Line 11 "Intelligence" between INTSUM
    # cycles per SINGLE_INT_WORKFLOW_INTEGRATION.md).
    "consumes_artifacts": ["INTSUM", "BDA", "KLIEGLIGHT", "PIR"],
    "header_fields": {
        "originator_call_sign": {"source": "session", "view": "header", "required": True,
                                   "render_label": "Originator"},
        "addressee_call_sign":  {"source": "session", "view": "header", "required": True,
                                   "render_label": "Addressee"},
        "precedence":           {"source": "session", "view": "header", "required": True,
                                   "default": "PRIORITY",
                                   "render_label": "Precedence",
                                   "enum": PRECEDENCE_ENUM},
        "dtg":                  HEADER_DTG,
        "prepared_by":       HEADER_PREPARED_BY,
        "intsum_artifact_id":   {"source": "upstream:INTSUM", "view": "internal", "required": False,
                                   "depends_on": ["upstream:INTSUM"]},
        "bda_artifact_id":      {"source": "upstream:BDA", "view": "internal", "required": False,
                                   "depends_on": ["upstream:BDA"]},
        "pir_artifact_id":      {"source": "upstream:PIR", "view": "internal", "required": False,
                                  "render_label": "PIR Reference",
                                  "depends_on": ["upstream:PIR"],
                                  "guidance": (
                                      "PIR artifact whose questions Line 7 (PIR status / current "
                                      "PIRs) reports against. SITREP Line 7 is a running update on "
                                      "PIR status (open / partial / answered / closed) — cite the "
                                      "PIR artifact_id so the analyst can trace each line item back "
                                      "to its commander-approved question."
                                  )},
        "classification":       HEADER_CLASSIFICATION,
    },
    "paragraph_fields": [
        {"name": "line_1_date_and_time", "view": "published", "shape": "string",
         "render_label": "Line 1 — Date and Time", "required": True,
         "guidance": "DTG format DDHHMM(X) MMMYY"},
        {"name": "line_2_unit", "view": "published", "shape": "string",
         "render_label": "Line 2 — Unit", "required": True},
        {"name": "line_3_reported_unit", "view": "published", "shape": "string",
         "render_label": "Line 3 — Reported Unit", "required": True},
        {"name": "line_4_home_location_mgrs", "view": "published", "shape": "string",
         "render_label": "Line 4 — Home Location", "required": True},
        {"name": "line_5_present_location_mgrs", "view": "published", "shape": "string",
         "render_label": "Line 5 — Present Location", "required": True},
        {"name": "line_6_activity", "view": "published", "shape": "string",
         "render_label": "Line 6 — Activity", "required": True},
        {"name": "line_7_combat_effectiveness", "view": "published", "shape": "string",
         "render_label": "Line 7 — Effective", "required": True,
         "guidance": "commander's combat-effectiveness evaluation (free text; common practice = GREEN/AMBER/RED/BLACK or C-ratings)"},
        {"name": "line_8_own_situation_disposition_status", "view": "published", "shape": "string",
         "render_label": "Line 8 — Own Situation Disposition/Status", "required": True},
        {"name": "line_9_situation_overview", "view": "published", "shape": "string",
         "render_label": "Line 9 — Situation Overview", "required": True,
         "provenance_required": True,
         "guidance": (
             "Commander's narrative overview of the situation this period — what the "
             "unit is doing, where it is in the operation, what changed. Synthesizes "
             "Lines 6/8 with operational context. Cite OPORD / FRAGO and any anchor "
             "INTSUM/BDA. Lines 10–15 will then dive into functional detail."
         ),
         "depends_on": [
             "upstream:BDA",
             "upstream:INTSUM",
         ]},
        {"name": "line_10_operations", "view": "published", "shape": "string",
         "render_label": "Line 10 — Operations", "required": True,
         "provenance_required": True,
         "guidance": "report-period offensive/defensive results + next-24h plans"},
        {"name": "line_11_intelligence", "view": "published", "shape": "string",
         "render_label": "Line 11 — Intelligence", "required": True,
         "provenance_required": True,
         "guidance": "references SPOTREPs/INTREPs/INTSUM from previous 24h",
         "depends_on": [
             "upstream:INTSUM",
         ]},
        {"name": "line_12_logistics", "view": "published", "shape": "string",
         "render_label": "Line 12 — Logistics", "required": False},
        {"name": "line_13_communications_connectivity", "view": "published", "shape": "string",
         "render_label": "Line 13 — Communications/Connectivity", "required": False},
        {"name": "line_14_personnel", "view": "published", "shape": "string",
         "render_label": "Line 14 — Personnel", "required": False},
        {"name": "line_15_political_military_diplomatic_events", "view": "published", "shape": "string",
         "render_label": "Line 15 — POL/MIL/DIP Events", "required": False},
        {"name": "line_16_commanders_evaluation_summary_of_lines_9_through_15",
         "view": "published", "shape": "string",
         "render_label": "Line 16 — Commander's Evaluation", "required": True,
         "guidance": (
             "Commander's synthesis across Lines 9–15 ONLY (situation overview, "
             "operations, intelligence, logistics, comms, personnel, POL/MIL/DIP). "
             "Do NOT re-summarize Lines 1–8 (those are header / disposition). "
             "1–3 sentences. This is the commander's bottom-line judgment, not a "
             "staff product."
         )},
        {"name": "line_17_narrative", "view": "published", "shape": "string",
         "render_label": "Line 17 — Narrative", "required": False,
         "guidance": (
             "Optional free-text narrative. Use ONLY when something doesn't fit Lines "
             "9–16 (background context, coordination notes, follow-on intent). Lines "
             "may not be deleted from the format — if you have no narrative to add, "
             "emit the literal string 'None this period.' so the line is present but "
             "explicitly empty."
         )},
        # `civilian_situation` is NOT one of the FM 6-99 18 lines — it is an
        # additional published paragraph that exists primarily to attach a
        # `cougaar.get_civil` retrieval node onto SITREP's DAG. Walks 4 + 5
        # failed SITREP with `FABRICATED_IDENTIFIERS: ['C-011']` because the
        # writer referenced civil entities in Lines 9 / 11 / 15 narrative but
        # the DAG had no get_civil retrieval, so `seen_ids` was empty and
        # `_validate_emit.detect_fabricated_ids()` flagged legitimate C-### IDs
        # as fabricated. Adding this paragraph fires the retrieval node;
        # `dag_executor.harvest_seen_ids` then seeds `state.seen` with C-### IDs
        # before validation runs.
        #
        # The render path for shape=='lines' filters on field names starting
        # with `line_`, so this field will not appear in the printed 18-line
        # SITREP — exactly the desired behaviour (FM 6-99 doctrine forbids
        # extra lines). The content the writer authors here is harvested for
        # cross-line citation context only.
        {"name": "civilian_situation", "view": "published", "shape": "string",
         "render_label": "Civil-Side Situation (internal — feeds Lines 9/11/15)",
         "required": False,
         "provenance_required": True,
         "guidance": (
             "Civil-side situation across the AO during this reporting period — "
             "civilian casualties, displaced-persons movements, protected-site "
             "status, sympathetic populations. Source data: the civil ASCOPE/PMESII "
             "rollup — pull civil-entity records by C-### ID and reference them "
             "VERBATIM. Cite the source vertex in _provenance "
             "(civil.events.C-### / civil.areas.C-###). This text feeds "
             "the writer's authorship of Lines 9 (Situation Overview), 11 "
             "(Intelligence), and 15 (POL/MIL/DIP Events); it does not print "
             "as its own line per FM 6-99 doctrine."
         ),
         "depends_on": [
             "entities:civil",
         ]},
        {"name": "line_18_authentication", "view": "published", "shape": "string",
         "render_label": "Line 18 — Authentication", "required": True}],
    "subtleties": [
        "SITREP is COMMANDER-OWNED; integrated across warfighting functions. INTSUM is G-2-owned, intel-only.",
        "Line 11 references previous-24h SPOTREPs/INTREPs/INTSUM by reference; doesn't embed them.",
        "Line 16 = synthesis of Lines 9–15 only (NOT 1–8).",
        "Lines may NOT be deleted from format; originator completes only essential lines; negative report may be required.",
        "UNITSITREP is a DIFFERENT product (28 lines). Not this artifact."],
    "hard_rules": [
        "Line numbers + names may not be deleted from the format; originator fills only essential lines, negative report may be required.",
        "DTG format DDHHMM(X) MMMYY.",
        "Locations default 6-digit MGRS with grid-zone designator.",
        "Line 16 summarizes Lines 9–15 ONLY — never re-summarize Lines 1–8.",
        "Authentication on Line 18.",
        "Lines 9/10/11 cite source artifacts (Line 11 references — not embeds — previous-24h SPOTREPs/INTREPs/INTSUM).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "INTSUM upstream: list_project_docs(filter={type:'INTSUM'}) then get_project_doc",
        "BDA upstream: list_project_docs(filter={type:'BDA'}) then get_project_doc",
        "Recent intel: get_recent_intel(window_hours=24)",
        "Threat picture (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob(), list_targets()",
        "Civil considerations (now merges OPORD-derived ASCOPE/PMESII rows with the static fixture — Line 9/11/15 narrative): get_civil()",
        "Operations overlay control measures (AO / boundaries / phase lines / axes / NAIs / TAIs / EAs / OBJ / NOGO/SLOWGO) — Line 9 situation overview cites phase lines / boundaries / axes: get_spatial_overlay()",
        "Sustainment overlay (BSA/DSA/LSA/FLE/APOD/SPOD + MSR/ASR lines + LRP/ATP/ROM/MTF/CCP/MCP/Class III/V/VIII points) — Line 12 logistics: get_spatial_overlay()",
        "Phased concept of operations (Line 9 current-phase framing): get_phases() — current phase + decisive point + phase objectives",
        "OPORD: get_project_doc(tag='OPORD')"],
    "post_emit_summary": "artifact_id, salient finding (key Line 9–15 highlight)",
}

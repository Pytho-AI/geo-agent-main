"""CARVER — CARVER Target Value Analysis — FM 3-60 App. G + Table G-1.

See templates/__init__.py for the assembled PRODUCT_SCHEMAS map.
"""
from ..common import (
    HEADER_CLASSIFICATION,
    HEADER_DTG,
    HEADER_PHASE,
    HEADER_PREPARED_BY,
    SCORE_1_5_ENUM,    # kept for the FM 3-60 alternate scale documented in guidance
    SCORE_1_10_ENUM,   # FM 34-36 default — 5 anchor pairs (9-10/7-8/5-6/3-4/1-2)
    TARGET_CATEGORY_ENUM,
    TARGET_CATEGORY_LABELS,
    PROVENANCE_DIRECTIVE,
    PROVENANCE_HARD_RULE,
)

SPEC = {
    "name": "CARVER",
    "output_format": "pptx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. G
    # Table G-1: target × 6 criteria + composite. Sort-by-composite-
    # descending is the doctrinal ordering rule — spreadsheet primitive.
    "output_formats": ["xlsx"],
    "legacy_formats": ["pptx"],
    "shape": "row",
    "doctrine": {
        "purpose": (
            "Target value analysis methodology to identify and rank specific targets "
            "(consumes HVTL, produces ranked scores → HPTL nomination input). Six "
            "criteria scored 1–5; composite total = sum (range 6–30). Same matrix "
            "scores both offensive (what to attack) and defensive (what to protect)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": "Rows ordered by composite_total_score descending (highest composite = highest priority for HPTL nomination).",
    },
    "order_by": {"field": "composite_total_score", "direction": "desc"},
    "row_source": "entities:marked",
    # Writer-controlled row-id selection. Without this CARVER would
    # score every kg_targets_active entry (the full candidate pool, ~200
    # rows for a corps fight). CARVER doctrinally is a SUBSET scoring
    # exercise — score the targets upstream HVTL + Threat COA Statement
    # elevated, not the full OOB. Mirrors HVTL row_id_selection_field
    # pattern (line 76).
    "row_id_selection_field": "selected_carver_kg_ids",
    # Threat Model is the Pytho analytical OPFOR abstraction CARVER
    # scoring needs (organizational_structure + threat_overview). Raw
    # DonovianDoctrine is NOT a dep — same anti-bloat rule HVTL applies.
    "consumes_artifacts": [
        "HVTL", "SITEMP", "Threat Overlay", "Threat Model",
    ],
    # Per-field upstream dep filter — narrows every CARVER field prompt to
    # the writer-relevant subsection of each artifact dep payload. Mirrors
    # HVTL default_data_source_filter (lines 101-129).
    "default_data_source_filter": {
        "upstream:HVTL": ["rows"],
        "upstream:Threat Model": ["organizational_structure", "threat_overview"],
        "upstream:Threat COA Statement": ["coas"],
        "upstream:SITEMP": [],
        "upstream:Threat Overlay": [],
    },
    "published_section_title": "CARVER Target Value Analysis",
    "header_fields": {
        # Phase defaults to Phase I (Penetration) via skeleton-fill —
        # matches HVTL line 136. CARVER must never publish with blank
        # phase header.
        "phase":              {**HEADER_PHASE, "default": "Phase I (Penetration)"},
        # Threat COA is now writer-derived from upstream HVTL + Threat
        # COA Statement (matches HVTL line 137-146 pattern). Drop the
        # session source — CARVER does not get the COA name from the
        # session middleware, it derives it from the upstream artifacts.
        "threat_coa":         {"source": "analytical", "view": "header",
                                 "required": True,
                                 "provenance_required": True,
                                 "render_label": "Threat COA",
                                 "depends_on": [
                                     "upstream:HVTL",
                                     "upstream:Threat COA Statement",
                                     "upstream:SITEMP",
                                 ],
                                 "guidance": (
                                    "Phase-scoped enemy COA the scoring applies to. CARVER "
                                    "scores are time-sensitive — refresh per phase. Pull "
                                    "from upstream HVTL header.threat_coa or Threat COA "
                                    "Statement coas[].name; cite the source artifact_id "
                                    "in _provenance."
                                 )},
        "dtg":                HEADER_DTG,
        # CARVER is doctrinally downstream of HVTL — make the reference
        # required so a CARVER without HVTL upstream raises a clear gap.
        "hvtl_artifact_id":   {"source": "upstream:HVTL", "view": "internal", "required": True,
                                 "render_label": "HVTL Reference",
                                 "depends_on": ["entities:marked", "upstream:HVTL"],
                                 "guidance": (
                                    "Reference the upstream HVTL artifact_id. "
                                    "CARVER is doctrinally downstream of HVTL — "
                                    "the published row pool is the HVT set elevated "
                                    "by the upstream HVTL + Threat COA Statement."
                                 )},
        "sitemp_artifact_id": {"source": "upstream:SITEMP", "view": "internal", "required": False,
                                 "render_label": "SITEMP Reference",
                                 "depends_on": ["upstream:SITEMP"]},
        "threat_overlay_artifact_id": {"source": "upstream:Threat Overlay", "view": "internal", "required": False,
                                          "render_label": "Threat Overlay Reference",
                                          "depends_on": ["upstream:Threat Overlay"]},
        "prepared_by":     HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        # Writer's analytical CARVER selection — list of kg_ids elevated
        # by upstream HVTL + Threat COA Statement that CARVER scores
        # this run. NSL/DEFEATED dropped at row-derivation. Singleton
        # wave — lands BEFORE the carver_scoring + carver_rationale
        # waves. Mirrors HVTL selected_hvt_kg_ids (lines 167-213).
        "selected_carver_kg_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            "render_label": "Selected CARVER kg_ids",
            "depends_on": [
                "upstream:HVTL",
                "upstream:Threat Model",
                "upstream:Threat COA Statement",
                "entities:marked",
            ],
            "guidance": (
                "Output: a JSON array of kg_id strings (T-XX#### shape). "
                "Each kg_id MUST verbatim-match an active list_targets "
                "entry. Selects the subset elevated by upstream HVTL + "
                "Threat COA Statement that CARVER scores this run. "
                "NSL-flagged + DEFEATED entries dropped at row derivation. "
                "NEVER list every active target — CARVER is a SUBSET "
                "scoring exercise. NEVER invent kg_ids."
            ),
        },
    },
    "row_fields": {
        "id":            {"source": "entity:id", "view": "internal",
                            "required": True, "provenance_required": True,
                            "render_label": "ID"},
        "name":          {"source": "entity:name", "view": "published",
                            "required": True, "render_label": "Target"},
        "category":      {"source": "entity:category", "view": "published",
                            "required": True, "render_label": "Category",
                            "enum": TARGET_CATEGORY_ENUM,
                            "enum_labels": TARGET_CATEGORY_LABELS},
        "location_mgrs": {"source": "entity:location_mgrs", "view": "published",
                            "required": False, "render_label": "Location"},
        "criticality_score":   {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "enum": SCORE_1_10_ENUM,
                                  "batch_group": "carver_scoring",
                                  "depends_on": ["selected_carver_kg_ids"],
                                  "render_label": "C",
                                  "guidance": (
                                    "Criticality — value of the target to the enemy. "
                                    "DEFAULT 1-10 anchors per FM 34-36 App. D: "
                                    "9-10 = immediate halt / cannot function without it; "
                                    "7-8 = halt within 1 day / ~66% curtailment; "
                                    "5-6 = halt within 1 week / ~33% curtailment; "
                                    "3-4 = halt within 10 days / ~10% curtailment; "
                                    "1-2 = no significant effect on enemy mission. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G Table G-1: "
                                    "5 ≈ 9-10; 4 ≈ 7-8; 3 ≈ 5-6; 2 ≈ 3-4; 1 ≈ 1-2."
                                  )},
        "criticality_rationale": {"source": "analytical", "view": "workpaper",
                                    "required": True, "provenance_required": True,
                                    "render_label": "Criticality Rationale",
                                    "batch_group": "carver_rationale",
                                    "depends_on": [
                                        "selected_carver_kg_ids",
                                        "criticality_score",
                                        "upstream:HVTL",
                                    ],
                                    "guidance": (
                                        "ONE sentence tying the score to function + critical "
                                        "elements (HVTL workpaper). Cite the source artifact."
                                    )},
        "accessibility_score": {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "enum": SCORE_1_10_ENUM,
                                  "batch_group": "carver_scoring",
                                  "depends_on": ["selected_carver_kg_ids"],
                                  "render_label": "A",
                                  "guidance": (
                                    "Accessibility — friendly attacker's ability to reach the "
                                    "target. DEFAULT 1-10 per FM 34-36 App. D: "
                                    "9-10 = easily accessible / standoff weapons feasible / "
                                    "outside any perimeter; "
                                    "7-8 = inside outer perimeter but outdoors; "
                                    "5-6 = inside a building, ground floor; "
                                    "3-4 = inside, upper floor or basement / climb or "
                                    "specialist entry required; "
                                    "1-2 = not accessible without extreme difficulty. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G: 5/4/3/2/1 collapses "
                                    "the pairs above (5 ≈ 9-10 … 1 ≈ 1-2)."
                                  )},
        "accessibility_rationale": {"source": "analytical", "view": "workpaper",
                                      "required": True, "provenance_required": True,
                                      "render_label": "Accessibility Rationale",
                                      "batch_group": "carver_rationale",
                                      "depends_on": [
                                          "selected_carver_kg_ids",
                                          "accessibility_score",
                                      ],
                                      "guidance": "Tie to terrain, ADA threat ring, standoff range; cite source."},
        "recuperability_score": {"source": "analytical", "view": "published",
                                   "required": True, "provenance_required": True,
                                   "enum": SCORE_1_10_ENUM,
                                   "batch_group": "carver_scoring",
                                   "depends_on": ["selected_carver_kg_ids"],
                                   "render_label": "R",
                                   "guidance": (
                                    "Recuperability — time for enemy to replace / repair / "
                                    "bypass. DEFAULT 1-10 per FM 34-36 App. D: "
                                    "9-10 = 1+ month to repair or irreplaceable; "
                                    "7-8 = 1 week to 1 month; "
                                    "5-6 = 72 hours to 1 week; "
                                    "3-4 = 24-72 hours; "
                                    "1-2 = same-day replacement / spare on hand. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G collapses the pairs."
                                  )},
        "recuperability_rationale": {"source": "analytical", "view": "workpaper",
                                        "required": True, "provenance_required": True,
                                        "render_label": "Recuperability Rationale",
                                        "batch_group": "carver_rationale",
                                        "depends_on": [
                                            "selected_carver_kg_ids",
                                            "recuperability_score",
                                        ],
                                        "guidance": "Tie to enemy OOB depth, supply chain, FRAGO/OOB source."},
        "vulnerability_score": {"source": "analytical", "view": "published",
                                  "required": True, "provenance_required": True,
                                  "enum": SCORE_1_10_ENUM,
                                  "batch_group": "carver_scoring",
                                  "depends_on": ["selected_carver_kg_ids"],
                                  "render_label": "V",
                                  "guidance": (
                                    "Vulnerability — friendly means & expertise to defeat the "
                                    "target. DEFAULT 1-10 per FM 34-36 App. D: "
                                    "9-10 = defeatable by laser / small arms / light demolition; "
                                    "7-8 = light explosive charges sufficient; "
                                    "5-6 = moderate (~10-30 lb) charges; "
                                    "3-4 = heavy / specialized munitions required; "
                                    "1-2 = effectively invulnerable to available means. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G collapses the pairs."
                                  )},
        "vulnerability_rationale": {"source": "analytical", "view": "workpaper",
                                      "required": True, "provenance_required": True,
                                      "render_label": "Vulnerability Rationale",
                                      "batch_group": "carver_rationale",
                                      "depends_on": [
                                          "selected_carver_kg_ids",
                                          "vulnerability_score",
                                      ],
                                      "guidance": "Tie to delivery means available + hardening; cite recent engagement evidence."},
        "effect_score":       {"source": "analytical", "view": "published",
                                 "required": True, "provenance_required": True,
                                 "enum": SCORE_1_10_ENUM,
                                 "batch_group": "carver_scoring",
                                 "depends_on": ["selected_carver_kg_ids"],
                                 "render_label": "E",
                                 "guidance": (
                                    "Effect — broader military / political / economic / "
                                    "psychological / sociological impact of striking the target "
                                    "(wider than Criticality). DEFAULT 1-10 per FM 34-36 App. D: "
                                    "9-10 = overwhelmingly positive friendly effect, no negatives; "
                                    "7-8 = moderately positive; "
                                    "5-6 = mixed / neutral; "
                                    "3-4 = moderately negative second-order effects; "
                                    "1-2 = overwhelmingly negative effects, no positives. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G collapses the pairs."
                                  )},
        "effect_rationale":   {"source": "analytical", "view": "workpaper",
                                 "required": True, "provenance_required": True,
                                 "render_label": "Effect Rationale",
                                 "batch_group": "carver_rationale",
                                 "depends_on": [
                                     "selected_carver_kg_ids",
                                     "effect_score",
                                 ],
                                 "guidance": "Call out non-military second-order effects explicitly (e.g. civilian impact, allied perception)."},
        "recognizability_score": {"source": "analytical", "view": "published",
                                    "required": True, "provenance_required": True,
                                    "enum": SCORE_1_10_ENUM,
                                    "batch_group": "carver_scoring",
                                    "depends_on": ["selected_carver_kg_ids"],
                                    "render_label": "R̂",
                                    "guidance": (
                                    "Recognizability — degree to which the target is "
                                    "identifiable by the attacker under operational conditions. "
                                    "DEFAULT 1-10 per FM 34-36 App. D: "
                                    "9-10 = clearly recognizable by all observers under all "
                                    "conditions; "
                                    "7-8 = easily recognized by most with little confusion; "
                                    "5-6 = recognized with some training and time on target; "
                                    "3-4 = hard to recognize / specialist training required; "
                                    "1-2 = extremely difficult to recognize / expert-only. "
                                    "ALTERNATE 1-5 per FM 3-60 App. G collapses the pairs."
                                  )},
        "recognizability_rationale": {"source": "analytical", "view": "workpaper",
                                        "required": True, "provenance_required": True,
                                        "render_label": "Recognizability Rationale",
                                        "batch_group": "carver_rationale",
                                        "depends_on": [
                                            "selected_carver_kg_ids",
                                            "recognizability_score",
                                            "upstream:HVTL",
                                        ],
                                        "guidance": "Tie to detection_signatures from HVTL workpaper (visual/IR/SAR/SIGINT band)."},
        "composite_total_score": {"source": "analytical", "view": "published",
                                    # Live Excel formula — the xlsx_exporter
                                    # writes the formula cell at render time
                                    # (xlsx_exporter.py:131-134). Writer LLMs
                                    # were emitting 0 into structured_data,
                                    # which then broke the downstream HPTL
                                    # workpaper consumption (extract reads 0
                                    # instead of the formula result).
                                    # Mark not-required + default=None so
                                    # the writer NEVER fills this field.
                                    "formula": "sum:criticality_score,accessibility_score,recuperability_score,vulnerability_score,effect_score,recognizability_score",
                                    "required": False,
                                    "default": None,
                                    "render_label": "Total",
                                    "guidance": (
                                        "DO NOT emit a numeric value here — "
                                        "the exporter computes via live Excel "
                                        "formula. Emit null and let the "
                                        "formula resolve at render time. "
                                        "FM 3-60 App. G Table G-1 defines "
                                        "composite = sum of all six; the "
                                        "formula path supersedes the writer "
                                        "value."
                                    )},
    },
    "subtleties": [
        "Two anchored scales are doctrinally published: FM 34-36 App. D "
        "(SOF Intelligence + EW Ops) uses 1-10 in five anchor pairs "
        "(9-10/7-8/5-6/3-4/1-2). FM 3-60 Aug 2023 App. G Table G-1 "
        "(conventional Army Targeting) uses 1-5 single-anchor. DEFAULT "
        "is 1-10 per FM 34-36 (the IDX 26 reference sample uses this); "
        "FM 3-60 1-5 collapses each pair into one value and remains valid "
        "for outputs that must align with FM 3-60 conventional Army.",
        "Composite = simple sum. Range 6-60 on the 1-10 default; range "
        "6-30 on the 1-5 FM 3-60 variant. Weighted CARVER variants are "
        "alternates and are NOT used here.",
        "Time-sensitive: scores must refresh across phases. Same target may carry different composites in different phases of the same operation.",
        "Effect criterion is broader than Criticality — includes military/political/economic/psychological/sociological effects.",
        "Dual-use: same matrix scores defensive (what to protect) and offensive (what to attack).",
        "Top-N directives: 'top three Phase 2 HVTs' is honored by the runner via _parse_top_n; the skeleton is sized to N rows so the writer doesn't trip the gap detector on unfilled tail rows.",
        "Doctrinal next: CARVER → HPTL (commander applies friendly-side priority on top of CARVER ranking).",
        "Every score + rationale cites source.",
    ],
    "hard_rules": [
        "All six scores required per row.",
        "Scores are integers from the active scale: DEFAULT 1-10 "
        "(SCORE_1_10_ENUM per FM 34-36 App. D), ALTERNATE 1-5 "
        "(SCORE_1_5_ENUM per FM 3-60 App. G). Both scales validate.",
        "composite_total_score = INTEGER sum of the six scores. Range 6-60 "
        "on the 1-10 default, 6-30 on the 1-5 alternate. No weighted variants.",
        "Rank by composite_total_score DESC (highest = highest priority); ties broken by Criticality, then Effect.",
        "Never invent ids — kg_targets_active is the candidate pool; the writer selects the subset elevated by the upstream HVTL + Threat COA via selected_carver_kg_ids. DEFEATED entries are excluded at row derivation.",
        "Cite source for every score in _provenance (per-criterion or row-level).",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "HVTL upstream: list_project_docs(filter={type:'HVTL'}) then get_project_doc(tag=<latest>)",
        "Target candidates: list_targets()",
        "Threat structure (now merges OPORD-derived threat-disposition rows + Road-to-War vectors): get_oob()",
        "SITEMP: list_project_docs(filter={type:'SITEMP'})",
        "Threat Overlay: list_project_docs(filter={type:'Threat Overlay'})",
        "Recent engagements (vulnerability evidence): get_recent_intel(types=['engagement','imagery'])",
        "OPORD context: get_project_doc(tag='OPORD')",
        "Threat OOB reference: get_project_doc(tag='OOB')",
        "Operations overlay control measures (operational context — axis / OBJ / EA / NAI / TAI proximity drives accessibility + recognizability scoring): get_spatial_overlay()",
        "Phased concept of operations (CARVER scoring shifts by phase): get_phases() — current phase + decisive point + phase objectives",
        "Prior CARVER (regen): list_project_docs(filter={type:'CARVER'}) then get_project_doc",
    ],
    "post_emit_summary": "artifact_id, row count, top 3 by composite_total_score",
}

"""TSS — Target Selection Standards — paras 2-16 – 2-18 + App. D Table D-2.

D3A Decide-phase product. TSS are the gating criteria the FSE + intelligence
section agree on so a battlefield acquisition can be declared a TARGET (vs a
SUSPECTED TARGET that still needs confirmation)6. Different TSS
may exist for the same enemy activity against different weapon systems
(para 2-18 — e.g., 150 m TLE for cannon artillery vs 1 km for attack aircraft).

paras 1-38 + 1-65 + Table 3-2 corroborate the matrix as a
DIVARTY-level S-2 targeting section product; this schema is echelon-agnostic
and the preparing_unit header field carries the actual owner.

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

# Doctrinal TSS column axis. Per para 2-17 the criteria are TLE
# (accuracy), size, status, timeliness. Para 2-19 adds reliability (the FAIO
# evaluates the source of the information as to its reliability and accuracy
# before declaring it a target). The schema renders four columns:
#   - accuracy_required_tle  (7 first bullet)
#   - timeliness             (7 fourth bullet)
#   - reliability            (9 — source reliability + verification)
#   - prioritization         (TSS gating priority — drives downstream AGM ordering;
#                              corresponds to the analyst's per-target prioritization
#                              note that overlays the HPTL priority for TSS purposes)
#
# Size + status are captured as separate scalar inputs in the row dict so the
# analyst sees them per-HPT alongside the four primary columns; they print
# inside the timeliness/reliability cells as needed.
TSS_COL_AXIS = [
    "accuracy_required_tle",
    "timeliness",
    "reliability",
    "prioritization",
]

SPEC = {
    "name": "TSS",
    "output_format": "docx",
    # XLSX-canonical per EXCEL_DOCTRINAL_ALIGNMENT.md §2. FM 3-60 App. D
    # Table D-2: HPT × {TLE, timeliness, reliability, prioritization} +
    # per-weapon-system variants — FAIO works cell-by-cell.
    "output_formats": ["xlsx"],
    "legacy_formats": ["docx"],
    # Row-shape product: one row per HPT from the consumed HPTL. Was
    # 'matrix' (single grid_table paragraph_field) — refactored to row
    # so the per-cell values are structured row_fields the writer can
    # author + downstream products can lookup by id without parsing
    # rendered grid markdown. matrix_spec/tss_matrix paragraph_field
    # removed accordingly (see hard_rule below: TSS rows = HPTL rows
    # one-to-one).
    "shape": "row",
    "row_source": "entities:marked",
    # Writer-controlled row-id selection. TSS rows MUST verbatim-match
    # every HPTL row — no drops, no additions, no re-prioritization. The
    # selected_tss_hpt_ids singleton encodes this 1:1 contract.
    "row_id_selection_field": "selected_tss_hpt_ids",
    "group_by": "category",
    "doctrine": {
        "purpose": (
            "Gating criteria the FSE + intel section agree on to declare an "
            "acquisition a TARGET vs a SUSPECTED TARGET. Different TSS may "
            "exist for the same HPT against different weapon systems. Sets "
            "the accuracy / timeliness / reliability bar each HPT must meet "
            "before the FAIO forwards it for engagement. Feeds AGM "
            "(engagement decision) and ICSM (collection tasking)." + PROVENANCE_DIRECTIVE
        ),
        "ordering_rule": (
            "Rows = HPTs from the consumed HPTL, in HPTL priority order. "
            "Columns: accuracy_required_tle (TLE in meters), timeliness "
            "(engagement time window), reliability (source-class verification "
            "standard), prioritization (TSS-level priority that modifies HPTL "
            "priority for engagement-gating purposes)."
        ),
    },
    # Tighten consumes_artifacts to the writer-relevant set. OPORD /
    # FRAGO / UNIT_SOP_TSS / get_oob / get_spatial_overlay / get_phases
    # were data_sources doc-block entries (citations for the analyst,
    # not artifact-dep payload). Dropping them from the dep set keeps
    # the writer prompt scoped.
    "consumes_artifacts": ["HPTL", "HVTL", "CARVER"],
    # Per-field upstream dep filter — narrows every TSS field prompt to
    # the writer-relevant subsection. Mirrors HVTL pattern.
    "default_data_source_filter": {
        "upstream:HPTL": ["rows", "header"],
        "upstream:HVTL": ["rows"],
        "upstream:CARVER": ["rows"],
    },
    "published_section_title": "Target Selection Standards",
    "header_fields": {
        "area_of_operations": HEADER_AO,
        "dtg":                HEADER_DTG,
        "phase":              HEADER_PHASE,
        "prepared_by":        HEADER_PREPARED_BY,
        "classification":     HEADER_CLASSIFICATION,
        "hptl_artifact_id":   {"source": "upstream:HPTL", "view": "internal",
                                 "required": True,
                                 "render_label": "HPTL Reference",
                                 "depends_on": ["upstream:HPTL"],
                                 "guidance": (
                                    "Upstream HPTL — the TSS rows must be "
                                    "exactly the HPTs on the consumed HPTL "
                                    "('TSS are criteria"
                                    "applied to enemy activity'; the HPTs ARE "
                                    "the enemy activity under consideration)."
                                 )},
        # Writer's analytical selection — list of HPT kg_ids the TSS
        # rows cover. By doctrine TSS is one-row-per-HPT with no drops
        # / no additions; the selection field is therefore the verbatim
        # set of HPTL row ids. Singleton wave — lands BEFORE the per-row
        # batch waves run.
        "selected_tss_hpt_ids": {
            "source": "analytical", "view": "internal",
            "required": True, "provenance_required": True,
            "render_label": "Selected HPT kg_ids",
            "depends_on": ["upstream:HPTL"],
            "guidance": (
                "JSON array of kg_id strings. Every kg_id MUST "
                "verbatim-match a row id on the consumed HPTL. TSS "
                "rows are exactly the HPTs from the HPTL — list ALL "
                "HPTL rows (do not drop, do not invent, do not "
                "re-prioritize); if HPTL is empty this list is "
                "empty."
            ),
        },
    },
    "row_fields": {
        # KG-sourced identity fields (mechanical resolve from kg entity).
        "id":            {"source": "entity:id", "view": "internal",
                            "required": True, "provenance_required": True,
                            "render_label": "ID"},
        "name":          {"source": "entity:name", "view": "published",
                            "required": True, "render_label": "HPT"},
        "category":      {"source": "entity:category", "view": "published",
                            "required": False, "render_label": "Category"},
        # The four doctrinal TSS gating columns — analytical per-row.
        # Batched into one wave per row via batch_group:tss_row_analytical
        # so the per-row fields fire AFTER selected_tss_hpt_ids has
        # landed (no full-pool fallback).
        "accuracy_required_tle": {
            "source": "analytical", "view": "published",
            "required": True, "provenance_required": True,
            "batch_group": "tss_row_analytical",
            "depends_on": ["selected_tss_hpt_ids"],
            "render_label": "Accuracy (TLE)",
            "guidance": (
                "Target Location Error tolerance for the planned weapon "
                "system on this row. Derive from the JWS table for the "
                "weapon system documented on the upstream HPTL row's "
                "tle_requirement workpaper field; never substitute a "
                "hardcoded anchor when the upstream HPTL workpaper field "
                "is populated. Format: NUMERIC value + unit "
                "(e.g., '150 m', '1 km', '6 m point')."
            ),
        },
        "timeliness": {
            "source": "analytical", "view": "published",
            "required": True, "provenance_required": True,
            "batch_group": "tss_row_analytical",
            "depends_on": ["selected_tss_hpt_ids"],
            "render_label": "Timeliness",
            "guidance": (
                "Engagement time window for this HPT category derived "
                "from the upstream HPTL row's dwell_time workpaper field "
                "+ unit doctrinal expected stay. Format: NUMERIC value + "
                "unit (e.g., '15 minutes', '1 hour', '6 hours')."
            ),
        },
        "reliability": {
            "source": "analytical", "view": "published",
            "required": True, "provenance_required": True,
            "batch_group": "tss_row_analytical",
            "depends_on": ["selected_tss_hpt_ids"],
            "render_label": "Reliability",
            "guidance": (
                "Source-class verification standard per STANAG 2511 "
                "(F1-F6 source reliability + 1-6 information credibility). "
                "Typical TSS gates require F2/2 or better for an HPT to "
                "be forwarded as a target. Format: STANAG 2511 letter/"
                "number pair (e.g., 'F2/2' or 'B2') OR a unit-SOP "
                "equivalent — never free-text adjectives."
            ),
        },
        "prioritization": {
            "source": "analytical", "view": "published",
            "required": True, "provenance_required": True,
            "batch_group": "tss_row_analytical",
            "depends_on": ["selected_tss_hpt_ids"],
            "render_label": "Prioritization",
            "guidance": (
                "TSS-gating priority — orders the AGM engagement queue "
                "when multiple HPTs meet TSS simultaneously. Inherits "
                "the HPTL priority by default; the FSE may locally bump "
                "a TSS priority for a TST-class HPT that meets all four "
                "criteria without altering the HPTL itself."
            ),
        },
    },
    "paragraph_fields": [
        # Sidecar lists — weapon-system variants + dwell-time notes —
        # consume the selected_tss_hpt_ids set and iterate over it. Both
        # share batch_group:tss_sidecar so they co-fire in one batched
        # LLM call AFTER row-id selection lands.
        {"name": "weapon_system_variants",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Weapon-System TSS Variants",
         "required": False,
         "batch_group": "tss_sidecar",
         "depends_on": [
             "selected_tss_hpt_ids",
             "upstream:HPTL",
         ],
         "guidance": (
            "'Different TSS may exist for a given "
            "enemy activity based on different weapons systems.' List "
            "variant pairings for any HPT in selected_tss_hpt_ids where "
            "the engagement system materially changes the TSS gate. "
            "Iterate over selected_tss_hpt_ids; leave empty if every "
            "HPT has a single planned engagement system."
         ),
         "item_subfields": [
             {"name": "target_id", "render_label": "HPT kg_id",
              "provenance_required": True,
              "guidance": "HPT entity id (kg_id) for the variant — matches the `id` column of the consumed HPTL row. Sourced from the consumed HPTL; lets downstream consumers (TIDAT, AGM, BDA) join by kg_id instead of name string."},
             {"name": "hpt", "render_label": "HPT",
              "guidance": "HPT name matching the kg:name value for the target_id."},
             {"name": "weapon_system", "render_label": "Weapon System",
              "guidance": "Engagement system the variant applies to. Pull from the planned weapon system documented on the upstream HPTL row + commander's targeting guidance; never substitute a hardcoded weapon name."},
             {"name": "accuracy_required_tle", "render_label": "Accuracy (TLE)",
              "guidance": "TLE for this weapon-system variant. Derive from the JWS table for the weapon_system on this row; never substitute a hardcoded anchor when the upstream HPTL row tle_requirement is populated."},
             {"name": "timeliness", "render_label": "Timeliness",
              "guidance": "Engagement time window for this weapon-system variant."},
             {"name": "rationale", "render_label": "Rationale",
              "provenance_required": True,
              "guidance": "Why this variant applies — JWS effects, weapon CEP, sortie availability, etc."},
         ]},
        {"name": "dwell_time_notes",
         "view": "published",
         "shape": "list_of_dicts",
         "render_label": "Dwell Time and Verification Notes",
         "required": False,
         "batch_group": "tss_sidecar",
         "depends_on": [
             "selected_tss_hpt_ids",
             "upstream:HPTL",
         ],
         "guidance": (
            "'Dwell time is the length of time "
            "a target is doctrinally expected to remain in one location.' The "
            "FAIO compares acquisition time against dwell time; accurate "
            "information from a reliable source must be verified before "
            "declaring it a target if the elapsed time exceeds dwell time. "
            "Iterate over selected_tss_hpt_ids — one entry per selected "
            "HPT id. Pull doctrinal dwell estimates from the HPTL "
            "workpaper field `dwell_time` when populated."
         ),
         "item_subfields": [
             {"name": "target_id", "render_label": "HPT kg_id",
              "provenance_required": True,
              "guidance": "HPT entity id (kg_id) for the dwell-time note — matches the `id` column of the consumed HPTL row. Sourced from the consumed HPTL; lets downstream consumers (TIDAT) join dwell-time tolerances by kg_id instead of name string."},
             {"name": "hpt", "render_label": "HPT",
              "guidance": "HPT name matching the kg:name value for the target_id."},
             {"name": "dwell_time", "render_label": "Dwell Time",
              "guidance": "Doctrinal expected time at one location. Pull from the upstream HPTL row dwell_time workpaper field when populated; otherwise derive from doctrinal class behavior."},
             {"name": "verification_method", "render_label": "Verification Method",
              "provenance_required": True,
              "guidance": "How a stale acquisition is re-confirmed before engagement (re-task ISR, cross-cue SIGINT, request UAS dwell, etc.)."},
         ]},
    ],
    "subtleties": [
        "TSS classify nominations into TARGET vs SUSPECTED TARGET (6). A SUSPECTED TARGET must be confirmed before any engagement; the TSS row defines what confirmation looks like (TLE re-check, reliability upgrade, dwell-time-based re-acquisition).",
        "TSS may VARY by weapon system for the same HPT (8). When the planned engagement system changes (e.g., cannon artillery → attack aircraft) the TLE / timeliness gate changes too. Capture variant pairings in weapon_system_variants.",
        "TSS is developed by the FSE in conjunction with the intelligence section (8). The FAIO uses TSS to confirm or verify targets (9) — the matrix is the FAIO's gating worksheet at execution time.",
        "Standard TSS may be pre-built from threat characteristics + standard weapon systems (8 last sentence). Unit SOPs typically carry a standing TSS that this artifact updates for the current phase.",
        "Dwell time interacts with the timeliness column: accurate-but-stale information past dwell time must be re-verified before declaring a target (9). Capture dwell-time tolerances in dwell_time_notes.",
        "Per IDX 26: every cell entry + every variant + every dwell note cites source in _provenance.",
    ],
    "hard_rules": [
        "selected_tss_hpt_ids MUST include every id from the consumed HPTL rows[].id — TSS is one-row-per-HPT with no drops, no additions. Verify count(selected_tss_hpt_ids) == count(HPTL.rows) before emitting.",
        "TSS rows are exactly the HPTs from the consumed HPTL — never invent rows, never drop rows.",
        "Every cell in the four-column matrix is populated. An HPT without a TLE / timeliness / reliability / prioritization value is an incomplete TSS — the analyst must consult JWS / unit SOP / STANAG 2511 anchors and fill it.",
        "TLE values are NUMERIC with units (e.g., '150 m', '1 km', '6 m point') — not narrative.",
        "Timeliness values are NUMERIC with time units (e.g., '15 minutes', '1 hour', '6 hours') — not narrative.",
        "Reliability uses the STANAG 2511 letter/number scale (e.g., 'F2/2' or 'B2') OR a unit-SOP equivalent — not free-text adjectives.",
        "When the planned engagement system is unknown, default to the HPTL's planned attack system; cite the source in _provenance.",
        "Every weapon_system_variants entry and every dwell_time_notes entry MUST carry both `hpt` (HPT name matching the matrix row label) AND `target_id` (the `id` value of the consumed HPTL row whose `name` equals that `hpt`). Pull target_id verbatim from the HPTL row's `id` column — never invent, never abbreviate, never substitute a name string. Downstream consumers (TIDAT, AGM, BDA) join these sidecars by target_id, not by `hpt`.",
        "Per IDX 26: every analytical field carries _provenance.",
        PROVENANCE_HARD_RULE,
    ],
    "data_sources": [
        "Upstream HPTL: list_project_docs(filter={type:'HPTL'}) then get_project_doc(tag=<latest>)",
        "Upstream HVTL: list_project_docs(filter={type:'HVTL'}) then get_project_doc(tag=<latest>)",
        "Upstream CARVER: list_project_docs(filter={type:'CARVER'}) then get_project_doc(tag=<latest>)",
        "Weapon-system TLE anchors: JMEM Weaponeering Software (referred to as JWS) — embedded reference",
    ],
    "post_emit_summary": "artifact_id, HPT row count vs upstream HPTL row count (must match), count of weapon-system variants, count of HPTs with sub-doctrinal TLE",
}
